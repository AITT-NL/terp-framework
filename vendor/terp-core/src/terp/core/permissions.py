"""Typed permission model primitives for the app control plane.

The first control-plane slice keeps the existing three-tier role ladder working
while adding the typed objects future modules should reference. Authority is an
object here, never a string in module code.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from enum import IntEnum


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


@dataclass(frozen=True)
class Permission:
    """A named capability guarded by the minimum role that implies it."""

    name: str
    min_role: Role

    def __post_init__(self) -> None:
        if not self.name or any(not _is_token(part) for part in self.name.split(".")):
            raise ValueError(f"Permission.name must be a dotted token, got {self.name!r}")


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
        """Every requirement not registered in this model."""
        return tuple(req for req in requirements if not self.has_requirement(req))

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


__all__ = [
    "ADMIN",
    "AuthorizationRequirement",
    "EDITOR",
    "Permission",
    "PermissionModel",
    "Role",
    "VIEWER",
    "as_role",
    "requirement_from",
    "role_from_rank",
]