"""terp.capabilities.mfa — a TOTP second factor, with recovery codes (ADR 0151).

Authentication in this platform was password-only, with OIDC as the single way to
delegate a second factor to somebody else's identity provider. An application whose most
dangerous surface is reached by an ordinary admin password — the parameters and
credential references that touch production systems — had no answer to offer.

This capability is that answer, and it is deliberately the smaller half of one:

* :mod:`~terp.capabilities.mfa.totp` implements RFC 6238 on the standard library, and is
  held to the specification's own **test vectors** rather than to its author's
  confidence.
* :mod:`~terp.capabilities.mfa.sealing` seals the shared secret at rest under an
  MFA-specific HKDF label. The secret *is* the factor and is never rotated by the person
  who owns it, so a plaintext leak hands over every enrolled account silently.
* :mod:`~terp.capabilities.mfa.recovery` issues single-use recovery codes, shown once and
  stored as digests — because a second factor with no way back in is a way to lose an
  account, and the support process that grows around that gap is weaker than the factor.
* The self-scoped router at ``/api/v1/mfa`` sets a factor up, proves it, reports it and
  removes it. Every route acts on the caller's own account and none takes a subject id.

**Enrolment is two steps on purpose.** A secret is issued, and gates nothing until a code
generated from it comes back. A secret that was mis-scanned and treated as live is a
lockout at the next login, which is the failure that makes people turn the feature off.

A **library** capability: it declares no ``terp.capabilities`` auto-discovery entry point.
A second factor is not something an app should acquire by installing a package — the
login route has to consult it, which is an explicit wiring decision — and mounting
enrolment in an app whose login never checks a factor would publish a control that does
nothing.
"""

from __future__ import annotations

from terp.capabilities.mfa.models import MfaEnrolment, MfaRecoveryCode
from terp.capabilities.mfa.operations import (
    MFA_CONFIRM,
    MFA_DISABLE,
    MFA_ENROL,
    MFA_OPERATIONS,
    MFA_STATUS,
)
from terp.capabilities.mfa.recovery import CODE_COUNT, generate_codes
from terp.capabilities.mfa.router import (
    DEFAULT_ISSUER,
    active_mfa_issuer,
    build_mfa_module,
    configure_mfa_issuer,
    module,
    reset_mfa_issuer,
    router,
)
from terp.capabilities.mfa.schemas import (
    MfaCodeRequest,
    MfaEnrolmentCreate,
    MfaEnrolmentRead,
    MfaEnrolmentUpdate,
    MfaSecretIssued,
    MfaStatusRead,
)
from terp.capabilities.mfa.sealing import (
    MfaSecretError,
    is_sealed_secret,
    seal_secret,
    unseal_secret,
)
from terp.capabilities.mfa.service import (
    MfaAlreadyEnrolledError,
    MfaCodeInvalidError,
    MfaNotEnrolledError,
    MfaService,
)

__all__ = [
    "CODE_COUNT",
    "DEFAULT_ISSUER",
    "MFA_CONFIRM",
    "MFA_DISABLE",
    "MFA_ENROL",
    "MFA_OPERATIONS",
    "MFA_STATUS",
    "MfaAlreadyEnrolledError",
    "MfaCodeInvalidError",
    "MfaCodeRequest",
    "MfaEnrolment",
    "MfaEnrolmentCreate",
    "MfaEnrolmentRead",
    "MfaEnrolmentUpdate",
    "MfaNotEnrolledError",
    "MfaRecoveryCode",
    "MfaSecretError",
    "MfaSecretIssued",
    "MfaService",
    "MfaStatusRead",
    "active_mfa_issuer",
    "build_mfa_module",
    "configure_mfa_issuer",
    "generate_codes",
    "is_sealed_secret",
    "module",
    "reset_mfa_issuer",
    "router",
    "seal_secret",
    "unseal_secret",
]
