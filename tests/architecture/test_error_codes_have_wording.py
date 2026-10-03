"""Every error code the core emits has wording in the UI, in every framework locale, or a stated reason.

The backend answers a failure with ``{code, detail, request_id}``; the UI shows its own wording
for a code it knows and the backend's English ``detail`` for one it does not. The middleware's
codes -- the rate limiter's, the body-size limit's, the idempotency layer's and the JSON guard's
-- and the unhandled-exception handler's ``internal_error`` were emitted with no wording, so a
Dutch screen said "Er is iets misgegaan." over "Too many requests; please retry later.". The
first version of this gate was written for three of them and found the rest; a review then found
that it read the one file of error classes where the core declares them in several.

**Scope: the core**, every module of ``terp.core``, which every app mounts. The capabilities'
own codes are not held here: each is mounted by some apps and not others, and several of their
refusals carry specifics in their detail that a fixed wording would drop. Which of them to word
is open in docs/internal/drafts/presentation-and-composition-design.md.

The codes are read from where they are emitted -- an error class's ``code``, a middleware
envelope, the last-resort handler's body -- and every envelope call site must be one the gate
can read, so a call written another way fails here instead of passing as nothing to word.
"""

from __future__ import annotations

import pathlib
import re

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_CORE = _ROOT / "packages" / "backend" / "core" / "src" / "terp" / "core"
_MESSAGES = _ROOT / "packages" / "frontend" / "react-core" / "src" / "errorMessages.tsx"

#: Codes the core emits that keep the backend's own detail on purpose, each with its reason.
_UNWORDED = {
    "weak_password": (
        "its detail names the policy's own requirements -- the length, the kinds of character -- "
        "which a fixed wording would drop; wording it needs the envelope to carry them"
    ),
}

_CLASS_CODE = re.compile(r'^\s+code(?::\s*ClassVar\[str\])?\s*=\s*"([a-z0-9_]+)"', re.M)
_ENVELOPE = re.compile(r'_envelope\(\s*"([a-z0-9_]+)"')
_SEND = re.compile(r'_send_json_error\(\s*send,\s*\d+,\s*"([a-z0-9_]+)"')
_HANDLER = re.compile(r'"code":\s*"([a-z0-9_]+)"')
#: The one call that passes a code on rather than naming one: ``_send_json_error``'s own body.
_FORWARD = re.compile(r"_envelope\(code, detail\)")


def _calls(text: str, name: str) -> int:
    """Call sites of ``name`` in ``text``: every use of the name itself (not ``build_error_envelope``), less its definition."""
    return len(re.findall(rf"(?<!\w){name}\(", text)) - text.count(f"def {name}(")


def _emitted() -> set[str]:
    codes: set[str] = set()
    for path in sorted(_CORE.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        for pattern in (_CLASS_CODE, _ENVELOPE, _SEND, _HANDLER):
            codes.update(pattern.findall(text))
        read = len(_ENVELOPE.findall(text)) + len(_FORWARD.findall(text))
        assert read == _calls(text, "_envelope"), (
            f"{path.name}: an _envelope call the gate cannot read; name its code as a literal"
        )
        assert len(_SEND.findall(text)) == _calls(text, "_send_json_error"), (
            f"{path.name}: a _send_json_error call the gate cannot read; name its status as a "
            "number and its code as a literal, in that order"
        )
    return codes


def _worded() -> set[str]:
    source = _MESSAGES.read_text(encoding="utf-8")
    body = source[source.index("function builtInErrorMessages") :]
    body = body[: body.index("\n}\n")]
    return set(re.findall(r"^\s+([a-z0-9_]+): strings\.errorCode", body, re.M))


def test_every_emitted_error_code_has_wording() -> None:
    missing = sorted(_emitted() - _worded() - set(_UNWORDED))
    assert not missing, (
        f"error codes the core emits with no wording in the UI: {missing}. Map each in "
        "builtInErrorMessages (errorMessages.tsx) to an errorCode* framework string -- a new one "
        "in uiText.tsx and every locale catalog where none fits -- or, where the backend's detail "
        "must reach the reader as written, list it in _UNWORDED with the reason; otherwise the "
        "English detail is shown under every locale."
    )


def test_an_unworded_code_is_still_emitted_and_still_unworded() -> None:
    # An exception that outlived its reason is a gap the next reader takes for a decision.
    emitted, worded = _emitted(), _worded()
    assert sorted(code for code in _UNWORDED if code not in emitted or code in worded) == []


def test_the_core_is_read_whole() -> None:
    # A code from each place the core declares one: the taxonomy's base and a subclass, a class
    # in another module, a middleware envelope, a middleware send and the last-resort handler.
    # A pattern that stopped matching any of them would read as "nothing to word" rather than fail.
    assert {
        "bad_request",
        "stale_data",
        "lease_held",
        "rate_limited",
        "request_too_large",
        "internal_error",
    } <= _emitted()
