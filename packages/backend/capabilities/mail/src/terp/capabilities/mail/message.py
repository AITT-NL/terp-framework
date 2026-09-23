"""What one message may carry, validated before it is queued rather than when it is sent.

A mail message is built from data — a customer's address, a work order's title — and the
two classic ways that goes wrong are both about headers. A line break in a subject or an
address ends the header and starts a new one, so ``"Hello\\r\\nBcc: everyone@..."`` turns
a notification into a bulk mail the application never sent on purpose; and an address
field that accepts ``"a@example.com, b@example.com"`` sends to two people where the code
meant one. Both are refused here, at the moment a feature *asks* to send, so the refusal
reaches the code that made the mistake instead of a worker log an hour later.

The message is plain text. That is a decision, not an omission: an HTML body assembled
from data is a second injection surface — a link or a form placed in a trusted sender's
mail — and it needs an auto-escaping renderer before it is safe to offer, which this
capability does not yet have. Everything a notification, a confirmation or a password
reset needs fits in text.
"""

from __future__ import annotations

from datetime import datetime
from email.headerregistry import Address
from email.message import EmailMessage
from email.policy import SMTP
from email.utils import format_datetime
from typing import Final

from pydantic import field_validator
from sqlmodel import Field

from terp.core import BaseSchema

from terp.capabilities.mail.settings import parse_address

#: At most this many recipients per message. A message to many visible recipients hands
#: every one of them everybody else's address, and it is the shape relays score as bulk
#: mail. Sending the same notice to many people is one message per person — one
#: ``send_mail`` each, which also means one refusal does not sink the rest.
MAX_RECIPIENTS: Final[int] = 50

#: The subject bound. Long enough for any subject a person reads; short enough that a
#: feature pasting a whole record into it is refused where it happens.
MAX_SUBJECT_LENGTH: Final[int] = 250

#: The body bound, in characters. The message travels as a job payload — a row in the
#: durable outbox — so it is bounded like any other stored input.
MAX_TEXT_LENGTH: Final[int] = 100_000


def _has_control_characters(value: str) -> bool:
    return any(ord(ch) < 32 or ord(ch) == 127 for ch in value)


class MailMessage(BaseSchema):
    """One message: who it is for, what it says, and where a reply should go.

    There is no ``sender`` field: every message is from the address the application
    declared in :class:`~terp.capabilities.mail.MailSettings`. ``reply_to`` is where a
    person's answer lands — the case a per-message sender is usually wanted for, without
    letting a feature send mail that claims to come from someone else.
    """

    to: list[str] = Field(min_length=1, max_length=MAX_RECIPIENTS)
    subject: str = Field(min_length=1, max_length=MAX_SUBJECT_LENGTH)
    text: str = Field(min_length=1, max_length=MAX_TEXT_LENGTH)
    reply_to: str | None = Field(default=None, max_length=254)

    @field_validator("to")
    @classmethod
    def _every_recipient_is_one_address(cls, value: list[str]) -> list[str]:
        for address in value:
            parse_address(address)
        return value

    @field_validator("reply_to")
    @classmethod
    def _reply_to_is_one_address(cls, value: str | None) -> str | None:
        if value is not None:
            parse_address(value)
        return value

    @field_validator("subject")
    @classmethod
    def _subject_is_one_line(cls, value: str) -> str:
        if _has_control_characters(value):
            raise ValueError(
                "the subject is one line of text: a line break or other control "
                "character in a header starts a header of its own"
            )
        return value

    @field_validator("text")
    @classmethod
    def _text_holds_no_nul(cls, value: str) -> str:
        # The message is stored as a job payload before it is sent, and PostgreSQL's
        # JSON types cannot hold a NUL character: accepting one here would turn a
        # validated send into a database error inside the business write.
        if "\x00" in value:
            raise ValueError("the text contains a NUL character")
        return value


def build_email(
    message: MailMessage,
    *,
    sender: Address,
    message_id: str,
    sent_at: datetime,
) -> EmailMessage:
    """Render *message* as an RFC 5322 message from the declared sender.

    ``Auto-Submitted: auto-generated`` (RFC 3834) is always set: this is mail a program
    sent, and saying so is what stops an out-of-office reply from starting a loop with
    it. The ``Message-ID`` is minted when the send was requested and stays the same on
    every retry, so a message delivered twice after a lost connection is recognisably one
    message. The body is quoted-printable UTF-8, readable in its raw form.
    """
    email = EmailMessage(policy=SMTP)
    email["From"] = sender
    email["To"] = [parse_address(address) for address in message.to]
    if message.reply_to is not None:
        email["Reply-To"] = parse_address(message.reply_to)
    email["Subject"] = message.subject
    email["Date"] = format_datetime(sent_at)
    email["Message-ID"] = message_id
    email["Auto-Submitted"] = "auto-generated"
    email.set_content(message.text, cte="quoted-printable")
    return email


__all__ = [
    "MAX_RECIPIENTS",
    "MAX_SUBJECT_LENGTH",
    "MAX_TEXT_LENGTH",
    "MailMessage",
    "build_email",
]
