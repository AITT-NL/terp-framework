"""``terp migrate check-roles``: whether a database's two roles are the ones ADR 0071 splits.

Where Terp provisions the database it makes both roles itself; where an operator brings one,
Terp creates no role, and a deploy checks the two it is given before anything is backed up
or migrated. :func:`check_roles` connects as the owner and reads both roles by name from the
catalog, so it needs no runtime connection. It holds its transaction read-only and never
commits it, so it changes nothing, and it returns every failure it finds, each on one line
naming what to change.
"""

from __future__ import annotations

import pathlib
from dataclasses import dataclass
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.pool import NullPool

from terp.migrations.errors import MigrationError
from terp.migrations.orchestrate import _refuse_role_names_that_are_not_plain, _runtime_schemas

#: The attributes a runtime role is refused beside superuser, with what each would let a
#: compromised app process do. An app's connection needs none of them.
_REFUSED_ATTRIBUTES = (
    (
        "rolcreaterole",
        "CREATEROLE",
        "which creates roles, and before PostgreSQL 16 takes any non-superuser role's rights",
    ),
    ("rolcreatedb", "CREATEDB", "which creates databases on the server"),
    ("rolreplication", "REPLICATION", "which streams every database's changes off the server"),
    ("rolbypassrls", "BYPASSRLS", "which passes every row-level security policy"),
)

#: How a relation's ``relkind`` reads in a failure. An index or a TOAST table always has its
#: table's owner, so neither is listed.
_RELATION_KINDS = {
    "r": "table",
    "p": "partitioned table",
    "v": "view",
    "m": "materialized view",
    "S": "sequence",
    "f": "foreign table",
    "c": "composite type",
}


@dataclass(frozen=True)
class RoleCheck:
    """What ``check-roles`` found (ADR 0071).

    *schemas* are the app's schemas it read, *pending* the app's schemas the database does
    not hold yet, which the owner creates at its first migration, and *failures* each check
    that did not hold, one line each, naming what to change. The roles hold when it is empty.
    """

    schemas: tuple[str, ...]
    pending: tuple[str, ...]
    failures: tuple[str, ...]


def check_roles(
    database_url: str,
    role: str,
    app_root: str | pathlib.Path | None = None,
    *,
    owner_role: str,
    package: str = "app",
    schema_layout: str | None = None,
) -> RoleCheck:
    """Check the runtime *role* and *owner_role* against the split of ADR 0071.

    The app's schemas are the ones ``grant-runtime`` grants on under the layout, and
    ``public`` always. A failure is reported where:

    - either role does not exist;
    - the runtime role is a superuser, or has ``CREATEROLE``, ``CREATEDB``, ``REPLICATION``
      or ``BYPASSRLS``;
    - the runtime role is a member of the owner role, directly or through another role:
      ``SET ROLE`` gives it the owner's rights even where it does not inherit them;
    - the runtime role owns a relation in the app's schemas, or is a member of a role that
      owns one there;
    - the runtime role may ``CREATE`` in the database or in one of the app's schemas;
    - the runtime role can act as the owner of ``public``, whose owner may drop every table
      in it, the version tables included;
    - the owner role does not own one of the app's schemas other than ``public``.

    A superuser passes every privilege check, and a member of the owner role holds the
    owner's rights, so while the runtime role is either, the checks those make moot are not
    run: one line names the cause, and a run once it is fixed lists what remains. A schema
    the database does not hold yet is not read; it is named in ``pending``.

    Plain role names only: anything else is refused before connecting, as
    ``grant-runtime`` refuses it, and so is a database that is not PostgreSQL. What it
    reports becomes a deploy's refusal, so a connection that fails is named without any of
    its values: the driver's own message carries the host, the port and the user.
    """
    _refuse_role_names_that_are_not_plain((role, "runtime role"), (owner_role, "owner role"))
    write_schemas, read_schemas = _runtime_schemas(schema_layout, app_root, package)
    schemas = list(dict.fromkeys([*write_schemas, *read_schemas, "public"]))
    engine = create_engine(database_url, hide_parameters=True, poolclass=NullPool)
    try:
        try:
            opened = engine.connect()
        except OperationalError as exc:
            raise MigrationError(
                "check-roles could not connect to the database as the owner: check the "
                "owner's connection (its host, port, database, user and password), which "
                "this command never prints (ADR 0071)"
            ) from exc
        with opened as connection:
            if connection.dialect.name != "postgresql":
                raise MigrationError(
                    "check-roles requires PostgreSQL; got dialect "
                    f"{connection.dialect.name!r} (ADR 0071)"
                )
            # The database holds this command to reading, and the transaction is never
            # committed: leaving the block rolls it back.
            connection.exec_driver_sql("SET TRANSACTION READ ONLY")
            return _check(connection, role, owner_role, schemas)
    finally:
        engine.dispose()


def _check(connection: Any, role: str, owner: str, schemas: list[str]) -> RoleCheck:
    found = {
        row.rolname: row
        for row in connection.execute(
            text(
                "SELECT rolname, rolsuper, rolcreaterole, rolcreatedb, rolreplication,"
                " rolbypassrls FROM pg_roles WHERE rolname = ANY(:names)"
            ),
            {"names": [role, owner]},
        )
    }
    owners = {
        row[0]: row[1]
        for row in connection.execute(
            text(
                "SELECT nspname, pg_get_userbyid(nspowner) FROM pg_namespace"
                " WHERE nspname = ANY(:schemas)"
            ),
            {"schemas": schemas},
        )
    }
    present = [schema for schema in schemas if schema in owners]
    failures: list[str] = []
    if role not in found:
        failures.append(
            f"the runtime role {role!r} does not exist: create the login the app connects "
            f"as (CREATE ROLE {_ident(role)} LOGIN), then grant it with terp migrate "
            "grant-runtime"
        )
    if owner not in found:
        failures.append(
            f"the owner role {owner!r} does not exist: name the role that owns the app's "
            "schemas and runs terp migrate"
        )
    if role in found:
        failures.extend(_runtime_failures(connection, found[role], owner, owner in found, present))
    if owner in found:
        failures.extend(
            f"schema {schema!r} is owned by {owners[schema]!r}, not the owner role "
            f"{owner!r}: ALTER SCHEMA {_ident(schema)} OWNER TO {_ident(owner)}"
            for schema in present
            if schema != "public" and owners[schema] != owner
        )
    return RoleCheck(
        schemas=tuple(present),
        pending=tuple(schema for schema in schemas if schema not in owners),
        failures=tuple(_one_line(failure) for failure in failures),
    )


def _runtime_failures(
    connection: Any, runtime: Any, owner: str, owner_exists: bool, present: list[str]
) -> list[str]:
    role = runtime.rolname
    failures: list[str] = []
    if runtime.rolsuper:
        failures.append(
            f"the runtime role {role!r} is a superuser, which passes every privilege check: "
            f"ALTER ROLE {_ident(role)} NOSUPERUSER"
        )
    failures.extend(
        f"the runtime role {role!r} has {name}, {why}: ALTER ROLE {_ident(role)} NO{name}"
        for column, name, why in _REFUSED_ATTRIBUTES
        if getattr(runtime, column)
    )
    if runtime.rolsuper:
        return failures
    member = owner_exists and connection.execute(
        text("SELECT pg_has_role(:role, :owner, 'MEMBER')"), {"role": role, "owner": owner}
    ).scalar()
    if member:
        failures.append(_membership(role, owner))
    relations = connection.execute(
        text(
            "SELECT n.nspname, c.relname, c.relkind, pg_get_userbyid(c.relowner)"
            " FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace"
            " WHERE n.nspname = ANY(:schemas) AND c.relkind NOT IN ('i', 'I', 't')"
            " AND pg_has_role(:role, c.relowner, 'MEMBER')"
            " AND NOT EXISTS (SELECT 1 FROM pg_roles o"
            " WHERE o.rolname = :owner AND o.oid = c.relowner)"
            " ORDER BY n.nspname, c.relname"
        ),
        {"schemas": present, "role": role, "owner": owner},
    ).all()
    if relations:
        failures.append(_relations(role, owner, relations))
    if member:
        return failures
    database, may_create = connection.execute(
        text("SELECT current_database(), has_database_privilege(:role, current_database(), 'CREATE')"),
        {"role": role},
    ).one()
    if may_create:
        failures.append(
            f"the runtime role {role!r} may CREATE in database {database!r}: revoke it "
            f"(REVOKE CREATE ON DATABASE {_ident(database)} FROM {_ident(role)}, and from "
            "PUBLIC or the role it holds it through), and give the database to the owner "
            "role if the runtime role owns it"
        )
    creatable = {
        row[0]
        for row in connection.execute(
            text(
                "SELECT nspname FROM pg_namespace WHERE nspname = ANY(:schemas)"
                " AND has_schema_privilege(:role, oid, 'CREATE')"
            ),
            {"schemas": present, "role": role},
        )
    }
    failures.extend(
        f"the runtime role {role!r} may CREATE in schema {schema!r}: REVOKE CREATE ON SCHEMA "
        f"{_ident(schema)} FROM {_ident(role)}, and from PUBLIC or the role it holds it through"
        for schema in present
        if schema in creatable
    )
    if "public" in present:
        holder, acts = connection.execute(
            text(
                "SELECT pg_get_userbyid(nspowner), pg_has_role(:role, nspowner, 'MEMBER')"
                " FROM pg_namespace WHERE nspname = 'public'"
            ),
            {"role": role},
        ).one()
        if acts:
            failures.append(
                f"the runtime role {role!r} can act as the owner of schema 'public' (owned "
                f"by {holder!r}), and a schema's owner may drop every table in it, the "
                f"version tables included: ALTER SCHEMA public OWNER TO {_ident(owner)}"
            )
    return failures


def _membership(role: str, owner: str) -> str:
    if role == owner:
        return (
            f"the runtime role and the owner role are both {role!r}: the app connects as a "
            "role of its own, which owns nothing"
        )
    return (
        f"the runtime role {role!r} is a member of the owner role {owner!r}, directly or "
        "through another role, so SET ROLE gives it the owner's rights: "
        f"REVOKE {_ident(owner)} FROM {_ident(role)}, or from the role it holds it through"
    )


def _relations(role: str, owner: str, relations: list[Any]) -> str:
    named = ", ".join(
        f"{f'{schema}.{name}'!r} ({_RELATION_KINDS.get(kind, kind)}, owned by {holder!r})"
        for schema, name, kind, holder in relations[:5]
    )
    more = f" and {len(relations) - 5} more" if len(relations) > 5 else ""
    return (
        f"the runtime role {role!r} can act as the owner of {len(relations)} relation(s) in "
        f"the app's schemas: {named}{more}: give them to the owner role (ALTER TABLE ... "
        f"OWNER TO {_ident(owner)}, or REASSIGN OWNED BY their owner TO {_ident(owner)})"
    )


def _ident(name: str) -> str:
    """*name* as a PostgreSQL quoted identifier, for a statement a failure suggests."""
    return '"' + name.replace('"', '""') + '"'


def _one_line(failure: str) -> str:
    """One failure per line, whatever a name read from the catalog holds."""
    return failure.replace("\r", "\\r").replace("\n", "\\n")


__all__ = ["RoleCheck", "check_roles"]
