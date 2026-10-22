"""At-rest sealing for the webhook signing secret (ADR 0076).

A ``WebhookSubscription.secret`` signs every outbound delivery, so a database
leak of plaintext secrets would let an attacker forge deliveries to every
registered receiver. The service chokepoint therefore seals the secret before
it is persisted (:func:`seal_secret`) and the delivery job unseals it only at
signing time (:func:`unseal_secret`) — the plaintext never rests in the row.

The cipher mirrors ``terp.core.secrets``: Fernet (AES128-CBC + HMAC-SHA256),
keyed from the live ``SECRET_KEY`` through an HKDF with a **webhooks-specific**
``info`` label — domain-separated from the config-seal key and every other
``SECRET_KEY`` use, so no sealed value is valid in another domain. This is a
deliberate sibling of (not a call into) the config-sealing API: that surface
guards a *single* registered decrypt call site for configuration, while the
webhook secret is unsealed by the delivery handler as part of normal operation.
What the two share is the :class:`~terp.core.SealingDomain` underneath, which
owns key rotation (ADR 0189): a secret is sealed under ``SECRET_KEY`` and opens
under it or any ``SECRET_KEY_DECRYPT_FALLBACKS`` entry, and ``terp secrets
reseal`` rewrites one sealed under a retired key.

Legacy tolerance: a row written before this control holds the plaintext secret;
:func:`unseal_secret` passes an unsealed value through unchanged so an existing
subscription keeps delivering, and the next secret rotation seals it.
"""

from __future__ import annotations

from typing import Final

from terp.core import AppError, SealingDomain

# Domain separation: the webhook-seal key is derived from SECRET_KEY with this
# label, never SECRET_KEY itself and never the config-seal derivation.
_HKDF_INFO: Final[bytes] = b"terp.capabilities.webhooks.secret-seal.v1"

_DOMAIN: Final[SealingDomain] = SealingDomain("webhooks.secret", _HKDF_INFO)


class WebhookSecretError(AppError):
    """500 — a sealed webhook secret opened under neither ``SECRET_KEY`` nor a fallback."""

    status_code = 500
    code = "webhook_secret_error"
    default_message = "The webhook signing secret could not be unsealed."


def is_sealed_secret(value: str) -> bool:
    """Whether *value* carries the sealed ``enc:v1:`` format."""
    return _DOMAIN.is_sealed(value)


def seal_secret(plaintext: str) -> str:
    """Seal a webhook signing secret for at-rest storage, under ``SECRET_KEY``."""
    return _DOMAIN.seal(plaintext)


def unseal_secret(stored: str) -> str:
    """The signing-time plaintext of *stored* — fail-closed on a bad seal.

    A sealed value that authenticates under neither ``SECRET_KEY`` nor any
    ``SECRET_KEY_DECRYPT_FALLBACKS`` entry raises :class:`WebhookSecretError` (the
    delivery records a terminal failure rather than signing with garbage). A plain
    (legacy, pre-sealing) value passes through unchanged.
    """
    if not is_sealed_secret(stored):
        return stored
    opened = _DOMAIN.open(stored)
    if opened is None:
        raise WebhookSecretError()
    return opened[0]


__all__ = ["WebhookSecretError", "is_sealed_secret", "seal_secret", "unseal_secret"]
