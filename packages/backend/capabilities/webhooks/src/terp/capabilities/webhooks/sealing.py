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

Legacy tolerance: a row written before this control holds the plaintext secret;
:func:`unseal_secret` passes an unsealed value through unchanged so an existing
subscription keeps delivering, and the next secret rotation seals it.
"""

from __future__ import annotations

import base64
from typing import Final

from terp.core import AppError, get_settings

#: The portable sealed format (shared shape with ``terp.core.secrets``, distinct key).
_SEAL_PREFIX: Final[str] = "enc:v1:"

# Domain separation: the webhook-seal key is derived from SECRET_KEY with this
# label, never SECRET_KEY itself and never the config-seal derivation.
_HKDF_INFO: Final[bytes] = b"terp.capabilities.webhooks.secret-seal.v1"


class WebhookSecretError(AppError):
    """500 — a sealed webhook secret did not authenticate under the current ``SECRET_KEY``."""

    status_code = 500
    code = "webhook_secret_error"
    default_message = "The webhook signing secret could not be unsealed."


def _cipher():  # the return type lives in the `cryptography` dependency
    """The sealing cipher, keyed from the live ``SECRET_KEY`` via HKDF."""
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF

    derived = HKDF(
        algorithm=hashes.SHA256(), length=32, salt=None, info=_HKDF_INFO
    ).derive(get_settings().SECRET_KEY.encode("utf-8"))
    return Fernet(base64.urlsafe_b64encode(derived))


def is_sealed_secret(value: str) -> bool:
    """Whether *value* carries the sealed ``enc:v1:`` format."""
    return value.startswith(_SEAL_PREFIX)


def seal_secret(plaintext: str) -> str:
    """Seal a webhook signing secret for at-rest storage."""
    token = _cipher().encrypt(plaintext.encode("utf-8"))
    return _SEAL_PREFIX + token.decode("ascii")


def unseal_secret(stored: str) -> str:
    """The signing-time plaintext of *stored* — fail-closed on a bad seal.

    A sealed value that does not authenticate under the current ``SECRET_KEY``
    raises :class:`WebhookSecretError` (the delivery records a terminal failure
    rather than signing with garbage). A plain (legacy, pre-sealing) value
    passes through unchanged.
    """
    if not is_sealed_secret(stored):
        return stored
    from cryptography.fernet import InvalidToken

    try:
        return _cipher().decrypt(stored.removeprefix(_SEAL_PREFIX).encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise WebhookSecretError() from exc


__all__ = ["WebhookSecretError", "is_sealed_secret", "seal_secret", "unseal_secret"]
