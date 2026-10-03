"""Every error code the platform emits has wording in the UI, in every framework locale.

The backend answers a failure with ``{code, detail, request_id}``; the UI shows its own wording
for a code it knows and the backend's English ``detail`` for one it does not. The middleware's
codes -- the rate limiter's, the body-size limit's, the idempotency layer's and the JSON guard's
-- and the unhandled-exception handler's ``internal_error`` were emitted with no wording, so a
Dutch screen said "Er is iets misgegaan." over "Too many requests; please retry later.". The
first version of this gate was written for three of them and found the rest.

The codes are read from where they are emitted: the ``AppError`` taxonomy, the middleware's
envelopes and the app's last-resort handler. Wording lives in react-core's built-in map, whose
values are framework strings, so a locale catalog that leaves one out is already refused.
"""

from __future__ import annotations

import pathlib
import re

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_CORE = _ROOT / "packages" / "backend" / "core" / "src" / "terp" / "core"
_MESSAGES = _ROOT / "packages" / "frontend" / "react-core" / "src" / "errorMessages.tsx"

_EMITTERS = (
    (_CORE / "errors.py", re.compile(r'^\s+code(?::\s*ClassVar\[str\])?\s*=\s*"([a-z_]+)"', re.M)),
    (_CORE / "_internal" / "middleware.py", re.compile(r'_envelope\(\s*"([a-z_]+)"')),
    (_CORE / "_internal" / "middleware.py", re.compile(r'_send_json_error\(\s*send,\s*\d+,\s*"([a-z_]+)"')),
    (_CORE / "app.py", re.compile(r'"code":\s*"([a-z_]+)"')),
)


def _emitted() -> set[str]:
    codes: set[str] = set()
    for path, pattern in _EMITTERS:
        found = pattern.findall(path.read_text(encoding="utf-8"))
        assert found, f"{path.name}: no error code matched {pattern.pattern!r}; the gate reads nothing"
        codes.update(found)
    return codes


def _worded() -> set[str]:
    source = _MESSAGES.read_text(encoding="utf-8")
    body = source[source.index("function builtInErrorMessages") :]
    body = body[: body.index("\n}\n")]
    return set(re.findall(r"^\s+([a-z_]+): strings\.errorCode", body, re.M))


def test_every_emitted_error_code_has_wording() -> None:
    missing = sorted(_emitted() - _worded())
    assert not missing, (
        f"error codes the platform emits with no wording in the UI: {missing}. Add an errorCode* "
        "framework string for each (uiText.tsx and every locale catalog) and map it in "
        "builtInErrorMessages (errorMessages.tsx); otherwise the backend's English detail is shown "
        "as written under every locale."
    )


def test_the_taxonomy_is_read() -> None:
    # The base class's code and a subclass's both count, so a pattern that stopped matching
    # class attributes would read as "nothing to word" rather than fail.
    assert {"bad_request", "stale_data", "rate_limited", "internal_error"} <= _emitted()
