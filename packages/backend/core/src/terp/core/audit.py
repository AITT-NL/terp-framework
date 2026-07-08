"""Audit auto-emit: the seam every mutation flows through (Tier-A control).

Audit is a **mandatory** cross-cutting control (design §10, ADR 0006): no business
app should silently mutate state without a trail of *who did what, when*. Terp
makes that trail unbypassable by emitting it from the **single**
:class:`~terp.core.base_service.BaseService` write chokepoint, so a module gets an
audit trail with **zero wiring**.

Layering: ``terp.core`` (layer 0) must not depend on a capability, so this module
defines only the **seam** — a typed :class:`AuditRecord`, an :class:`AuditPolicy`
registry with a safe default (audit every mutation), and an emit function whose
default sink merely *logs* (a structured, redacted line; no persistence). The
durable sink — an append-only table — is supplied by the opt-in
``terp.capabilities.audit`` capability and installed by ``create_app`` (just like
``get_principal`` is the auth seam and ``base_query`` is the tenancy seam).

Two-layer enforcement: the runtime half is this fail-closed auto-emit (every
``BaseService`` create/update/delete calls :func:`emit_audit`, and a sink that
raises aborts the business transaction). The build-time half is the
``terp.arch`` ``mutations_emit_audit`` rule, which forbids a module from writing
to the session outside the audited chokepoint. Turning audit off is an explicit,
justified act — :meth:`AuditPolicy.disabled` — never a silent omission.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from enum import Enum
from typing import Any, Final

from sqlmodel import Session

from terp.core.logging import get_request_id

_logger = logging.getLogger("terp.core.audit")

# The acting subject for the current request, bound by :func:`bind_audit_actor`
# (a dependency ``create_app`` mounts on every router) and read by
# :func:`emit_audit`. ``None`` outside a request or for an unauthenticated call.
audit_actor_ctx: ContextVar[uuid.UUID | None] = ContextVar(
    "terp_audit_actor", default=None
)

# Default substrings that mark a payload key as carrying credential material; the
# value is masked before the record is persisted or logged. Overridable per app
# via :attr:`AuditPolicy.redact_keys` (Tier-B: the shape is fixed, the content is
# the consumer's).
_DEFAULT_REDACT_KEYS: Final[tuple[str, ...]] = (
    "password",
    "passwd",
    "secret",
    "token",
    "authorization",
    "api_key",
    "apikey",
    "private_key",
)

_REDACTED: Final[str] = "***redacted***"


class AuditAction(str, Enum):
    """The lifecycle action an audit record describes (a typed object, never a bare string)."""

    CREATED = "created"
    UPDATED = "updated"
    DELETED = "deleted"


@dataclass(frozen=True)
class AuditRecord:
    """One audit fact: *actor* performed *action* on *target* at request *request_id*.

    Built centrally by :func:`emit_audit` from the write chokepoint and the
    request-scoped context, so a module never assembles one by hand.
    """

    action: AuditAction
    target_type: str
    target_id: str
    actor_id: uuid.UUID | None = None
    request_id: str | None = None
    payload: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class AuditPolicy:
    """The central audit registry — a Tier-A control with a safe default.

    The default audits **every** mutation. Redaction is centralized here
    (:attr:`redact_keys`) so a careless payload cannot leak a secret into the
    trail or the logs. Disabling audit is a conscious, greppable act
    (:meth:`disabled`) — a security control may not be silently absent.
    """

    enabled: bool = True
    redact_keys: tuple[str, ...] = _DEFAULT_REDACT_KEYS
    retention_days: int | None = None
    disabled_reason: str | None = None

    def __post_init__(self) -> None:
        if self.retention_days is not None and self.retention_days <= 0:
            raise ValueError("AuditPolicy.retention_days must be a positive number of days")
        if not self.enabled and not self.disabled_reason:
            raise ValueError(
                "a disabled AuditPolicy needs a reason; use AuditPolicy.disabled(reason=...)"
            )

    @classmethod
    def default(cls) -> AuditPolicy:
        """The safe default: audit every mutation with central redaction."""
        return cls()

    @classmethod
    def disabled(cls, *, reason: str) -> AuditPolicy:
        """Turn auditing off as an explicit, justified, greppable opt-out."""
        if not reason or not reason.strip():
            raise ValueError("AuditPolicy.disabled(reason=...) requires a non-empty justification")
        return cls(enabled=False, disabled_reason=reason.strip())

    def redact(self, payload: Mapping[str, Any] | None) -> dict[str, Any] | None:
        """Return a copy of *payload* with credential-bearing values masked."""
        if not payload:
            return None
        return {
            key: (
                _REDACTED if self._is_sensitive(str(key)) else self._redact_value(value)
            )
            for key, value in payload.items()
        }

    def _redact_value(self, value: Any) -> Any:
        if isinstance(value, Mapping):
            return {
                key: (
                    _REDACTED if self._is_sensitive(str(key)) else self._redact_value(item)
                )
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [self._redact_value(item) for item in value]
        if isinstance(value, tuple):
            return tuple(self._redact_value(item) for item in value)
        return value

    def _is_sensitive(self, key: str) -> bool:
        lowered = key.lower()
        return any(part in lowered for part in self.redact_keys)


# A sink persists (or otherwise records) one already-redacted audit record inside
# the caller's transaction. The default merely logs; the durable sink is provided
# by ``terp.capabilities.audit`` and installed via :func:`configure_audit`.
AuditSink = Callable[[Session, AuditRecord, AuditPolicy], None]


@dataclass(frozen=True)
class DurableAuditSink:
    """A callable audit sink explicitly declaring that it persists durably.

    Production boot refuses the log-only fallback *and* unmarked callables, so a
    placeholder ``lambda`` cannot accidentally satisfy the audit requirement. The
    durable audit capability wraps its real append-only-table sink in this marker.
    """

    name: str
    sink: AuditSink

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("DurableAuditSink.name must be non-empty")

    def __call__(self, session: Session, record: AuditRecord, policy: AuditPolicy) -> None:
        self.sink(session, record, policy)


def is_durable_audit_sink(sink: AuditSink | None) -> bool:
    """Return whether *sink* is an explicitly marked durable audit sink."""
    return isinstance(sink, DurableAuditSink)


def _log_sink(session: Session, record: AuditRecord, policy: AuditPolicy) -> None:
    """The default no-op-persistence sink: emit one structured, redacted log line.

    Defense-in-depth — even with no durable sink installed, the audit *intent* is
    captured in the logs (which already pass through the central redacting
    filter). The ``session`` is unused here; a persistent sink rides it.
    """
    _logger.info(
        "audit_event",
        extra={
            "audit_action": record.action.value,
            "audit_target_type": record.target_type,
            "audit_target_id": record.target_id,
            "audit_actor_id": str(record.actor_id) if record.actor_id else None,
            "audit_request_id": record.request_id,
            "audit_payload": record.payload,
        },
    )


_active_policy: AuditPolicy = AuditPolicy.default()
_active_sink: AuditSink = _log_sink


def configure_audit(policy: AuditPolicy, *, sink: AuditSink | None = None) -> None:
    """Install the active audit *policy* and *sink* (called once by ``create_app``).

    *sink* defaults to the structured-log sink, so an app that does not install
    ``terp.capabilities.audit`` still gets a logged trail. A capability supplies a
    durable sink (e.g. an append-only table) here.
    """
    global _active_policy, _active_sink
    _active_policy = policy
    _active_sink = sink if sink is not None else _log_sink


def set_audit_sink(sink: AuditSink) -> None:
    """Install just the audit *sink*, keeping the active policy (capability hook)."""
    global _active_sink
    _active_sink = sink


def reset_audit_runtime() -> None:
    """Restore the default policy + log sink (the composition-root/test baseline)."""
    global _active_policy, _active_sink
    _active_policy = AuditPolicy.default()
    _active_sink = _log_sink


def emit_audit(
    session: Session,
    *,
    action: AuditAction,
    target_type: str,
    target_id: str,
    payload: Mapping[str, Any] | None = None,
) -> None:
    """Emit one audit record for a mutation through the active sink (fail-closed).

    Called from the single ``BaseService`` write chokepoint, so every audited
    mutation produces a record with **zero** module wiring. The actor and request
    id are read from the request-scoped context; the payload is centrally redacted
    before it ever reaches the sink or the logs. Does nothing when the active
    :class:`AuditPolicy` is disabled (an explicit opt-out). A sink that raises
    propagates — the business transaction it rides is aborted rather than committed
    without its trail.
    """
    if not _active_policy.enabled:
        return
    record = AuditRecord(
        action=action,
        target_type=target_type,
        target_id=target_id,
        actor_id=audit_actor_ctx.get(),
        request_id=get_request_id(),
        payload=_active_policy.redact(payload),
    )
    _active_sink(session, record, _active_policy)


def current_actor_id() -> uuid.UUID | None:
    """Return the actor bound to the current request context, or ``None``.

    The public read seam over the actor binding :func:`bind_audit_actor` installs
    per request. A consumer-registered row-scope predicate (ADR 0017) that keys read
    visibility on the caller — e.g. "an owner sees their own private rows" — reads the
    actor here instead of threading a principal through service calls or touching the
    context var directly. ``None`` means no authenticated actor is bound (an anonymous
    or system context); a fail-closed predicate should treat it as matching nothing.
    """
    return audit_actor_ctx.get()


@contextmanager
def bind_audit_actor(actor_id: uuid.UUID | None) -> Iterator[None]:
    """Bind *actor_id* to the audit context for the duration of the block.

    ``create_app`` enters this (via an async dependency) for every request,
    resolving the caller through the ``get_principal`` seam, so an auto-emitted
    record knows *who* acted without a module ever threading the actor through its
    service calls. A non-HTTP caller (worker, script) can wrap a unit of work the
    same way. Implemented as a set/reset pair (not a bare ``set``) so the binding
    cannot leak across requests sharing a worker thread; enter and exit must run in
    the same context (an async dependency, not a threadpooled sync one).
    """
    token = audit_actor_ctx.set(actor_id)
    try:
        yield
    finally:
        audit_actor_ctx.reset(token)


__all__ = [
    "AuditAction",
    "AuditPolicy",
    "AuditRecord",
    "AuditSink",
    "DurableAuditSink",
    "audit_actor_ctx",
    "bind_audit_actor",
    "configure_audit",
    "current_actor_id",
    "emit_audit",
    "is_durable_audit_sink",
    "reset_audit_runtime",
    "set_audit_sink",
]
