"""``terp leases`` CLI: the operator's window onto custody, and the recovery cycle by hand.

The lease seam (ADR 0095) only pays off if a human can act on it during an incident, so these
tests are written from that seat. They prove that ``terp leases list`` names *who* holds a
resource and *until when* — the distinction a bare ``claimed`` column cannot make — that
``--expired`` isolates exactly what the next cycle will act on, and that ``terp leases reap``
runs the domain's registered recovery so the stuck row moves without anyone opening a SQL
client.

Two absences are asserted as deliberately as the behaviour. A kind with **no** registered
reaper is called out in the listing, because "nothing reaped it" and "nobody declared a
recovery for it" look identical on the rows alone, and the second is the mistake an author
actually makes. And there is no ``release`` command at all: force-releasing a live lease is
the split brain the fence exists to prevent.
"""

from __future__ import annotations

import pathlib
import sys
from collections.abc import Iterator

import pytest

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_CLI_SRC = _REPO_ROOT / "packages" / "backend" / "cli" / "src"
sys.path.insert(0, str(_CLI_SRC))

from terp.cli import main, reap_leases_command, render_leases  # noqa: E402

# An app that wires the durable store, mounts the leases module, declares a recovery for its
# own queue table, and leaves one row `claimed` under a lease that has already lapsed — the
# state an operator finds after a worker was killed.
_LEASED_APP = '''\
from datetime import UTC, datetime, timedelta

from sqlmodel import Field, Session, SQLModel, select

from terp.core import (
    AuditAction,
    BaseSchema,
    BaseService,
    BaseTable,
    BaseUpdateSchema,
    ControlPlane,
    JobCatalog,
    LeaseResource,
    OperationCatalog,
    create_app,
    register_lease_reaper,
)
from terp.core._internal.engine import get_engine

from terp.capabilities.leases import (
    LEASE_REAP,
    LEASES_LIST,
    LEASES_LIST_EXPIRED,
    LEASES_REAP,
    DatabaseLeaseStore,
)
from terp.capabilities.leases import module as leases_module


class Ticket(BaseTable, table=True):
    __tablename__ = "cli_ticket"
    status: str = Field(default="queued", max_length=16)


class TicketCreate(BaseSchema):
    status: str = Field(default="queued", max_length=16)


class TicketUpdate(BaseUpdateSchema):
    status: str | None = Field(default=None, max_length=16)


class TicketService(BaseService[Ticket, TicketCreate, TicketUpdate]):
    model = Ticket


def requeue(session, lease):
    service = TicketService()
    row = service.get(session, __import__("uuid").UUID(lease.resource.key))
    service.update(session, row.id, TicketUpdate(status="queued", version=row.version))


# A clock parked in the past, so the lease this app takes is already lapsed by the time the
# CLI looks at it (no sleeping in a test, and no fixture reaching into the store).
STALE = datetime.now(UTC) - timedelta(hours=1)


def build():
    # Registered at composition, not import: the registry is process-global, so a test
    # that clears it between runs must still get the recovery back on the next build.
    register_lease_reaper("cli_ticket", requeue)
    app = create_app(
        [leases_module],
        control_plane=ControlPlane(
            jobs=JobCatalog([LEASE_REAP]),
            operations=OperationCatalog(
                operations=(LEASES_LIST, LEASES_LIST_EXPIRED, LEASES_REAP)
            ),
        ),
        lease_store=DatabaseLeaseStore(),
    )
    engine = get_engine()
    SQLModel.metadata.create_all(engine)
    # The CLI calls build() on every invocation, so seeding is idempotent: a second command
    # in the same test must find the state the first one left, not a fresh stuck ticket.
    with Session(engine) as session:
        if session.exec(select(Ticket)).first() is None:
            ticket = Ticket(status="claimed")
            session.add(ticket)
            session.commit()
            DatabaseLeaseStore(clock=lambda: STALE).acquire(
                session,
                LeaseResource(kind="cli_ticket", key=str(ticket.id)),
                holder="worker-that-died",
                ttl_seconds=60,
            )
    return app
'''

# The same app minus any registered recovery: a lease with nowhere to put its row back.
_UNREAPED_APP = '''\
from datetime import UTC, datetime, timedelta

from sqlmodel import Session, SQLModel

from terp.core import ControlPlane, JobCatalog, LeaseResource, OperationCatalog, create_app
from terp.core._internal.engine import get_engine

from terp.capabilities.leases import (
    LEASE_REAP,
    LEASES_LIST,
    LEASES_LIST_EXPIRED,
    LEASES_REAP,
    DatabaseLeaseStore,
)
from terp.capabilities.leases import module as leases_module

STALE = datetime.now(UTC) - timedelta(hours=1)


def build():
    app = create_app(
        [leases_module],
        control_plane=ControlPlane(
            jobs=JobCatalog([LEASE_REAP]),
            operations=OperationCatalog(
                operations=(LEASES_LIST, LEASES_LIST_EXPIRED, LEASES_REAP)
            ),
        ),
        lease_store=DatabaseLeaseStore(),
    )
    engine = get_engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        # Idempotent for the same reason as the leased app: acquire on an already-held
        # resource returns None rather than planting a second lease.
        DatabaseLeaseStore(clock=lambda: STALE).acquire(
            session,
            LeaseResource(kind="pipeline", key="nightly"),
            holder="worker-1",
            ttl_seconds=60,
        )
    return app
'''

# An app that never names a store: the seam stays unconfigured, and the CLI has to say so.
_UNLEASED_APP = '''\
from terp.core import create_app


def build():
    return create_app([])
'''


@pytest.fixture
def lease_db(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Point the process engine at a temp file database and reset it afterwards."""
    from terp.core._internal.engine import reset_engine
    from terp.core.config import settings

    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite:///{tmp_path / 'cli_leases.db'}")
    reset_engine()
    yield
    reset_engine()


@pytest.fixture(autouse=True)
def _clean_reapers() -> Iterator[None]:
    """Snapshot the process-global reaper registry, and put it back afterwards.

    Clearing it outright would be wrong in the way :mod:`terp.core.runtime` warns about: a
    reaper is a *capability* registration installed at import and meant to outlive a composed
    app, so a test that wipes it silently disarms every capability that registered one — and
    the damage lands on whatever runs next, not here.
    """
    from terp.core.leases import (
        register_lease_reaper,
        registered_lease_reapers,
        reset_lease_reapers,
        reset_leases_runtime,
    )

    before = dict(registered_lease_reapers())
    yield
    reset_lease_reapers()
    for kind, reaper in before.items():
        register_lease_reaper(kind, reaper)
    reset_leases_runtime()


def _app(tmp_path: pathlib.Path, name: str, source: str) -> str:
    """Write *source* as an importable module and return the CLI's app reference.

    Deliberately does **not** evict an already-imported module: these app sources declare
    table models, and re-executing the module body would redeclare them on the shared
    SQLModel metadata. ``build()`` re-runs per test either way (it is what the CLI calls), so
    each test still gets a fresh app against a fresh temp database.
    """
    (tmp_path / f"{name}.py").write_text(source, encoding="utf-8")
    return f"{name}:build"


def test_list_names_the_holder_and_the_deadline_not_just_that_something_is_claimed(
    tmp_path: pathlib.Path, lease_db: None
) -> None:
    ref = _app(tmp_path, "cli_leases_app", _LEASED_APP)
    output = render_leases(app_ref=ref, app_root=tmp_path)
    assert "cli_ticket:" in output
    assert "holder=worker-that-died" in output
    assert "EXPIRED at" in output and "awaiting reap" in output
    # The recovery that exists for this kind is named, so an operator knows reaping will act.
    assert "Registered recoveries: cli_ticket" in output


def test_expired_isolates_exactly_what_the_next_cycle_will_act_on(
    tmp_path: pathlib.Path, lease_db: None
) -> None:
    ref = _app(tmp_path, "cli_leases_app", _LEASED_APP)
    stuck = render_leases(app_ref=ref, app_root=tmp_path, expired_only=True)
    assert "Expired leases (1 of 1)" in stuck
    # A kind filter narrows it further; an unrelated kind shows nothing rather than everything.
    assert "(0 of 0)" in render_leases(
        app_ref=ref, app_root=tmp_path, expired_only=True, kind="pipeline"
    )


def test_reap_runs_the_registered_recovery_so_the_stuck_row_moves(
    tmp_path: pathlib.Path, lease_db: None
) -> None:
    ref = _app(tmp_path, "cli_leases_app", _LEASED_APP)
    message = reap_leases_command(app_ref=ref, app_root=tmp_path)
    assert "recovered=1" in message

    import importlib

    from sqlmodel import Session, select

    from terp.core._internal.engine import get_engine

    module = importlib.import_module("cli_leases_app")
    with Session(get_engine()) as session:
        ticket = session.exec(select(module.Ticket)).one()
    assert ticket.status == "queued"  # walked back without anyone opening a SQL client
    # Nothing left to reap, and running it again is a no-op rather than an error.
    assert "scanned=0" in reap_leases_command(app_ref=ref, app_root=tmp_path)


def test_a_lease_kind_with_no_registered_recovery_is_called_out(
    tmp_path: pathlib.Path, lease_db: None
) -> None:
    # "Nothing reaped it" and "nobody declared a recovery for it" look identical on the rows,
    # and the gap is named per kind rather than as a blanket note — other capabilities in the
    # process legitimately have recoveries of their own.
    ref = _app(tmp_path, "cli_leases_unreaped_app", _UNREAPED_APP)
    output = render_leases(app_ref=ref, app_root=tmp_path)
    assert "Kinds with no recovery: pipeline" in output
    assert "nothing puts their rows back" in output
    # Reaping still frees the resource — that is the whole recovery for a pure mutex.
    assert "released=1" in reap_leases_command(app_ref=ref, app_root=tmp_path)


def test_a_kind_with_a_recovery_is_not_listed_as_uncovered(
    tmp_path: pathlib.Path, lease_db: None
) -> None:
    ref = _app(tmp_path, "cli_leases_app", _LEASED_APP)
    output = render_leases(app_ref=ref, app_root=tmp_path)
    assert "cli_ticket" in output.split("Registered recoveries:")[1]
    assert "Kinds with no recovery" not in output


def test_both_commands_say_what_is_missing_when_the_app_wired_no_store(
    tmp_path: pathlib.Path, lease_db: None
) -> None:
    ref = _app(tmp_path, "cli_leases_unwired_app", _UNLEASED_APP)
    for call in (render_leases, reap_leases_command):
        with pytest.raises(SystemExit) as raised:
            call(app_ref=ref, app_root=tmp_path)
        assert "configured no lease store" in str(raised.value)
        assert "terp guide leases" in str(raised.value)


def test_the_commands_are_reachable_from_argv(
    tmp_path: pathlib.Path, lease_db: None, capsys: pytest.CaptureFixture[str]
) -> None:
    ref = _app(tmp_path, "cli_leases_app", _LEASED_APP)
    main(["leases", "list", "--app", ref, "--app-root", str(tmp_path), "--expired"])
    assert "worker-that-died" in capsys.readouterr().out
    main(["leases", "reap", "--app", ref, "--app-root", str(tmp_path), "--limit", "10"])
    assert "recovered=1" in capsys.readouterr().out


def test_purging_trims_free_records_so_the_table_does_not_grow_per_row(
    tmp_path: pathlib.Path, lease_db: None
) -> None:
    # A row-shaped resource leaves one record per row ever processed; the maintenance half of
    # the cycle is what keeps that bounded.
    ref = _app(tmp_path, "cli_leases_app", _LEASED_APP)
    reap_leases_command(app_ref=ref, app_root=tmp_path)  # forfeits the lapsed lease
    # A tiny idle window, because the record was freed moments ago: what is under test is
    # that the flag reaches the cycle (the window itself is covered against an injected
    # clock in test_leases.py).
    message = reap_leases_command(
        app_ref=ref, app_root=tmp_path, purge_idle_seconds=0.001
    )
    assert "purged=1" in message


def test_there_is_no_force_release_command(tmp_path: pathlib.Path) -> None:
    # Taking a live lease away from a holder that may still be running is the split brain the
    # epoch fence exists to prevent; a command for it would be a standing invitation.
    with pytest.raises(SystemExit):
        main(["leases", "release", "--app", "x:y"])


def test_the_listing_distinguishes_free_live_and_expired_leases(
    tmp_path: pathlib.Path, lease_db: None
) -> None:
    """The three states an operator has to tell apart, in the same page.

    "Free" is not "expired": a finished resource has no lease to have lapsed, and calling it
    expired would put every completed unit of work on the needs-attention list.
    """
    ref = _app(tmp_path, "cli_leases_app", _LEASED_APP)
    reap_leases_command(app_ref=ref, app_root=tmp_path)  # the stuck one becomes free

    from sqlmodel import Session

    from terp.core import LeaseResource
    from terp.core._internal.engine import get_engine
    from terp.core.leases import active_lease_store

    with Session(get_engine()) as session:
        active_lease_store().acquire(  # type: ignore[union-attr]
            session,
            LeaseResource(kind="pipeline", key="nightly"),
            holder="a-live-worker",
            ttl_seconds=3600,
        )

    output = render_leases(app_ref=ref, app_root=tmp_path)
    assert "held until" in output  # the live one
    assert "free" in output  # the reaped one
    assert "EXPIRED" not in output  # ...and nothing is pretending to need attention
