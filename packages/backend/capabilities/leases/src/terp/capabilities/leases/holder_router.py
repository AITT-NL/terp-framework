"""The HOLDER's surface: one endpoint, so a worker outside this process can stay alive.

Separate from ``router.py`` on purpose, and the separation is the design. That router is an
operator's window — three endpoints, all ``ADMIN``, and a documented refusal to offer a
force-release, because stealing a live lease is the split brain the fence exists to prevent.
A worker proving it is still working is not an operator action, so folding a heartbeat into
that module would have meant either making every worker an admin or quietly widening a gate
whose narrowness is the point.

The auth capability already answers this shape: it ships a public-write login module beside
a ``Policy.default()`` ``me`` module, one capability with two audiences and two policies.
This is the same, and the app mounts whichever it needs::

    create_app(
        specs=[
            leases.module,                                    # operators: who holds what
            leases.holder_module(resolve_holder=my_resolver),  # workers: I am still here
        ],
        lease_store=DatabaseLeaseStore(),
    )

**Why the app supplies the resolver.** Authentication says which principal is calling;
only the app knows what that principal is *called* in its own leases — a service-account
id, a worker name, a pod identity. The platform cannot guess that mapping, and guessing it
is how an endpoint ends up trusting a holder id the caller simply asserted. So the seam is
a callable, exactly as ``build_me_router`` takes ``resolve_current_user``: the app maps
principal to holder, and a caller that resolves to a different holder is refused before
anything is renewed.

Three checks stand between a request and a renewed lease, and none is redundant:

* the module policy rejects an anonymous caller;
* *resolve_holder* refuses a caller acting as a holder that is not theirs;
* the store's fence refuses an ``epoch`` that is not the live one, so a heartbeat from a
  process whose claim was already reaped and re-granted extends nothing.

The last one is what makes a late heartbeat safe rather than catastrophic: the worst a
stale holder can do is learn that it lost the lease.
"""

from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, Depends

from terp.core import (
    AuthenticationError,
    ConflictError,
    LeaseResource,
    ModuleSpec,
    PermissionDeniedError,
    Policy,
    Roles,
    Principal,
    SessionDep,
    get_principal,
    operation,
)

from terp.capabilities.leases.operations import LEASES_HEARTBEAT
from terp.capabilities.leases.schemas import LeaseHeartbeat, LeaseHeartbeatAccepted
from terp.capabilities.leases.service import heartbeat

#: Maps the authenticated principal to the lease holder id it may act as, or ``None`` when
#: this principal holds no leases at all. The app owns this because the holder vocabulary
#: is the app's, not the platform's.
HolderResolver = Callable[[Principal], str | None]


def build_holder_router(resolve_holder: HolderResolver) -> APIRouter:
    """Build the holder's heartbeat router via the *resolve_holder* seam."""
    router = APIRouter(tags=["leases"])

    @router.post("/{kind}/{key}/heartbeat", response_model=LeaseHeartbeatAccepted)
    @operation(LEASES_HEARTBEAT)
    def send_heartbeat(
        kind: str,
        key: str,
        body: LeaseHeartbeat,
        session: SessionDep,
        principal: Principal | None = Depends(get_principal),
    ) -> LeaseHeartbeatAccepted:
        # The module guard rejects anonymous callers before this runs; the explicit check
        # keeps the router correct — a clean 401, never an AttributeError — even if it were
        # ever mounted without that guard. Same reasoning as `build_me_router`.
        if principal is None:
            raise AuthenticationError()
        acting_as = resolve_holder(principal)
        if acting_as is None or acting_as != body.holder:
            # Deliberately not 404: the caller IS authenticated and the resource may well
            # exist. What it may not do is speak for a holder that is not itself, and
            # saying so is not a leak — it already knows its own identity.
            raise PermissionDeniedError(
                "this principal may not heartbeat a lease held by another holder"
            )
        renewed = heartbeat(
            session,
            LeaseResource(kind=kind, key=key),
            holder=body.holder,
            epoch=body.epoch,
            ttl_seconds=body.ttl_seconds,
        )
        if renewed is None:
            # One meaning, and it is the actionable one: you are not the holder any more.
            # Either the claim lapsed and was re-granted, or the epoch is stale. Both say
            # STOP WORKING — a successor may already be doing this, and continuing is the
            # double-processing the lease was taken to prevent.
            raise ConflictError(
                "this lease is no longer held at that epoch; stop working on the resource "
                "— it has lapsed or been re-granted"
            )
        assert renewed.expires_at is not None  # noqa: S101 - a renewed lease always has one
        return LeaseHeartbeatAccepted(
            resource_kind=kind,
            resource_key=key,
            holder=renewed.holder,
            epoch=renewed.epoch,
            expires_at=renewed.expires_at,
        )

    return router


def holder_module(*, resolve_holder: HolderResolver, name: str = "custody") -> ModuleSpec:
    """The holder-facing lease module: authenticated, and fenced rather than privileged.

    Mounted at ``/api/v1/custody`` rather than under ``leases``, because a module's name IS
    its prefix and the operator's window already owns that one. ``custody`` is ADR 0095's
    own word for what a lease is — and it reads as what the caller is doing (*keeping* its
    custody) rather than as a second way to administer leases.

    Authenticated, at ``VIEWER`` for both — not ``ADMIN``, and deliberately not the
    ``EDITOR`` that ``Policy.default()`` asks of a write. A heartbeat is a holder's report
    about its OWN claim: the only thing it can change is the expiry of a lease the caller
    already holds, and the authorization that matters is the holder mapping plus the epoch
    fence, neither of which a role can express. Demanding ``EDITOR`` would make a worker
    that leases a resource in order to READ it consistently take a write privilege it
    otherwise has no business holding — a gate that looks stricter while granting more.
    """
    return ModuleSpec(
        name=name,
        router=build_holder_router(resolve_holder),
        policy=Policy(read=Roles.VIEWER, write=Roles.VIEWER),
    )


__all__ = ["HolderResolver", "build_holder_router", "holder_module"]
