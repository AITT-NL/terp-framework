"""The runtime configuration a Dockerfile gives its last stage, replayed over its base's.

``sign`` holds the backend image's configuration to the commit's own Dockerfile (ADR 0187
decision 6, step 5): the fields that decide what a container of the image runs, as whom, where,
with which environment, and how it is probed and stopped (:data:`FIELDS`). The expected value is
the base image's configuration, which the sandbox reads from the base the Dockerfile pins by
digest, with each instruction of the last stage, and of the stages it is built ``FROM``, applied
the way BuildKit's Dockerfile frontend applies it: ``ENV``, ``ARG``, ``WORKDIR``, ``USER``,
``CMD``, ``ENTRYPOINT``, ``HEALTHCHECK``, ``VOLUME``, ``STOPSIGNAL`` and ``SHELL``. Labels and
exposed ports run nothing and are not compared.

Nothing is run or fetched here: the Dockerfile is text. A shape this reader does not follow
(another escape character, a base or a stage with ``ONBUILD`` triggers, a variable form it does
not expand, the builder's own platform) is refused as one ``sign`` cannot compare, never read
as tampering.
"""

from __future__ import annotations

import json
import posixpath
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from terp.cli.release._common import ReleaseError

#: The configuration fields compared: everything ``docker run`` takes from an image that runs
#: or decides how something runs.
FIELDS = ("Entrypoint", "Cmd", "Env", "User", "WorkingDir", "Healthcheck", "Volumes", "StopSignal", "Shell")

_DEFAULT_SHELL = ["/bin/sh", "-c"]
_DIRECTIVE = re.compile(r"#\s*([a-zA-Z][a-zA-Z0-9]*)\s*=\s*(.+?)\s*")
_CONTINUED = re.compile(r"(.*?)\\[ \t]*")
_HEREDOC = re.compile(r"<<(-?)([\"']?)([A-Za-z_][A-Za-z0-9_]*)\2")
_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
#: What may follow a bare ``$``: a name, a positional parameter or a special one (all unset).
_BARE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*|[0-9]+|[@*#?$!-]")
_SPACE = re.compile(r"\s+")
_DURATION = re.compile(r"([0-9]*\.?[0-9]+)(ns|us|µs|ms|s|m|h)")
_UNITS = {"ns": 1, "us": 10**3, "µs": 10**3, "ms": 10**6, "s": 10**9, "m": 60 * 10**9, "h": 3600 * 10**9}
_HEALTH_FLAGS = {"interval": "Interval", "timeout": "Timeout", "start-period": "StartPeriod",
                 "start-interval": "StartInterval", "retries": "Retries"}
_IGNORED = frozenset({"run", "copy", "add", "label", "expose", "maintainer"})
_BUILDER_ARGS = frozenset({"BUILDPLATFORM", "BUILDOS", "BUILDARCH", "BUILDVARIANT"})


def _uncomparable(dockerfile: str, why: str) -> ReleaseError:
    return ReleaseError(f"{dockerfile} {why}, a shape sign cannot compare the image's configuration with")


@dataclass
class _Stage:
    base: str
    name: str
    instructions: list[tuple[str, str]] = field(default_factory=list)


def _instructions(text: str, dockerfile: str) -> list[tuple[str, str]]:
    """``(keyword, arguments)`` of every instruction, lines joined as BuildKit's parser joins them."""
    raw = text.splitlines()
    found: list[tuple[str, str]] = []
    index, directives = 0, True
    while index < len(raw):
        line = raw[index].lstrip()
        index += 1
        directive = _DIRECTIVE.fullmatch(line) if directives else None
        if directive is not None:
            if directive.group(1).lower() == "escape" and directive.group(2) != "\\":
                raise _uncomparable(dockerfile, f"sets the escape character to {directive.group(2)!r}")
            continue
        directives = False
        if not line or line.startswith("#"):
            continue
        continued = _CONTINUED.fullmatch(line)
        current = continued.group(1) if continued else line
        while continued and index < len(raw):
            following = raw[index]
            index += 1
            if following.lstrip().startswith("#") or not following.strip():
                continue
            continued = _CONTINUED.fullmatch(following)
            current += continued.group(1) if continued else following
        keyword, *rest_of = _SPACE.split(current.strip(), maxsplit=1)
        keyword, rest = keyword.lower(), (rest_of[0] if rest_of else "")
        found.append((keyword, rest))
        if keyword in ("run", "copy", "add") and not rest.startswith("["):
            for strip, _quote, word in _HEREDOC.findall(rest):  # the bodies are no instructions
                while index < len(raw) and (raw[index].lstrip("\t") if strip else raw[index]) != word:
                    index += 1
                index += 1
    return found


def _stages(text: str, dockerfile: str) -> tuple[list[str], list[_Stage]]:
    """The ``ARG`` words before the first ``FROM``, and every stage."""
    preamble: list[str] = []
    stages: list[_Stage] = []
    for keyword, rest in _instructions(text, dockerfile):
        if keyword == "from":
            words = [word for word in rest.split() if not word.startswith("--")]
            name = words[2].lower() if len(words) == 3 and words[1].lower() == "as" else ""
            stages.append(_Stage(words[0] if words else "", name))
        elif stages:
            stages[-1].instructions.append((keyword, rest))
        elif keyword == "arg":
            preamble += _words(rest)
    if not stages:
        raise _uncomparable(dockerfile, "has no FROM")
    return preamble, stages


def chain(stages: list[_Stage]) -> list[_Stage]:
    """The last stage and every stage it is built ``FROM``, the first built from an image."""
    at = len(stages) - 1
    built = [stages[at]]
    while True:
        earlier = [i for i in range(at) if stages[i].name and stages[i].name == stages[at].base.lower()]
        if not earlier:
            return built
        at = earlier[-1]
        built.insert(0, stages[at])


def _words(rest: str) -> list[str]:
    """Whitespace-separated words, quotes and escapes kept, as BuildKit's ``parseWords`` splits."""
    words: list[str] = []
    word, quote, index, started = "", "", 0, False
    while index < len(rest):
        char = rest[index]
        if quote:
            if char == quote:
                quote = ""
            elif char == "\\" and quote == '"' and index + 1 < len(rest):
                word += char
                index += 1
                char = rest[index]
            word += char
        elif char.isspace():
            if started:
                words.append(word)
            word, started = "", False
        else:
            started = True
            if char in "'\"":
                quote = char
            elif char == "\\" and index + 1 < len(rest):  # a line never ends in one: it continues
                word += char
                index += 1
                char = rest[index]
            word += char
        index += 1
    if started:
        words.append(word)
    return words


class _Lexer:
    """BuildKit's shell lexer over one word: quotes removed, escapes taken, variables expanded."""

    def __init__(self, text: str, env: Mapping[str, str], dockerfile: str) -> None:
        self.text, self.env, self.dockerfile, self.at = text, env, dockerfile, 0

    def word(self, stop: str = "") -> str:
        out: list[str] = []
        while self.at < len(self.text) and self.text[self.at] != stop:
            char = self.text[self.at]
            self.at += 1
            if char == "\\":
                if self.at < len(self.text):
                    out.append(self.text[self.at])
                    self.at += 1
            elif char == "'":
                end = self.text.find("'", self.at)
                if end < 0:
                    raise _uncomparable(self.dockerfile, "leaves a quote open")
                out.append(self.text[self.at : end])
                self.at = end + 1
            elif char == '"':
                out.append(self._double())
            elif char == "$":
                out.append(self._dollar())
            else:
                out.append(char)
        return "".join(out)

    def _double(self) -> str:
        out: list[str] = []
        while self.at < len(self.text) and self.text[self.at] != '"':
            char = self.text[self.at]
            self.at += 1
            if char == "\\" and self.at < len(self.text) and self.text[self.at] in '"$\\':
                out.append(self.text[self.at])
                self.at += 1
            elif char == "$":
                out.append(self._dollar())
            else:
                out.append(char)
        if self.at >= len(self.text):
            raise _uncomparable(self.dockerfile, "leaves a quote open")
        self.at += 1
        return "".join(out)

    def _dollar(self) -> str:
        if self.text.startswith("{", self.at):
            self.at += 1
            name = _NAME.match(self.text, self.at)
            if name is None:
                raise _uncomparable(self.dockerfile, "uses a ${...} form without a variable name")
            self.at = name.end()
            value = self.env.get(name.group())
            operator = next((op for op in (":-", ":+", "-", "+") if self.text.startswith(op, self.at)), None)
            if operator is None:
                if not self.text.startswith("}", self.at):
                    raise _uncomparable(self.dockerfile, f"expands ${{{name.group()}}} in a form this reader does not")
                self.at += 1
                return value or ""
            self.at += len(operator)
            alternative = self.word("}")
            if self.at >= len(self.text):
                raise _uncomparable(self.dockerfile, "leaves a ${ open")
            self.at += 1
            if operator == ":-":
                return value if value else alternative
            if operator == "-":
                return value if value is not None else alternative
            if operator == ":+":
                return alternative if value else ""
            return alternative if value is not None else ""
        name = _BARE.match(self.text, self.at)
        if name is None:
            return "$"
        self.at = name.end()
        return self.env.get(name.group()) or ""


def _expand(text: str, env: Mapping[str, str], dockerfile: str) -> str:
    return _Lexer(text, env, dockerfile).word()


def _json_list(rest: str) -> list[str] | None:
    """An exec-form argument list, or ``None`` for the shell form."""
    if not rest.startswith("["):
        return None
    try:
        parsed = json.loads(rest)
    except ValueError:
        return None
    if not isinstance(parsed, list) or not all(isinstance(item, str) for item in parsed):
        return None
    return parsed


def _command(rest: str, shell: list[str] | None) -> list[str]:
    exec_form = _json_list(rest)
    return exec_form if exec_form is not None else [*(shell or _DEFAULT_SHELL), rest]


def _flags(rest: str) -> tuple[dict[str, str], str]:
    flags: dict[str, str] = {}
    while rest.startswith("--"):
        token, _, rest = rest.partition(" ")
        name, _, value = token[2:].partition("=")
        flags[name.lower()] = value
        rest = rest.strip()
    return flags, rest


def _duration(text: str, dockerfile: str) -> int:
    if text == "0":
        return 0
    parts = _DURATION.findall(text)
    if not parts or "".join(number + unit for number, unit in parts) != text:
        raise _uncomparable(dockerfile, f"gives a HEALTHCHECK a duration {text!r} this reader does not read")
    return round(sum(float(number) * _UNITS[unit] for number, unit in parts))


def _healthcheck(rest: str, dockerfile: str) -> dict[str, Any]:
    flags, rest = _flags(rest)
    kind, *more = _SPACE.split(rest, maxsplit=1)
    command = more[0] if more else ""
    if kind.upper() == "NONE":
        return {"Test": ["NONE"]}
    if kind.upper() != "CMD" or not command.strip():
        raise _uncomparable(dockerfile, f"has a HEALTHCHECK {rest!r} this reader does not read")
    exec_form = _json_list(command.strip())
    check: dict[str, Any] = {"Test": ["CMD", *exec_form] if exec_form is not None else ["CMD-SHELL", command.strip()]}
    for flag, value in flags.items():
        if flag not in _HEALTH_FLAGS:
            raise _uncomparable(dockerfile, f"gives a HEALTHCHECK the flag --{flag}")
        if flag == "retries":
            if not value.isdigit():
                raise _uncomparable(dockerfile, f"gives a HEALTHCHECK --retries={value}")
            check["Retries"] = int(value)
        else:
            check[_HEALTH_FLAGS[flag]] = _duration(value, dockerfile)
    return check


@dataclass
class _Replay:
    """One stage chain applied over the base's configuration."""

    dockerfile: str
    config: dict[str, Any]
    build_args: Mapping[str, str]
    globals: Mapping[str, str]
    args: dict[str, str] = field(default_factory=dict)

    def env(self) -> dict[str, str]:
        listed = dict(item.partition("=")[::2] for item in self.config.get("Env") or [])
        return {**self.args, **listed}

    def apply(self, keyword: str, rest: str, cmd_set: bool) -> bool:
        """Apply one instruction; whether the stage has set ``CMD`` since."""
        handler = getattr(self, f"_{keyword}", None)
        if handler is None:
            if keyword in _IGNORED:
                return cmd_set
            raise _uncomparable(self.dockerfile, f"has an instruction {keyword.upper()} this reader does not know")
        return handler(rest, cmd_set)

    def _env(self, rest: str, cmd_set: bool) -> bool:
        words = _words(rest)
        if words and "=" not in words[0]:
            key, *value = _SPACE.split(rest, maxsplit=1)
            pairs = [(key, value[0] if value else "")]
        else:
            if any("=" not in word for word in words):
                raise _uncomparable(self.dockerfile, f"has an ENV {rest!r} that is no list of name=value")
            pairs = [(word.partition("=")[0], word.partition("=")[2]) for word in words]
        env = self.env()
        listed = list(self.config.get("Env") or [])
        for raw_key, raw_value in pairs:
            key, value = _expand(raw_key, env, self.dockerfile), _expand(raw_value, env, self.dockerfile)
            at = next((i for i, item in enumerate(listed) if item.partition("=")[0] == key), None)
            if at is None:
                listed.append(f"{key}={value}")
            else:
                listed[at] = f"{key}={value}"
        self.config["Env"] = listed
        return cmd_set

    def _arg(self, rest: str, cmd_set: bool) -> bool:
        for word in _words(rest):
            name, has_default, default = word.partition("=")
            if name in _BUILDER_ARGS:
                raise _uncomparable(self.dockerfile, f"reads the builder's own platform ({name})")
            if name in self.build_args:
                self.args[name] = self.build_args[name]
            elif has_default:
                self.args[name] = _expand(default, self.env(), self.dockerfile)
            elif name in self.globals:
                self.args[name] = self.globals[name]
        return cmd_set

    def _workdir(self, rest: str, cmd_set: bool) -> bool:
        path = _expand(rest, self.env(), self.dockerfile)
        joined = posixpath.normpath(posixpath.join(self.config.get("WorkingDir") or "/", path))
        self.config["WorkingDir"] = "/" + joined.lstrip("/")
        return cmd_set

    def _user(self, rest: str, cmd_set: bool) -> bool:
        self.config["User"] = _expand(rest, self.env(), self.dockerfile)
        return cmd_set

    def _stopsignal(self, rest: str, cmd_set: bool) -> bool:
        self.config["StopSignal"] = _expand(rest, self.env(), self.dockerfile)
        return cmd_set

    def _cmd(self, rest: str, cmd_set: bool) -> bool:
        self.config["Cmd"] = _command(rest, self.config.get("Shell"))
        return True

    def _entrypoint(self, rest: str, cmd_set: bool) -> bool:
        self.config["Entrypoint"] = _command(rest, self.config.get("Shell"))
        if not cmd_set:  # an inherited CMD does not survive a new ENTRYPOINT
            self.config["Cmd"] = None
        return cmd_set

    def _shell(self, rest: str, cmd_set: bool) -> bool:
        shell = _json_list(rest)
        if not shell:
            raise _uncomparable(self.dockerfile, "has a SHELL that is no JSON list")
        self.config["Shell"] = shell
        return cmd_set

    def _healthcheck(self, rest: str, cmd_set: bool) -> bool:
        self.config["Healthcheck"] = _healthcheck(rest, self.dockerfile)
        return cmd_set

    def _volume(self, rest: str, cmd_set: bool) -> bool:
        listed = _json_list(rest)
        volumes = dict(self.config.get("Volumes") or {})
        for volume in listed if listed is not None else _words(rest):
            volumes[_expand(volume, self.env(), self.dockerfile)] = {}
        self.config["Volumes"] = volumes
        return cmd_set

    def _onbuild(self, rest: str, cmd_set: bool) -> bool:
        raise _uncomparable(self.dockerfile, "has an ONBUILD trigger in a stage another is built from")


def runtime_config(
    text: str, dockerfile: str, base: Mapping[str, Any], build_args: Mapping[str, str], platform: str
) -> dict[str, Any]:
    """The compared fields of the configuration the Dockerfile *text* gives its last stage."""
    if base.get("OnBuild"):
        raise _uncomparable(dockerfile, "is built on a base with ONBUILD triggers")
    os_name, _, rest = platform.partition("/")
    arch, _, variant = rest.partition("/")
    targets = {"TARGETPLATFORM": platform, "TARGETOS": os_name, "TARGETARCH": arch, "TARGETVARIANT": variant}
    given = {**targets, **build_args}
    preamble, stages = _stages(text, dockerfile)
    globals_ = {}
    for word in preamble:
        name, has_default, default = word.partition("=")
        if name in given or has_default:
            globals_[name] = given.get(name, _expand(default, globals_, dockerfile))
    replay = _Replay(dockerfile, {name: base.get(name) for name in FIELDS}, given, globals_)
    stages = chain(stages)
    for stage in stages:
        cmd_set = False
        for keyword, rest in stage.instructions:
            if keyword == "onbuild" and stage is stages[-1]:
                continue  # a trigger for whatever builds on this image; it runs nothing here
            cmd_set = replay.apply(keyword, rest, cmd_set)
    return replay.config


def _normal(name: str, value: Any) -> Any:
    if not value or (name == "WorkingDir" and value == "/"):
        return None
    if name == "Healthcheck":
        return {key: item for key, item in value.items() if item} or None
    if name == "Volumes":
        return sorted(value)
    return value


def differences(expected: Mapping[str, Any], image: Mapping[str, Any]) -> list[str]:
    """How *image*'s configuration differs from *expected* in the compared fields.

    The environment is told by variable name alone: a value may be a credential.
    """
    found: list[str] = []
    for name in FIELDS:
        if name == "Env":
            continue
        ours, theirs = _normal(name, expected.get(name)), _normal(name, image.get(name))
        if ours != theirs:
            found.append(f"the image's {name} is {json.dumps(theirs)}, and its Dockerfile makes it {json.dumps(ours)}")
    listed = [item.partition("=") for item in image.get("Env") or []]
    theirs_env = {key: value for key, _, value in listed}
    ours_env = {key: value for key, _, value in (item.partition("=") for item in expected.get("Env") or [])}
    if len(theirs_env) != len(listed):
        found.append("the image's environment sets a variable more than once")
    for key in sorted(set(ours_env) | set(theirs_env)):
        if key not in ours_env:
            found.append(f"the image's environment sets {key}, which its Dockerfile does not")
        elif key not in theirs_env:
            found.append(f"the image's environment does not set {key}, which its Dockerfile does")
        elif ours_env[key] != theirs_env[key]:
            found.append(f"the image's environment gives {key} another value than its Dockerfile does")
    return found


__all__ = ["FIELDS", "chain", "differences", "runtime_config"]
