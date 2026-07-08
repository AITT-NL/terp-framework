"""Unit gate for the ``terp.core.audit`` seam (the Tier-A auto-emit control).

Exercises the policy registry, the central redaction, the request-scoped actor
binding, and the emit chokepoint (disabled vs. enabled, default log sink vs. an
installed sink) — the fail-closed/edge paths the end-to-end reference tests do not
all reach, so the framework holds 100% line coverage.
"""

from __future__ import annotations

import uuid

import pytest

from terp.core import AuditAction, AuditPolicy, AuditRecord, DurableAuditSink
from terp.core.audit import (
    audit_actor_ctx,
    bind_audit_actor,
    configure_audit,
    emit_audit,
    is_durable_audit_sink,
    reset_audit_runtime,
    set_audit_sink,
)
from terp.core.logging import request_id_ctx


def _collecting_sink() -> tuple[list[AuditRecord], object]:
    records: list[AuditRecord] = []

    def sink(session: object, record: AuditRecord, policy: AuditPolicy) -> None:
        records.append(record)

    return records, sink


# --------------------------------------------------------------------------- #
# AuditPolicy registry
# --------------------------------------------------------------------------- #
def test_default_policy_audits_everything() -> None:
    policy = AuditPolicy.default()
    assert policy.enabled is True
    assert policy.disabled_reason is None
    assert policy.retention_days is None


def test_disabled_policy_requires_a_reason() -> None:
    policy = AuditPolicy.disabled(reason="internal demo, no persistence")
    assert policy.enabled is False
    assert policy.disabled_reason == "internal demo, no persistence"

    with pytest.raises(ValueError, match="non-empty justification"):
        AuditPolicy.disabled(reason="   ")


def test_disabled_without_reason_is_rejected() -> None:
    # The frozen dataclass cannot be hand-built into a silently-off state.
    with pytest.raises(ValueError, match="needs a reason"):
        AuditPolicy(enabled=False)


def test_retention_days_must_be_positive() -> None:
    assert AuditPolicy(retention_days=30).retention_days == 30
    with pytest.raises(ValueError, match="positive number of days"):
        AuditPolicy(retention_days=0)


def test_policy_redacts_sensitive_payload_keys() -> None:
    policy = AuditPolicy.default()
    redacted = policy.redact(
        {
            "email": "a@b.c",
            "password": "hunter2",
            "api_key": "k",
            "nested": {"access_token": "t", "ok": "kept"},
            "items": [{"private_key": "pk", "label": "visible"}],
            "tupled": ({"secret": "s"},),
        }
    )
    assert redacted["email"] == "a@b.c"
    assert redacted["password"] == "***redacted***"
    assert redacted["api_key"] == "***redacted***"
    assert redacted["nested"] == {"access_token": "***redacted***", "ok": "kept"}
    assert redacted["items"] == [{"private_key": "***redacted***", "label": "visible"}]
    assert redacted["tupled"] == ({"secret": "***redacted***"},)
    # Empty / absent payloads normalize to None.
    assert policy.redact(None) is None
    assert policy.redact({}) is None


def test_policy_redact_keys_are_overridable() -> None:
    policy = AuditPolicy(redact_keys=("ssn",))
    redacted = policy.redact({"ssn": "123", "password": "kept-not-in-keys"})
    assert redacted == {"ssn": "***redacted***", "password": "kept-not-in-keys"}


# --------------------------------------------------------------------------- #
# actor binding (request-scoped, leak-free)
# --------------------------------------------------------------------------- #
def test_bind_audit_actor_sets_then_resets() -> None:
    actor = uuid.uuid4()
    assert audit_actor_ctx.get() is None
    with bind_audit_actor(actor):
        assert audit_actor_ctx.get() == actor
    # Leaving the block runs the reset (no leak across the boundary).
    assert audit_actor_ctx.get() is None


def test_bind_audit_actor_nested_scope_restores_prior_actor() -> None:
    outer, inner = uuid.uuid4(), uuid.uuid4()
    with bind_audit_actor(outer):
        assert audit_actor_ctx.get() == outer
        with bind_audit_actor(inner):
            assert audit_actor_ctx.get() == inner
        assert audit_actor_ctx.get() == outer
    assert audit_actor_ctx.get() is None


# --------------------------------------------------------------------------- #
# emit_audit chokepoint
# --------------------------------------------------------------------------- #
def test_emit_audit_builds_record_from_context() -> None:
    records, sink = _collecting_sink()
    configure_audit(AuditPolicy.default(), sink=sink)
    actor = uuid.uuid4()
    actor_token = audit_actor_ctx.set(actor)
    rid_token = request_id_ctx.set("req-123")
    try:
        emit_audit(
            None,
            action=AuditAction.CREATED,
            target_type="Note",
            target_id="n1",
            payload={"secret": "s", "kept": "k"},
        )
    finally:
        audit_actor_ctx.reset(actor_token)
        request_id_ctx.reset(rid_token)

    assert len(records) == 1
    record = records[0]
    assert record.action is AuditAction.CREATED
    assert record.target_type == "Note"
    assert record.target_id == "n1"
    assert record.actor_id == actor
    assert record.request_id == "req-123"
    # Redaction happens centrally, before the sink ever sees the payload.
    assert record.payload == {"secret": "***redacted***", "kept": "k"}


def test_emit_audit_is_a_noop_when_disabled() -> None:
    records, sink = _collecting_sink()
    configure_audit(AuditPolicy.disabled(reason="off for this test"), sink=sink)
    emit_audit(None, action=AuditAction.DELETED, target_type="Note", target_id="n1")
    assert records == []


def test_default_sink_is_log_only(caplog: pytest.LogCaptureFixture) -> None:
    # configure_audit with no sink falls back to the structured log sink.
    configure_audit(AuditPolicy.default())
    with caplog.at_level("INFO", logger="terp.core.audit"):
        emit_audit(None, action=AuditAction.UPDATED, target_type="Task", target_id="t1")
    assert any(record.message == "audit_event" for record in caplog.records)


def test_set_audit_sink_swaps_only_the_sink() -> None:
    records, sink = _collecting_sink()
    configure_audit(AuditPolicy.default())
    set_audit_sink(sink)
    emit_audit(None, action=AuditAction.CREATED, target_type="Note", target_id="n2")
    assert [record.target_id for record in records] == ["n2"]


def test_durable_audit_sink_marker_wraps_a_sink() -> None:
    records, sink = _collecting_sink()
    durable = DurableAuditSink(name="test.sink", sink=sink)
    assert is_durable_audit_sink(durable) is True
    assert is_durable_audit_sink(sink) is False
    durable(None, AuditRecord(AuditAction.CREATED, "Note", "n"), AuditPolicy.default())
    assert [record.target_id for record in records] == ["n"]


def test_durable_audit_sink_name_must_be_non_empty() -> None:
    _, sink = _collecting_sink()
    with pytest.raises(ValueError, match="non-empty"):
        DurableAuditSink(name=" ", sink=sink)


def test_reset_audit_runtime_restores_defaults() -> None:
    records, sink = _collecting_sink()
    configure_audit(AuditPolicy.disabled(reason="x"), sink=sink)
    reset_audit_runtime()
    # After reset the default (enabled) policy + log sink are active again.
    emit_audit(None, action=AuditAction.CREATED, target_type="Note", target_id="n3")
    assert records == []  # the collecting sink was reset away
