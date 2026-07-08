"""Secrets sealed by default — ``encrypt_config`` / ``mask_config`` / ``decrypt_config``.

The design's §5.4 control: a sealed configuration value stays opaque everywhere.
:func:`mask_config` is the only representation a module may render (a constant
mask that leaks neither the value nor its length); :func:`encrypt_config` seals a
plaintext into the portable ``enc:v1:`` format; and :func:`decrypt_config` — the
**single decrypt chokepoint** — refuses to run anywhere except the one call site
the composition root registered via :func:`register_decrypt_call_site`.

Two-layer enforcement (ADR 0006): the runtime half is the fail-closed call-site
allowlist inside :func:`decrypt_config` (no registered site ⇒ every decrypt
fails; a caller other than the registered site ⇒ :class:`SecretsError`); the
build-time half is the ``no_adhoc_config_decrypt`` arch rule, which forbids a
``decrypt_config(...)`` call in app code so the one sanctioned site is a
budgeted, greppable ``# arch-allow-*`` opt-out. The kernel gate proves the
runtime half in ``test_decrypt_single_call_site``.

Layering: the sealing cipher (Fernet — AES128-CBC + HMAC-SHA256, keyed from
``SECRET_KEY`` through an HKDF with a Terp-specific ``info`` label so the seal
key is domain-separated from every other ``SECRET_KEY`` use) comes from the
``cryptography`` package, an **optional extra** (``terp-core[secrets]``)
imported lazily so the kernel's default dependency set stays minimal; an app
that never seals config never loads it.
"""

from __future__ import annotations

import base64
import sys
from collections.abc import Callable
from typing import Final

from terp.core.config import get_settings
from terp.core.errors import AppError

#: The rendering of every masked configuration value. A constant (never a prefix
#: or suffix of the real value, never its length) so a masked surface leaks nothing.
MASKED_VALUE: Final[str] = "****"

#: The portable sealed format: ``enc:v1:<fernet-token>``. Versioned so a future
#: cipher rotation can coexist with already-sealed values.
_SEAL_PREFIX: Final[str] = "enc:v1:"

# Domain separation for the seal key: SECRET_KEY is used elsewhere (e.g. JWT
# signing), so the config-seal key is derived, never SECRET_KEY itself.
_HKDF_INFO: Final[bytes] = b"terp.core.secrets.config-seal.v1"


class SecretsError(AppError):
    """500 — a sealed-config operation failed or was attempted from a forbidden surface."""

    status_code = 500
    code = "secrets_error"
    default_message = "Sealed configuration could not be processed."


def _load_fernet():  # the return types live in the optional extra, so no annotation
    """Import the optional cipher (``terp-core[secrets]``); fail closed if absent."""
    try:
        from cryptography.fernet import Fernet, InvalidToken
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    except ImportError as exc:
        raise SecretsError(
            "Config sealing requires the 'cryptography' package — "
            "install the terp-core[secrets] extra."
        ) from exc
    return Fernet, InvalidToken, hashes, HKDF


def _cipher():  # the return type lives in the optional extra, so no annotation
    """The sealing cipher, keyed from the live ``SECRET_KEY`` via HKDF."""
    fernet_cls, _invalid_token, hashes, hkdf_cls = _load_fernet()
    derived = hkdf_cls(
        algorithm=hashes.SHA256(), length=32, salt=None, info=_HKDF_INFO
    ).derive(get_settings().SECRET_KEY.encode("utf-8"))
    return fernet_cls(base64.urlsafe_b64encode(derived))


def is_sealed_config(value: str) -> bool:
    """Whether *value* carries the sealed ``enc:v1:`` format."""
    return value.startswith(_SEAL_PREFIX)


def mask_config(value: str) -> str:  # masking deliberately never reads the value
    """The masked rendering of a configuration value (the only module-facing view).

    Always the constant :data:`MASKED_VALUE` — a mask that varied with the value
    (a prefix, a suffix, its length) would be an oracle, so it never does.
    """
    return MASKED_VALUE


def encrypt_config(plaintext: str) -> str:
    """Seal *plaintext* into the portable ``enc:v1:`` format.

    Safe to call anywhere (sealing leaks nothing); the counterpart
    :func:`decrypt_config` is the guarded chokepoint.
    """
    token = _cipher().encrypt(plaintext.encode("utf-8"))
    return _SEAL_PREFIX + token.decode("ascii")


# The single allowlisted decrypt call site (design §5.4). Empty ⇒ every decrypt
# fails closed; the composition root registers exactly one callable per process.
_decrypt_call_site: Callable[..., object] | None = None


def register_decrypt_call_site(func: Callable[..., object]) -> Callable[..., object]:
    """Register *func* as the **only** callable allowed to run ``decrypt_config``.

    Usable as a decorator. Exactly one call site exists per process: registering
    a second, different callable raises :class:`SecretsError` (re-registering the
    same callable is idempotent), so the decrypt surface can never silently grow.
    """
    global _decrypt_call_site
    if _decrypt_call_site is not None and _decrypt_call_site is not func:
        raise SecretsError(
            "A decrypt call site is already registered; exactly one is allowed "
            "per process (design §5.4)."
        )
    _decrypt_call_site = func
    return func


def reset_decrypt_call_site_runtime() -> None:
    """Clear the registered call site (the composition-root/test baseline)."""
    global _decrypt_call_site
    _decrypt_call_site = None


def decrypt_config(sealed: str) -> str:
    """Unseal *sealed* — permitted **only** from the registered call site.

    Fail-closed on every path: no registered call site, a caller other than the
    registered one, a value that is not in the sealed format, or a token that
    does not authenticate under the current ``SECRET_KEY`` all raise
    :class:`SecretsError`. Every other surface renders :func:`mask_config`.
    """
    site = _decrypt_call_site
    if site is None:
        raise SecretsError(
            "decrypt_config has no registered call site; register exactly one "
            "with register_decrypt_call_site (design §5.4)."
        )
    caller = sys._getframe(1).f_code
    if caller is not site.__code__:
        raise SecretsError(
            "decrypt_config was called outside the registered call site; sealed "
            "values are masked everywhere else (design §5.4)."
        )
    if not is_sealed_config(sealed):
        raise SecretsError("The value is not in the sealed 'enc:v1:' format.")
    _fernet, invalid_token, _hashes, _hkdf = _load_fernet()
    try:
        plaintext = _cipher().decrypt(sealed.removeprefix(_SEAL_PREFIX).encode("ascii"))
    except invalid_token as exc:
        raise SecretsError(
            "The sealed value did not authenticate under the current SECRET_KEY."
        ) from exc
    return plaintext.decode("utf-8")


__all__ = [
    "MASKED_VALUE",
    "SecretsError",
    "decrypt_config",
    "encrypt_config",
    "is_sealed_config",
    "mask_config",
    "register_decrypt_call_site",
    "reset_decrypt_call_site_runtime",
]
