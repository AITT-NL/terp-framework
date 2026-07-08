"""Argon2 password hashing (recommended defaults)."""

from __future__ import annotations

from pwdlib import PasswordHash

_password_hash = PasswordHash.recommended()

# Lazily-built fixed hash that `verify_password_dummy` burns a verification
# against, so a refused login costs the same as a real password check.
_dummy_hash: str | None = None


def hash_password(password: str) -> str:
    """Hash *password* with Argon2 (per-password salt, recommended parameters)."""
    return _password_hash.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Return ``True`` iff *password* matches *password_hash*."""
    return _password_hash.verify(password, password_hash)


def verify_password_dummy() -> None:
    """Burn one Argon2 verification against a fixed dummy hash (timing equalization).

    An authenticate path that refuses *before* verifying — unknown email, inactive
    account, SSO-only user with no local credential — must call this so the refusal
    costs the same as a real password check. Without it, a login attempt against a
    valid email takes ~an Argon2 verify while an invalid one returns in microseconds:
    a remote timing side channel that enumerates registered accounts. The dummy hash
    is built lazily on first use (never at import) and the result is discarded.
    """
    global _dummy_hash
    if _dummy_hash is None:
        _dummy_hash = _password_hash.hash("terp-timing-equalization-dummy")
    _password_hash.verify("terp-timing-equalization-probe", _dummy_hash)


__all__ = ["hash_password", "verify_password", "verify_password_dummy"]
