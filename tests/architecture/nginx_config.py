"""An nginx configuration read as nginx reads it, for the tests that hold a server's headers.

A line-by-line reading cannot tell where a header applies, and where is the whole question:
nginx applies an ``add_header`` from an outer block only to a block that declares none of its
own. So a header on the ``server`` block is not a header on a location that sets
``Cache-Control``, and a policy written once in ``location /`` is absent from every other
location. This reads the directives into their blocks and answers, for each location that
serves a file, the headers its responses carry.

It reads what the framework's own configurations use: directives, blocks, quoted strings,
comments and ``${NAME}`` (the SPA's config is an envsubst template). A shape it does not read
is a failure, never a guess.
"""

from __future__ import annotations

from dataclasses import dataclass, field

_SPECIAL = "{};"


@dataclass
class Directive:
    """One directive: its name, its arguments, and its block when it opens one."""

    name: str
    args: list[str]
    block: list[Directive] | None = None
    #: The ``add_header`` directives a response from this block carries, inherited included.
    headers: dict[str, tuple[str, bool]] = field(default_factory=dict)


def _tokens(text: str) -> list[str]:
    tokens: list[str] = []
    index = 0
    while index < len(text):
        char = text[index]
        if char.isspace():
            index += 1
        elif char == "#":
            end = text.find("\n", index)
            index = len(text) if end == -1 else end
        elif char in _SPECIAL:
            tokens.append(char)
            index += 1
        elif char in "\"'":
            end = index + 1
            value = []
            while text[end] != char:
                if text[end] == "\\":
                    end += 1
                value.append(text[end])
                end += 1
            tokens.append("".join(value))
            index = end + 1
        else:
            word = []
            while index < len(text) and not text[index].isspace() and text[index] not in ";{}":
                if text.startswith("${", index):
                    close = text.index("}", index)
                    word.append(text[index : close + 1])
                    index = close + 1
                    continue
                word.append(text[index])
                index += 1
            tokens.append("".join(word))
    return tokens


def parse(text: str) -> list[Directive]:
    """The directives of *text*, each block nested under the directive that opens it."""
    stack: list[list[Directive]] = [[]]
    words: list[str] = []
    for token in _tokens(text):
        if token == ";":
            stack[-1].append(Directive(words[0], words[1:]))
            words = []
        elif token == "{":
            block: list[Directive] = []
            stack[-1].append(Directive(words[0], words[1:], block))
            stack.append(block)
            words = []
        elif token == "}":
            assert not words, f"a block closes after an unterminated directive: {words}"
            stack.pop()
        else:
            words.append(token)
    assert len(stack) == 1 and not words, "the configuration ends inside a block or a directive"
    return stack[0]


def _own_headers(block: list[Directive]) -> dict[str, tuple[str, bool]]:
    return {
        item.args[0]: (item.args[1], item.args[2:] == ["always"])
        for item in block
        if item.name == "add_header"
    }


def locations(text: str) -> list[Directive]:
    """Every ``location`` of every ``server`` in *text*, each with the headers it carries."""
    found: list[Directive] = []

    def walk(block: list[Directive], inherited: dict[str, tuple[str, bool]]) -> None:
        headers = _own_headers(block) or inherited
        for item in block:
            if item.block is None:
                continue
            if item.name == "location":
                item.headers = _own_headers(item.block) or headers
                found.append(item)
            walk(item.block, headers)

    walk(parse(text), {})
    return found


def serves_files(location: Directive) -> bool:
    """Whether *location* answers from the filesystem: it neither returns nor proxies."""
    assert location.block is not None
    return not any(item.name in ("return", "proxy_pass") for item in location.block)


def where(location: Directive) -> str:
    """``location /assets/``, as a reader finds it in the file."""
    return " ".join(["location", *location.args])


#: The policy every response of a file carries: the template SPA's, and the static site's.
POLICY = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
    "font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; "
    "frame-ancestors 'none'; form-action 'self'"
)

#: The document headers each of those responses carries (ADR 0104), each with ``always``.
DOCUMENT_HEADERS = {
    "Content-Security-Policy": POLICY,
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
}


def unheaded_file_locations(text: str) -> dict[str, list[str]]:
    """Each location of *text* that serves a file, with the document headers it lacks.

    A location that declares an ``add_header`` of its own carries only its own, so a header
    written once elsewhere is not one of its headers.
    """
    return {
        where(location): [
            f"{header}: {value}"
            for header, value in DOCUMENT_HEADERS.items()
            if location.headers.get(header) != (value, True)
        ]
        for location in locations(text)
        if serves_files(location)
    }


__all__ = [
    "DOCUMENT_HEADERS",
    "POLICY",
    "Directive",
    "locations",
    "parse",
    "serves_files",
    "unheaded_file_locations",
    "where",
]
