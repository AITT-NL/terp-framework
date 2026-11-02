"""One encoder for the profile's grammar: every scalar typed as fixed text, a value or an id.

A command element, a health path and a mount path are values: always double-quoted, every
``$`` doubled so compose never interpolates them, ASCII-only with ``\\u``/``\\U`` escapes. A
scalar built from ids, the project name and fixed text stands plain only where YAML 1.1 and
the 1.2 core schema both read it as that string (ADR 0187 decision 2).
"""

from __future__ import annotations

import re

#: What may stand in a plain scalar the generator writes: an id's characters and the fixed
#: text it is joined with. No space, no '#', no flow indicator, no leading '-' or digit-free
#: indicator, so the only question left is how YAML resolves the finished scalar.
_PLAIN = re.compile(r"[A-Za-z0-9_./][A-Za-z0-9_./:-]*")

#: Scalars YAML 1.1 (the type repository PyYAML and older compose readers apply) or the 1.2
#: core schema (the one current compose reads with) resolves to something other than a
#: string. Matched against the whole scalar; a scalar that matches is quoted.
_NOT_A_STRING = re.compile(
    r"""
    (?: y|Y|yes|Yes|YES|n|N|no|No|NO|true|True|TRUE|false|False|FALSE|on|On|ON|off|Off|OFF
      | ~|null|Null|NULL
      | [-+]?0b[0-1_]+ | [-+]?0o?[0-7_]+ | [-+]?0x[0-9a-fA-F_]+ | [-+]?[0-9][0-9_]*
      | [-+]?[0-9][0-9_]*(?::[0-5]?[0-9])+(?:\.[0-9_]*)?
      | [-+]?(?:\.[0-9][0-9_]*|[0-9][0-9_]*(?:\.[0-9_]*)?)(?:[eE][-+]?[0-9]+)?
      | [-+]?\.(?:inf|Inf|INF) | \.(?:nan|NaN|NAN)
      | [0-9]{4}-[0-9]{1,2}-[0-9]{1,2}(?:[Tt ].*)?
      | << | =
    )
    """,
    re.VERBOSE,
)


def _escape(text: str) -> str:
    """*text* as the inside of a YAML double-quoted scalar, ASCII only."""
    out: list[str] = []
    for char in text:
        point = ord(char)
        if char in '"\\':
            out.append("\\" + char)
        elif 0x20 <= point < 0x7F:
            out.append(char)
        elif point > 0xFFFF:
            out.append(f"\\U{point:08X}")
        else:
            out.append(f"\\u{point:04X}")
    return "".join(out)


def value(text: str) -> str:
    """A declaration value: always double-quoted, every ``$`` doubled for compose."""
    return '"' + _escape(text.replace("$", "$$")) + '"'


def fixed(text: str) -> str:
    """Framework text in a flow sequence: double-quoted, written as it stands."""
    return '"' + _escape(text) + '"'


def plain_safe(scalar: str) -> bool:
    """Whether *scalar* may stand plain: YAML 1.1 and 1.2 both read it as this string."""
    return _PLAIN.fullmatch(scalar) is not None and _NOT_A_STRING.fullmatch(scalar) is None


def scalar(text: str, *, leading_id: bool = True) -> str:
    """A scalar built from ids and fixed text, plain where that is safe.

    *leading_id*: the scalar starts with an id, which stands plain only when it does not
    start with a digit. A scalar that starts with fixed text (``.app.<id>.env``) or with
    the project name is held to the resolver alone.
    """
    if plain_safe(text) and not (leading_id and text[:1].isdigit()):
        return text
    return fixed(text)


def _flow(items: tuple[str, ...], encode=value) -> str:
    return "[" + ", ".join(encode(item) for item in items) + "]"
