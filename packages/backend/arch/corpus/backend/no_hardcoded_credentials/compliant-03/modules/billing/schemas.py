"""Compliant: enum vocabulary whose literal is the member's own name.

A member like ``SECRET_REFERENCE = "secret_reference"`` names a parameter kind —
the string carries no secret material, it *is* the identifier's wire spelling.
Flagging it would push authors to spell the same vocabulary as ``auto()`` purely
to dodge the rule, hiding the wire value from readers of the schema.
"""

from enum import StrEnum


class ParameterType(StrEnum):
    TEXT = "text"
    NUMBER = "number"
    SECRET_REFERENCE = "secret_reference"


class TokenKind(StrEnum):
    ACCESS_TOKEN = "access_token"
    REFRESH_TOKEN = "refresh_token"
