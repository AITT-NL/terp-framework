"""At-rest sealing for the TOTP shared secret.

The enrolment secret *is* the second factor: anyone holding it can generate the codes
for that account forever, and unlike a password it is never rotated by the person who
owns it. A database leak of plaintext secrets would therefore hand over every enrolled
account's second factor silently — the victims' phones keep producing the same codes the
attacker now produces, so nothing about the account looks wrong.

The cipher is a deliberate sibling of ``terp.capabilities.webhooks.sealing`` rather than
a call into it: Fernet (AES128-CBC + HMAC-SHA256) keyed from the live ``SECRET_KEY``
through HKDF with an **MFA-specific** ``info`` label. Domain separation is the point — a
sealed value from one domain must not decrypt in another, so a leaked webhook secret is
not an enrolment secret and neither is a sealed config value. Each is its own
:class:`~terp.core.SealingDomain`, which owns key rotation (ADR 0189): a secret is
sealed under ``SECRET_KEY`` and opens under it or any ``SECRET_KEY_DECRYPT_FALLBACKS``
entry, and ``terp secrets reseal`` rewrites one sealed under a retired key.

Unlike the webhook secret there is **no legacy tolerance**. That capability passes an
unsealed value through unchanged, because rows predating its sealing control exist and
must keep delivering. No row here predates this control, so a secret that does not
carry the sealed prefix is not a legacy value — it is a bug or a tampered row, and
reading it as a valid factor would be the one mistake this module exists to prevent.
"""

from __future__ import annotations

from typing import Final

from terp.core import AppError, SealingDomain

# Domain separation: the MFA-seal key is derived from SECRET_KEY with this label, never
# SECRET_KEY itself and never another capability's derivation.
_HKDF_INFO: Final[bytes] = b"terp.capabilities.mfa.totp-seal.v1"

_DOMAIN: Final[SealingDomain] = SealingDomain("mfa.totp", _HKDF_INFO)


class MfaSecretError(AppError):
    """500 — an enrolment secret could not be read under any configured key.

    Deliberately a 500 and deliberately not "invalid code": the caller did nothing
    wrong, and reporting it as a failed verification would tell an operator their users
    are typing the wrong digits while the real fault is a rotated key or a damaged row.
    """

    status_code = 500
    code = "mfa_secret_error"
    default_message = "The second-factor enrolment could not be read."


def is_sealed_secret(value: str) -> bool:
    """Whether *value* carries the sealed ``enc:v1:`` format."""
    return _DOMAIN.is_sealed(value)


def seal_secret(plaintext: str) -> str:
    """Seal a TOTP shared secret for at-rest storage, under ``SECRET_KEY``."""
    return _DOMAIN.seal(plaintext)


def unseal_secret(stored: str) -> str:
    """The verification-time plaintext of *stored* — fail-closed on anything else.

    A value with no sealed prefix raises rather than being used: see the module
    docstring for why this capability has no legacy-plaintext path. A sealed value
    opens under ``SECRET_KEY`` or a ``SECRET_KEY_DECRYPT_FALLBACKS`` entry, or not at all.
    """
    opened = _DOMAIN.open(stored)
    if opened is None:
        raise MfaSecretError()
    return opened[0]


__all__ = ["MfaSecretError", "is_sealed_secret", "seal_secret", "unseal_secret"]
