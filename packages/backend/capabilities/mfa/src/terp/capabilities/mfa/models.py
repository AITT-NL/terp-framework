"""The two tables a second factor needs: one enrolment per subject, and its recovery codes.

``MfaEnrolment`` is keyed by ``user_id`` and **unique** on it. One subject has one second
factor: a second row would mean two secrets both valid, which is a factor that cannot be
revoked by replacing it.

``confirmed_at`` is what separates a *started* enrolment from a *live* one, and it is the
reason enrolment is two steps rather than one. A secret issued but never proved is not a
second factor — the person may have mistyped it into their authenticator, or scanned
nothing at all — and treating it as live would lock them out of their own account at the
next login. So the row exists from the moment the secret is issued (it has to: the server
must remember what it offered), and it gates nothing until a code generated from it comes
back.

``MfaRecoveryCode`` holds one row per issued code, storing a digest and never the code.
``used_at`` stamps consumption rather than deleting the row: a spent recovery code is
something an operator wants to see in the trail, and a deleted row answers no questions.
The reference to the enrolment declares ``CASCADE`` because a recovery code is a *part*
of its enrolment — disabling the factor destroys the codes with it, which is the one
behaviour that leaves nothing usable behind.
"""

from __future__ import annotations

import datetime
import uuid
from typing import Final

from sqlalchemy import DateTime
from sqlmodel import Field

from terp.core import BaseTable, OnDelete, Ref

from terp.capabilities.mfa.recovery import CODE_HASH_LENGTH

#: Caps every caller-independent string column. The secret is sealed before it is
#: stored, and Fernet output is comfortably inside this.
SECRET_MAX: Final[int] = 512


class MfaEnrolment(BaseTable, table=True):
    """One subject's second factor: the sealed shared secret and whether it is live.

    ``id`` / ``created_at`` / ``updated_at`` / ``version`` are inherited from
    ``BaseTable``. ``secret`` is **never** serialised out of the API boundary — no read
    DTO carries it, and the enrolment response returns the plaintext exactly once, at
    the moment it is generated, because an authenticator app has to be given it.
    """

    __tablename__ = "mfa_enrolment"

    user_id: uuid.UUID = Field(index=True, unique=True)
    secret: str = Field(max_length=SECRET_MAX)
    #: ``None`` until a code generated from the secret comes back. A started enrolment
    #: gates nothing; see the module docstring for why that is not an oversight.
    confirmed_at: datetime.datetime | None = Field(  # type: ignore[call-overload]
        default=None,
        sa_type=DateTime(timezone=True),
        nullable=True,
        index=True,
    )


class MfaRecoveryCode(BaseTable, table=True):
    """One single-use recovery code, stored as a digest and stamped when spent."""

    __tablename__ = "mfa_recovery_code"

    enrolment_id: uuid.UUID = Ref("mfa_enrolment.id", on_delete=OnDelete.CASCADE, index=True)
    code_hash: str = Field(max_length=CODE_HASH_LENGTH, index=True)
    used_at: datetime.datetime | None = Field(  # type: ignore[call-overload]
        default=None,
        sa_type=DateTime(timezone=True),
        nullable=True,
    )


__all__ = ["SECRET_MAX", "MfaEnrolment", "MfaRecoveryCode"]
