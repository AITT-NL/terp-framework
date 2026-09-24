"""RFC 6238 time-based one-time passwords, on the standard library.

No dependency for this. TOTP is HMAC-SHA1 over a counter derived from the clock
(RFC 4226 truncation, RFC 6238 time step) — about twenty lines against ``hmac`` and
``hashlib``, and the specification ships **test vectors**, so correctness here is
checkable rather than asserted. Those vectors are in the suite; a change that broke the
algorithm could not stay green.

The alternative was a dependency for twenty lines of well-specified arithmetic, which is
a supply-chain edge every consumer inherits. Where that trade would go the other way is
anything requiring primitive design — and this requires none: the primitive is
``hmac.new``, which is the standard library's.

Two properties the arithmetic does not give you, and which a caller cannot add
afterwards:

* **Comparison is constant-time.** A code is a shared secret for thirty seconds and
  ``==`` on strings leaks its prefix through timing. :func:`verify` uses
  ``hmac.compare_digest`` on every candidate.
* **Drift is bounded and symmetric.** Phone clocks are wrong. A window of one step
  either side (±30 s by default) is the RFC's own suggestion; widening it multiplies the
  codes a guesser may hit, so it is a parameter with a small default rather than
  something a call site improvises.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
from typing import Final

#: The RFC 6238 default time step. Not configurable: an authenticator app assumes it,
#: and a deployment that changed it would produce codes no enrolled phone can generate.
TIME_STEP_SECONDS: Final[int] = 30

#: Digits in a generated code. Six is what every authenticator app shows.
DIGITS: Final[int] = 6

#: How many steps either side of the current one are accepted. One step (±30 s) covers
#: ordinary phone-clock drift and the time a person takes to type. Each extra step is
#: another code a guesser may hit, so this stays small and is stated rather than tuned.
DEFAULT_DRIFT_STEPS: Final[int] = 1

#: Bytes of entropy in a generated shared secret (160 bits, the RFC 4226 recommendation
#: for HMAC-SHA1).
_SECRET_BYTES: Final[int] = 20


def generate_secret() -> str:
    """A fresh base32 shared secret, in the form an authenticator app expects."""
    return base64.b32encode(secrets.token_bytes(_SECRET_BYTES)).decode("ascii").rstrip("=")


def _counter_code(secret: str, counter: int) -> str:
    """The RFC 4226 HOTP value for *counter* — the whole of the arithmetic."""
    # Base32 alphabets in the wild arrive unpadded and lower-cased; normalise both rather
    # than making every caller remember to.
    normalised = secret.strip().replace(" ", "").upper()
    padding = "=" * (-len(normalised) % 8)
    key = base64.b32decode(normalised + padding, casefold=True)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    # Dynamic truncation (RFC 4226 §5.3): the low nibble of the last byte picks the
    # offset, and the high bit of the selected word is masked off so the result is
    # positive on every platform's signed interpretation.
    offset = digest[-1] & 0x0F
    (truncated,) = struct.unpack(">I", digest[offset : offset + 4])
    return str((truncated & 0x7FFF_FFFF) % (10**DIGITS)).zfill(DIGITS)


def generate(secret: str, *, at: float | None = None) -> str:
    """The code *secret* produces now (or at *at*, a UNIX timestamp)."""
    moment = time.time() if at is None else at
    return _counter_code(secret, int(moment // TIME_STEP_SECONDS))


def verify_step(
    secret: str,
    code: str,
    *,
    at: float | None = None,
    drift_steps: int = DEFAULT_DRIFT_STEPS,
) -> int | None:
    """Which time step *code* satisfies for *secret*, or ``None`` if none does.

    The step is returned rather than a bare yes, because a caller cannot enforce
    single use without knowing which code was spent: a code is valid for its whole
    window, so "it verified" is true again thirty seconds later for the same six
    digits. RFC 6238 section 5.2 puts the duty on the verifier, and the verifier is the
    only party holding the state to discharge it.

    Every candidate is compared in constant time **and** every candidate is compared:
    returning early on the first match would leak, through timing, which step matched,
    and with it the direction and size of the caller's clock error. The match is
    recorded and the loop runs to the end.
    """
    candidate = code.strip().replace(" ", "")
    if len(candidate) != DIGITS or not candidate.isdigit():
        return None
    moment = time.time() if at is None else at
    step = int(moment // TIME_STEP_SECONDS)
    matched: int | None = None
    for offset in range(-drift_steps, drift_steps + 1):
        expected = _counter_code(secret, step + offset)
        hit = hmac.compare_digest(expected, candidate)
        matched = step + offset if hit else matched
    return matched


def verify(
    secret: str,
    code: str,
    *,
    at: float | None = None,
    drift_steps: int = DEFAULT_DRIFT_STEPS,
) -> bool:
    """Whether *code* is valid for *secret* now, within the drift window.

    Answers the question without the step, for callers that hold no state to spend it
    against. A caller that stores an enrolment wants :func:`verify_step`.
    """
    return verify_step(secret, code, at=at, drift_steps=drift_steps) is not None


def provisioning_uri(secret: str, *, account: str, issuer: str) -> str:
    """The ``otpauth://`` URI an authenticator app scans as a QR code.

    Built here rather than by a caller because the parameter names are part of the
    de-facto standard every app implements, and a typo in one produces an enrolment that
    scans cleanly and then never matches.
    """
    from urllib.parse import quote, urlencode

    label = quote(f"{issuer}:{account}", safe="")
    query = urlencode(
        {
            "secret": secret,
            "issuer": issuer,
            "algorithm": "SHA1",
            "digits": DIGITS,
            "period": TIME_STEP_SECONDS,
        }
    )
    return f"otpauth://totp/{label}?{query}"


__all__ = [
    "DEFAULT_DRIFT_STEPS",
    "DIGITS",
    "TIME_STEP_SECONDS",
    "generate",
    "generate_secret",
    "provisioning_uri",
    "verify",
    "verify_step",
]
