"""The extension seam: ``ModuleSpec`` + ``Policy`` + ``Roles``.

A Terp module exposes exactly one :class:`ModuleSpec`. This is the entire public
extension surface: discovery collects every spec and the composition root wires
routers (behind a policy-derived guard), services, event ``emits`` / ``subscribes``,
and declared ``jobs`` with no central edits. Cross-cutting references —
``policy``, the event ``emits`` / ``subscribes``, and ``jobs`` — are typed
control-plane objects, never bare strings, and the boot validates them against the
control plane.

Secure-by-default: a module's security posture is **declared** as a
:class:`Policy`. The composition root denies any router whose spec declares no
policy (deny-by-default); a truly public route must opt in via
``Policy.public(reason=...)`` — a visible, justified exception (greppable by its
reason). A public **write** additionally trips the ``public_modules_are_read_only``
rule, so an unauthenticated mutation needs a budgeted opt-out (ADR 0040).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import IntEnum

from fastapi import APIRouter

from terp.core.events import EventDefinition
from terp.core.jobs import JobDefinition
from terp.core.permissions import (
    AuthorizationRequirement,
    Permission,
    Role,
    requirement_from,
)


class Roles(IntEnum):
    """Ordered role vocabulary; higher value = more privilege.

    Deliberately generic (not a company-specific role list). Capabilities and
    apps map their own role semantics onto these tiers.
    """

    VIEWER = 10
    EDITOR = 20
    ADMIN = 30


AuthzRef = Role | Permission | Roles


@dataclass(frozen=True, init=False)
class Policy:
    """A module's declared security posture.

    ``Policy.default()`` is authenticated, reads require ``VIEWER`` and mutations
    require ``EDITOR``. ``Policy.public(reason=...)`` is the only way to drop
    authentication, and it requires a non-empty justification.
    """

    authenticated: bool
    read_requirement: AuthorizationRequirement
    write_requirement: AuthorizationRequirement
    public_reason: str | None
    public_write_reason: str | None

    def __init__(
        self,
        *,
        authenticated: bool = True,
        read: AuthzRef | None = None,
        write: AuthzRef | None = None,
        read_role: Roles | None = None,
        write_role: Roles | None = None,
        public_reason: str | None = None,
        public_write_reason: str | None = None,
    ) -> None:
        if read is not None and read_role is not None:
            raise ValueError("Policy accepts read= or read_role=, not both (fix recipe: terp guide policy)")
        if write is not None and write_role is not None:
            raise ValueError("Policy accepts write= or write_role=, not both (fix recipe: terp guide policy)")
        normalized_public_reason = public_reason.strip() if public_reason is not None else None
        normalized_public_write_reason = (
            public_write_reason.strip() if public_write_reason is not None else None
        )
        if normalized_public_reason == "":
            raise ValueError("Policy public_reason requires a non-empty justification (fix recipe: terp guide policy)")
        if normalized_public_write_reason == "":
            raise ValueError("Policy public_write_reason requires a non-empty justification (fix recipe: terp guide policy)")
        if normalized_public_reason is not None and authenticated:
            raise ValueError("Policy public_reason requires authenticated=False (fix recipe: terp guide policy)")
        if normalized_public_write_reason is not None and normalized_public_reason is None:
            raise ValueError("Policy public_write_reason requires public_reason (fix recipe: terp guide policy)")
        read_value = read if read is not None else (read_role or Roles.VIEWER)
        write_value = write if write is not None else (write_role or Roles.EDITOR)
        object.__setattr__(self, "authenticated", authenticated)
        object.__setattr__(self, "read_requirement", requirement_from(read_value))
        object.__setattr__(self, "write_requirement", requirement_from(write_value))
        object.__setattr__(self, "public_reason", normalized_public_reason)
        object.__setattr__(self, "public_write_reason", normalized_public_write_reason)

    @classmethod
    def default(cls) -> Policy:
        """Secure default: authenticated; read=VIEWER, write=EDITOR."""
        return cls()

    @classmethod
    def public(cls, *, reason: str) -> Policy:
        """Opt out of authentication with a mandatory, greppable justification."""
        if not reason or not reason.strip():
            raise ValueError("Policy.public(reason=...) requires a non-empty justification (fix recipe: terp guide policy)")
        return cls(authenticated=False, public_reason=reason.strip())

    @classmethod
    def public_write(cls, *, reason: str) -> Policy:
        """Opt out of authentication for routes that include writes.

        Public write surfaces (login, OAuth callbacks, webhooks) are rare and must be
        explicitly visible at runtime. ``Policy.public`` remains read-only; boot refuses
        public routers with mutating methods unless they use this stronger opt-out.
        """
        if not reason or not reason.strip():
            raise ValueError("Policy.public_write(reason=...) requires a non-empty justification (fix recipe: terp guide policy)")
        normalized = reason.strip()
        return cls(
            authenticated=False,
            public_reason=normalized,
            public_write_reason=normalized,
        )

    @classmethod
    def tiers(cls, *, read: AuthzRef, write: AuthzRef) -> Policy:
        """Policy sugar for tier-only apps; internally identical to ``Policy(read=...)``."""
        return cls(read=read, write=write)

    @property
    def is_public(self) -> bool:
        return self.public_reason is not None

    @property
    def allows_public_writes(self) -> bool:
        return self.public_write_reason is not None


@dataclass(frozen=True)
class ModuleSpec:
    """The single manifest a module exposes — the entire public extension API.

    Only ``name`` is required. ``policy`` is intentionally optional here so the
    composition root can **fail closed** on a missing policy (deny-by-default)
    rather than this dataclass silently defaulting to something permissive.

    ``max_request_bytes`` declares a request-body ceiling for this module's own
    mount prefix (``/api/v1/<name>``): the kernel's request-size middleware
    applies it instead of the global ``SecurityConfig.max_request_bytes`` for
    requests under that prefix — and only there, so a body-carrying surface (a
    file upload) can accept more than the global cap without widening it for
    every other endpoint (ADR 0067). ``None`` (the default) keeps the global cap.
    """

    name: str
    router: APIRouter | None = None
    services: Sequence[type] = field(default_factory=tuple)
    requires: Sequence[str] = field(default_factory=tuple)
    emits: Sequence[EventDefinition] = field(default_factory=tuple)
    subscribes: Sequence[EventDefinition] = field(default_factory=tuple)
    jobs: Sequence[JobDefinition] = field(default_factory=tuple)
    policy: Policy | None = None
    tenant_scoped: bool = False
    max_request_bytes: int | None = None

    def __post_init__(self) -> None:
        if not self.name or not self.name.isidentifier():
            raise ValueError(
                f"ModuleSpec.name must be a valid identifier, got {self.name!r}"
            )
        if self.max_request_bytes is not None and self.max_request_bytes <= 0:
            raise ValueError(
                "ModuleSpec.max_request_bytes must be positive when set, got "
                f"{self.max_request_bytes!r}"
            )


__all__ = ["AuthzRef", "ModuleSpec", "Policy", "Roles"]
