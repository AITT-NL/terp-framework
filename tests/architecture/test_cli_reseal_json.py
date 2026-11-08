"""``terp secrets reseal`` reaches a sealed value nested in a JSON column (ADR 0199).

A queued mail is the case that made it matter: its message is a sealed value inside an
``outbox_message.payload`` document, and a re-seal that walked string columns only called a
database clean while that mail still needed the retired key to be sent. Every test that
needs a server runs on SQLite and on PostgreSQL (``terp_db_url``), whose ``json`` has no
equality operator, which is why the swap compares a document's text form:

* a queued mail is found, counted under the fallback, re-sealed and still delivered once the
  fallback is gone, with nothing else in its row's document moved;
* every sealed string in a document is judged, at any depth and as a key, a ``jsonb`` one
  included, and only the ones under a fallback are rewritten;
* a document someone else changed between the read and the write is never overwritten;
* a JSON column of a table the app does not map is read, counted and never written;
* a document that does not parse is never reported clean.
"""

from __future__ import annotations

import json
import pathlib
import secrets
import sys
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import JSON, Column, Engine, Integer, MetaData, String, Table, Text, cast, create_engine, insert, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Session

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_CLI_SRC = _REPO_ROOT / "packages" / "backend" / "cli" / "src"
sys.path.insert(0, str(_CLI_SRC))

from terp.cli.reseal import ResealReport, _as_document, _render, survey

from terp.core import (
    JobCatalog,
    SealState,
    check_sealed_value,
    decrypt_config,
    encrypt_config,
    register_decrypt_call_site,
    settings,
)
from terp.core.jobs import configure_jobs
from terp.core._internal.session_guard import WriteGuardedSession

from terp.capabilities.mail import (
    MAIL_SEND,
    CapturingMailTransport,
    MailMessage,
    MailSettings,
    configure_mail,
    reset_mail,
    send_mail,
)
from terp.capabilities.mail.delivery import MailJobPayload
from terp.capabilities.outbox import OutboxJobQueue, OutboxMessage, OutboxWorker

_OLD = secrets.token_urlsafe(32)
_NEW = secrets.token_urlsafe(32)


@pytest.fixture(autouse=True)
def _old_key(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Every test seals under the old key first; none keeps the relay it declared."""
    monkeypatch.setattr(settings, "SECRET_KEY", _OLD)
    monkeypatch.setattr(settings, "SECRET_KEY_FALLBACKS", [])
    monkeypatch.setattr(settings, "SECRET_KEY_DECRYPT_FALLBACKS", [])
    yield
    reset_mail()


def _rotate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "SECRET_KEY", _NEW)
    monkeypatch.setattr(settings, "SECRET_KEY_FALLBACKS", [_OLD])
    monkeypatch.setattr(settings, "SECRET_KEY_DECRYPT_FALLBACKS", [_OLD])


@pytest.fixture
def engine(terp_db_url: str) -> Iterator[Engine]:
    eng = create_engine(terp_db_url)
    yield eng
    eng.dispose()


def _counts(report: ResealReport, table: str, column: str) -> dict[str, int]:
    (tally,) = [t for t in report.columns if (t.table, t.column) == (table, column)]
    names = ("current", "resealed", "fallback", "unreadable", "changed")
    return {name: getattr(tally, name) for name in names if getattr(tally, name)}


# --------------------------------------------------------------------------- #
# a queued mail, end to end
# --------------------------------------------------------------------------- #
def _payload_of(engine: Engine, table: Table) -> dict[str, Any]:
    with engine.connect() as conn:
        return conn.execute(select(table.c.payload)).scalar_one()


def test_a_queued_mail_is_counted_resealed_and_still_delivered(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    mapping = MetaData()
    outbox = OutboxMessage.__table__.to_metadata(mapping)  # type: ignore[attr-defined]
    mapping.create_all(engine)
    configure_jobs(JobCatalog([MAIL_SEND]), queue=OutboxJobQueue(), system_actor_id=uuid.uuid4())
    relay = CapturingMailTransport()
    configure_mail(MailSettings(sender="Orders <noreply@example.test>", host="smtp.example.test"), transport=relay)
    message = MailMessage(to=["customer@example.test"], subject="Your order has shipped", text="Order 1042.")
    with WriteGuardedSession(engine) as session:
        message_id = send_mail(session, message)
    queued = _payload_of(engine, outbox)

    # Control: under the key it was sealed with, it is current, and nothing needs doing.
    assert _counts(survey(engine, write=False, metadata=mapping), "outbox_message", "payload") == {"current": 1}
    _rotate(monkeypatch)
    checked = survey(engine, write=False, metadata=mapping)
    assert _counts(checked, "outbox_message", "payload") == {"fallback": 1} and not checked.clean
    assert "outbox_message.payload" in _render(checked)
    assert "1 value(s) still open only under SECRET_KEY_DECRYPT_FALLBACKS" in _render(checked)
    assert _payload_of(engine, outbox) == queued, "--check writes nothing"

    written = survey(engine, write=True, metadata=mapping)
    assert _counts(written, "outbox_message", "payload") == {"resealed": 1} and written.clean
    resealed = _payload_of(engine, outbox)
    assert {key: value for key, value in resealed.items() if key != "payload"} == {
        key: value for key, value in queued.items() if key != "payload"
    }, "nothing else in the row's document moved"
    assert resealed["payload"]["message_id"] == queued["payload"]["message_id"] == message_id
    assert resealed["payload"]["sealed"] != queued["payload"]["sealed"]

    # The fallback can go: the mail opens under SECRET_KEY alone, a second run writes
    # nothing, and the worker sends the message that was queued.
    monkeypatch.setattr(settings, "SECRET_KEY_DECRYPT_FALLBACKS", [])
    again = survey(engine, write=True, metadata=mapping)
    assert _counts(again, "outbox_message", "payload") == {"current": 1} and again.clean
    worker = OutboxWorker(
        lambda: Session(engine),
        job_session_factory=lambda: WriteGuardedSession(engine),
        clock=lambda: datetime.now(UTC) + timedelta(seconds=1),
    )
    assert worker.drain_once().dispatched == 1
    (email,) = relay.sent
    assert (email["To"], email["Subject"], email["Message-ID"]) == (
        "customer@example.test",
        "Your order has shipped",
        message_id,
    )
    assert MailJobPayload.model_validate(resealed["payload"]).message() == message


# --------------------------------------------------------------------------- #
# every sealed string in a document, and nothing else
# --------------------------------------------------------------------------- #
def _documents(mapping: MetaData) -> Table:
    return Table(
        "cli_reseal_documents",
        mapping,
        Column("id", Integer, primary_key=True, autoincrement=False),
        Column("doc", JSON().with_variant(JSONB(), "postgresql")),  # jsonb where there is one
        Column("token", String(512), nullable=True),
        Column("note", JSON, nullable=True),
        Column("stamped", Integer, nullable=True, onupdate=1),  # an update stamp: never moved
    )


def _opened(value: str) -> str:
    """The one decrypt call site, registered by the test that reads what values hold."""
    return decrypt_config(value)


def _plain(value: Any) -> Any:
    """*value* with every sealed string that opens replaced by what it holds, at any depth."""
    if isinstance(value, str):
        return ("opened", _opened(value)) if check_sealed_value(value).state is not SealState.UNREADABLE else value
    if isinstance(value, list):
        return [_plain(item) for item in value]
    if isinstance(value, dict):
        return {json.dumps(_plain(key)): _plain(item) for key, item in value.items()}
    return value


def _sealed_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value] if value.startswith("enc:v1:") else []
    if isinstance(value, list):
        return [found for item in value for found in _sealed_strings(item)]
    if isinstance(value, dict):
        return [found for key, item in value.items() for found in [*_sealed_strings(key), *_sealed_strings(item)]]
    return []


def test_every_sealed_string_in_a_document_is_judged_and_only_a_fallback_is_rewritten(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    register_decrypt_call_site(_opened)
    mapping = MetaData()
    documents = _documents(mapping)
    mapping.create_all(engine)
    old = [encrypt_config(text) for text in ("one", "two", "three", "a key", "a token", "four")]
    _rotate(monkeypatch)
    unreadable = "enc:v1:" + secrets.token_urlsafe(40)
    doc = {
        "plain": "not sealed",
        "mentions": 'a text that says "enc:v1:" is not a sealed value',
        "numbers": [3, 0.5, -7, 1e21],
        "flags": {"yes": True, "no": False, "nothing": None},
        "unicode": "Café ☕",
        "fallback": old[0],
        "nested": {"list": [old[1], {"deep": old[2]}]},
        old[3]: "a sealed key",
        "current": encrypt_config("five"),
        "unreadable": unreadable,
    }
    with engine.begin() as conn:
        conn.execute(insert(documents).values(id=1, doc=doc, token=old[4], note=None))
        # A row the string column selects, whose document holds nothing sealed.
        conn.execute(insert(documents).values(id=2, doc={"plain": "nothing"}, token=old[5], note=None))

    checked = survey(engine, write=False, metadata=mapping)
    assert _counts(checked, "cli_reseal_documents", "doc") == {"current": 1, "fallback": 4, "unreadable": 1}
    assert _counts(checked, "cli_reseal_documents", "token") == {"fallback": 2}

    written = survey(engine, write=True, metadata=mapping)
    assert _counts(written, "cli_reseal_documents", "doc") == {"current": 1, "resealed": 4, "unreadable": 1}
    assert _counts(written, "cli_reseal_documents", "token") == {"resealed": 2}
    with engine.connect() as conn:
        after, untouched = conn.execute(select(documents.c.doc).order_by(documents.c.id)).scalars().all()
        stamps = conn.execute(select(documents.c.stamped)).scalars().all()
    assert untouched == {"plain": "nothing"}
    assert stamps == [None, None], "a re-seal moves no update stamp"
    assert _plain(after) == _plain(doc), "every key and value is what it was; only the keys moved"
    assert set(_sealed_strings(after)) & set(old) == set(), "no value is left under the fallback"
    assert unreadable in _sealed_strings(after) and doc["current"] in _sealed_strings(after)
    monkeypatch.setattr(settings, "SECRET_KEY_DECRYPT_FALLBACKS", [])
    assert {check_sealed_value(v).state for v in _sealed_strings(after) if v != unreadable} == {SealState.CURRENT}


def test_every_byte_a_reseal_has_no_reason_to_change_is_left_as_it_was(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Read as an object and written back, the document lost what a float does not keep:
    # 1234567890.123456789012 came back as 1234567890.1234567 beside the value being re-sealed.
    register_decrypt_call_site(_opened)
    mapping = MetaData()
    documents = _documents(mapping)
    mapping.create_all(engine)
    old = encrypt_config("one")
    _rotate(monkeypatch)
    text = json.dumps({"precise": 0, "ends": 'a quote then "' + old, "sealed": old}).replace(
        '"precise": 0', '"precise": 1234567890.123456789012'
    )
    with engine.begin() as conn:
        conn.execute(insert(documents).values(id=1, doc=_as_document(conn, documents.c.doc, text)))
    written = survey(engine, write=True, metadata=mapping)
    assert _counts(written, "cli_reseal_documents", "doc") == {"resealed": 1}
    with engine.connect() as conn:
        stored = conn.execute(select(cast(documents.c.doc, Text))).scalar_one()
        after = conn.execute(select(documents.c.doc)).scalar_one()
    assert "1234567890.123456789012" in stored
    # A string that only ends in the sealed text is not the sealed value, and is left alone.
    assert after["ends"] == 'a quote then "' + old and after["sealed"] != old
    assert _opened(after["sealed"]) == "one"


# --------------------------------------------------------------------------- #
# a concurrent writer is never overwritten
# --------------------------------------------------------------------------- #
def test_a_document_changed_between_the_read_and_the_write_is_never_overwritten(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    import terp.core

    mapping = MetaData()
    documents = _documents(mapping)
    mapping.create_all(engine)
    stale = encrypt_config("one")
    with engine.begin() as conn:
        conn.execute(insert(documents).values(id=1, doc={"secret": stale, "kept": "as written"}))
    _rotate(monkeypatch)
    concurrent = {"secret": encrypt_config("rotated by its owner"), "kept": "rewritten meanwhile"}
    real_check = terp.core.check_sealed_value

    def racing_check(stored: str) -> Any:
        # The app rewrites the document after the re-seal read it and before it writes.
        if stored == stale:
            with engine.begin() as other:
                other.execute(documents.update().where(documents.c.id == 1).values(doc=concurrent))
        return real_check(stored)

    monkeypatch.setattr(terp.core, "check_sealed_value", racing_check)
    raced = survey(engine, write=True, metadata=mapping)
    assert _counts(raced, "cli_reseal_documents", "doc") == {"changed": 1} and not raced.clean
    assert "1 value(s) changed while being re-sealed; run again" in _render(raced)
    with engine.connect() as conn:
        assert conn.execute(select(documents.c.doc)).scalar_one() == concurrent

    # Control: the next run judges what the writer left, which is under the current key.
    monkeypatch.setattr(terp.core, "check_sealed_value", real_check)
    settled = survey(engine, write=True, metadata=mapping)
    assert _counts(settled, "cli_reseal_documents", "doc") == {"current": 1} and settled.clean


# --------------------------------------------------------------------------- #
# what it can read but not rewrite
# --------------------------------------------------------------------------- #
def test_a_json_column_the_app_does_not_map_is_read_counted_and_never_written(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    legacy = Table(
        "cli_reseal_legacy_documents",
        MetaData(),
        Column("id", Integer, primary_key=True, autoincrement=False),
        Column("doc", JSON),
    )
    legacy.create(engine)
    sealed = encrypt_config("legacy")
    with engine.begin() as conn:
        conn.execute(insert(legacy).values(id=1, doc={"secret": sealed}))
    _rotate(monkeypatch)

    report = survey(engine, write=True, metadata=MetaData())  # the app maps none of it
    assert _counts(report, "cli_reseal_legacy_documents", "doc") == {"fallback": 1} and not report.clean
    assert report.skipped == {
        "cli_reseal_legacy_documents": "the app does not map it, so there is no model to write it through"
    }
    with engine.connect() as conn:
        assert conn.execute(select(legacy.c.doc)).scalar_one() == {"secret": sealed}


def test_a_document_that_does_not_parse_is_never_reported_clean(tmp_path: pathlib.Path) -> None:
    """SQLite stores a JSON column as text, so it can hold what PostgreSQL's ``json`` refuses."""
    from sqlalchemy import text

    engine = create_engine(f"sqlite:///{tmp_path / 'damaged.db'}")
    mapping = MetaData()
    _documents(mapping)
    mapping.create_all(engine)
    damaged = '{"secret": "' + encrypt_config("one") + '", '  # cut off mid-document
    insert_row = text("INSERT INTO cli_reseal_documents (id, doc, token) VALUES (:id, :doc, :token)")
    with engine.begin() as conn:
        conn.execute(insert_row.bindparams(id=1, doc=damaged, token=None))
        # Damaged too, but holding nothing sealed: its row is read for the token beside it,
        # and a document is judged only where its text holds the sealed format.
        conn.execute(insert_row.bindparams(id=2, doc='{"plain": ', token=encrypt_config("two")))

    report = survey(engine, write=True, metadata=mapping)
    assert _counts(report, "cli_reseal_documents", "doc") == {"unreadable": 1} and not report.clean
    assert _counts(report, "cli_reseal_documents", "token") == {"current": 1}
    with engine.connect() as conn:
        stored = conn.execute(text("SELECT doc FROM cli_reseal_documents ORDER BY id")).scalars().all()
    assert stored == [damaged, '{"plain": ']
    engine.dispose()
