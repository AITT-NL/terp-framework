from dataclasses import dataclass


@dataclass(frozen=True)
class Invitation:
    email: str


class Mailbox:
    email: str = ""


def invite(email: str, phone: str | None = None) -> Invitation:
    return Invitation(email=email)
