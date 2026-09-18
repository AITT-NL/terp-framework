"""The seam a second factor plugs into, and the refusal that asks for one.

The auth capability owns the login protocol and deliberately owns no factor. This
protocol is a two-method port — *is this subject enrolled?* and *does this code
satisfy them?* — which ``terp-cap-mfa`` implements and any other implementation
could. Keeping it here rather than importing the MFA capability is what lets the
login route consult a factor without auth depending on one.

**Why the code rides on the login body instead of a challenge token.**

The familiar shape is two round trips: the password returns a short-lived challenge
credential, and the second request exchanges it plus the code for a session. That was
considered and not taken, because the challenge is a *second bearer token* — one more
credential to mint, verify, expire, revoke and leak, whose only job is to remember a
password check that happened four seconds ago.

Re-posting the password costs the client nothing it has not already done (it held the
password to send it once, over the same TLS connection) and costs the platform a whole
credential type it would otherwise have to defend. So ``POST /login`` answers
:class:`MfaRequiredError`, the client prompts, and posts the pair again with the code.

The cost is stated rather than hidden: an attacker **holding a valid password** learns
from that refusal that the account has a second factor. They learn nothing they could
not learn by trying, and they already hold the password — but it is a distinguishable
response, and a deployment that considers that unacceptable wants the challenge shape.
"""

from __future__ import annotations

import uuid
from typing import Protocol

from sqlmodel import Session

from terp.core import AppError


class MfaRequiredError(AppError):
    """401 — the password was right and this account needs its second factor too.

    Distinguishable from a wrong password **on purpose**: a client that cannot tell the
    two apart has no way to prompt for a code, and would have to guess from a bare 401
    whether to show "wrong password" or "enter your code". Showing the wrong one of
    those is how people conclude the feature is broken and ask for it to be turned off.
    """

    status_code = 401
    code = "mfa_required"
    default_message = "This account requires a second factor. Enter the code and try again."


class SecondFactor(Protocol):
    """What the login route needs from a second-factor implementation.

    Two methods, and the split matters: *enrolled* decides whether a code is demanded at
    all, and must be false for a subject who started an enrolment and never proved it —
    otherwise a mis-scanned QR code becomes a lockout. *verify* answers only for a
    subject the first method said yes about.
    """

    def is_enrolled(self, session: Session, user_id: uuid.UUID) -> bool:
        """Whether a **confirmed** second factor stands between this subject and a session."""
        ...

    def verify(self, session: Session, user_id: uuid.UUID, code: str) -> bool:
        """Whether *code* satisfies this subject's second factor."""
        ...


__all__ = ["MfaRequiredError", "SecondFactor"]
