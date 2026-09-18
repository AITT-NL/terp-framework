"""Recovery codes: the way back in when the phone is gone.

A second factor that cannot be recovered is a way to lose an account, and the support
process that grows around that gap — "ring us and we will turn it off" — is a social-
engineering surface far weaker than the factor it rescues. So enrolment issues a fixed
set of single-use codes, shown once.

Three properties, each of which is the whole point of that property:

* **Shown once, stored hashed.** The row holds ``sha256`` of the code, never the code.
  A plain hash is right here and a slow KDF would be wrong: these are 80-bit random
  strings this module generated, not human-chosen passwords, so there is no dictionary
  to mount and nothing for a work factor to buy. (The enrolment *secret* is sealed
  rather than hashed for the opposite reason — verification needs to reproduce it.)
* **Single use.** A code that still worked after being used is a password with extra
  steps. Consumption stamps the row, and the stamped row stays for the trail.
* **Constant-time comparison**, over every stored code. Hashes make timing much less
  interesting than it is for the TOTP code, but the loop costs nothing and the habit is
  the thing that survives a later change to the format.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from typing import Final

#: How many codes an enrolment issues. Ten is the common default: enough that losing a
#: printout is survivable, few enough that a person keeps them somewhere deliberate.
CODE_COUNT: Final[int] = 10

#: Bytes of entropy per code (80 bits), rendered as base32 without padding.
_CODE_BYTES: Final[int] = 10

#: The stored digest's width, mirrored by the column cap.
CODE_HASH_LENGTH: Final[int] = 64


def generate_codes(count: int = CODE_COUNT) -> list[str]:
    """*count* fresh recovery codes, in the form the person is shown once.

    Grouped with a hyphen because these get written down and read back by hand, and an
    unbroken sixteen-character string is where transcription errors come from.
    """
    codes: list[str] = []
    for _ in range(count):
        raw = base32(secrets.token_bytes(_CODE_BYTES))
        codes.append(f"{raw[:4]}-{raw[4:8]}-{raw[8:12]}-{raw[12:16]}")
    return codes


def base32(value: bytes) -> str:
    """Unpadded, upper-case base32 — the alphabet people can read back reliably."""
    import base64

    return base64.b32encode(value).decode("ascii").rstrip("=")


def normalise(code: str) -> str:
    """The comparable form of a typed code: no spaces or hyphens, upper-case.

    People retype these from paper, so the separators and the case are presentation
    rather than content. Normalising at the boundary keeps that judgement in one place
    instead of at every comparison.
    """
    return code.strip().replace("-", "").replace(" ", "").upper()


def hash_code(code: str) -> str:
    """The stored digest of *code*."""
    return hashlib.sha256(normalise(code).encode("utf-8")).hexdigest()


def matches(code: str, stored_hash: str) -> bool:
    """Whether *code* hashes to *stored_hash*, compared in constant time."""
    return hmac.compare_digest(hash_code(code), stored_hash)


__all__ = [
    "CODE_COUNT",
    "CODE_HASH_LENGTH",
    "base32",
    "generate_codes",
    "hash_code",
    "matches",
    "normalise",
]
