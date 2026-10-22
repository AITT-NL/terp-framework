"""A checksum over what a seed decides, so two databases a seed built can be compared.

A seed is held to two properties: a second run on the same database writes nothing,
and two fresh databases it seeds hold the same data. Neither can be checked by
comparing rows as they are stored, because a fresh run does not reproduce the values
a write *generates* rather than the seed *declares*:

* every row's primary key is a fresh ``uuid4``;
* every timestamp (``created_at``, ``updated_at``, any column a write stamps with the
  current time) is the moment of that run;
* a password or client-secret hash carries a fresh random salt;
* and every column that points at another row — an owner, an actor stamp, an audit
  record's target — carries that row's generated id.

:func:`seed_checksum` therefore hashes the **business columns**, by a rule that does
not need the app to declare anything:

1. Every table of the metadata that exists in the database is read, every row.
2. A table's own single-column primary key is left out, and so is every ``DateTime``
   column. A ``Date`` is kept: a seed that sets a due date has decided it.
3. A string in PHC hash format (``$argon2id$v=19$m=...,t=...,p=...$<salt>$<hash>``) is
   compared by its scheme and parameters only, never its salt or digest.
4. A value that is the UUID primary key of a row in the database — wherever it appears:
   a foreign key, an untyped reference column, a JSON payload — is replaced by that
   row's table and a fingerprint of that row's own business columns. So "the note was
   created by the user whose email is ``admin@example.test``" is compared, and the id the
   user happened to get is not. A UUID that is no row's key (a ``uuid5`` tenant, a
   dangling reference) is kept as it is, so a reference a seed got from ``uuid4`` still
   shows up as a difference.
5. Rows are compared as a set: the order a database returns them in does not count.

``generated=True`` keeps every column exactly as stored instead. Two equal checksums of
that kind mean nothing was written between them at all — no row added, changed or
re-stamped — which is what "a second seed run is a no-op" means.
"""

from __future__ import annotations

import datetime as _dt
import decimal
import hashlib
import json
import re
import uuid
from collections.abc import Callable, Mapping
from typing import Any

from sqlalchemy import DateTime, MetaData, Table, inspect, select
from sqlalchemy.engine import Connection, Engine

__all__ = ["seed_checksum"]

#: A PHC-format hash: ``$<scheme>`` followed by ``$``-separated segments, no whitespace.
_PHC = re.compile(r"\$[a-z0-9-]{1,32}(?:\$[^$\s]+){2,}")


def _is_timestamp(column: Any) -> bool:
    """True for a ``DateTime`` column, including one behind a type decorator."""
    return isinstance(column.type, DateTime) or isinstance(
        getattr(column.type, "impl", None), DateTime
    )


def _uuid_key(value: object) -> str | None:
    """*value* as a canonical UUID string, when it is one."""
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, str) and len(value) in {32, 36}:
        try:
            return str(uuid.UUID(value))
        except ValueError:
            return None
    return None


def _phc_scheme(value: str) -> str | None:
    """The scheme and parameters of a PHC hash, without its salt and digest."""
    if not _PHC.fullmatch(value):
        return None
    scheme, *rest = value.split("$")[1:]
    return "$".join(["", scheme, *(segment for segment in rest if "=" in segment)])


def _plain(value: object) -> object:
    """*value* as JSON can carry it, unchanged in meaning."""
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_plain(item) for item in value]
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, _dt.datetime | _dt.date | _dt.time):
        return value.isoformat()
    if isinstance(value, decimal.Decimal | uuid.UUID):
        return str(value)
    return repr(value)


def _digest(payload: object) -> str:
    """SHA-256 of *payload*'s canonical JSON."""
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _business(value: object, refer: Callable[[str], str | None]) -> object:
    """*value* with references resolved by *refer* and hashes reduced to their scheme."""
    key = _uuid_key(value)
    if key is not None:
        resolved = refer(key)
        return resolved if resolved is not None else key
    if isinstance(value, str):
        scheme = _phc_scheme(value)
        return scheme if scheme is not None else value
    if isinstance(value, Mapping):
        return {str(name): _business(item, refer) for name, item in value.items()}
    if isinstance(value, list | tuple):
        return [_business(item, refer) for item in value]
    return _plain(value)


def _tables(connection: Connection, metadata: MetaData) -> list[Table]:
    """The metadata's tables that exist in the database, in dependency order."""
    inspector = inspect(connection)
    return [
        table
        for table in metadata.sorted_tables
        if inspector.has_table(table.name, schema=table.schema)
    ]


def seed_checksum(
    bind: Engine | Connection,
    *,
    metadata: MetaData | None = None,
    generated: bool = False,
) -> str:
    """A SHA-256 over the business columns of every seeded table (see the module docstring).

    Two databases a seed built have equal checksums when they hold the same data: the
    same rows, with the same values in every column the seed decides. *metadata*
    defaults to ``SQLModel.metadata``, the one every Terp model registers on.

    ``generated=True`` hashes every column as stored, ids and timestamps included, so
    two equal checksums mean nothing was written in between: take one after the first
    run and one after the second to prove the second run is a no-op.
    """
    if metadata is None:
        from sqlmodel import SQLModel

        metadata = SQLModel.metadata
    if isinstance(bind, Engine):
        with bind.connect() as connection:
            return _checksum(connection, metadata, generated=generated)
    return _checksum(bind, metadata, generated=generated)


def _checksum(connection: Connection, metadata: MetaData, *, generated: bool) -> str:
    tables = _tables(connection, metadata)
    rows = {
        table.name: [dict(row) for row in connection.execute(select(table)).mappings()]
        for table in tables
    }
    if generated:
        return _digest(
            {
                name: sorted(_digest(_plain(row)) for row in table_rows)
                for name, table_rows in rows.items()
            }
        )

    keys: dict[str, str] = {}
    kept: dict[str, list[str]] = {}
    owners: dict[str, tuple[str, dict[str, object]]] = {}
    for table in tables:
        primary = list(table.primary_key.columns)
        own_key = primary[0].name if len(primary) == 1 else None
        kept[table.name] = [
            column.name
            for column in table.columns
            if column.name != own_key and not _is_timestamp(column)
        ]
        if own_key is None:
            continue
        for row in rows[table.name]:
            key = _uuid_key(row[own_key])
            if key is not None:
                keys[key] = table.name
                owners[key] = (table.name, row)

    def by_table(key: str) -> str | None:
        return f"ref:{keys[key]}" if key in keys else None

    fingerprints = {
        key: _digest(
            [name, {column: _business(row[column], by_table) for column in kept[name]}]
        )
        for key, (name, row) in owners.items()
    }

    def by_row(key: str) -> str | None:
        return f"ref:{keys[key]}:{fingerprints[key]}" if key in keys else None

    return _digest(
        {
            table.name: sorted(
                _digest({column: _business(row[column], by_row) for column in kept[table.name]})
                for row in rows[table.name]
            )
            for table in tables
        }
    )
