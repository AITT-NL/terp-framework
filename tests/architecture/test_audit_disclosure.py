"""A disclosure is an audit fact, and a read is allowed to write exactly this one.

The trail could describe a write and nothing else: the vocabulary was ``created`` /
``updated`` / ``deleted``, emitted from the ``BaseService`` write chokepoint. So "who
changed this row" was answerable and "who *saw* this row" was not — an export, a file
download, or a screen that reveals guarded values left no record at all.

What makes the read counterpart interesting is not the verb, it is that the framework
is built to stop precisely this write. The request session is write-guarded, and during
a safe method the read-only guard refuses a mutation outright — that guard exists to
keep a GET from touching business state. A disclosure record is the one thing a read
must be able to persist, so it runs as its own unit of work rather than borrowing the
request's, and these tests pin both halves: that it gets written during a GET at all,
and that it is written *before* the data it describes is handed over.
"""

from __future__ import annotations

import uuid

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from terp.core import AuditAction, AuditPolicy, bind_audit_actor, emit_disclosure
from terp.core._internal.session_guard import enter_write_unit, read_only_request
from terp.core.audit import configure_audit, reset_audit_runtime

from terp.capabilities.audit import AuditEvent, persist_audit


@pytest.fixture()
def engine(monkeypatch: pytest.MonkeyPatch, tmp_path):
    """A throwaway database, wired in as the engine the disclosure seam opens.

    Backed by a *file* rather than ``sqlite://``, deliberately: an in-memory database
    has to share one connection across every session, which would hide the property
    the independence test below exists to check by putting two "separate"
    transactions on the same connection.
    """
    made = create_engine(f"sqlite:///{tmp_path / 'audit.db'}")
    SQLModel.metadata.create_all(made, tables=[AuditEvent.__table__])
    # The seam resolves the engine at call time, which is what lets a test point it at
    # a throwaway database rather than requiring a running stack.
    import terp.core.audit as audit_module

    monkeypatch.setattr(audit_module, "get_engine", lambda: made)
    try:
        yield made
    finally:
        reset_audit_runtime()
        made.dispose()


def _rows(engine) -> list[AuditEvent]:
    with Session(engine) as session:
        return list(session.exec(select(AuditEvent)).all())


def test_a_disclosure_is_recorded_and_committed_on_its_own(engine) -> None:
    """No session is passed in, and the row is durable once the call returns."""
    configure_audit(AuditPolicy(enabled=True), sink=persist_audit)
    actor = uuid.uuid4()

    with bind_audit_actor(actor):
        emit_disclosure(target_type="export", target_id="payroll-2026-08")

    (row,) = _rows(engine)
    assert row.action == AuditAction.DISCLOSED.value
    assert row.target_type == "export"
    assert row.target_id == "payroll-2026-08"
    assert row.actor_id == actor


def test_a_disclosure_is_recorded_during_a_read_only_request(engine) -> None:
    """The case the whole feature exists for: a GET.

    ``create_app`` opens ``read_only_request(True)`` for every safe method, and the
    write guard refuses a mutation there. An implementation that merely opened the
    write-permission scope raised ``ReadOnlyRequestError`` and recorded nothing —
    working in every test that called it outside a request and failing on the only
    call site that would ever exist.
    """
    configure_audit(AuditPolicy(enabled=True), sink=persist_audit)

    with read_only_request(True):
        emit_disclosure(target_type="export", target_id="payroll-2026-08")

    assert [row.target_id for row in _rows(engine)] == ["payroll-2026-08"]


def test_the_record_is_written_before_the_data_could_be_handed_over(engine) -> None:
    """A sink that refuses must abort the disclosure, not be noted after it.

    If recording came second, a sink failure would leave data already disclosed and no
    trace of it — the exact state an audit trail exists to make impossible.
    """
    configure_audit(AuditPolicy(enabled=True), sink=_refusing_sink)

    disclosed: list[str] = []
    with pytest.raises(RuntimeError, match="sink is down"):
        emit_disclosure(target_type="export", target_id="payroll-2026-08")
        disclosed.append("payroll")  # unreachable: recording raises first

    assert disclosed == [], "the payload must not be handed over when recording failed"
    assert _rows(engine) == []


def _refusing_sink(session, record, policy) -> None:
    raise RuntimeError("the audit sink is down")


def test_the_payload_is_centrally_redacted(engine) -> None:
    """A disclosure record must not become the place a secret is written down."""
    configure_audit(AuditPolicy(enabled=True), sink=persist_audit)

    emit_disclosure(
        target_type="mapping",
        target_id="acme",
        payload={"column": "iban", "api_key": "sk-live-should-never-land"},
    )

    (row,) = _rows(engine)
    assert row.payload["column"] == "iban"
    assert "sk-live-should-never-land" not in str(row.payload)


def test_a_disabled_policy_records_nothing(engine) -> None:
    """The explicit opt-out behaves the same for a disclosure as for a write."""
    configure_audit(AuditPolicy.disabled(reason="deliberately off in this test"), sink=persist_audit)
    emit_disclosure(target_type="export", target_id="payroll")
    assert _rows(engine) == []


def test_a_disclosure_commits_even_if_the_request_that_made_it_rolls_back(
    engine,
) -> None:
    """It is recorded on its own transaction, so nothing the caller does can retract it.

    This is what "written before the data is handed over" is worth in practice. If the
    record rode the caller's transaction it would vanish on rollback — and a request
    that discloses data and *then* fails has still disclosed it. Here the caller's work
    is discarded and the disclosure survives, because the two never shared a unit of
    work: the seam opens its own session and commits it before returning.
    """
    configure_audit(AuditPolicy(enabled=True), sink=persist_audit)

    with Session(engine) as caller, enter_write_unit():
        caller.add(AuditEvent(action="created", target_type="widget", target_id="w1"))
        emit_disclosure(target_type="export", target_id="payroll")
        caller.rollback()

    assert [row.target_id for row in _rows(engine)] == ["payroll"]


def test_the_verb_fits_the_column_that_stores_it() -> None:
    """The action column is a plain bounded string, which is why no migration was needed.

    It is not a native enum and carries no CHECK constraint, so a new member is storable
    on an existing database the moment it fits. This is the assertion that would have
    caught it if that stopped being true.
    """
    column = AuditEvent.__table__.c.action
    assert column.type.length == 16
    assert len(AuditAction.DISCLOSED.value) <= column.type.length
