"""``terp workbench adopt`` -- bring an app's ``workbench.json`` to a schema version, by its diff.

The template seeds ``workbench.json`` once and the app owns it afterwards (copier
``_skip_if_exists``, ADR 0110 decision 6). That is right -- an upgrade that rewrote it
would make it describe the template instead of the app -- and it has one consequence
nobody had a remedy for: a later version of the vocabulary never reaches an app that
already has a file. Every existing project would keep the version it was rendered with
forever. Adoption is the step that carries a file forward, and it is the app's own,
run where its author can see what it changes (ADR 0186).

What it does, in order:

1. **Refuses a version the vocabulary does not define.** ``--schema`` names a version of
   the Terp Standard's ``workbench-declaration.schema.json``; a version no release of it
   defines yet has no blocks to write, and inventing them here would be a second copy of
   the vocabulary, which is the defect the spec move ended. This toolchain's vocabulary
   defines version 1 only, so today ``--schema 2`` is refused by name and writes nothing.
2. **Reads the file the way the gate does**, and stops at anything it cannot read: a file
   it cannot parse is not one it may rewrite, and a later version than the target is
   never written down.
3. **Derives what the compose file says and the file must agree with** -- the variable
   each declared service's host port actually arrives through -- and refuses a fact it
   cannot represent: a declared service the compose file no longer defines (which service
   plays the role now is the author's to say), a fixed host port (the fact the file
   records is not true and cannot be made true by writing it), two variables for one
   service, and a seam the compose file never reads.
4. **Shows the diff, and writes only with** ``--write``. ``--check`` writes nothing and
   fails when adoption has something to write, for an app's own CI to opt into. It is not
   part of ``terp verify``: the day a later version ships, every app would turn red over a
   file it has not adopted, which is the thing ADR 0110 decision 7 rules out.

Everything the compose file cannot settle is carried over untouched: roles, readiness
paths, the ``commands`` block, every key the vocabulary does not have, and the order of
the keys. An absent file stays absent -- adoption carries a declaration forward, it does not
declare an app -- and an opted-out one stays opted out.
"""

from __future__ import annotations

import copy
import difflib
import json
import pathlib
import re
from dataclasses import dataclass
from typing import Any

import yaml

from terp.arch import workbench as vocabulary
from terp.cli._output import emit
from terp.cli.workbench import WORKBENCH_FILE, _interpolates, _published_host_ports, load, read

#: A variable a published host port is interpolated from: ``${WEB_PORT:-5173}``.
_VARIABLE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)")


class AdoptionRefused(Exception):
    """A fact the target version cannot represent, or a file adoption may not rewrite."""


@dataclass(frozen=True)
class Adoption:
    """What adoption would write: the file as it is, and as it would be."""

    before: str
    after: str
    target: int

    @property
    def changes(self) -> bool:
        return self.before != self.after

    def diff(self) -> str:
        return "".join(
            difflib.unified_diff(
                self.before.splitlines(keepends=True),
                self.after.splitlines(keepends=True),
                fromfile=f"a/{WORKBENCH_FILE}",
                tofile=f"b/{WORKBENCH_FILE}",
            )
        )


def latest_version() -> int:
    """The newest schema version this toolchain's vocabulary defines."""
    return max(vocabulary.SUPPORTED_VERSIONS)


def plan(project_root: pathlib.Path, target: int) -> Adoption | None:
    """What adopting *project_root*'s declaration into *target* would write.

    ``None`` when there is nothing to adopt: no file, or one opted out.
    :class:`AdoptionRefused` for a target the vocabulary does not define, a file this
    toolchain cannot read, and a fact the target cannot represent.
    """
    if target not in vocabulary.SUPPORTED_VERSIONS:
        raise AdoptionRefused(
            f"schemaVersion {target} is not one this toolchain's vocabulary defines "
            f"(terp-spec {vocabulary.SPEC_RELEASE} defines "
            f"{', '.join(str(v) for v in sorted(vocabulary.SUPPORTED_VERSIONS))}). There "
            "are no blocks to write for it yet: adoption into it arrives with the release "
            "whose vocabulary defines it."
        )
    path = project_root / WORKBENCH_FILE
    declared, findings = load(project_root)
    if findings:
        raise AdoptionRefused(
            f"{WORKBENCH_FILE} cannot be read, so it cannot be rewritten:\n  "
            + "\n  ".join(f"{f.message} {f.remedy}".strip() for f in findings)
        )
    if declared is None or declared.unmanaged:
        return None
    before = path.read_text(encoding="utf-8")
    document = json.loads(before)
    adopted = copy.deepcopy(document)
    adopted["schemaVersion"] = target
    compose = _compose(project_root, declared.compose_file, declared.describes_a_compose_file)
    if compose is not None:
        _settle_ports(adopted, compose, declared.compose_file)
        _settle_seams(adopted, compose, declared.compose_file)
    if adopted == document:
        return Adoption(before=before, after=before, target=target)
    _, findings = read(adopted)
    if findings:
        raise AdoptionRefused(
            f"the compose file's own names would make {WORKBENCH_FILE} unreadable:\n  "
            + "\n  ".join(f"{f.message} {f.remedy}".strip() for f in findings)
        )
    return Adoption(before=before, after=json.dumps(adopted, indent=2) + "\n", target=target)


def _compose(root: pathlib.Path, name: str, claimed: bool) -> dict[str, Any] | None:
    path = root / name
    if not path.is_file():
        if claimed:
            raise AdoptionRefused(f"{WORKBENCH_FILE} names {name!r}, which does not exist.")
        return None
    try:
        parsed = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise AdoptionRefused(f"{name} is unreadable: {exc}") from exc
    services = parsed.get("services") if isinstance(parsed, dict) else None
    if not isinstance(services, dict):
        raise AdoptionRefused(f"{name} declares no services.")
    return parsed


def _settle_ports(document: dict[str, Any], compose: dict[str, Any], name: str) -> None:
    """Each declared host-port variable, as the compose file actually publishes it."""
    services = compose["services"]
    for index, entry in enumerate(document["services"]):
        service = entry["service"]
        if "hostPortEnv" not in entry:
            continue
        if service not in services:
            raise AdoptionRefused(
                f"services[{index}] describes {service!r}, which {name} does not define. "
                "Which service plays this role now is yours to say: point the entry at "
                "it, or drop the entry."
            )
        published = _published_host_ports(services[service] or {})
        if not published:
            continue
        variables = sorted({match for value in published for match in _VARIABLE.findall(value)})
        if not variables:
            raise AdoptionRefused(
                f"{service!r} publishes the fixed host port {published[0]!r}, and the fact "
                f"{WORKBENCH_FILE} records -- that it arrives through a variable -- cannot be "
                f'written true. Publish it as "${{{entry["hostPortEnv"]}:-<default>}}:<container '
                'port>" first.'
            )
        if entry["hostPortEnv"] in variables:
            continue
        if len(variables) > 1:
            raise AdoptionRefused(
                f"{service!r} publishes its host ports through {', '.join(variables)}, and "
                f"{WORKBENCH_FILE} can name one: say which in services[{index}].hostPortEnv."
            )
        entry["hostPortEnv"] = variables[0]


def _settle_seams(document: dict[str, Any], compose: dict[str, Any], name: str) -> None:
    """A declared seam the compose file never reads is not one adoption can invent a name for."""
    for label, variable in document.get("env", {}).items():
        if not _interpolates(compose, variable):
            raise AdoptionRefused(
                f'env.{label} names ${{{variable}}}, which {name} never reads. Name the '
                "variable the compose file reads there, or drop the seam."
            )


def run_workbench_adopt(
    *, root: str = ".", schema: int | None = None, write: bool = False, check: bool = False
) -> int:
    """``terp workbench adopt``: print what adoption would write; the exit code says what happened."""
    project_root = pathlib.Path(root).expanduser().resolve()
    target = latest_version() if schema is None else schema
    try:
        adoption = plan(project_root, target)
    except AdoptionRefused as exc:
        emit(f"Nothing was written. {exc}")
        return 1
    if adoption is None:
        declared, _ = load(project_root)
        if declared is None:
            emit(
                f"No {WORKBENCH_FILE}: this app declares no development topology, which "
                "passes. There is nothing to adopt."
            )
        else:
            emit(
                f"{WORKBENCH_FILE} declares this app unmanaged: {declared.reason}\n"
                "There is nothing to adopt."
            )
        return 0
    if not adoption.changes:
        emit(f"{WORKBENCH_FILE} is at schemaVersion {target} and agrees with its compose file.")
        return 0
    emit(adoption.diff().rstrip("\n"))
    if check:
        emit(
            f"\n{WORKBENCH_FILE} is not adopted into schemaVersion {target}: run "
            f"`terp workbench adopt --schema {target} --write`."
        )
        return 1
    if not write:
        emit(f"\nNothing was written. Run with --write to write {WORKBENCH_FILE} as shown.")
        return 0
    (project_root / WORKBENCH_FILE).write_text(adoption.after, encoding="utf-8", newline="\n")
    emit(f"\nWrote {WORKBENCH_FILE} at schemaVersion {target}.")
    return 0


__all__ = ["Adoption", "AdoptionRefused", "latest_version", "plan", "run_workbench_adopt"]
