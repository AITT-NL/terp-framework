"""The job catalog: a typed, NO-DRIFT background-work seam with a safe in-process default.

This is the kernel half of Terp's async/jobs design (ADR 0043, the design doc's
Phase 1): the small, typed, **serializable** ports a module uses to run a named unit
of work — now or later, in-process today or on a broker tomorrow — without ever
naming an engine. It is shaped exactly like the proven seams it sits beside: the
event bus (``EventDispatcher`` + ``EventCatalog`` + typed ``emit``, ADR 0008), the
throttle store (``ThrottleStore`` + ``InMemoryThrottleStore``, ADR 0036), and the
audit sink (``AuditSink`` + ``audit_actor_ctx``, ADR 0007).

``terp.core`` is layer 0, so this module imports **no** engine (no ``celery`` /
``redis`` / ``azure-*`` / ``apscheduler`` / ``multiprocessing`` / ``threading`` as a
runtime) — the import-linter contract and ``test_core_boundary`` fail the build on an
upward import. Concrete engines are opt-in capability packages a consumer wires at
``create_app(...)``; the durable outbox and the broker adapters are later ADRs. The
worker loop / context binder lives under :mod:`terp.core._internal.job_runtime` so a
module cannot import it (the ``no_internal_imports`` rule).

Two-layer enforcement of the no-drift guarantee (ADR 0006), mirroring the event bus:

* **Runtime (fail closed).** :func:`enqueue` accepts **only** a typed
  :class:`JobDefinition`, resolves the **canonical** catalog entry, and rejects an
  unknown name *or* a same-name *shadow* (a look-alike with a different
  handler/schema) with a :class:`JobError` — exactly as :func:`terp.core.emit` rejects
  a non-catalog event. ``create_app`` boot-validates every ``ModuleSpec.jobs`` against
  the catalog (an undeclared reference fails the boot).
* **Build time.** The ``terp.arch`` ``jobs_reference_catalog`` rule forbids a
  bare-string or inline-literal job anywhere ``enqueue`` / ``ModuleSpec`` names one.

Context propagation (the design's §7, the highest-risk integration point) lives in the
runtime: a :class:`JobEnvelope` **carries** the originating ``actor_id`` / ``tenant_id``
/ ``request_id`` captured at enqueue time, and the runner **re-binds** them before
invoking the handler — so every write a job makes is still audited and actor / tenant
stamped, with a configured **system actor** standing in when no user originated the
work.
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import TYPE_CHECKING, Any, Final

from sqlmodel import Session

from terp.core.audit import audit_actor_ctx
from terp.core.logging import get_request_id

if TYPE_CHECKING:  # pragma: no cover - typing only, no runtime import of the type
    from collections.abc import Iterable, Mapping


def _is_dotted_token(value: str) -> bool:
    """True for dotted job names like ``sync.customers.pull`` (mirrors the event rule)."""
    if not value:
        return False
    return all(
        part and part.replace("_", "").replace("-", "").isalnum()
        for part in value.split(".")
    )


def _utc_now() -> datetime:
    """UTC ``now`` provider for the enqueue stamp (private so tests can patch it)."""
    return datetime.now(UTC)


class JobVisibility(str, Enum):
    """Who may see a job's payload (a typed object, never a bare string).

    Mirrors :class:`~terp.core.EventVisibility`: the axis an adapter / dashboard MUST
    check before surfacing a payload. It is **advisory metadata, not yet an enforced
    gate** — a future broker / dashboard adapter is responsible for honoring it
    (failing closed on a non-``PUBLIC`` payload); the in-process runner never relays a
    payload outward.
    """

    PUBLIC = "public"  # safe to surface outward
    INTERNAL = "internal"  # backend workers only
    RESTRICTED = "restricted"  # never relayed verbatim (may carry PII/secrets)


@dataclass(frozen=True)
class RetryPolicy:
    """How a durable runner should retry a failing job (carried, not run, in Phase 1).

    The in-process default executes a job once and lets a failure propagate (fail
    closed); a later durable outbox / broker adapter reads this policy to retry with
    exponential backoff and dead-letter after ``max_attempts``. It is declared up front
    so a handler's retry semantics travel with its :class:`JobDefinition` and do not
    change when the engine does.
    """

    max_attempts: int = 5
    backoff_seconds: float = 2.0
    backoff_multiplier: float = 2.0  # exponential
    max_backoff_seconds: float = 300.0
    retry_on: tuple[type[BaseException], ...] = (Exception,)

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("RetryPolicy.max_attempts must be at least 1")
        if self.backoff_seconds < 0 or self.max_backoff_seconds < 0:
            raise ValueError("RetryPolicy backoff seconds must be non-negative")


@dataclass(frozen=True)
class JobDefinition:
    """A typed job contract: a namespaced *name*, a *payload schema*, and a *handler*.

    The only thing :func:`enqueue` accepts — so every job has a validated payload model
    and an explicit, **named** handler (never a closure shipped to a remote worker),
    and a module references a declared catalog constant rather than minting a string.
    Declare these once in the control plane's job catalog. The handler is resolved **by
    name** through the catalog, so the same definition works in-process today and over a
    broker tomorrow (portability rule 1: named + catalog-registered).
    """

    name: str
    payload_schema: type
    handler: Callable[[JobContext, Any], None]
    retry: RetryPolicy = field(default_factory=RetryPolicy)
    queue: str = "default"  # routing hint; an adapter may map it to a real queue/topic
    visibility: JobVisibility = JobVisibility.INTERNAL

    def __post_init__(self) -> None:
        if not _is_dotted_token(self.name):
            raise ValueError(
                f"JobDefinition.name must be a dotted token, got {self.name!r}"
            )
        if not hasattr(self.payload_schema, "model_validate"):
            raise TypeError(
                f"JobDefinition.payload_schema must be a model type with "
                f"model_validate (e.g. a BaseSchema), got {self.payload_schema!r}"
            )
        if not callable(self.handler):
            raise TypeError(
                f"JobDefinition.handler must be callable, got {self.handler!r}"
            )


@dataclass(frozen=True)
class JobEnvelope:
    """One unit of queued work — what crosses the wire, so it must be JSON-serializable.

    Built centrally by :func:`enqueue` from a :class:`JobDefinition`, the validated
    payload, and the request-scoped context. It carries **ids, not entities** (portability
    rule 2) and, crucially (the design's §7), the originating ``actor_id`` / ``tenant_id``
    / ``request_id`` so the runner can re-bind the context a background worker otherwise
    lacks — keeping the job's writes audited and tenant-isolated.
    """

    name: str
    payload: Mapping[str, Any]
    idempotency_key: str | None = None
    actor_id: uuid.UUID | None = None
    tenant_id: uuid.UUID | None = None
    request_id: str | None = None
    enqueued_at: datetime = field(default_factory=_utc_now)
    attempt: int = 1


@dataclass(frozen=True)
class JobContext:
    """The bound context a handler runs inside: the session plus the re-bound identity.

    Handed to the handler by the runner, after it has opened a session and re-bound the
    envelope's actor / tenant / request id. A handler reads ``session`` to persist
    through the audited ``BaseService`` chokepoint (so its writes are audited + stamped
    with no special-casing) and inspects ``attempt`` for idempotency. To chain work it
    calls the typed :func:`enqueue` chokepoint (``enqueue(ctx.session, job=…, payload=…)``)
    — never a raw queue — so a follow-up job carries the same no-drift guarantee. It must
    **not** read ambient request state — there is none in a worker (portability rule 5).
    """

    session: Session
    actor_id: uuid.UUID | None = None
    tenant_id: uuid.UUID | None = None
    request_id: str | None = None
    attempt: int = 1


@dataclass(frozen=True)
class JobCatalog:
    """The central registry of every :class:`JobDefinition` an app may enqueue.

    Mirrors :class:`~terp.core.EventCatalog`: the default is **empty** (no jobs), and
    when jobs are used this is the single source of truth they reference — a module
    cannot enqueue anything not declared here. Duplicate names are rejected.
    """

    jobs: tuple[JobDefinition, ...] = ()

    def __post_init__(self) -> None:
        jobs = tuple(self.jobs)
        by_name: dict[str, JobDefinition] = {}
        for definition in jobs:
            if definition.name in by_name:
                raise ValueError(f"duplicate job declaration: {definition.name!r}")
            by_name[definition.name] = definition
        object.__setattr__(self, "jobs", jobs)
        object.__setattr__(self, "_by_name", by_name)

    @classmethod
    def default(cls) -> JobCatalog:
        """The compatibility catalog: empty — no jobs are declared."""
        return cls()

    def has_name(self, name: str) -> bool:
        """Return whether a job with *name* is registered."""
        return name in self._by_name

    def get(self, name: str) -> JobDefinition | None:
        """Return the canonical definition registered for *name* (or ``None``)."""
        return self._by_name.get(name)

    def has_job(self, definition: JobDefinition) -> bool:
        """Return whether *definition* is the canonical one registered for its name.

        Matched by **value**, not just by name: a same-name definition with a different
        handler / schema is a *shadow* and is rejected, so the catalog stays the one
        source of truth (no drift through a look-alike).
        """
        return self._by_name.get(definition.name) == definition

    def missing_jobs(
        self, definitions: Iterable[JobDefinition]
    ) -> tuple[JobDefinition, ...]:
        """Every definition not registered in this catalog."""
        return tuple(d for d in definitions if not self.has_job(d))

    def names(self) -> tuple[str, ...]:
        """The registered job names, in declaration order."""
        return tuple(d.name for d in self.jobs)


class JobError(RuntimeError):
    """Raised when :func:`enqueue` is given a job that is not the registered catalog entry.

    Covers both an unknown name and a same-name shadow (different handler / schema) —
    either way the enqueue is fail-closed, mirroring :class:`~terp.core.EventError`.
    """


class JobQueue(ABC):
    """A backend that accepts an enqueued :class:`JobEnvelope` and returns a job id.

    The single port every adapter implements. :meth:`enqueue` receives the caller's
    ``session`` **on purpose**: a durable adapter writes its outbox row in the *same
    transaction* as the business write (no dual-write), while the in-process default
    ignores the session for execution and runs the handler in its own audited unit. An
    implementation must be safe to call from a request handler and must never block the
    request on remote I/O beyond what the consumer accepts.
    """

    @abstractmethod
    def enqueue(self, session: Session, envelope: JobEnvelope) -> str:
        """Accept *envelope* for execution and return an opaque job id."""


class InProcessJobQueue(JobQueue):
    """The default queue: run the handler **inline**, in its own audited unit of work.

    Zero infra — dev / test / single-process behave exactly as before. It does not use
    the caller's ``session`` (so it never commits the request's partial work); instead
    it opens a fresh session from *session_factory* (the request-style write-guarded
    session by default) and runs the job through
    :func:`terp.core._internal.job_runtime.run_job`, which re-binds the envelope's actor
    / tenant / request id first. A failing handler propagates (the unit rolls back) —
    fail closed; retries and durability are the later outbox adapter's job. The clock /
    session are injectable for tests, mirroring :class:`~terp.core.InMemoryThrottleStore`.

    Run **synchronously**, not on a threadpool: the layer-0 boundary forbids ``threading``
    as a runtime in core, and a deployment that needs real off-request execution wires a
    durable / broker adapter instead.
    """

    def __init__(self, *, session_factory: Callable[[], Session] | None = None) -> None:
        self._session_factory = session_factory

    def enqueue(self, session: Session, envelope: JobEnvelope) -> str:
        # Imported lazily so terp.core.jobs (the public types) does not import the
        # internal runner at module load (and a module cannot reach the runner at all).
        from terp.core._internal.job_runtime import run_job

        run_job(envelope, session_factory=self._session_factory)
        return envelope.idempotency_key or f"{envelope.name}:{envelope.enqueued_at.isoformat()}"


# A marker stamped on a durable, restart-surviving job queue (e.g. an outbox-backed
# adapter), so ``create_app(require_durable_jobs=True)`` can fail closed at boot when the
# in-process default is wired in production. Mirrors the durable-audit-sink and
# shared-throttle-store boot markers (ADR 0007/0036/0040): a backend stamps it, the kernel
# boot guard checks it, neither imports the other. InProcessJobQueue is deliberately
# *unmarked* — it loses queued work on restart.
_DURABLE_QUEUE_ATTR: Final[str] = "__terp_durable_job_queue__"


def mark_durable_job_queue(queue: JobQueue) -> JobQueue:
    """Mark *queue* as a durable, restart-surviving backend, and return it.

    A durable adapter (a future ``terp-cap-outbox`` / broker queue) wraps itself with
    this so ``create_app(require_durable_jobs=True)`` accepts it; the in-process default
    stays unmarked (and would lose jobs on restart).
    """
    setattr(queue, _DURABLE_QUEUE_ATTR, True)
    return queue


def is_durable_job_queue(queue: JobQueue | None) -> bool:
    """Return whether *queue* is marked as a durable, restart-surviving backend."""
    return bool(getattr(queue, _DURABLE_QUEUE_ATTR, False))


# The seam a scope capability (tenancy) fills so a job carries + restores the caller's
# tenant without core importing the capability — the job-side analogue of
# ``register_scope_predicate`` (ADR 0017). ``read`` captures the ambient tenant at
# enqueue (into the envelope); ``bind`` re-binds it for the handler at run time. Both stay
# ``None`` until a capability registers them, so a single-tenant app is unaffected.
_TenantReader = Callable[[], uuid.UUID | None]
_TenantBinder = Callable[[uuid.UUID | None], AbstractContextManager[None]]

_active_catalog: JobCatalog = JobCatalog.default()
_active_queue: JobQueue = InProcessJobQueue()
_system_actor_id: uuid.UUID | None = None
_tenant_reader: _TenantReader | None = None
_tenant_binder: _TenantBinder | None = None


def register_job_tenant_context(
    *, read: _TenantReader, bind: _TenantBinder
) -> None:
    """Register how a job captures + restores the caller's tenant (a scope-capability seam).

    The tenancy capability supplies ``read`` (the current-tenant getter, captured into the
    envelope at :func:`enqueue`) and ``bind`` (a context manager the runner opens around
    the handler), so a job's reads/writes stay tenant-isolated without the kernel importing
    tenancy. Registration replaces any previous pair; it is a capability registration (like
    a scope predicate), so it persists across composed apps and is cleared only by
    :func:`reset_job_tenant_context`.
    """
    global _tenant_reader, _tenant_binder
    _tenant_reader = read
    _tenant_binder = bind


def active_job_catalog() -> JobCatalog:
    """The catalog the jobs runtime currently enforces (set by ``create_app``)."""
    return _active_catalog


def active_job_queue() -> JobQueue:
    """The queue the jobs runtime currently dispatches to (the in-process default by default)."""
    return _active_queue


def active_job_system_actor() -> uuid.UUID | None:
    """The configured stand-in actor for a job that no user originated (or ``None``)."""
    return _system_actor_id


def active_job_tenant_binder() -> _TenantBinder | None:
    """The registered tenant binder the runner opens around a handler (or ``None``)."""
    return _tenant_binder


def configure_jobs(
    catalog: JobCatalog,
    *,
    queue: JobQueue | None = None,
    system_actor_id: uuid.UUID | None = None,
) -> None:
    """Install the active job *catalog*, *queue*, and *system_actor_id* (called by ``create_app``).

    *queue* defaults to a fresh :class:`InProcessJobQueue` (so an app that declares jobs
    but wires no adapter still runs them inline). *system_actor_id* is the control-plane
    default actor a job runs as when no user originated it, so audit / ownership stamping
    is never silently ``None`` in production. Mirrors :func:`terp.core.configure_events`.
    """
    global _active_catalog, _active_queue, _system_actor_id
    _active_catalog = catalog
    _active_queue = queue if queue is not None else InProcessJobQueue()
    _system_actor_id = system_actor_id


def reset_jobs_runtime() -> None:
    """Restore the empty catalog + in-process queue + no system actor (per-app runtime).

    The composition-root / test baseline (the autouse fixture calls it), mirroring
    :func:`terp.core.reset_events_runtime`. The tenant-context seam is a separate
    capability registration (like a scope predicate), so it is **not** cleared here — it
    has its own :func:`reset_job_tenant_context`, and a capability that registers it at
    import survives across composed apps.
    """
    global _active_catalog, _active_queue, _system_actor_id
    _active_catalog = JobCatalog.default()
    _active_queue = InProcessJobQueue()
    _system_actor_id = None


def reset_job_tenant_context() -> None:
    """Clear the registered tenant-context seam (a test seam; capabilities re-register on import).

    Mirrors :func:`terp.core.scoping.reset_scope_predicates`: the tenant seam is a
    capability registration, not per-app runtime, so resetting it is separate from
    :func:`reset_jobs_runtime`.
    """
    global _tenant_reader, _tenant_binder
    _tenant_reader = None
    _tenant_binder = None


def _validate_payload(definition: JobDefinition, payload: Any) -> dict[str, Any]:
    """Validate *payload* against the definition's schema and return a JSON dict.

    Round-trips through ``model_dump(mode="json")`` so the envelope payload is pure JSON
    (portability rule 2: no ORM rows / Python objects cross the wire).
    """
    schema = definition.payload_schema
    if payload is None:
        validated = schema()
    elif hasattr(payload, "model_dump"):
        validated = schema.model_validate(payload.model_dump())
    else:
        validated = schema.model_validate(payload)
    return dict(validated.model_dump(mode="json"))


def enqueue(
    session: Session,
    *,
    job: JobDefinition,
    payload: Any,
    idempotency_key: str | None = None,
) -> str:
    """Enqueue one catalog *job* through the active queue (fail closed).

    The single producer chokepoint a module calls — the job analogue of
    :func:`terp.core.emit`. *job* is a typed :class:`JobDefinition` (never a string), and
    it must **match** its registered :class:`JobCatalog` entry — an unknown name *or* a
    same-name shadow (different handler / schema) raises :class:`JobError` rather than
    drifting through. The payload is validated against the **catalog's** canonical schema,
    and the originating actor / tenant / request id are captured into the
    :class:`JobEnvelope` so the runner can re-bind them (the design's §7). Returns the
    queue's opaque job id. The in-process default runs the handler inline in its own
    audited unit; a durable adapter persists the envelope on *session* for a worker to
    drain — neither changes this call site.
    """
    registered = _active_catalog.get(job.name)
    if registered is None:
        raise JobError(
            f"job {job.name!r} is not registered in the JobCatalog; "
            "declare it in the control plane's jobs before enqueuing it"
        )
    if registered != job:
        raise JobError(
            f"job {job.name!r} does not match its registered catalog definition "
            "(handler or payload schema differ); reference the catalog constant "
            "rather than redefining it"
        )
    envelope = JobEnvelope(
        name=registered.name,
        payload=_validate_payload(registered, payload),
        idempotency_key=idempotency_key,
        actor_id=audit_actor_ctx.get(),
        tenant_id=_tenant_reader() if _tenant_reader is not None else None,
        request_id=get_request_id(),
    )
    return _active_queue.enqueue(session, envelope)


__all__ = [
    "InProcessJobQueue",
    "JobCatalog",
    "JobContext",
    "JobDefinition",
    "JobEnvelope",
    "JobError",
    "JobQueue",
    "JobVisibility",
    "RetryPolicy",
    "active_job_catalog",
    "active_job_queue",
    "active_job_system_actor",
    "active_job_tenant_binder",
    "configure_jobs",
    "enqueue",
    "is_durable_job_queue",
    "mark_durable_job_queue",
    "register_job_tenant_context",
    "reset_job_tenant_context",
    "reset_jobs_runtime",
]
