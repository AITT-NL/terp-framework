"""Typed permission model primitives for the app control plane.

The first control-plane slice keeps the existing three-tier role ladder working
while adding the typed objects future modules should reference. Authority is an
object here, never a string in module code.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum, IntEnum

from sqlmodel import Session


def _is_token(value: str) -> bool:
    """True for simple authority tokens (letters/digits/underscore/hyphen)."""
    return bool(value) and value.replace("_", "").replace("-", "").isalnum()


@dataclass(frozen=True, order=True)
class Role:
    """A named, ordered role tier in a consumer's permission model."""

    name: str
    rank: int

    def __post_init__(self) -> None:
        if not _is_token(self.name):
            raise ValueError(f"Role.name must be a simple token, got {self.name!r}")


class LabelCoverage(str, Enum):
    """How strictly an app requires its declarations to carry a human label.

    The same three-state shape as :class:`~terp.core.operations.OperationCoverage`, and for
    the same reason. A permission name is a dotted token addressed to a machine:
    ``notes.delete`` tells a person who already knows the codebase what holding it buys and
    tells everyone else nothing. ADR 0102 solved that for routes by giving each one a
    source-language sentence, and a permission has exactly the same reader — the
    administrator deciding whether to tick it — with no such field until now.

    ``STRICT`` is the state in which a permission editor can promise that every row it shows
    is explained. ``OFF`` is the default because turning the requirement on before
    declarations carry labels would refuse the boot of every app that has any — the same
    reason ADR 0102 gives about its own coverage flip. ``WARN`` is the staging step and
    afterwards the documented escape; ``OFF`` is honest about offering no guarantee at all.

    Whether ``STRICT`` should become the default is deliberately **not** claimed here.
    ADR 0102 only calls strict *its* destination default because that was settled and
    recorded as an amendment; the same question for labels is open, and is listed as such in
    ADR 0121. A docstring is the wrong place to decide it.
    """

    #: Labels are honored where present and never required (the default).
    OFF = "off"
    #: Unlabelled declarations are reported for a view to surface; the boot proceeds.
    WARN = "warn"
    #: A declared permission with no label fails the boot.
    STRICT = "strict"


@dataclass(frozen=True)
class Permission:
    """A named capability guarded by the minimum role that implies it.

    ``label`` is one sentence saying what *holding* this permission buys, in the source
    language — the text a permission editor puts beside the row it is asking an administrator
    to tick. It is optional in the constructor and gated by :class:`LabelCoverage` instead,
    which is deliberate on two counts: requiring it outright would break every existing call
    site for a field nothing renders yet, and the framework already has one proven way to
    stage exactly this kind of requirement (ADR 0102).

    It is a different question from an ``OperationDefinition`` label, which says what one
    *route* does. A permission is usually the authority behind several routes, and "Delete a
    note" is not an answer to "what does holding ``notes.delete`` mean".
    """

    name: str
    min_role: Role
    label: str = ""

    def __post_init__(self) -> None:
        if not self.name or any(not _is_token(part) for part in self.name.split(".")):
            raise ValueError(f"Permission.name must be a dotted token, got {self.name!r}")
        if self.label != self.label.strip():
            raise ValueError(
                f"Permission.label must not be padded with whitespace, got {self.label!r} "
                f"for {self.name!r}"
            )


@dataclass(frozen=True)
class AuthorizationRequirement:
    """The normalized form used by ``Policy`` and boot validation."""

    kind: str
    name: str
    min_rank: int

    @classmethod
    def from_role(cls, role: Role) -> AuthorizationRequirement:
        return cls(kind="role", name=role.name, min_rank=role.rank)

    @classmethod
    def from_permission(cls, permission: Permission) -> AuthorizationRequirement:
        return cls(
            kind="permission",
            name=permission.name,
            min_rank=permission.min_role.rank,
        )

    @property
    def label(self) -> str:
        return f"{self.kind}:{self.name}"


VIEWER = Role("viewer", rank=10)
EDITOR = Role("editor", rank=20)
ADMIN = Role("admin", rank=30)


def role_from_rank(rank: int) -> Role:
    """Return the default role object matching a legacy rank."""
    if rank == VIEWER.rank:
        return VIEWER
    if rank == EDITOR.rank:
        return EDITOR
    if rank == ADMIN.rank:
        return ADMIN
    raise ValueError(f"no default Role is registered for rank {rank}")


@dataclass(frozen=True)
class PermissionModel:
    """The central registry of authority objects for one application."""

    roles: Sequence[Role] = field(default_factory=lambda: (VIEWER, EDITOR, ADMIN))
    permissions: Sequence[Permission] = field(default_factory=tuple)
    label_coverage: LabelCoverage = LabelCoverage.OFF

    def __post_init__(self) -> None:
        roles = tuple(self.roles)
        permissions = tuple(self.permissions)
        role_names = _index_unique(roles, key=lambda role: role.name, label="role")
        role_ranks = _index_unique(roles, key=lambda role: role.rank, label="role rank")
        registered_roles = set(role_names.values())
        for permission in permissions:
            if permission.min_role not in registered_roles:
                raise ValueError(
                    f"permission {permission.name!r} references unregistered role "
                    f"{permission.min_role.name!r}"
                )
        permissions_by_name = _index_unique(
            permissions,
            key=lambda permission: permission.name,
            label="permission",
        )
        object.__setattr__(self, "roles", roles)
        object.__setattr__(self, "permissions", permissions)
        object.__setattr__(self, "_roles_by_name", role_names)
        object.__setattr__(self, "_roles_by_rank", role_ranks)
        object.__setattr__(self, "_permissions_by_name", permissions_by_name)

    @classmethod
    def default(cls) -> PermissionModel:
        """The compatibility model: the existing viewer < editor < admin ladder."""
        return cls()

    def has_requirement(self, requirement: AuthorizationRequirement) -> bool:
        """Return whether *requirement* is declared by this model."""
        if requirement.kind == "role":
            return requirement.name in self._roles_by_name
        if requirement.kind == "permission":
            return requirement.name in self._permissions_by_name
        return False

    def has_role(self, role: Role) -> bool:
        """Return whether *role* is registered exactly by name and rank."""
        registered = self._roles_by_name.get(role.name)
        return registered == role

    def missing_requirements(
        self, requirements: Iterable[AuthorizationRequirement]
    ) -> tuple[AuthorizationRequirement, ...]:
        """Every requirement whose *name* this model does not register at all."""
        return tuple(req for req in requirements if not self.has_requirement(req))

    def shadowed_requirements(
        self, requirements: Iterable[AuthorizationRequirement]
    ) -> tuple[AuthorizationRequirement, ...]:
        """Every requirement whose name is registered but whose rank floor disagrees.

        A registered *name* is not the same as the registered *entry*, and the difference is
        a privilege discrepancy rather than a tidiness one. ``Policy`` keeps the rank floor
        of whichever object it was handed (``AuthorizationRequirement.from_role`` /
        ``from_permission`` read it straight off), while every view — the access graph, the
        grant catalog, the Studio matrix — reports the floor of the entry this model
        registers. So a policy citing ``Role("admin", rank=1)``, or a same-name
        ``Permission`` declared with a lower ``min_role``, is enforced at the floor it
        carries and displayed at the floor that was declared.

        Authority was the only control-plane registry matched by name alone. Events, jobs and
        operations are each matched **by value**, and all three docstrings name this exact
        hazard — accepting a same-id definition "would let a route present one wording while
        the catalog documents another". An authority shadow is that with a rank attached,
        which is why it is the one worth a boot error rather than a warning.

        The comparison is on the rank floor only, not the whole object: an
        :class:`AuthorizationRequirement` carries ``kind`` / ``name`` / ``min_rank`` and not
        the ``Permission`` it came from, so a shadow differing *only* in ``label`` passes
        here. That one is caught where the module claims its permissions on its spec and the
        boot cross-checks those by value; it is harmless in the meantime, because every view
        projects the registered entry's label rather than the policy's copy.
        """
        shadows: list[AuthorizationRequirement] = []
        for requirement in requirements:
            declared_rank = self.declared_rank(requirement)
            if declared_rank is None or declared_rank == requirement.min_rank:
                continue
            low, high = sorted((declared_rank, requirement.min_rank))
            # Only a rank some registered role actually occupies makes the two floors
            # behave differently. Without this window the check refuses a configuration
            # ADR 0022 blesses: every bundled capability pins ``Policy(read_role=Roles.ADMIN)``
            # at rank 30, so an app declaring its own ``admin`` at 40 would be refused even
            # when it has no role in 30..39 for the gap to admit — the two floors are then
            # the same gate by different numbers, and refusing that is a false positive.
            if any(low <= role.rank < high for role in self.roles):
                shadows.append(requirement)
        return tuple(shadows)

    def has_permission(self, permission: Permission) -> bool:
        """Whether *permission* is the canonical entry registered for its name.

        Matched by **value**, exactly as the event, job and operation catalogs match theirs,
        and for the reason all three docstrings give: a same-name declaration carrying a
        different floor or a different label is a *shadow*, and accepting it would let a
        module claim one thing while the control plane documents another.
        """
        return self._permissions_by_name.get(permission.name) == permission

    def missing_permissions(
        self, permissions: Iterable[Permission]
    ) -> tuple[Permission, ...]:
        """Every permission that is not this model's registered entry, by value."""
        return tuple(p for p in permissions if not self.has_permission(p))

    def declares(self, name: str) -> bool:
        """Whether a permission called *name* is declared at all.

        The name-only question, for the one caller that has only a name: a route-level
        ``require_permission`` marker records the permission's name, not the object.
        """
        return name in self._permissions_by_name

    def unlabelled_permissions(self) -> tuple[Permission, ...]:
        """Every declared permission carrying no label, in declaration order.

        The input to the boot-time coverage check. Roles are deliberately not included: a
        role name is already a word a person reads (``viewer``), and the packaged ladder is
        localized through the frontend catalog rather than declared here.
        """
        return tuple(
            permission for permission in self.permissions if not permission.label
        )

    def declared_rank(self, requirement: AuthorizationRequirement) -> int | None:
        """The rank floor this model declares for *requirement*, or ``None`` if unregistered."""
        if requirement.kind == "role":
            return getattr(self._roles_by_name.get(requirement.name), "rank", None)
        if requirement.kind == "permission":
            permission = self._permissions_by_name.get(requirement.name)
            return None if permission is None else permission.min_role.rank
        return None

    def has_rank(self, rank: int) -> bool:
        """Whether this model declares a role at *rank*.

        The guard's counterpart to :meth:`has_role` for a rank that arrives without a role
        object — a per-module rung, which is stored as an integer because rank is what the
        guard compares. Without it the two were asymmetric: an unregistered *global* role was
        refused while an unregistered *module* rank cleared any floor, so a row at rank 999
        was full authority in that module even though no ladder declared it.
        """
        return rank in self._roles_by_rank

    def role_for_rank(self, rank: int) -> Role:
        """Return the registered role with *rank*, or fail closed."""
        try:
            return self._roles_by_rank[rank]
        except KeyError as exc:
            raise ValueError(f"no Role with rank {rank} is registered") from exc


def _index_unique[T, K](items: Sequence[T], *, key: Callable[[T], K], label: str) -> dict[K, T]:
    """Index *items* by *key* while rejecting duplicate declarations."""
    indexed: dict[K, T] = {}
    for item in items:
        item_key = key(item)
        if item_key in indexed:
            raise ValueError(f"duplicate {label} declaration: {item_key!r}")
        indexed[item_key] = item
    return indexed


def requirement_from(value: Role | Permission | IntEnum) -> AuthorizationRequirement:
    """Normalize a public authz object to an authorization requirement.

    ``IntEnum`` support keeps the legacy ``Roles`` enum compatible while the new
    typed model lands.
    """
    if isinstance(value, Permission):
        return AuthorizationRequirement.from_permission(value)
    if isinstance(value, Role):
        return AuthorizationRequirement.from_role(value)
    if isinstance(value, IntEnum):
        return AuthorizationRequirement.from_role(role_from_rank(int(value)))
    raise TypeError(
        "authorization requirements must be Role, Permission, or the legacy Roles enum"
    )


def as_role(value: Role | IntEnum) -> Role:
    """Normalize a role reference to a typed :class:`Role`.

    A ``Role`` passes through unchanged; the legacy ``Roles`` ``IntEnum`` maps to
    the matching default role by rank. This is the seam that lets a principal or
    token carry any consumer-defined role while the bundled ``Roles`` enum keeps
    working.
    """
    if isinstance(value, Role):
        return value
    if isinstance(value, IntEnum):
        return role_from_rank(int(value))
    raise TypeError("a role must be a Role or the legacy Roles enum")


# --------------------------------------------------------------------------- #
# The permission-projection seam (ADR 0096)
# --------------------------------------------------------------------------- #

# What a caller's *own* effective permission names are, for the UI to gate on. The
# capability that owns grants fills this; the kernel and the auth capability never import
# it, exactly like a scope predicate (ADR 0017).
PermissionProjector = Callable[[Session, uuid.UUID], Iterable[str]]

_permission_projectors: list[PermissionProjector] = []


def register_permission_projector(projector: PermissionProjector) -> None:
    """Register a source of a caller's effective permission names (idempotent).

    The access capability registers its grant lookup here at import, so ``GET /me`` reports
    what the caller may actually do without the auth capability importing access. More than
    one may register (grants plus, say, a licence-derived set); the projections are unioned,
    which is the only composition that cannot *remove* an authority the server would honour
    — a UI that under-reports hides a button the user is entitled to, and one that
    over-reports shows a button the server refuses, so the union is the honest side to err on
    only because every projector is itself authoritative for what it returns.
    """
    if projector not in _permission_projectors:
        _permission_projectors.append(projector)


def registered_permission_projectors() -> tuple[PermissionProjector, ...]:
    """Every registered projector, in registration order."""
    return tuple(_permission_projectors)


def project_permissions(session: Session, subject_id: uuid.UUID) -> tuple[str, ...]:
    """The caller's effective permission names, sorted and deduplicated.

    Empty when nothing is registered, which is the honest answer for an app that mounts no
    grant capability: it has no named permissions, so a UI has nothing to gate on beyond
    role rank. Sorted so the ``/me`` payload is stable — an unstable list would defeat any
    client-side caching and make the response diff noisily in tests.
    """
    projected: set[str] = set()
    for projector in _permission_projectors:
        projected.update(projector(session, subject_id))
    return tuple(sorted(projected))


def reset_permission_projectors() -> None:
    """Clear the registry (a test seam; capabilities re-register at import)."""
    _permission_projectors.clear()


# --------------------------------------------------------------------------- #
# The module-rank projection seam (ADR 0121)
# --------------------------------------------------------------------------- #

# Which rung a caller holds in each module, for the UI to gate on. Shaped like
# ``PermissionProjector`` and filled the same way, by the capability that owns the rows.
ModuleRankProjector = Callable[[Session, uuid.UUID], Mapping[str, int]]

_module_rank_projectors: list[ModuleRankProjector] = []


def register_module_rank_projector(projector: ModuleRankProjector) -> None:
    """Register a source of the caller's per-module rungs (idempotent).

    The frontend half of per-module authority, and without it the control is half-built: the
    guard honours a rung the packaged UI cannot see, so a module a caller may reach only
    through one stays hidden and the button they are entitled to is never rendered. The
    ideology calls a control that exists on one side of the wire only what it is.

    Composed by taking the **highest** rung per module across projectors, which is the same
    composition the guard performs and the only one that cannot report less authority than the
    server will honour. Under-reporting hides a button someone may use; over-reporting shows
    one the server refuses. Neither is good and the second is at least visible, but the real
    reason is that ``max`` is what the resolver does, so any other choice would make the two
    sides disagree by construction.
    """
    if projector not in _module_rank_projectors:
        _module_rank_projectors.append(projector)


def project_module_ranks(session: Session, subject_id: uuid.UUID) -> dict[str, int]:
    """The caller's rung in each module they hold one in, highest wins.

    Empty for an app that mounts no assignment capability, which is the honest answer: it has
    no per-module rungs, so a UI gates on the global rank exactly as it did before.
    """
    projected: dict[str, int] = {}
    for projector in _module_rank_projectors:
        for module, rank in projector(session, subject_id).items():
            # Sentinel-free for the reason the other two accumulators are: a `-1` default
            # silently drops a rank at or below it, and ranks are app-declared integers.
            current = projected.get(module)
            if current is None or rank > current:
                projected[module] = rank
    return dict(sorted(projected.items()))


def reset_module_rank_projectors() -> None:
    """Clear the registry (a test seam; capabilities re-register at import)."""
    _module_rank_projectors.clear()


__all__ = [
    "ADMIN",
    "AuthorizationRequirement",
    "EDITOR",
    "LabelCoverage",
    "ModuleRankProjector",
    "Permission",
    "PermissionModel",
    "PermissionProjector",
    "Role",
    "VIEWER",
    "as_role",
    "project_module_ranks",
    "project_permissions",
    "register_module_rank_projector",
    "register_permission_projector",
    "registered_permission_projectors",
    "reset_module_rank_projectors",
    "reset_permission_projectors",
    "requirement_from",
    "role_from_rank",
]