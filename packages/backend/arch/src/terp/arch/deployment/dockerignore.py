"""``.dockerignore`` read the way Docker reads it, to ask whether a path stays out of a build.

The generated state's check asks whether the environment files a unit loads are left out of
the build context (ADR 0187 decision 1), and the answer has to be Docker's own, not a
resemblance of it: a ``.dockerignore`` that a looser reader passes is a secret baked into an
image layer by ``COPY . .``. So this follows the builder's pattern matcher
(``moby/patternmatcher``, which BuildKit and the classic builder share):

* one pattern per line, surrounding whitespace trimmed; a line beginning with ``#`` is a
  comment and an empty line is nothing;
* a pattern beginning with ``!`` is an exception, which re-includes what it matches;
* a pattern is cleaned as a path (``a//b/`` is ``a/b``, ``./a`` is ``a``) and a leading ``/``
  is dropped, because every pattern is relative to the root of the context: unlike git,
  ``.env`` matches the root's ``.env`` only, and ``**/.env`` matches it at any depth;
* ``*`` is any run of characters but ``/``, ``?`` is one such character, ``**`` is any run
  including ``/`` (``**/`` also matching nothing at all), ``[...]`` is a character class
  (``[^...]`` negated, ranges allowed), and ``\\`` makes the next character literal;
* a path is excluded when a pattern matches it or any directory above it, and the last
  matching pattern decides, so an exception after an exclusion wins.

A pattern this cannot read - a class that never closes, a trailing ``\\`` - is reported as
such, never guessed and never a crash: Docker itself refuses the build over it.
"""

from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Pattern:
    """One ``.dockerignore`` line, compiled."""

    text: str
    negated: bool
    regex: re.Pattern[str]


@dataclass(frozen=True)
class Unreadable:
    """A line Docker's matcher cannot compile either, and why."""

    line: int
    text: str
    reason: str


def _class(pattern: str, start: int) -> tuple[str, int]:
    """The character class opening at *start*, as a regex fragment, and where it ends."""
    index = start + 1
    out = "["
    if pattern[index : index + 1] == "^":
        out += "^"
        index += 1
    first = True
    while index < len(pattern):
        char = pattern[index]
        if char == "]" and not first:
            return out + "]", index
        if char == "\\":
            if index + 1 >= len(pattern):
                break
            out += re.escape(pattern[index + 1])
            index += 2
        else:
            out += "\\" + char if char in "[\\^" else char
            index += 1
        first = False
    raise ValueError("a character class that never closes")


def compile_pattern(pattern: str) -> re.Pattern[str]:
    """*pattern* (already cleaned, no ``!``) as an anchored regular expression."""
    out = ""
    index = 0
    while index < len(pattern):
        char = pattern[index]
        if pattern.startswith("**/", index):
            out += "(?:.*/)?"
            index += 3
            continue
        if pattern.startswith("**", index):
            out += ".*"
            index += 2
            continue
        if char == "*":
            out += "[^/]*"
        elif char == "?":
            out += "[^/]"
        elif char == "[":
            fragment, index = _class(pattern, index)
            out += fragment
        elif char == "\\":
            if index + 1 >= len(pattern):
                raise ValueError("a trailing backslash escapes nothing")
            index += 1
            out += re.escape(pattern[index])
        else:
            out += re.escape(char)
        index += 1
    return re.compile(out)


def _clean(text: str) -> str:
    cleaned = posixpath.normpath(text)
    return cleaned.lstrip("/") if cleaned != "/" else cleaned


def parse(text: str) -> tuple[list[Pattern], list[Unreadable]]:
    """Every pattern of a ``.dockerignore``, and every line that cannot be read."""
    patterns: list[Pattern] = []
    unreadable: list[Unreadable] = []
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        negated = line.startswith("!")
        body = line[1:].strip() if negated else line
        try:
            patterns.append(Pattern(line, negated, compile_pattern(_clean(body))))
        except ValueError as exc:
            unreadable.append(Unreadable(number, line, str(exc)))
    return patterns, unreadable


def _prefixes(path: str) -> list[str]:
    """*path* and every directory above it: excluding a directory excludes what it holds."""
    parts = path.split("/")
    return ["/".join(parts[: count + 1]) for count in range(len(parts))]


def excluded(path: str, patterns: list[Pattern]) -> bool:
    """Whether Docker leaves *path* (relative to the context, ``/``-separated) out of it."""
    left_out = False
    for pattern in patterns:
        if any(pattern.regex.fullmatch(candidate) for candidate in _prefixes(path)):
            left_out = not pattern.negated
    return left_out


__all__ = ["Pattern", "Unreadable", "compile_pattern", "excluded", "parse"]
