"""Gate for the lease seam (ADR 0095): the fence, the expiry, the reaper, and the boot guard.

The whole primitive rests on three claims, and each is tested as a claim rather than as a
happy path:

* **Exclusivity** — a second holder is refused while a lease is live, and *granted* once it
  lapses, with a bumped epoch.
* **The fence** — a holder whose lease lapsed and was re-granted can no longer renew,
  release or forfeit. This is the property expiry alone does not give, and it is what stops
  a paused worker from writing over its successor.
* **Recovery** — an expired lease's registered reaper runs and the lease is forfeited in
  **one** transaction, so a cycle can neither re-run a completed recovery forever nor lose
  the record that work needs picking up.

The durable :class:`DatabaseLeaseStore` is driven over a real SQLite engine (including a
lease taken inside a ``BaseService`` write, which proves the atomicity claim by rolling both
back together), while the in-memory store is held to the identical contract so the seam's
semantics cannot drift between them.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Field, Session, SQLModel, create_engine, select

from terp.core import (
    BaseSchema,
    BaseService,
    BaseTable,
    BaseUpdateSchema,
    BootError,
    ControlPlane,
    InMemoryLeaseStore,
    JobCatalog,
    JobContext,
    Lease,
    LeaseError,
    LeaseGuard,
    LeaseHeldError,
    LeaseLostError,
    LeaseResource,
    LeaseStore,
    Principal,
    Roles,
    acquire_lease,
    active_lease_store,
    create_app,
    expired_leases,
    forfeit_lease,
    hold_lease,
    is_durable_lease_store,
    lease_reaper_for,
    mark_durable_lease_store,
    purge_free_leases,
    register_lease_reaper,
    release_lease,
    renew_lease,
)
from terp.core._internal.session_guard import WriteGuardedSession
from terp.core.db import get_session
from terp.core.jobs import configure_jobs
from terp.core.leases import (
    LEASE_HOLDER_MAX,
    LEASE_KEY_MAX,
    LEASE_KIND_MAX,
    configure_leases,
    registered_lease_reapers,
    reset_lease_reapers,
    reset_leases_runtime,
)
from terp.core.runtime import capture_runtimes, reset_runtimes, restore_runtimes

from terp.capabilities.leases import (
    LEASE_REAP,
    DatabaseLeaseStore,
    LeaseReapPayload,
    ReapResult,
    ResourceLease,
    ResourceLeaseRead,
    lease_reap_schedule,
    list_leases,
    reap_expired_leases,
    reap_now,
)
from terp.capabilities.leases.router import module as leases_module

_T0 = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)
_ADMIN = Principal(id=uuid.uuid4(), role=Roles.ADMIN)


class _Clock:
    """A mutable, injectable clock so a lease can lapse without anyone sleeping."""

    def __init__(self, now: datetime = _T0) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now = self.now + timedelta(seconds=seconds)


# --------------------------------------------------------------------------- #
# A synthetic "queue" table whose stale claims are what a reaper walks back.
# --------------------------------------------------------------------------- #
class _Ticket(BaseTable, table=True):
    __tablename__ = "_lease_ticket"
    status: str = Field(default="queued", max_length=16)


class _TicketCreate(BaseSchema):
    status: str = Field(default="queued", max_length=16)


class _TicketUpdate(BaseUpdateSchema):
    status: str | None = Field(default=None, max_length=16)


class _TicketService(BaseService[_Ticket, _TicketCreate, _TicketUpdate]):
    model = _Ticket


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture
def engine() -> Iterator[object]:
    """An in-memory SQLite engine on one shared connection (the router shares it)."""
    eng = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    SQLModel.metadata.create_all(eng)
    try:
        yield eng
    finally:
        eng.dispose()


@pytest.fixture
def clock() -> _Clock:
    return _Clock()


@pytest.fixture
def store(clock: _Clock) -> Iterator[DatabaseLeaseStore]:
    """The durable store wired as the app's lease seam (as ``create_app`` would)."""
    backend = DatabaseLeaseStore(clock=clock)
    configure_leases(backend)
    yield backend
    reset_leases_runtime()


@pytest.fixture(autouse=True)
def _clean_reapers() -> Iterator[None]:
    """Snapshot the process-global reaper registry, and put it back afterwards.

    Clearing it outright would be wrong in the way :mod:`terp.core.runtime` warns about: a
    reaper is a *capability* registration installed at import and meant to outlive a composed
    app, so a test that wipes it silently disarms every capability that registered one — and
    the damage lands on whatever runs next, not here.
    """
    before = dict(registered_lease_reapers())
    reset_lease_reapers()
    yield
    reset_lease_reapers()
    for kind, reaper in before.items():
        register_lease_reaper(kind, reaper)


def _resource(key: str = "p1", kind: str = "pipeline") -> LeaseResource:
    return LeaseResource(kind=kind, key=key)


# --------------------------------------------------------------------------- #
# (1) The vocabulary: resources, leases, validation
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("kind", "key"),
    [("", "k"), ("   ", "k"), ("pipeline", ""), ("pipeline", "  ")],
)
def test_a_resource_refuses_an_empty_kind_or_key(kind: str, key: str) -> None:
    with pytest.raises(ValueError, match="non-empty"):
        LeaseResource(kind=kind, key=key)


@pytest.mark.parametrize(
    ("kind", "key"),
    [("k" * (LEASE_KIND_MAX + 1), "x"), ("pipeline", "k" * (LEASE_KEY_MAX + 1))],
)
def test_a_resource_refuses_a_value_past_its_column_bound(kind: str, key: str) -> None:
    # Fails in Python naming the field, rather than mid-transaction on a backend that
    # enforces VARCHAR(n) while SQLite quietly accepted it in the tests.
    with pytest.raises(ValueError, match="exceeding its"):
        LeaseResource(kind=kind, key=key)


def test_for_row_derives_the_resource_from_the_table_and_primary_key() -> None:
    ticket = _Ticket()
    resource = LeaseResource.for_row(ticket)
    assert resource == LeaseResource(kind="_lease_ticket", key=str(ticket.id))
    assert str(resource) == f"_lease_ticket:{ticket.id}"


def test_for_row_refuses_something_that_is_not_a_table_row() -> None:
    with pytest.raises(TypeError, match="__tablename__ and id"):
        LeaseResource.for_row(object())


def test_a_lease_reports_its_expiry_and_never_a_negative_remainder() -> None:
    lease = Lease(resource=_resource(), holder="w1", epoch=1, expires_at=_T0)
    assert lease.is_expired(_T0) is True  # the boundary counts as expired
    assert lease.is_expired(_T0 - timedelta(seconds=1)) is False
    assert lease.remaining(_T0 + timedelta(seconds=30)) == timedelta(0)
    assert lease.remaining(_T0 - timedelta(seconds=5)) == timedelta(seconds=5)


# --------------------------------------------------------------------------- #
# (2) The store contract — asserted identically for both implementations
# --------------------------------------------------------------------------- #
@pytest.fixture(params=["memory", "database"])
def any_store(request: pytest.FixtureRequest, clock: _Clock) -> LeaseStore:
    """Both stores, so the seam's semantics cannot drift between them."""
    if request.param == "memory":
        return InMemoryLeaseStore(clock=clock)
    return DatabaseLeaseStore(clock=clock)


def test_one_holder_wins_and_the_second_is_refused(
    any_store: LeaseStore, engine: object, clock: _Clock
) -> None:
    with Session(engine) as session:  # type: ignore[arg-type]
        first = any_store.acquire(session, _resource(), holder="w1", ttl_seconds=60)
        assert first is not None and first.epoch == 1
        assert any_store.acquire(session, _resource(), holder="w2", ttl_seconds=60) is None


def test_an_expired_lease_is_regranted_with_a_bumped_epoch(
    any_store: LeaseStore, engine: object, clock: _Clock
) -> None:
    with Session(engine) as session:  # type: ignore[arg-type]
        first = any_store.acquire(session, _resource(), holder="w1", ttl_seconds=60)
        assert first is not None
        clock.advance(61)
        second = any_store.acquire(session, _resource(), holder="w2", ttl_seconds=60)
        assert second is not None
        # The bumped epoch is the fence: w1's grant is now provably stale.
        assert second.epoch == first.epoch + 1 and second.holder == "w2"


def test_renewing_extends_the_lease_for_the_same_holder_and_epoch(
    any_store: LeaseStore, engine: object, clock: _Clock
) -> None:
    with Session(engine) as session:  # type: ignore[arg-type]
        lease = any_store.acquire(session, _resource(), holder="w1", ttl_seconds=60)
        assert lease is not None
        clock.advance(30)
        renewed = any_store.renew(session, lease, ttl_seconds=60)
        assert renewed is not None
        assert renewed.expires_at > lease.expires_at
        assert renewed.epoch == lease.epoch  # a renewal is not a new grant


def test_renewing_an_already_expired_lease_is_refused_not_resurrected(
    any_store: LeaseStore, engine: object, clock: _Clock
) -> None:
    with Session(engine) as session:  # type: ignore[arg-type]
        lease = any_store.acquire(session, _resource(), holder="w1", ttl_seconds=60)
        assert lease is not None
        clock.advance(61)
        assert any_store.renew(session, lease, ttl_seconds=60) is None


def test_a_superseded_holder_can_neither_renew_nor_release_nor_forfeit(
    any_store: LeaseStore, engine: object, clock: _Clock
) -> None:
    with Session(engine) as session:  # type: ignore[arg-type]
        stale = any_store.acquire(session, _resource(), holder="w1", ttl_seconds=60)
        assert stale is not None
        clock.advance(61)
        successor = any_store.acquire(session, _resource(), holder="w2", ttl_seconds=60)
        assert successor is not None
        # This is the property expiry alone does not provide: w1 is alive, awake, and
        # holding a grant that the database now refuses to honour in any direction.
        assert any_store.renew(session, stale, ttl_seconds=60) is None
        assert any_store.release(session, stale) is False
        assert any_store.forfeit(session, stale) is False
        # ...and the successor is untouched by any of it.
        assert any_store.renew(session, successor, ttl_seconds=60) is not None


def test_releasing_frees_the_resource_for_the_next_holder(
    any_store: LeaseStore, engine: object
) -> None:
    with Session(engine) as session:  # type: ignore[arg-type]
        lease = any_store.acquire(session, _resource(), holder="w1", ttl_seconds=60)
        assert lease is not None
        assert any_store.release(session, lease) is True
        assert any_store.release(session, lease) is False  # already given back
        again = any_store.acquire(session, _resource(), holder="w2", ttl_seconds=60)
        assert again is not None and again.epoch == lease.epoch + 1


def test_releasing_an_expired_lease_nobody_took_still_hands_it_back(
    any_store: LeaseStore, engine: object, clock: _Clock
) -> None:
    # Finishing late is not the same as being superseded: while no successor exists the
    # holder may still close out cleanly, which is why release carries no expiry condition.
    with Session(engine) as session:  # type: ignore[arg-type]
        lease = any_store.acquire(session, _resource(), holder="w1", ttl_seconds=60)
        assert lease is not None
        clock.advance(61)
        assert any_store.release(session, lease) is True


def test_expired_lists_only_lapsed_held_leases_bounded_and_filtered(
    any_store: LeaseStore, engine: object, clock: _Clock
) -> None:
    with Session(engine) as session:  # type: ignore[arg-type]
        stale_a = any_store.acquire(session, _resource("a"), holder="w1", ttl_seconds=10)
        stale_b = any_store.acquire(
            session, _resource("b", kind="connection"), holder="w2", ttl_seconds=20
        )
        released = any_store.acquire(session, _resource("c"), holder="w3", ttl_seconds=10)
        assert stale_a and stale_b and released
        any_store.release(session, released)
        clock.advance(21)
        live = any_store.acquire(session, _resource("d"), holder="w4", ttl_seconds=600)
        assert live is not None

        found = any_store.expired(session)
        assert {str(lease.resource) for lease in found} == {"pipeline:a", "connection:b"}
        # Soonest-expiring first, so a backlog is worked oldest-pain-first.
        assert found[0].resource.key == "a"
        assert [lease.resource.key for lease in any_store.expired(session, limit=1)] == ["a"]
        by_kind = any_store.expired(session, kind="connection")
        assert [lease.resource.key for lease in by_kind] == ["b"]


def test_forfeit_clears_an_expired_lease_but_never_a_live_one(
    any_store: LeaseStore, engine: object, clock: _Clock
) -> None:
    with Session(engine) as session:  # type: ignore[arg-type]
        lease = any_store.acquire(session, _resource(), holder="w1", ttl_seconds=60)
        assert lease is not None
        assert any_store.forfeit(session, lease) is False  # still live: not the reaper's
        clock.advance(61)
        assert any_store.forfeit(session, lease) is True
        assert any_store.expired(session) == ()


def test_purge_deletes_only_free_records_idle_past_the_cutoff(
    any_store: LeaseStore, engine: object, clock: _Clock
) -> None:
    with Session(engine) as session:  # type: ignore[arg-type]
        done = any_store.acquire(session, _resource("a"), holder="w1", ttl_seconds=60)
        held = any_store.acquire(session, _resource("b"), holder="w2", ttl_seconds=60)
        assert done and held
        any_store.release(session, done)
        clock.advance(3600)
        assert any_store.purge(session, idle_seconds=1800) == 1
        # The held record survives however old it is — purging it would drop a live fence.
        assert any_store.acquire(session, _resource("b"), holder="w3", ttl_seconds=60)


@pytest.mark.parametrize("ttl", [0, -1, -0.5])
def test_a_non_positive_ttl_is_refused(
    any_store: LeaseStore, engine: object, ttl: float
) -> None:
    with Session(engine) as session:  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="positive number of seconds"):
            any_store.acquire(session, _resource(), holder="w1", ttl_seconds=ttl)
        lease = any_store.acquire(session, _resource(), holder="w1", ttl_seconds=60)
        assert lease is not None
        with pytest.raises(ValueError, match="positive number of seconds"):
            any_store.renew(session, lease, ttl_seconds=ttl)
        with pytest.raises(ValueError, match="positive number of seconds"):
            any_store.purge(session, idle_seconds=ttl)


@pytest.mark.parametrize("holder", ["", "   "])
def test_an_empty_holder_is_refused(
    any_store: LeaseStore, engine: object, holder: str
) -> None:
    with Session(engine) as session:  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="non-empty"):
            any_store.acquire(session, _resource(), holder=holder, ttl_seconds=60)


def test_an_over_long_holder_is_refused_by_the_seam(engine: object, clock: _Clock) -> None:
    store = InMemoryLeaseStore(clock=clock)
    with Session(engine) as session:  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="exceeding its"):
            store.acquire(
                session, _resource(), holder="w" * (LEASE_HOLDER_MAX + 1), ttl_seconds=60
            )


def test_a_non_positive_batch_limit_is_refused(
    any_store: LeaseStore, engine: object
) -> None:
    with Session(engine) as session:  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="limit must be positive"):
            any_store.expired(session, limit=0)


def test_the_in_memory_store_can_be_reset(engine: object, clock: _Clock) -> None:
    store = InMemoryLeaseStore(clock=clock)
    with Session(engine) as session:  # type: ignore[arg-type]
        assert store.acquire(session, _resource(), holder="w1", ttl_seconds=60)
        store.reset()
        # A reset store has forgotten the grant, so epoch restarts from 1.
        regranted = store.acquire(session, _resource(), holder="w2", ttl_seconds=60)
        assert regranted is not None and regranted.epoch == 1


# --------------------------------------------------------------------------- #
# (3) The durable store's own guarantees: atomicity and SKIP LOCKED
# --------------------------------------------------------------------------- #
class _ClaimingTicketService(_TicketService):
    """A service that claims a row and takes its lease in one audited write.

    The sanctioned shape: the lease is taken from ``_after_write``, so it joins the write
    unit ``_save`` opened and commits with the row change. ``holder`` is per-instance, the
    way a worker's id would be.
    """

    def __init__(self, holder: str) -> None:
        self._holder = holder

    def _after_write(self, session, entity, action):  # type: ignore[no-untyped-def]
        if entity.status == "claimed":
            hold_lease(
                session,
                LeaseResource.for_row(entity),
                holder=self._holder,
                ttl_seconds=60,
            )


def test_a_claim_and_its_lease_commit_as_one_write(engine: object, store: DatabaseLeaseStore) -> None:
    """The reason the store writes on the caller's session, stated as a test."""
    ticket_id = _queued_ticket(engine)
    with WriteGuardedSession(engine) as session:  # type: ignore[arg-type]
        row = _ClaimingTicketService("w1").get(session, ticket_id)
        _ClaimingTicketService("w1").update(
            session, ticket_id, _TicketUpdate(status="claimed", version=row.version)
        )
    with Session(engine) as session:  # type: ignore[arg-type]
        assert _ticket_status(engine, ticket_id) == "claimed"
        # ...and the lease landed in the same transaction.
        held = store.expired(session)
        assert held == ()  # not expired yet, but definitely taken:
        assert (
            store.acquire(
                session,
                LeaseResource(kind="_lease_ticket", key=str(ticket_id)),
                holder="w2",
                ttl_seconds=60,
            )
            is None
        )


def test_a_refused_lease_rolls_the_claim_back_so_the_row_never_reaches_claimed(
    engine: object, store: DatabaseLeaseStore
) -> None:
    """The payoff of doing it in one write: no compensating update, ever.

    A second worker's claim is refused *inside* the write unit, so the row it tried to take
    is left exactly as it was — rather than sitting in ``claimed`` while a follow-up update
    tries to put it back.
    """
    ticket_id = _queued_ticket(engine)
    with WriteGuardedSession(engine) as session:  # type: ignore[arg-type]
        row = _ClaimingTicketService("w1").get(session, ticket_id)
        _ClaimingTicketService("w1").update(
            session, ticket_id, _TicketUpdate(status="claimed", version=row.version)
        )
    assert _ticket_status(engine, ticket_id) == "claimed"

    with WriteGuardedSession(engine) as session:  # type: ignore[arg-type]
        row = _ClaimingTicketService("w2").get(session, ticket_id)
        with pytest.raises(LeaseHeldError):
            _ClaimingTicketService("w2").update(
                session, ticket_id, _TicketUpdate(status="claimed", version=row.version)
            )
        session.rollback()
    # w1 still holds it and the row was never rewritten by the loser.
    assert _ticket_status(engine, ticket_id) == "claimed"


def test_a_rolled_back_write_takes_its_lease_with_it(engine: object, store: DatabaseLeaseStore) -> None:
    """A claim that committed while the row change rolled back would leave the resource
    leased to a worker that never took the work — the mirror image of the orphan the seam
    exists to remove."""
    ticket_id = _queued_ticket(engine)

    class _Boom(RuntimeError):
        pass

    class _Failing(_ClaimingTicketService):
        def _after_write(self, session, entity, action):  # type: ignore[no-untyped-def]
            super()._after_write(session, entity, action)
            raise _Boom()

    with WriteGuardedSession(engine) as session:  # type: ignore[arg-type]
        row = _Failing("w1").get(session, ticket_id)
        with pytest.raises(_Boom):
            _Failing("w1").update(
                session, ticket_id, _TicketUpdate(status="claimed", version=row.version)
            )
        session.rollback()

    assert _ticket_status(engine, ticket_id) == "queued"
    with Session(engine) as session:  # type: ignore[arg-type]
        # The lease went with the write, so the resource is free for the next worker.
        assert store.acquire(
            session,
            LeaseResource(kind="_lease_ticket", key=str(ticket_id)),
            holder="w2",
            ttl_seconds=60,
        ) is not None


def test_skip_locked_is_a_contention_choice_not_a_correctness_one(
    engine: object, clock: _Clock
) -> None:
    """Both scans return the same lapsed set; SKIP LOCKED only changes who waits.

    SQLite cannot parse the clause, so the portable scan is the default and the flag is what
    a PostgreSQL deployment (or ``terp leases reap``) turns on — never something the
    capability decides by reaching for the connection.
    """
    portable = DatabaseLeaseStore(clock=clock)
    with Session(engine) as session:  # type: ignore[arg-type]
        assert portable.acquire(session, _resource(), holder="w1", ttl_seconds=10)
        clock.advance(11)
        assert [str(lease.resource) for lease in portable.expired(session)] == ["pipeline:p1"]


def test_the_first_acquire_creates_the_record_and_a_raced_insert_loses_cleanly(
    engine: object, clock: _Clock
) -> None:
    store = DatabaseLeaseStore(clock=clock)
    with Session(engine) as session:  # type: ignore[arg-type]
        assert store._find(session, _resource()) is None
        assert store.acquire(session, _resource(), holder="w1", ttl_seconds=60) is not None
        assert store._find(session, _resource()) is not None
        # A second store instance racing the same never-before-leased resource takes the
        # insert path, hits the unique constraint inside its SAVEPOINT, and reports the
        # resource as held rather than blowing up the caller's transaction.
        assert store._insert(
            session, _resource(), holder="w2", expires_at=clock() + timedelta(60), now=clock()
        ) is None
        # The caller's transaction survived the constraint violation.
        assert session.exec(select(ResourceLease)).one().holder == "w1"


def test_an_expiry_read_back_naive_is_still_comparable(engine: object, clock: _Clock) -> None:
    """SQLite drops the offset; an expiry that came back naive must not poison the scan."""
    store = DatabaseLeaseStore(clock=clock)
    with Session(engine) as session:  # type: ignore[arg-type]
        assert store.acquire(session, _resource(), holder="w1", ttl_seconds=10)
        clock.advance(11)
        lapsed = store.expired(session)
        assert len(lapsed) == 1 and lapsed[0].expires_at.tzinfo is not None


# --------------------------------------------------------------------------- #
# (4) The reaper registry
# --------------------------------------------------------------------------- #
def test_a_reaper_registers_once_per_kind_and_refuses_a_rival() -> None:
    def first(session: Session, lease: Lease) -> None: ...

    def second(session: Session, lease: Lease) -> None: ...

    register_lease_reaper("pipeline", first)
    register_lease_reaper("pipeline", first)  # idempotent for the same callable
    assert lease_reaper_for("pipeline") is first
    assert dict(registered_lease_reapers()) == {"pipeline": first}
    with pytest.raises(ValueError, match="already registered"):
        register_lease_reaper("pipeline", second)


def test_a_reaper_needs_a_kind_to_be_registered_for() -> None:
    with pytest.raises(ValueError, match="non-empty kind"):
        register_lease_reaper("  ", lambda session, lease: None)


def test_an_unregistered_kind_has_no_reaper() -> None:
    assert lease_reaper_for("nothing-here") is None


# --------------------------------------------------------------------------- #
# (5) Recovery: the domain row walked back, atomically with the forfeit
# --------------------------------------------------------------------------- #
def _queued_ticket(engine: object) -> uuid.UUID:
    with Session(engine) as session:  # type: ignore[arg-type]
        ticket = _Ticket(status="queued")
        session.add(ticket)
        session.commit()
        return ticket.id


def _claimed_ticket(engine: object) -> uuid.UUID:
    with Session(engine) as session:  # type: ignore[arg-type]
        ticket = _Ticket(status="claimed")
        session.add(ticket)
        session.commit()
        return ticket.id


def _ticket_status(engine: object, ticket_id: uuid.UUID) -> str:
    with Session(engine) as session:  # type: ignore[arg-type]
        return session.exec(select(_Ticket).where(_Ticket.id == ticket_id)).one().status


def test_an_expired_lease_has_its_domain_row_walked_back_and_the_lease_forfeited(
    engine: object, store: DatabaseLeaseStore, clock: _Clock
) -> None:
    ticket_id = _claimed_ticket(engine)
    tickets = _TicketService()

    def requeue(session: Session, lease: Lease) -> None:
        row = tickets.get(session, uuid.UUID(lease.resource.key))
        tickets.update(session, row.id, _TicketUpdate(status="queued", version=row.version))

    register_lease_reaper("_lease_ticket", requeue)

    with Session(engine) as session:  # type: ignore[arg-type]
        resource = LeaseResource(kind="_lease_ticket", key=str(ticket_id))
        assert store.acquire(session, resource, holder="dead-worker", ttl_seconds=30)
    clock.advance(31)

    with Session(engine) as session:  # type: ignore[arg-type]
        result = reap_expired_leases(session, store)

    assert result == ReapResult(scanned=1, recovered=1, released=0, failed=0, purged=0)
    assert _ticket_status(engine, ticket_id) == "queued"
    with Session(engine) as session:  # type: ignore[arg-type]
        # Forfeited, so the next cycle has nothing to do and the resource is claimable.
        assert store.expired(session) == ()
        assert store.acquire(
            session, LeaseResource(kind="_lease_ticket", key=str(ticket_id)),
            holder="next-worker", ttl_seconds=30,
        ) is not None


def test_a_kind_with_no_reaper_is_released_because_expiry_was_the_whole_recovery(
    engine: object, store: DatabaseLeaseStore, clock: _Clock
) -> None:
    # The pure-mutex shape: nothing to walk back, so freeing the resource is the answer —
    # but the lease is still forfeited, or the scan would return it forever.
    with Session(engine) as session:  # type: ignore[arg-type]
        assert store.acquire(session, _resource(), holder="w1", ttl_seconds=10)
    clock.advance(11)
    with Session(engine) as session:  # type: ignore[arg-type]
        result = reap_expired_leases(session, store)
        assert result == ReapResult(scanned=1, released=1)
        assert store.expired(session) == ()


def test_a_failing_reaper_is_isolated_and_its_lease_is_left_for_the_next_cycle(
    engine: object, store: DatabaseLeaseStore, clock: _Clock
) -> None:
    def explode(session: Session, lease: Lease) -> None:
        raise RuntimeError("the domain's recovery is broken")

    register_lease_reaper("broken", explode)

    with Session(engine) as session:  # type: ignore[arg-type]
        assert store.acquire(session, _resource("x", kind="broken"), holder="w1", ttl_seconds=10)
        assert store.acquire(session, _resource("y"), holder="w2", ttl_seconds=10)
    clock.advance(11)

    with Session(engine) as session:  # type: ignore[arg-type]
        result = reap_expired_leases(session, store)
        assert result.scanned == 2 and result.failed == 1 and result.released == 1
        # The broken kind is still there to retry; the healthy one is done.
        assert [str(lease.resource) for lease in store.expired(session)] == ["broken:x"]


def test_a_reap_cycle_can_also_purge_free_records(
    engine: object, store: DatabaseLeaseStore, clock: _Clock
) -> None:
    with Session(engine) as session:  # type: ignore[arg-type]
        lease = store.acquire(session, _resource("old"), holder="w1", ttl_seconds=60)
        assert lease is not None
        store.release(session, lease)
    clock.advance(7200)
    with Session(engine) as session:  # type: ignore[arg-type]
        result = reap_expired_leases(session, store, purge_idle_seconds=3600)
        assert result.purged == 1
        assert session.exec(select(ResourceLease)).all() == []


def test_the_reap_tally_renders_for_an_operator() -> None:
    assert str(ReapResult(scanned=3, recovered=1, released=1, failed=1, purged=2)) == (
        "scanned=3 recovered=1 released=1 failed=1 purged=2"
    )


# --------------------------------------------------------------------------- #
# (6) The chokepoint functions and the guard
# --------------------------------------------------------------------------- #
def test_every_lease_call_fails_closed_when_no_store_is_configured(engine: object) -> None:
    reset_leases_runtime()
    lease = Lease(resource=_resource(), holder="w1", epoch=1, expires_at=_T0)
    with Session(engine) as session:  # type: ignore[arg-type]
        for call in (
            lambda: acquire_lease(session, _resource(), holder="w1", ttl_seconds=60),
            lambda: renew_lease(session, lease, ttl_seconds=60),
            lambda: release_lease(session, lease),
            lambda: expired_leases(session),
            lambda: forfeit_lease(session, lease),
            lambda: purge_free_leases(session, idle_seconds=60),
        ):
            with pytest.raises(LeaseError, match="no lease store is configured"):
                call()


def test_hold_lease_raises_a_409_when_the_resource_is_taken(
    engine: object, store: DatabaseLeaseStore
) -> None:
    with Session(engine) as session:  # type: ignore[arg-type]
        guard = hold_lease(session, _resource(), holder="w1", ttl_seconds=60)
        assert isinstance(guard, LeaseGuard) and guard.released is False
        with pytest.raises(LeaseHeldError) as raised:
            hold_lease(session, _resource(), holder="w2", ttl_seconds=60)
        assert raised.value.status_code == 409 and raised.value.code == "lease_held"


def test_the_chokepoint_functions_delegate_to_the_configured_store(
    engine: object, store: DatabaseLeaseStore, clock: _Clock
) -> None:
    assert active_lease_store() is store
    with Session(engine) as session:  # type: ignore[arg-type]
        lease = acquire_lease(session, _resource(), holder="w1", ttl_seconds=60)
        assert lease is not None
        assert acquire_lease(session, _resource(), holder="w2", ttl_seconds=60) is None
        clock.advance(30)
        renewed = renew_lease(session, lease, ttl_seconds=60)
        assert renewed is not None
        clock.advance(61)
        assert expired_leases(session)[0].holder == "w1"
        assert forfeit_lease(session, renewed) is True
        assert release_lease(session, renewed) is False
        clock.advance(7200)
        assert purge_free_leases(session, idle_seconds=3600) == 1


def test_the_guard_only_writes_once_the_lease_is_past_its_half_life(
    engine: object, store: DatabaseLeaseStore, clock: _Clock
) -> None:
    with Session(engine) as session:  # type: ignore[arg-type]
        guard = hold_lease(session, _resource(), holder="w1", ttl_seconds=60)
        first = guard.lease
        clock.advance(10)
        assert guard.heartbeat() is first  # cheap: nothing written yet
        clock.advance(25)  # now past half of 60s
        renewed = guard.heartbeat()
        assert renewed is not first and renewed.expires_at > first.expires_at


def test_the_guard_fails_closed_when_its_lease_was_taken_over(
    engine: object, store: DatabaseLeaseStore, clock: _Clock
) -> None:
    with Session(engine) as session:  # type: ignore[arg-type]
        guard = hold_lease(session, _resource(), holder="w1", ttl_seconds=30)
        clock.advance(31)
        assert store.acquire(session, _resource(), holder="w2", ttl_seconds=30) is not None
        # Raising rather than returning False is the point: a boolean is forgettable, and
        # forgetting it means finishing work a successor is already doing.
        with pytest.raises(LeaseLostError) as raised:
            guard.heartbeat()
        assert raised.value.code == "lease_lost"
        assert guard.released is True
        with pytest.raises(LeaseLostError):
            guard.heartbeat()  # a lost guard stays lost


def test_the_guard_releases_once_and_on_the_way_out_of_a_with_block(
    engine: object, store: DatabaseLeaseStore
) -> None:
    with Session(engine) as session:  # type: ignore[arg-type]
        guard = hold_lease(session, _resource(), holder="w1", ttl_seconds=60)
        assert guard.release() is True
        assert guard.release() is False  # idempotent, so `finally` may call it blindly

        with pytest.raises(RuntimeError, match="work blew up"):
            with hold_lease(session, _resource(), holder="w2", ttl_seconds=60) as inner:
                assert inner.released is False
                raise RuntimeError("work blew up")
        # An exception means the holder is alive and reporting, so the resource goes back
        # immediately instead of waiting out its TTL.
        assert acquire_lease(session, _resource(), holder="w3", ttl_seconds=60) is not None


# --------------------------------------------------------------------------- #
# (7) The boot guard and the runtime seam
# --------------------------------------------------------------------------- #
def test_boot_refuses_a_store_whose_leases_die_with_their_holder() -> None:
    with pytest.raises(BootError, match="require_durable_leases=True"):
        create_app([], lease_store=InMemoryLeaseStore(), require_durable_leases=True)
    # ...and refuses no store at all, which is the emptiest promise of the three.
    with pytest.raises(BootError, match="require_durable_leases=True"):
        create_app([], require_durable_leases=True)


def test_boot_accepts_a_marked_durable_store_and_installs_it() -> None:
    store = DatabaseLeaseStore()
    assert is_durable_lease_store(store) is True
    create_app([], lease_store=store, require_durable_leases=True)
    assert active_lease_store() is store


def test_an_app_that_leases_nothing_gets_no_store_at_all() -> None:
    # No accidental per-process leases: the seam stays unconfigured until asked for.
    create_app([])
    assert active_lease_store() is None
    assert is_durable_lease_store(None) is False
    assert is_durable_lease_store(InMemoryLeaseStore()) is False
    assert is_durable_lease_store(mark_durable_lease_store(InMemoryLeaseStore())) is True


def test_the_lease_seam_is_isolated_like_every_other_runtime_seam() -> None:
    store = InMemoryLeaseStore()
    configure_leases(store)
    snapshot = capture_runtimes()
    reset_runtimes()
    assert active_lease_store() is None
    restore_runtimes(snapshot)
    assert active_lease_store() is store
    reset_leases_runtime()


# --------------------------------------------------------------------------- #
# (8) The declared job and its schedule
# --------------------------------------------------------------------------- #
def test_the_reap_job_recovers_through_the_jobs_seam(
    engine: object, store: DatabaseLeaseStore, clock: _Clock
) -> None:
    with Session(engine) as session:  # type: ignore[arg-type]
        assert store.acquire(session, _resource(), holder="w1", ttl_seconds=10)
    clock.advance(11)
    with Session(engine) as session:  # type: ignore[arg-type]
        LEASE_REAP.handler(JobContext(session=session), LeaseReapPayload())
        assert store.expired(session) == ()


def test_the_reap_job_says_what_is_missing_when_no_store_is_wired(engine: object) -> None:
    reset_leases_runtime()
    with Session(engine) as session:  # type: ignore[arg-type]
        with pytest.raises(LeaseError, match="nothing to scan"):
            LEASE_REAP.handler(JobContext(session=session), LeaseReapPayload())


def test_the_reap_payload_bounds_its_batch() -> None:
    assert LeaseReapPayload().limit == 100
    with pytest.raises(ValueError):
        LeaseReapPayload(limit=0)
    with pytest.raises(ValueError):
        LeaseReapPayload(limit=1001)
    with pytest.raises(ValueError):
        LeaseReapPayload(purge_idle_seconds=0)


def test_the_reap_schedule_carries_a_fresh_payload_each_tick() -> None:
    schedule = lease_reap_schedule(cron="*/5 * * * *", kind="pipeline", limit=50)
    assert schedule.name == "leases.reap" and schedule.job is LEASE_REAP
    first = schedule.payload_factory()
    second = schedule.payload_factory()
    assert first == second and first is not second
    assert first.kind == "pipeline" and first.limit == 50


# --------------------------------------------------------------------------- #
# (9) The operator's window
# --------------------------------------------------------------------------- #
def _client(engine: object) -> TestClient:
    app: FastAPI = create_app(
        [leases_module],
        principal_provider=lambda: _ADMIN,
        control_plane=ControlPlane(jobs=JobCatalog([LEASE_REAP])),
    )

    def _session_override() -> Iterator[Session]:
        with Session(engine) as session:  # type: ignore[arg-type]
            yield session

    app.dependency_overrides[get_session] = _session_override
    return TestClient(app)


def test_the_admin_router_shows_what_is_held_what_is_stuck_and_can_reap_it(
    engine: object, store: DatabaseLeaseStore, clock: _Clock
) -> None:
    ticket_id = _claimed_ticket(engine)
    tickets = _TicketService()

    def requeue(session: Session, lease: Lease) -> None:
        row = tickets.get(session, uuid.UUID(lease.resource.key))
        tickets.update(session, row.id, _TicketUpdate(status="queued", version=row.version))

    register_lease_reaper("_lease_ticket", requeue)
    with Session(engine) as session:  # type: ignore[arg-type]
        assert store.acquire(
            session, LeaseResource(kind="_lease_ticket", key=str(ticket_id)),
            holder="dead-worker", ttl_seconds=10,
        )
        assert store.acquire(session, _resource("live"), holder="w2", ttl_seconds=6000)
    clock.advance(11)

    # create_app in _client reinstalls the runtime seams, so re-wire the store afterwards.
    client = _client(engine)
    configure_leases(store)

    listing = client.get("/api/v1/leases/")
    assert listing.status_code == 200, listing.text
    assert listing.json()["total"] == 2
    flags = {item["resource_kind"]: item["expired"] for item in listing.json()["items"]}
    assert flags == {"_lease_ticket": True, "pipeline": False}

    filtered = client.get("/api/v1/leases/", params={"kind": "pipeline"})
    assert filtered.json()["total"] == 1

    stuck = client.get("/api/v1/leases/expired")
    assert stuck.json()["total"] == 1
    assert stuck.json()["items"][0]["holder"] == "dead-worker"

    reaped = client.post("/api/v1/leases/reap")
    assert reaped.status_code == 200, reaped.text
    assert reaped.json() == {
        "scanned": 1,
        "recovered": 1,
        "released": 0,
        "failed": 0,
        "purged": 0,
    }
    assert _ticket_status(engine, ticket_id) == "queued"
    assert client.get("/api/v1/leases/expired").json()["total"] == 0


def test_reads_work_before_a_store_is_wired_but_reaping_says_what_is_missing(
    engine: object,
) -> None:
    reset_leases_runtime()
    with Session(engine) as session:  # type: ignore[arg-type]
        rows, total, now = list_leases(session, pagination=_pagination())
        assert rows == [] and total == 0 and now.tzinfo is not None
        with pytest.raises(LeaseError, match="configured no lease store"):
            reap_now(session)


def _pagination() -> object:
    from terp.core import PaginationParams

    return PaginationParams(skip=0, limit=50)


def test_a_free_record_is_not_reported_as_expired(engine: object, clock: _Clock) -> None:
    # Otherwise every finished resource would sit on the operator's "needs attention" list.
    store = DatabaseLeaseStore(clock=clock)
    configure_leases(store)
    try:
        with Session(engine) as session:  # type: ignore[arg-type]
            lease = store.acquire(session, _resource(), holder="w1", ttl_seconds=10)
            assert lease is not None
            store.release(session, lease)
            clock.advance(11)
            row = session.exec(select(ResourceLease)).one()
            assert ResourceLeaseRead.of(row, now=clock()).expired is False
    finally:
        reset_leases_runtime()


def test_the_job_catalog_and_module_declare_the_reaper(engine: object) -> None:
    configure_jobs(JobCatalog([LEASE_REAP]))
    assert leases_module.name == "leases"
    assert leases_module.jobs == (LEASE_REAP,)
    assert LEASE_REAP.retry.max_attempts == 2


# --------------------------------------------------------------------------- #
# (10) The paths only a race reaches, and the defaults nothing injects
# --------------------------------------------------------------------------- #
def test_losing_the_first_ever_insert_reports_the_resource_as_held(
    engine: object, clock: _Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two workers reach a never-before-leased resource together.

    Both see no record and both try to insert; the unique constraint lets exactly one
    through, and the loser must report "held" rather than raising the constraint error at
    its caller. Simulated by blinding the first lookup, because the interleaving is
    otherwise unreachable from a single connection.
    """
    store = DatabaseLeaseStore(clock=clock)
    with Session(engine) as session:  # type: ignore[arg-type]
        winner = store.acquire(session, _resource(), holder="w1", ttl_seconds=60)
        assert winner is not None

        blinded = {"first": True}
        real_find = store._find

        def _blind_once(sess, resource):  # type: ignore[no-untyped-def]
            if blinded["first"]:
                blinded["first"] = False
                return None  # "there is no record yet" — as the loser saw it
            return real_find(sess, resource)

        monkeypatch.setattr(store, "_find", _blind_once)
        assert store.acquire(session, _resource(), holder="w2", ttl_seconds=60) is None
        # ...and the winner still holds it, unharmed by the loser's failed insert.
        assert store.renew(session, winner, ttl_seconds=60) is not None


def test_a_grant_that_moves_under_the_claim_refuses_rather_than_overwrites(
    engine: object, clock: _Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The epoch in the WHERE clause is what makes the claim atomic.

    If another worker grants the resource between this one's read and its UPDATE, the
    statement matches zero rows — so the claim is refused instead of silently stealing a
    lease that now belongs to someone else.
    """
    store = DatabaseLeaseStore(clock=clock)
    with Session(engine) as session:  # type: ignore[arg-type]
        lease = store.acquire(session, _resource(), holder="w1", ttl_seconds=10)
        assert lease is not None
        clock.advance(11)

        real_find = store._find

        def _report_a_stale_epoch(sess, resource):  # type: ignore[no-untyped-def]
            row = real_find(sess, resource)
            # What the loser read a moment before the winner bumped the epoch.
            return type(
                "_Stale",
                (),
                {"epoch": row.epoch - 1, "holder": None, "expires_at": None},
            )()

        monkeypatch.setattr(store, "_find", _report_a_stale_epoch)
        assert store.acquire(session, _resource(), holder="w2", ttl_seconds=60) is None


def test_skip_locked_is_rendered_when_the_deployment_asks_for_it(
    engine: object, clock: _Clock
) -> None:
    # SQLite ignores the clause rather than rejecting it, so the same scan is exercised on
    # the path a PostgreSQL deployment takes.
    store = DatabaseLeaseStore(clock=clock, skip_locked=True)
    with Session(engine) as session:  # type: ignore[arg-type]
        assert store.acquire(session, _resource(), holder="w1", ttl_seconds=10)
        clock.advance(11)
        assert [str(lease.resource) for lease in store.expired(session)] == ["pipeline:p1"]


def test_the_default_clock_is_real_time(engine: object) -> None:
    # Nothing injects a clock in production, so the default has to work: a lease taken now
    # is live now, and its record carries real timestamps.
    store = DatabaseLeaseStore()
    with Session(engine) as session:  # type: ignore[arg-type]
        lease = store.acquire(session, _resource(), holder="w1", ttl_seconds=60)
        assert lease is not None
        assert lease.is_expired(store.clock()) is False
        row = session.exec(select(ResourceLease)).one()
        assert row.touched_at is not None and row.created_at is not None
    assert InMemoryLeaseStore().clock() is not None


def test_a_lease_record_defaults_to_free_with_real_timestamps() -> None:
    # The store always writes its own timestamps, so the model's defaults are only exercised
    # by a hand-built row (a fixture, a migration backfill) - they still have to be sane, or
    # such a row would land with a null stamp and never be purged.
    row = ResourceLease(resource_kind="pipeline", resource_key="p1")
    assert row.holder is None and row.epoch == 0 and row.expires_at is None
    assert row.touched_at.tzinfo is not None and row.created_at.tzinfo is not None
