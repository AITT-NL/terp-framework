"""Per-module role assignment: the capability gap ADR 0121 exists to close.

Before this, a user carried exactly one rank and a group carried none, so "editor in one
module, viewer everywhere else" was not expressible. The only ways to let someone write in one
module were to raise their rank everywhere — the ten-second workaround ADR 0089 was written
about — or to redesign that module in code so its write requirement was a `Permission` with a
`VIEWER` floor, which has to be decided per module, in advance, by someone who can read the
source.

The assertions here are about *behaviour at the guard*, not about rows: what a request is
allowed to do, and what an assignment in one module does and does not reach.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from types import SimpleNamespace

import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from terp.core import (
    ADMIN,
    EDITOR,
    VIEWER,
    BootError,
    ControlPlane,
    ModuleAccess,
    ModuleSpec,
    PermissionModel,
    Policy,
    Principal,
    Role,
    Roles,
    PermissionDeniedError,
    ValidationFailedError,
    create_app,
    get_session,
)

import terp.capabilities.access.models  # noqa: F401  (register the access tables)
from terp.capabilities.access import (
    ModuleRoleService,
    assignable_modules,
    project_held_module_ranks,
    register_subject_expander,
    reset_subject_expanders,
    resolve_module_rank,
    validate_assignment,
)
from terp.core.app import build_guard
from terp.core.permissions import (
    project_module_ranks,
    register_module_rank_projector,
    registered_module_rank_projectors,
    reset_module_rank_projectors,
)

from terp.capabilities.groups import register_group_expansion


@pytest.fixture(autouse=True)
def _canonical_expanders() -> Iterator[None]:
    """Restore the process-global expander registry after every test in this file.

    Copied from the groups suite, which learned it first, and the reason is worth stating
    because getting it wrong is silent and cross-file: the groups capability registers its
    membership expander at **import** time, once per process. A test that clears the registry
    and walks away has removed it for every suite that runs afterwards, and it never comes
    back — which is exactly the order-dependent failure this file caused in the example app's
    group-grant test before this fixture existed.
    """
    yield
    reset_subject_expanders()
    register_group_expansion()


@pytest.fixture(autouse=True)
def _isolate_module_rank_projectors() -> Iterator[None]:
    """Snapshot the module-rank projector registry, and put it back afterwards.

    Copied from the ``/me`` suite for the same reason the expander fixture above is copied
    from the groups suite: the access capability registers its projector at **import** time,
    once per process, and a test that clears the registry has disarmed it for everything that
    runs afterwards. Snapshot-and-restore is the only cleanup that leaves the process as it
    was found.
    """
    before = registered_module_rank_projectors()
    yield
    reset_module_rank_projectors()
    for projector in before:
        register_module_rank_projector(projector)


@pytest.fixture
def engine() -> Iterator[Engine]:
    db = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    SQLModel.metadata.create_all(db)
    try:
        yield db
    finally:
        SQLModel.metadata.drop_all(db)
        db.dispose()


def _writable_module(name: str) -> ModuleSpec:
    """A module whose write tier is EDITOR and which has opted into assignment."""
    router = APIRouter()

    @router.post("/", response_model=str)
    def write() -> str:  # pragma: no cover - exercised over HTTP
        return f"wrote {name}"

    return ModuleSpec(
        name=name,
        router=router,
        policy=Policy.default(),
        access=ModuleAccess(label=name.title(), assignable=True),
    )


def _client(engine: Engine, principal: Principal, *names: str) -> TestClient:
    app = create_app(
        [_writable_module(name) for name in names],
        principal_provider=lambda: principal,
        control_plane=ControlPlane(permissions=PermissionModel.default()),
        module_rank_resolver=resolve_module_rank,
    )

    def _session() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = _session
    return TestClient(app)


def test_a_module_role_raises_authority_in_that_module_and_nowhere_else(
    engine: Engine,
) -> None:
    """The whole point, asserted at the guard.

    Both halves matter and neither is sufficient alone: without the first, the assignment is
    inert; without the second, it is a global promotion wearing a module's name, which is the
    outcome this design exists to avoid.
    """
    viewer = Principal(id=uuid.uuid4(), role=Roles.VIEWER)
    client = _client(engine, viewer, "notes", "tasks")

    assert client.post("/api/v1/notes/").status_code == 403
    assert client.post("/api/v1/tasks/").status_code == 403

    with Session(engine) as session:
        ModuleRoleService().assign(session, viewer.id, "notes", EDITOR.rank)
        session.commit()

    assert client.post("/api/v1/notes/").status_code == 200
    assert client.post("/api/v1/tasks/").status_code == 403


def test_a_module_role_assigned_to_a_group_reaches_its_members(engine: Engine) -> None:
    """The FK-less ``subject_id`` is what buys this, with no new machinery.

    A group's id is a subject, so an assignment naming the group is resolved through the same
    expansion seam that already makes a group's *grants* reach its members. Registered by hand
    here rather than by installing the groups capability, which is how the expansion seam's own
    tests do it.
    """
    group = uuid.uuid4()
    member = Principal(id=uuid.uuid4(), role=Roles.VIEWER)
    register_subject_expander(
        lambda _session, subject: (group,) if subject == member.id else ()
    )
    client = _client(engine, member, "notes")
    assert client.post("/api/v1/notes/").status_code == 403

    with Session(engine) as session:
        ModuleRoleService().assign(session, group, "notes", EDITOR.rank)
        session.commit()

    assert client.post("/api/v1/notes/").status_code == 200


def test_a_module_role_never_lowers_a_global_rank(engine: Engine) -> None:
    """The effective rank is `max(global, module)`, so a low rung cannot demote anyone.

    An admin holding *viewer* in a module still writes there. This is the case an
    implementation that **replaced** the global rank with the module rank would break, which
    is a plausible way to write it and a silent demotion if you do.
    """
    admin = Principal(id=uuid.uuid4(), role=Roles.ADMIN)
    client = _client(engine, admin, "notes")
    with Session(engine) as session:
        ModuleRoleService().assign(session, admin.id, "notes", VIEWER.rank)
        session.commit()
    assert client.post("/api/v1/notes/").status_code == 200


def test_the_highest_rung_across_the_expanded_subject_set_wins(engine: Engine) -> None:
    """`max` over the *set*, which needs two rows in one module to observe at all.

    Written after a mutation exposed the gap: the unique constraint allows one rung per
    subject per module, so with a single row `max` and `min` are the same query and swapping
    them broke nothing. Two rows only arise through expansion — a subject holding one rung
    directly while a group they belong to holds another in the same module — and that is
    exactly the case where subtracting instead of adding would quietly cost someone access
    they had been given.

    Asserted in both directions, because a `min` passes the direct-is-higher half.
    """
    service = ModuleRoleService()
    group = uuid.uuid4()
    member = uuid.uuid4()
    register_subject_expander(
        lambda _session, subject: (group,) if subject == member else ()
    )
    with Session(engine) as session:
        # The group holds the higher rung.
        service.assign(session, member, "notes", VIEWER.rank)
        service.assign(session, group, "notes", ADMIN.rank)
        session.commit()
        assert service.highest_rank(session, member, "notes") == ADMIN.rank

        # And now the direct assignment is the higher one.
        service.assign(session, member, "tasks", ADMIN.rank)
        service.assign(session, group, "tasks", VIEWER.rank)
        session.commit()
        assert service.highest_rank(session, member, "tasks") == ADMIN.rank


def test_the_resolver_is_not_consulted_when_the_caller_already_clears_the_floor(
    engine: Engine,
) -> None:
    """A per-module role can only raise authority, so clearing callers need no query.

    Counted rather than reasoned about: this is on the request path of every guarded route in
    the framework, and the laziness is the difference between one query for the callers who
    need it and one for everybody.
    """
    calls: list[str] = []

    def counting_resolver(session: Session, subject_id: uuid.UUID, module: str) -> int:
        calls.append(module)
        return resolve_module_rank(session, subject_id, module)

    editor = Principal(id=uuid.uuid4(), role=Roles.EDITOR)
    app = create_app(
        [_writable_module("notes")],
        principal_provider=lambda: editor,
        control_plane=ControlPlane(permissions=PermissionModel.default()),
        module_rank_resolver=counting_resolver,
    )

    def _session() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = _session
    assert TestClient(app).post("/api/v1/notes/").status_code == 200
    assert calls == []


def test_boot_refuses_an_assignable_module_with_no_resolver_installed() -> None:
    """A declaration the runtime cannot act on is worse than no declaration.

    The pane would offer an administrator a rung to assign and every assignment would silently
    do nothing. Caught at composition time, on the same pattern as the `permission_enforcer`
    check (ADR 0016 §3), rather than discovered when someone wonders why the access they
    granted had no effect.
    """
    with pytest.raises(BootError, match="module_rank_resolver"):
        create_app([_writable_module("notes")])

    # A module that has *not* opted in needs no resolver, which is what keeps this from being
    # a breaking change for every existing app.
    plain = ModuleSpec(name="notes", policy=Policy.default())
    assert create_app([plain]).title == "Terp app"


def test_an_assignment_is_refused_unless_the_declarations_support_it() -> None:
    """Three refusals with three different fixes, so they are three different messages.

    ADR 0089's "there is no `--force`" applied to a second table: an assignment that could
    never fire, or could fire somewhere nobody intended, is not a lenient assignment.
    """
    plane = ControlPlane(permissions=PermissionModel.default())
    opted_in = _writable_module("notes")
    platform = ModuleSpec(
        name="users",
        policy=Policy.default(),
        access=ModuleAccess.platform_only(reason="accounts are the platform's own authority"),
    )
    silent = ModuleSpec(name="tasks", policy=Policy.default())
    specs = (opted_in, platform, silent)

    validate_assignment(plane, specs, "notes", EDITOR.rank)  # no raise

    with pytest.raises(ValidationFailedError, match="never per-module assignable"):
        validate_assignment(plane, specs, "users", ADMIN.rank)
    with pytest.raises(ValidationFailedError, match="has not opted into"):
        validate_assignment(plane, specs, "tasks", EDITOR.rank)
    with pytest.raises(ValidationFailedError, match="no role at rank 25"):
        validate_assignment(plane, specs, "notes", 25)

    # A rank the app *does* declare passes, even an unusual one — the check is against the
    # app's ladder, not against the packaged three.
    custom = ControlPlane(
        permissions=PermissionModel(roles=(VIEWER, EDITOR, Role("approver", rank=25), ADMIN))
    )
    validate_assignment(custom, specs, "notes", 25)  # no raise

    assert assignable_modules(specs) == {"notes": "Notes"}


def test_revoking_does_not_validate_so_a_stale_assignment_can_be_cleared(
    engine: Engine,
) -> None:
    """The assignment you most need to remove is the one the app no longer supports.

    Same reasoning `terp grant revoke` gives for not checking its catalog: insisting a module
    still qualifies would make a stale row unreachable.
    """
    service = ModuleRoleService()
    subject = uuid.uuid4()
    with Session(engine) as session:
        service.assign(session, subject, "retired", EDITOR.rank)
        session.commit()
        assert service.highest_rank(session, subject, "retired") == EDITOR.rank
        assert service.revoke(session, subject, "retired") is True
        session.commit()
        assert service.highest_rank(session, subject, "retired") == 0
        # And revoking what is not there is not an error.
        assert service.revoke(session, subject, "retired") is False


def test_assigning_the_same_subject_twice_updates_the_one_fact(engine: Engine) -> None:
    """One rung per subject per module — the unique constraint says so, and so does this.

    A rank change is the same fact with a new value rather than a second row, which is what
    keeps "what does this person hold here?" answerable with one lookup.
    """
    service = ModuleRoleService()
    subject = uuid.uuid4()
    with Session(engine) as session:
        first = service.assign(session, subject, "notes", VIEWER.rank)
        again = service.assign(session, subject, "notes", VIEWER.rank)
        assert again.id == first.id
        raised = service.assign(session, subject, "notes", ADMIN.rank)
        assert raised.id == first.id
        session.commit()
        rows, total = service.list_for(session, subject, skip=0, limit=10)
        assert total == 1
        assert rows[0].role_rank == ADMIN.rank


def test_deleting_a_group_takes_its_module_roles_with_it(engine: Engine) -> None:
    """A group is a subject in *both* access tables, so the cascade has to know both.

    The grants cascade has existed since groups did, with a docstring arguing that a deleted
    group must not keep authorizing its former members through a dangling subject id. This
    branch added a second table the cascade did not know about — so a deleted group's rungs
    stayed behind, reported by `terp module-role list` for a group that no longer exists and
    ready to authorize again the moment anything re-created a membership row pointing at that
    id. Asserted on both tables together, because the point is that they agree.
    """
    from terp.capabilities.access import AccessService
    from terp.capabilities.groups import GroupsService
    from terp.capabilities.groups.schemas import GroupCreate

    groups = GroupsService()
    roles = ModuleRoleService()
    access = AccessService()

    with Session(engine) as session:
        group = groups.create(session, GroupCreate(name="Doomed"))
        roles.assign(session, group.id, "notes", EDITOR.rank)
        access.grant(session, group.id, "notes.delete")
        assert roles.highest_rank(session, group.id, "notes") == EDITOR.rank

        groups.delete(session, group.id)

        assert roles.highest_rank(session, group.id, "notes") == 0
        assert access.permissions_for(session, group.id) == set()


def test_clearing_the_floor_by_module_role_is_reported_distinctly(engine: Engine) -> None:
    """`allowed_in_module` is not decoration: it is the answer to "why can they do that?".

    Both outcomes are `allowed`, so nothing about the decision changes — which is exactly why
    this needed its own test. A leftover mutation collapsing the two reasons into `allowed`
    broke no test at all, and the field is the one a provenance view uses to distinguish "this
    person's own rank was enough" from "a rung somebody assigned in this module was".
    """
    from terp.core.module_spec import decide

    policy = Policy(read=VIEWER, write=EDITOR)
    viewer = Role("viewer", rank=10)

    # Cleared by the global rank alone.
    assert decide(policy, method="GET", role=viewer).reason == "allowed"
    # Cleared only because of the module rung — same `allowed`, different answer.
    elevated = decide(policy, method="POST", role=viewer, module_rank=lambda: 20)
    assert elevated.allowed is True
    assert elevated.reason == "allowed_in_module"
    # And an editor writing needs no rung at all, so it stays the plain reason.
    assert (
        decide(policy, method="POST", role=Role("editor", rank=20), module_rank=lambda: 30).reason
        == "allowed"
    )


def _admin_only_module(name: str, access: ModuleAccess | None) -> ModuleSpec:
    """An admin-gated module, so a VIEWER holding a rung there is a visible escalation."""
    router = APIRouter()

    @router.post("/", response_model=str)
    def write() -> str:  # pragma: no cover - exercised over HTTP
        return f"wrote {name}"

    return ModuleSpec(
        name=name,
        router=router,
        policy=Policy(read_role=Roles.ADMIN, write_role=Roles.ADMIN),
        access=access,
    )


def test_a_rung_in_a_module_that_refuses_assignment_does_not_elevate(engine: Engine) -> None:
    """The declaration has to be a gate at the DECISION point, not a convention at the writer.

    Found by review, and it was worse than reported: a `ModuleRole` row naming a
    `platform_only` module *or* a module that never opted in elevated the caller anyway. Both
    modules here are admin-gated, so a VIEWER reaching them is full platform authority —
    `admin` in a `users`-shaped module provisions accounts, and in an `access`-shaped one hands
    out every other authority. That is the exact escalation ADR 0121 §5 exists to prevent.

    `validate_assignment` refuses to *create* such a row, and that was the whole enforcement:
    the guard read whatever was in the table, so any other write path — a seed, a migration, a
    future endpoint, a bug — turned a refused declaration into admin. The suite was green
    throughout, because every existing assertion about the refusal was aimed at the writer.

    Fixing it at the guard also makes the stale reporting honest: a row every view calls stale
    now genuinely does nothing.
    """
    viewer = Principal(id=uuid.uuid4(), role=Roles.VIEWER)
    app = create_app(
        [
            _admin_only_module(
                "iam", ModuleAccess.platform_only(reason="the platform's own authority")
            ),
            _admin_only_module("silent", None),
            _admin_only_module("opted_in", ModuleAccess(label="Opted in", assignable=True)),
        ],
        principal_provider=lambda: viewer,
        control_plane=ControlPlane(permissions=PermissionModel.default()),
        module_rank_resolver=resolve_module_rank,
    )

    def _session() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = _session
    client = TestClient(app)

    with Session(engine) as session:
        for module in ("iam", "silent", "opted_in"):
            ModuleRoleService().assign(session, viewer.id, module, ADMIN.rank)
        session.commit()

    assert client.post("/api/v1/iam/").status_code == 403
    assert client.post("/api/v1/silent/").status_code == 403
    # The positive half, without which the two above pass against a guard that ignores every
    # module role: the module that DID opt in still elevates.
    assert client.post("/api/v1/opted_in/").status_code == 200


def test_a_rank_the_ladder_does_not_declare_clears_nothing(engine: Engine) -> None:
    """Symmetry with the global role, which the guard already refuses when unregistered.

    Found by review. The two disagreed in the dangerous direction: an unregistered *global*
    role was denied outright, while a stored module rank at any integer cleared every floor at
    or below it — so a row at rank 999 was full authority in that module though no ladder
    declared such a rung. `validate_assignment` refuses to write one, and that was the whole
    enforcement, which is the same mistake as trusting the table about a refusing module.

    A rank the app has *since stopped* declaring lands here too, and clearing nothing is the
    right answer for it while the row stays visible to the views that report it stale.
    """
    viewer = Principal(id=uuid.uuid4(), role=Roles.VIEWER)
    client = _client(engine, viewer, "notes")
    service = ModuleRoleService()

    with Session(engine) as session:
        service.assign(session, viewer.id, "notes", 999)
        session.commit()
    assert client.post("/api/v1/notes/").status_code == 403

    # The positive half: a rank the ladder *does* declare still elevates, without which the
    # assertion above passes against a guard that ignores every module role.
    with Session(engine) as session:
        service.assign(session, viewer.id, "notes", EDITOR.rank)
        session.commit()
    assert client.post("/api/v1/notes/").status_code == 200



def test_the_display_projection_reports_every_rung_a_subject_holds(engine: Engine) -> None:
    """The `/me` counterpart of `resolve_module_rank`: every module at once, not one yes/no.

    A **display** input and never a decision — the guard re-resolves on every request — but a
    frontend that gates a button on the caller's own authority needs it, and a projection that
    under-reports makes the button vanish for someone who may in fact press it (ADR 0121).

    The fixture holds two rungs in `notes`, one directly and one through a group, stored in the
    order that makes `max` observable: the **lower** rank is written first, so an accumulator
    that kept the first value it saw, or compared with `min`, would answer `viewer` where the
    truth is `editor`. With one row per module the two are indistinguishable, which is why the
    group half of the fixture is here rather than in the resolver's own test.
    """
    group = uuid.uuid4()
    subject = uuid.uuid4()
    register_subject_expander(
        lambda _session, holder: (group,) if holder == subject else ()
    )
    with Session(engine) as session:
        ModuleRoleService().assign(session, subject, "notes", VIEWER.rank)
        ModuleRoleService().assign(session, group, "notes", EDITOR.rank)
        ModuleRoleService().assign(session, subject, "tasks", ADMIN.rank)
        session.commit()

        held = project_held_module_ranks(session, subject)

    assert held == {"notes": EDITOR.rank, "tasks": ADMIN.rank}


def test_the_projection_merges_across_projectors_and_keeps_the_higher(engine: Engine) -> None:
    """`project_module_ranks` folds every registered projector, and a rung wins by rank.

    The kernel holds the registry so `GET /me` can report per-module rungs without the auth or
    identity capability importing the one that stores them — the seam shape the grant
    projection already uses. Nothing in the framework registers a second projector, so the fold
    *across* projectors is only observable with one registered here; without that, the
    accumulator is indistinguishable from `dict.update`, which would let whichever projector
    ran last lower an authority another had already reported.

    The fake reports a *lower* rank for a module the real projector also answers and a higher
    one for a module it does not, so both directions of the comparison are exercised.
    """
    subject = uuid.uuid4()
    register_subject_expander(lambda _session, _holder: ())
    with Session(engine) as session:
        ModuleRoleService().assign(session, subject, "notes", EDITOR.rank)
        session.commit()

        def _fake(_session: Session, _subject_id: uuid.UUID) -> dict[str, int]:
            return {"notes": VIEWER.rank, "reports": ADMIN.rank}

        # Restored by `_isolate_module_rank_projectors`, which snapshots rather than clears:
        # the capability's own registration is made at import and has to survive this test.
        register_module_rank_projector(_fake)
        projected = project_module_ranks(session, subject)

    assert projected == {"notes": EDITOR.rank, "reports": ADMIN.rank}


def test_a_stored_rank_is_filtered_only_where_a_model_declares_the_ladder(
    engine: Engine,
) -> None:
    """A guard built without a permission model cannot check a rank, so it does not pretend to.

    `build_guard`'s `permission_model` is optional, and the kernel's own guard tests build one
    without it. The rank filter has to answer something for that case, and taking the stored
    rank as given is the only answer that is not a lie: with no declared ladder there is no
    rung to compare against, and answering `0` would deny an app that simply never registered a
    model.

    Composition never reaches it — `create_app` resolves a control plane before it builds a
    guard, so a real mount always has the model and an undeclared rank really is refused, which
    is the pairing asserted here. This pins the hand-composed case, which is the one the
    kernel's own tests use.
    """
    subject = uuid.uuid4()
    viewer = Principal(id=subject, role=VIEWER)
    post = SimpleNamespace(method="POST")
    register_subject_expander(lambda _session, _holder: ())
    with Session(engine) as session:
        # A rank no default ladder declares. `assign` stores it: validation lives at the
        # writer, and the guard deliberately does not trust the table either way.
        ModuleRoleService().assign(session, subject, "notes", 25)
        session.commit()

        def _resolver(inner: Session, holder: uuid.UUID, module: str) -> int:
            return ModuleRoleService().highest_rank(inner, holder, module)

        undeclared_is_refused = build_guard(
            Policy.default(),
            module_name="notes",
            module_rank_resolver=_resolver,
            permission_model=PermissionModel.default(),
        )
        with pytest.raises(PermissionDeniedError):
            undeclared_is_refused(post, principal=viewer, session=session)

        # Same rank, same row, no model: nothing declares the ladder, so the rank stands and
        # a viewer clears the EDITOR write tier through it.
        no_ladder_to_check = build_guard(
            Policy.default(),
            module_name="notes",
            module_rank_resolver=_resolver,
            permission_model=None,
        )
        no_ladder_to_check(post, principal=viewer, session=session)  # no raise
