"""The self-scoped second-factor router: set one up, prove it, inspect it, remove it.

Every route here acts on **the caller's own** account, read from the authenticated
principal. None takes a subject id, so none can be turned into a way to enrol, inspect or
disable somebody else's factor — the shape ``GET /me`` uses, and for the same reason: an
id parameter on a self-scoped route is an object-level authorization bug waiting for the
first person who tries another id.

Mounted at the VIEWER tier for both reads and writes: any authenticated caller manages
their own factor, because a read-only account is not a second-class one.
There is deliberately no administrative *disable* route. An operator who can turn off
somebody else's second factor is the weakest link in the control, and support-desk
disabling is the social-engineering path that defeats MFA in practice — a person who has
lost their phone uses a recovery code, which is why the enrolment issues them.
"""

from __future__ import annotations

from typing import Final

from fastapi import APIRouter, Depends

from terp.core import (
    AuthenticationError,
    ModuleSpec,
    Policy,
    Principal,
    Roles,
    SessionDep,
    get_principal,
    operation,
)

from terp.capabilities.mfa.operations import (
    MFA_CONFIRM,
    MFA_DISABLE,
    MFA_ENROL,
    MFA_STATUS,
)
from terp.capabilities.mfa.schemas import (
    MfaCodeRequest,
    MfaEnrolmentRead,
    MfaSecretIssued,
    MfaStatusRead,
)
from terp.capabilities.mfa.service import MfaService

router = APIRouter(tags=["mfa"])
_service = MfaService()

#: The label an authenticator app shows beside the generated codes. A person may hold
#: accounts in several systems, and the issuer is the only thing distinguishing one
#: six-digit row from another, so it is the deployment's own name — the framework cannot
#: know it and declines to guess, defaulting to its own name rather than inventing one.
DEFAULT_ISSUER: Final[str] = "Terp"

# The active issuer (module-level, composition-root-configured — the same seam shape the
# files capability uses for its upload limit). Never client data: it is baked into every
# enrolment QR code, so a caller who could set it could make their enrolment impersonate
# another system in the victim's authenticator app.
_issuer: str = DEFAULT_ISSUER


def configure_mfa_issuer(name: str) -> None:
    """Name the deployment in the codes its people enrol (a composition-root line).

    Validated eagerly so a mis-wired root fails at boot rather than at the first
    enrolment — and a blank issuer is the failure worth catching, because it produces a
    QR code that scans cleanly and then shows up in the authenticator app as an unlabelled
    row the person cannot tell from any other.
    """
    global _issuer
    cleaned = name.strip()
    if not cleaned:
        raise ValueError("the MFA issuer must be a non-empty name")
    _issuer = cleaned


def active_mfa_issuer() -> str:
    """The issuer new enrolments are currently labelled with."""
    return _issuer


def reset_mfa_issuer() -> None:
    """Restore the default issuer (the test-isolation reset)."""
    global _issuer
    _issuer = DEFAULT_ISSUER


def _caller(principal: Principal | None) -> Principal:
    """The authenticated caller, or a clean 401.

    The module guard rejects an anonymous caller before any handler runs; this keeps the
    router correct — a 401, never an ``AttributeError`` — if it is ever mounted without
    one.
    """
    if principal is None:
        raise AuthenticationError()
    return principal


@router.get("/", response_model=MfaStatusRead)
@operation(MFA_STATUS)
def read_status(
    session: SessionDep, principal: Principal | None = Depends(get_principal)
) -> MfaStatusRead:
    from sqlmodel import select

    from terp.capabilities.mfa.models import MfaRecoveryCode

    caller = _caller(principal)
    enrolment = _service.enrolment_for(session, caller.id)
    remaining = 0
    if enrolment is not None:
        remaining = len(
            session.exec(
                select(MfaRecoveryCode).where(
                    MfaRecoveryCode.enrolment_id == enrolment.id,
                    MfaRecoveryCode.used_at.is_(None),  # type: ignore[union-attr]
                )
            ).all()
        )
    return MfaStatusRead(
        enrolled=enrolment is not None,
        confirmed=enrolment is not None and enrolment.confirmed_at is not None,
        recovery_codes_remaining=remaining,
    )


@router.post("/", response_model=MfaSecretIssued, status_code=201)
@operation(MFA_ENROL)
def begin_enrolment(
    session: SessionDep, principal: Principal | None = Depends(get_principal)
) -> MfaSecretIssued:
    # The only response in this capability that carries a plaintext secret, and the only
    # moment one crosses the boundary: an authenticator app cannot be enrolled without
    # it. It is not stored in this form and no read DTO can return it again.
    caller = _caller(principal)
    return _service.begin_enrolment(
        session,
        caller.id,
        account=str(caller.id),
        issuer=active_mfa_issuer(),
    )


@router.post("/confirm", response_model=MfaEnrolmentRead)
@operation(MFA_CONFIRM)
def confirm_enrolment(
    payload: MfaCodeRequest,
    session: SessionDep,
    principal: Principal | None = Depends(get_principal),
) -> MfaEnrolmentRead:
    caller = _caller(principal)
    return MfaEnrolmentRead.model_validate(
        _service.confirm_enrolment(session, caller.id, payload.code)
    )


@router.delete("/", status_code=204)
@operation(MFA_DISABLE)
def disable(
    session: SessionDep, principal: Principal | None = Depends(get_principal)
) -> None:
    caller = _caller(principal)
    _service.disable(session, caller.id)


def build_mfa_module(*, name: str = "mfa") -> ModuleSpec:
    """The self-scoped second-factor ``ModuleSpec`` (any authenticated caller).

    VIEWER on the write tier, not the EDITOR a bare ``Policy.default()`` would impose.
    Enrolling is a POST, but it changes nothing except the caller's own security, and a
    read-only account is not a second-class one: gating this at EDITOR would deny a
    second factor to exactly the accounts an application hands out most freely, which
    inverts the control.
    """
    return ModuleSpec(
        name=name, router=router, policy=Policy(read=Roles.VIEWER, write=Roles.VIEWER)
    )


module = build_mfa_module()


__all__ = [
    "DEFAULT_ISSUER",
    "active_mfa_issuer",
    "build_mfa_module",
    "configure_mfa_issuer",
    "module",
    "reset_mfa_issuer",
    "router",
]
