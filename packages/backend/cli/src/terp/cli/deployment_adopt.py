"""``terp deployment adopt`` -- move an app between the deploy declaration's states (ADR 0187).

The state is two recorded facts that must agree: ``"build"`` in ``deployment.json``, which
the gate reads, and ``deploy_build`` in ``.copier-answers.yml``, which ``copier update``
reads. Copier renders an update's OLD template version with the RECORDED answers, so with
``generated`` recorded the three production build files read as the app's own and are left
alone from the very first update; adoption therefore writes the answer itself, and needs no
template source, network, git or clean tree. It changes nothing else in the answers file.

* ``--build generated`` needs a readable, true, renderable declaration and scaffolding from
  a template version that asks the question (an answers file without ``deploy_build`` is
  refused: a ``copier update`` records it first). It sets both facts, renders, removes a
  generator path the declaration does not produce, and shows the diff: no build file
  changes for a template-shaped app at the template version it was rendered from. A
  project name compose or Docker would refuse is refused here, by the generator.
* ``--build own`` on a generated app sets both facts back and changes no file: the last
  render becomes the app's, and the next update merges into it as into any ``own`` app's.
  On an undeclared app it writes ``deployment.json`` from the production profile
  (:mod:`terp.cli.deployment_declare`).
* ``--unmanaged "<reason>"`` writes ADR 0184's opt-out, and records ``own`` for a template
  answer that said ``generated``, since the build files are the app's again.

Every adoption writes all of its files or none, prints the diff, and ``--dry-run`` only
prints. It never leaves a state ``terp verify --only generated`` is red for.
"""

from __future__ import annotations

import difflib
import json
import pathlib
import re
from dataclasses import dataclass, field
from typing import Any

import yaml

from terp.arch.deployment import (
    DEPLOYMENT_FILE,
    OWNED_PATHS,
    Declaration,
    Finding,
    Unmanaged,
    generate,
    generated,
    published_table,
    published_tables,
    read,
    readable,
)
from terp.arch.deployment.generator import FRONTEND_LOCK
from terp.arch.deployment.profile import truth_findings
from terp.arch.deployment.render_check import (
    ANSWER,
    ANSWERS_FILE,
    RENDER_COMMAND,
    ignore_findings,
    project_name,
)
from terp.cli._output import emit
from terp.cli.deployment_declare import DeclareRefused, derive
from terp.cli.deployment_render import render_changes, write_files

#: ``"build": "own"`` or ``"build": "generated"``, as JSON writes the member.
_BUILD_MEMBER = re.compile(r'("build"\s*:\s*)"(?:own|generated)"')

#: The recorded answer's line, as copier writes a plain scalar.
_ANSWER_LINE = re.compile(rf"^{ANSWER}:[^\n]*$", re.MULTILINE)


class AdoptionRefused(Exception):
    """The app cannot take the state it was asked for, as it stands; nothing was written."""


@dataclass
class Plan:
    """What an adoption writes: each path's bytes before and after (``None``: absent)."""

    headline: str
    changes: dict[str, tuple[bytes | None, bytes | None]] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    #: The generated check must be green once the plan is written.
    renders: bool = False

    def change(self, root: pathlib.Path, path: str, after: bytes | None) -> None:
        target = root / path
        before = target.read_bytes() if target.is_file() else None
        if before != after:
            self.changes[path] = (before, after)


def _lines(findings: list[Finding]) -> str:
    return "\n".join(
        f"  - {finding.file}: {finding.message}"
        + (f"\n    {finding.remedy}" if finding.remedy else "")
        for finding in findings
    )


def _declaration_text(text: str, build: str) -> bytes:
    """``deployment.json`` with only its build changed, its own formatting kept."""
    # One match is the member itself: a readable declaration has "build" at the top level
    # only (every nested object refuses unknown keys), and inside a JSON string a quote is
    # escaped, so the pattern cannot match there. A build spelt with escapes is not edited
    # in place: the whole file is written again.
    matches = list(_BUILD_MEMBER.finditer(text))
    if len(matches) == 1:
        (match,) = matches
        edited = f'{text[: match.start()]}{match.group(1)}"{build}"{text[match.end() :]}'
        return edited.encode("utf-8")
    wanted = {**json.loads(text), "build": build}
    return (json.dumps(wanted, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def _answers(root: pathlib.Path) -> tuple[str, dict[str, Any]] | None:
    """The answers file's text and its answers, ``None`` without one; refused unreadable."""
    path = root / ANSWERS_FILE
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8")
    try:
        recorded = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise AdoptionRefused(f"{ANSWERS_FILE} cannot be read as YAML ({exc}).") from exc
    if not isinstance(recorded, dict):
        raise AdoptionRefused(f"{ANSWERS_FILE} holds no answers.")
    return text, recorded


def _answer_text(text: str, recorded: dict[str, Any], build: str) -> bytes:
    """The answers file with ``deploy_build`` set to *build*, and nothing else changed."""
    edited = _ANSWER_LINE.sub(f"{ANSWER}: {build}", text, count=1)
    if yaml.safe_load(edited) != {**recorded, ANSWER: build}:
        raise AdoptionRefused(
            f"{ANSWER} in {ANSWERS_FILE} is not written as one plain line, so it cannot be set "
            f"in place: write `{ANSWER}: {build}` there by hand, and run adoption again."
        )
    return edited.encode("utf-8")


def _record_answer(plan: Plan, root: pathlib.Path, build: str, *, required: bool) -> None:
    """Set the template answer to *build*; without the question, refuse or leave it."""
    found = _answers(root)
    if found is None:
        return
    text, recorded = found
    if ANSWER not in recorded:
        if required:
            raise AdoptionRefused(
                f"{ANSWERS_FILE} records no {ANSWER}: this app's scaffolding comes from a "
                "template version that does not ask it, and that version's every `copier "
                "update` renders the build files over the generator's. Run `copier update` "
                f"first (`uv run terp upgrade --check` prints the recipe), which records "
                f"{ANSWER}: own, then adopt again."
            )
        return
    if recorded[ANSWER] != build:
        plan.change(root, ANSWERS_FILE, _answer_text(text, recorded, build))


def _declared(root: pathlib.Path) -> Declaration | Unmanaged | None:
    declared, findings = readable(root)
    if findings:
        raise AdoptionRefused(
            f"{DEPLOYMENT_FILE} cannot be read, so it cannot be rewritten "
            "(`uv run terp verify --only deployment` says the same):\n" + _lines(findings)
        )
    return declared


def plan_generated(root: pathlib.Path) -> Plan:
    """``--build generated``: both facts set, and the build files the generator's."""
    if not (root / DEPLOYMENT_FILE).is_file():
        raise AdoptionRefused(
            f"There is no {DEPLOYMENT_FILE}: declare the app first with `uv run terp "
            "deployment adopt --build own`, review and commit what it writes, then adopt "
            "generated."
        )
    declared = _declared(root)
    if isinstance(declared, Unmanaged):
        raise AdoptionRefused(
            f"{DEPLOYMENT_FILE} declares the app unmanaged ({declared.reason}). Declare it "
            "with `uv run terp deployment adopt --build own` first."
        )
    assert isinstance(declared, Declaration)
    table = published_table()
    if declared.build == "own":
        untrue = truth_findings(root, declared, table)
        if untrue:
            raise AdoptionRefused(
                f"{DEPLOYMENT_FILE} says what its profile does not, and a render of it would "
                "change what is deployed without anyone having declared it "
                "(`uv run terp verify --only deployment`):\n" + _lines(untrue)
            )
    plan = Plan('Adopting "build": "generated" (ADR 0187).', renders=True)
    text = (root / DEPLOYMENT_FILE).read_text(encoding="utf-8")
    after = _declaration_text(text, "generated")
    target, findings = read(json.loads(after), table)
    if findings:
        raise AdoptionRefused(
            f'{DEPLOYMENT_FILE} cannot say "build": "generated" as it stands:\n'
            + _lines(findings)
        )
    assert isinstance(target, Declaration)
    _record_answer(plan, root, "generated", required=True)
    name, missing = project_name(root)
    if name is None:
        raise AdoptionRefused(
            "The generator names the deployment after the project:\n" + _lines(missing)
        )
    files, refused = generate(
        target, name, tables=published_tables(), frontend_lock=(root / FRONTEND_LOCK).is_file()
    )
    if refused:
        raise AdoptionRefused(
            f"The generator cannot render {DEPLOYMENT_FILE} faithfully, so the app stays "
            '"own":\n' + _lines(refused)
        )
    leaking, _notes = ignore_findings(root, target)
    if leaking:
        raise AdoptionRefused(
            "An environment file the units load would reach git or an image:\n" + _lines(leaking)
        )
    plan.change(root, DEPLOYMENT_FILE, after)
    changed, stale = render_changes(root, files)
    for path in changed:
        plan.change(root, path, files[path])
    for path in stale:
        plan.change(root, path, None)
    return plan


def plan_own(root: pathlib.Path) -> Plan:
    """``--build own``: back from generated with no file change, or declared from the profile."""
    path = root / DEPLOYMENT_FILE
    declared = _declared(root) if path.is_file() else None
    if isinstance(declared, Declaration):
        plan = Plan('Adopting "build": "own": the build files are the app\'s from here on.')
        if declared.build != "own":
            plan.change(root, DEPLOYMENT_FILE, _declaration_text(path.read_text("utf-8"), "own"))
        _record_answer(plan, root, "own", required=False)
        return plan
    try:
        found = derive(root, published_table())
    except DeclareRefused as exc:
        raise AdoptionRefused(str(exc)) from exc
    plan = Plan(
        f"Declaring the app from docker-compose.prod.yml, as it runs today (ADR 0184): "
        f'{DEPLOYMENT_FILE} says "build": "own".',
        notes=found.notes,
    )
    plan.change(root, DEPLOYMENT_FILE, (json.dumps(found.raw, indent=2) + "\n").encode("utf-8"))
    if found.profile is not None:
        plan.change(root, "docker-compose.prod.yml", found.profile.encode("utf-8"))
        plan.notes.append(
            "docker-compose.prod.yml now pins each datastore to the datastore table's digest, "
            "which a declared kind unit must run exactly"
        )
    _record_answer(plan, root, "own", required=False)
    return plan


def plan_unmanaged(root: pathlib.Path, reason: str) -> Plan:
    """``--unmanaged "<reason>"``: ADR 0184's opt-out, and the build files the app's."""
    reason = reason.strip()
    raw = {"schemaVersion": 1, "unmanaged": True, "reason": reason}
    _opt_out, findings = read(raw, published_table())
    if findings:
        raise AdoptionRefused("The opt-out cannot carry that reason:\n" + _lines(findings))
    plan = Plan(f"Declaring the app unmanaged (ADR 0184): {reason}")
    plan.change(root, DEPLOYMENT_FILE, (json.dumps(raw, indent=2) + "\n").encode("utf-8"))
    _record_answer(plan, root, "own", required=False)
    return plan


def _diff(path: str, before: bytes | None, after: bytes | None) -> str:
    if after is None:
        return f"removed {path}"
    old = [] if before is None else before.decode("utf-8", "replace").splitlines(keepends=True)
    new = after.decode("utf-8", "replace").splitlines(keepends=True)
    return "".join(
        difflib.unified_diff(
            old, new, "/dev/null" if before is None else f"a/{path}", f"b/{path}", n=1
        )
    ).rstrip("\n")


def _report(plan: Plan) -> list[str]:
    lines = [plan.headline, ""]
    lines.extend(_diff(path, *plan.changes[path]) for path in sorted(plan.changes))
    built = [path for path in OWNED_PATHS if path in plan.changes]
    lines.append("")
    lines.append(
        f"Build files changed: {', '.join(built)}."
        if built
        else "No build file changed: "
        + ", ".join(OWNED_PATHS)
        + " stay byte for byte as they are."
    )
    lines.extend(f"note: {note}" for note in plan.notes)
    return lines


def run_adopt_command(
    *,
    root: str | pathlib.Path = ".",
    build: str | None = None,
    unmanaged: str | None = None,
    dry_run: bool = False,
) -> int:
    """``terp deployment adopt``: the exit code; the diff and what was written are printed."""
    project_root = pathlib.Path(root)
    try:
        if unmanaged is not None:
            plan = plan_unmanaged(project_root, unmanaged)
        elif build == "generated":
            plan = plan_generated(project_root)
        else:
            plan = plan_own(project_root)
    except AdoptionRefused as exc:
        emit(f"Nothing was written. {exc}")
        return 1
    if not plan.changes:
        emit(plan.headline)
        emit("Nothing to write: the app is in that state already.")
        return 0
    emit("\n".join(_report(plan)))
    if dry_run:
        emit("\nNothing was written (--dry-run).")
        return 0
    write_files(
        project_root,
        {path: after for path, (_before, after) in plan.changes.items() if after is not None},
        [path for path, (_before, after) in plan.changes.items() if after is None],
    )
    emit(f"\nWrote {', '.join(sorted(plan.changes))}. Commit them together.")
    if plan.renders:
        emit(
            "From here on change deployment.json and run "
            f"`{RENDER_COMMAND}`; `copier update` leaves the build files to it."
        )
        after = generated(project_root)
        if after.drift.findings:
            emit(
                "\nstill red under `terp verify --only generated`:\n"
                + _lines(after.drift.findings)
            )
            return 1
    return 0


__all__ = [
    "AdoptionRefused",
    "Plan",
    "plan_generated",
    "plan_own",
    "plan_unmanaged",
    "run_adopt_command",
]
