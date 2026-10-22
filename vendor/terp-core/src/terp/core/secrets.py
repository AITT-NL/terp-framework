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

**Sealing domains and key rotation (ADR 0189).** Every value Terp seals at rest
belongs to one :class:`SealingDomain`: sealed config here, a webhook signing
secret and an MFA enrolment in their capabilities. A domain seals under
``SECRET_KEY`` alone and opens under it and then each
``SECRET_KEY_DECRYPT_FALLBACKS`` entry, so a value sealed before a rotation still
opens after it while nothing new is ever sealed with a retired key. Each domain
registers itself as it is built, which is how ``terp secrets reseal`` finds every
one of them: :func:`check_sealed_value` says which domain a stored value belongs
to and whether it still needs a fallback, and hands back its re-sealing under
``SECRET_KEY`` — never the plaintext.
"""

from __future__ import annotations

import base64
import enum
import hashlib
import hmac
import sys
from collections.abc import Callable
from dataclasses import dataclass
from typing import Final

from terp.core.config import get_settings
from terp.core.errors import AppError
from terp.core.runtime import register_runtime_seam

#: The rendering of every masked configuration value. A constant (never a prefix
#: or suffix of the real value, never its length) so a masked surface leaks nothing.
MASKED_VALUE: Final[str] = "****"

#: The portable sealed format: ``enc:v1:<fernet-token>``. Versioned so a future
#: cipher rotation can coexist with already-sealed values. Every domain shares it;
#: the key, not the prefix, is what tells one domain's value from another's.
_SEAL_PREFIX: Final[str] = "enc:v1:"

# Domain separation for the seal key: SECRET_KEY is used elsewhere (e.g. JWT
# signing), so the config-seal key is derived, never SECRET_KEY itself.
_HKDF_INFO: Final[bytes] = b"terp.core.secrets.config-seal.v1"


class SecretsError(AppError):
    """500 — a sealed-config operation failed or was attempted from a forbidden surface."""

    status_code = 500
    code = "secrets_error"
    default_message = "Sealed configuration could not be processed."


def derive_key(secret: str, info: bytes) -> bytes:
    """The 32-byte key for one use of *secret*: HKDF-SHA256 (RFC 5869) under *info*.

    Every use of ``SECRET_KEY`` takes its own key this way, under a fixed ``info``
    label that names the use and its version, so a value made for one use fails
    every other and none of them is ``SECRET_KEY`` itself. A new derivation for a
    use is a new label, and the old label becomes a key that only opens or
    verifies — a rotation, handled by the same fallback paths as a changed key.

    No salt: RFC 5869 makes it optional, the input is already a high-entropy secret,
    and a salt published in this source would add nothing the label does not.
    Standard library only, so a use that never seals (signing) needs no extra; it is
    byte-for-byte what ``cryptography``'s ``HKDF(SHA256, length=32, salt=None,
    info=...)`` returns, which is how the sealing domains derived their keys before
    this function existed — so everything they sealed then still opens.
    """
    pseudorandom_key = hmac.new(bytes(32), secret.encode("utf-8"), hashlib.sha256).digest()
    return hmac.new(pseudorandom_key, info + b"\x01", hashlib.sha256).digest()


def _load_fernet():  # the return types live in the optional extra, so no annotation
    """Import the optional cipher (``terp-core[secrets]``); fail closed if absent."""
    try:
        from cryptography.fernet import Fernet, InvalidToken
    except ImportError as exc:
        raise SecretsError(
            "Config sealing requires the 'cryptography' package — "
            "install the terp-core[secrets] extra."
        ) from exc
    return Fernet, InvalidToken


class SealState(enum.StrEnum):
    """Which key a stored value opens under — what a re-seal needs to know about it."""

    #: Opens under ``SECRET_KEY``: nothing to do.
    CURRENT = "current"
    #: Opens only under a ``SECRET_KEY_DECRYPT_FALLBACKS`` entry: re-seal it.
    FALLBACK = "fallback"
    #: No registered domain opens it under any configured key.
    UNREADABLE = "unreadable"


@dataclass(frozen=True)
class SealCheck:
    """One stored value, judged without exposing what it holds.

    *domain* names the :class:`SealingDomain` whose key opened it (``None`` when
    none did). *resealed* is set only for :attr:`SealState.FALLBACK`: the same
    plaintext sealed under ``SECRET_KEY``, ready to be written in its place.
    """

    state: SealState
    domain: str | None = None
    resealed: str | None = None


# Every sealing domain built in this process, by name. Static, like the arch rules:
# a domain is a capability's declaration made once at import, so this is not a
# per-app runtime seam and is never reset between apps.
_DOMAINS: dict[str, SealingDomain] = {}


class SealingDomain:
    """One kind of value sealed at rest, with its own key derived from ``SECRET_KEY``.

    A capability that seals a value builds one at import, under a ``name`` and an
    ``info`` label nobody else uses; app code seals with :func:`encrypt_config`
    instead. The domain owns the rotation rule so that no sealer can get it wrong on
    its own: :meth:`seal` uses ``SECRET_KEY`` alone, :meth:`open` tries
    ``SECRET_KEY`` and then each ``SECRET_KEY_DECRYPT_FALLBACKS`` entry, and
    ``SECRET_KEY_FALLBACKS`` — which only verifies signatures — never opens anything.

    Building a domain registers it, so ``terp secrets reseal`` re-seals its values
    without anyone remembering to add it. A second domain with a name or a label
    already taken is refused: one label, one domain, or a value would open in two.
    """

    def __init__(self, name: str, info: bytes) -> None:
        for other in _DOMAINS.values():
            if other.name == name or other.info == info:
                raise SecretsError(
                    f"A sealing domain named {other.name!r} already uses this name or "
                    "label; every domain needs its own, or one domain's values would "
                    "open in another's."
                )
        self.name = name
        self.info = info
        _DOMAINS[name] = self

    def is_sealed(self, value: str) -> bool:
        """Whether *value* carries the sealed ``enc:v1:`` format (any domain's)."""
        return value.startswith(_SEAL_PREFIX)

    def _cipher(self, secret: str):  # the return type lives in the optional extra
        fernet_cls, _invalid_token = _load_fernet()
        return fernet_cls(base64.urlsafe_b64encode(derive_key(secret, self.info)))

    def seal(self, plaintext: str) -> str:
        """Seal *plaintext* under ``SECRET_KEY`` — the only key anything is sealed with."""
        token = self._cipher(get_settings().SECRET_KEY).encrypt(plaintext.encode("utf-8"))
        return _SEAL_PREFIX + token.decode("ascii")

    def open(self, stored: str) -> tuple[str, bool] | None:
        """``(plaintext, needed_a_fallback)`` for *stored*, or ``None`` if no key opens it.

        ``None`` covers a value without the sealed prefix, one sealed by another domain,
        one sealed under a key no longer configured, and a damaged one alike: the caller
        raises its own typed error, and none of them is plaintext to be trusted.
        """
        if not self.is_sealed(stored):
            return None
        _fernet_cls, invalid_token = _load_fernet()
        try:
            token = stored.removeprefix(_SEAL_PREFIX).encode("ascii")
        except UnicodeEncodeError:
            return None  # a Fernet token is ASCII; anything else was never one
        settings = get_settings()
        keys = [(settings.SECRET_KEY, False)] + [
            (fallback, True) for fallback in settings.SECRET_KEY_DECRYPT_FALLBACKS
        ]
        for secret, is_fallback in keys:
            try:
                return self._cipher(secret).decrypt(token).decode("utf-8"), is_fallback
            except invalid_token:
                continue
        return None

    def check(self, stored: str) -> SealCheck:
        """Judge *stored* for a re-seal: :class:`SealCheck`, never the plaintext."""
        opened = self.open(stored)
        if opened is None:
            return SealCheck(SealState.UNREADABLE)
        plaintext, is_fallback = opened
        if not is_fallback:
            return SealCheck(SealState.CURRENT, domain=self.name)
        return SealCheck(SealState.FALLBACK, domain=self.name, resealed=self.seal(plaintext))


def sealing_domains() -> tuple[str, ...]:
    """The names of every sealing domain built in this process, in build order.

    Names, not the domains: a domain can open what it sealed, and handing out the
    config domain would be a way round :func:`decrypt_config`'s one call site.
    """
    return tuple(_DOMAINS)


def check_sealed_value(stored: str) -> SealCheck:
    """Which domain *stored* belongs to, and whether it still needs a fallback key.

    Every domain shares the ``enc:v1:`` prefix, so the domain is found by trying each
    one's keys; Fernet authenticates, so only the domain that sealed a value can open
    it. A value no domain opens is :attr:`SealState.UNREADABLE` — sealed under a key
    that is no longer configured, damaged, or not a sealed value at all.
    """
    for domain in _DOMAINS.values():
        check = domain.check(stored)
        if check.state is not SealState.UNREADABLE:
            return check
    return SealCheck(SealState.UNREADABLE)


_CONFIG: Final[SealingDomain] = SealingDomain("config", _HKDF_INFO)


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
    """Seal *plaintext* into the portable ``enc:v1:`` format, under ``SECRET_KEY``.

    Safe to call anywhere (sealing leaks nothing); the counterpart
    :func:`decrypt_config` is the guarded chokepoint.
    """
    return _CONFIG.seal(plaintext)


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


def _capture_decrypt_call_site_runtime() -> Callable[..., object] | None:
    """Snapshot the registered call site (the runtime-seam capture hook)."""
    return _decrypt_call_site


def _restore_decrypt_call_site_runtime(state: Callable[..., object] | None) -> None:
    """Put back a :func:`_capture_decrypt_call_site_runtime` snapshot (restore hook)."""
    global _decrypt_call_site
    _decrypt_call_site = state


# Registered as a per-app runtime seam so a test that registers a call site cannot
# leak it: the next test registering a *different* callable would otherwise hit the
# one-call-site-per-process guard and fail for a reason that has nothing to do with it.
register_runtime_seam(
    "decrypt_call_site",
    capture=_capture_decrypt_call_site_runtime,
    restore=_restore_decrypt_call_site_runtime,
    reset=reset_decrypt_call_site_runtime,
)


def decrypt_config(sealed: str) -> str:
    """Unseal *sealed* — permitted **only** from the registered call site.

    Fail-closed on every path: no registered call site, a caller other than the
    registered one, a value that is not in the sealed format, or a token that
    authenticates under neither ``SECRET_KEY`` nor any
    ``SECRET_KEY_DECRYPT_FALLBACKS`` entry all raise :class:`SecretsError`. Every
    other surface renders :func:`mask_config`.
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
    opened = _CONFIG.open(sealed)
    if opened is None:
        raise SecretsError(
            "The sealed value did not authenticate under SECRET_KEY or any "
            "SECRET_KEY_DECRYPT_FALLBACKS entry."
        )
    return opened[0]


__all__ = [
    "MASKED_VALUE",
    "SealCheck",
    "SealState",
    "SealingDomain",
    "SecretsError",
    "check_sealed_value",
    "decrypt_config",
    "derive_key",
    "encrypt_config",
    "is_sealed_config",
    "mask_config",
    "register_decrypt_call_site",
    "reset_decrypt_call_site_runtime",
    "sealing_domains",
]
