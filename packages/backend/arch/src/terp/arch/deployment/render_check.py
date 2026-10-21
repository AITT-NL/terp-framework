"""The generated state's check: a committed copy that is not the render is refused (ADR 0187).

Where ``deployment.json`` says ``"build": "generated"`` the three production build files are
the generator's, and a person or an agent changes them by changing the declaration, the
project name or the framework version, then rendering again. This module asks, from files
alone and without importing the app, whether what is committed is what that render gives:

* the declaration must render - the generator's refusal, word for word, is the finding;
* every generator-owned file must be the render byte for byte (a short diff, and the fix),
  and a generator-owned path the render does not produce must be absent;
* the environment files a unit loads (``.env``, ``.app.env``, each backend unit's
  ``.app.<id>.env``) must be ignored by git, asked of ``git check-ignore``, and left out of
  the build context, asked of a matcher with Docker's own semantics
  (:mod:`terp.arch.deployment.dockerignore`). In a tree that lies in no git work tree the git
  half is noted, not judged; a pattern either cannot read is a finding, never a crash;
* the build the app's template answers record (``deploy_build`` in ``.copier-answers.yml``)
  must agree with the declaration's, which is silent for an app with no answers file and
  noted for answers that predate the question.

It also notes, never red, a profile ``terp release`` will refuse under ADR 0184 decision 9:
no migration step and other than exactly one ``api`` unit. Everything else - an undeclared
app, ``own``, ``unmanaged``, a declaration that cannot be read - is not its business, and the
caller (:func:`terp.arch.deployment.generated`) never reaches it for those.
"""

from __future__ import annotations

import difflib
import pathlib
import shutil
import subprocess
import tomllib
from dataclasses import dataclass, field

import yaml

from terp.arch.deployment import dockerignore
from terp.arch.deployment._refusals import _backend_ids
from terp.arch.deployment.generator import (
    BACKEND_DOCKERFILE,
    FRONTEND_DOCKERFILE,
    FRONTEND_LOCK,
    OWNED_PATHS,
    generate,
)
from terp.arch.deployment.reader import DEPLOYMENT_FILE, Declaration, Finding
from terp.arch.deployment.tables import Tables

#: The template's answers file, and the question that records the build state in it.
ANSWERS_FILE = ".copier-answers.yml"
ANSWER = "deploy_build"

#: The fix every drift names.
RENDER_COMMAND = "uv run terp deployment render"

#: How many lines of a drift's diff a finding quotes.
_DIFF_LINES = 12

#: Why a generator-owned path is rendered, for the message about one that should not exist.
_WHY_RENDERED = {
    BACKEND_DOCKERFILE: "no unit runs the backend image",
    FRONTEND_DOCKERFILE: "no web unit is declared",
}


@dataclass
class Drift:
    """What the check found for one generated declaration."""

    findings: list[Finding] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    #: The render, path to bytes; empty when the generator refuses.
    files: dict[str, bytes] = field(default_factory=dict)


def project_name(project_root: pathlib.Path) -> tuple[str | None, list[Finding]]:
    """``[project].name`` from ``pyproject.toml``, used verbatim, or why there is none."""
    path = project_root / "pyproject.toml"
    if not path.is_file():
        return None, [
            Finding(
                "pyproject.toml is missing, and the generator names the compose project and "
                "the images after its project.name (allowed: a pyproject.toml with a "
                "[project] name)",
                file="pyproject.toml",
            )
        ]
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        return None, [
            Finding(f"pyproject.toml cannot be read as TOML ({exc})", file="pyproject.toml")
        ]
    project = data.get("project")
    name = project.get("name") if isinstance(project, dict) else None
    if not isinstance(name, str) or not name:
        return None, [
            Finding(
                "pyproject.toml declares no project.name, and the generator names the compose "
                "project and the images after it (allowed: a [project] name)",
                file="pyproject.toml",
            )
        ]
    return name, []


def _text(data: bytes) -> list[str]:
    return data.decode("utf-8", errors="replace").splitlines(keepends=True)


def _drift(project_root: pathlib.Path, files: dict[str, bytes]) -> list[Finding]:
    """Every generator-owned path that is not what the render says it is."""
    found: list[Finding] = []
    remedy = f"Run `{RENDER_COMMAND}` and commit what it writes, together with deployment.json."
    for path in OWNED_PATHS:
        committed = project_root / path
        if path not in files:
            if committed.exists():
                found.append(
                    Finding(
                        f"{path} exists, and deployment.json renders nothing for it: "
                        f"{_WHY_RENDERED[path]} (allowed: no file)",
                        remedy,
                        path,
                    )
                )
            continue
        if not committed.is_file():
            found.append(
                Finding(
                    f"{path} is missing, and deployment.json renders it (allowed: the "
                    "generator's render)",
                    remedy,
                    path,
                )
            )
            continue
        current = committed.read_bytes()
        if current == files[path]:
            continue
        diff = list(
            difflib.unified_diff(
                _text(current), _text(files[path]), f"{path} (committed)", f"{path} (render)", n=1
            )
        )
        shown = "".join(diff[:_DIFF_LINES]).rstrip("\n") or "(the bytes differ: line endings)"
        found.append(
            Finding(
                f"{path} is not the render of deployment.json (allowed: the generator's "
                f"render, never an edit of the file):\n{shown}",
                remedy,
                path,
            )
        )
    return found


def _loaded_env_files(declaration: Declaration) -> list[str]:
    return [".env", ".app.env", *(f".app.{ident}.env" for ident in _backend_ids(declaration))]


def _docker_half(project_root: pathlib.Path, names: list[str]) -> list[Finding]:
    path = project_root / ".dockerignore"
    text = path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""
    patterns, unreadable = dockerignore.parse(text)
    found = [
        Finding(
            f".dockerignore line {bad.line} {bad.text!r} cannot be read: {bad.reason} "
            "(allowed: a pattern Docker's matcher reads)",
            "Docker refuses a build over a pattern it cannot read; fix or remove the line.",
            ".dockerignore",
        )
        for bad in unreadable
    ]
    leaking = [name for name in names if not dockerignore.excluded(name, patterns)]
    if leaking:
        found.append(
            Finding(
                f".dockerignore lets {', '.join(leaking)} into the build context, and the "
                "units deployment.json declares load them, so a `COPY . .` bakes them into "
                "an image layer (allowed: patterns that leave .env, .app.env and each backend "
                "unit's .app.<id>.env out of the build context, such as **/.env and "
                "**/.app.*.env)",
                "Add the patterns to .dockerignore; the template's own carries them.",
                ".dockerignore",
            )
        )
    return found


def _git(git: str, project_root: pathlib.Path, *args: str) -> subprocess.CompletedProcess[str]:
    # Read-only, fixed argv, no shell: git's own answers about its own work tree.
    return subprocess.run(  # noqa: S603
        [git, "-C", str(project_root), *args], capture_output=True, text=True, check=False
    )


def _git_half(project_root: pathlib.Path, names: list[str]) -> tuple[list[Finding], list[str]]:
    git = shutil.which("git")
    if git is None:
        return [], ["the git half of the environment-file check is not judged: git is not on PATH"]
    # Whether there is a work tree is git's question too: a `.git` that git cannot read is
    # no work tree, and its ignore rules are no answer.
    inside = _git(git, project_root, "rev-parse", "--is-inside-work-tree")
    if inside.returncode != 0 or inside.stdout.strip() != "true":
        return [], [
            "the git half of the environment-file check is not judged: the project lies in "
            "no git work tree"
        ]
    found: list[Finding] = []
    tracked: list[str] = []
    for name in names:
        answer = _git(git, project_root, "check-ignore", "--no-index", "-q", "--", name)
        if answer.returncode == 1:
            tracked.append(name)
        elif answer.returncode != 0:
            found.append(
                Finding(
                    f"git check-ignore cannot read the ignore rules for {name}: "
                    f"{answer.stderr.strip() or answer.returncode} (allowed: ignore rules git reads)",
                    file=".gitignore",
                )
            )
    if tracked:
        found.append(
            Finding(
                f"git does not ignore {', '.join(tracked)}, and the units deployment.json "
                "declares load them, so a commit can carry them (allowed: .gitignore patterns "
                "that cover .env, .app.env and each backend unit's .app.<id>.env)",
                "Add the patterns to .gitignore; the template's own carries them.",
                ".gitignore",
            )
        )
    return found, []


def _answers(project_root: pathlib.Path) -> tuple[list[Finding], list[str]]:
    path = project_root / ANSWERS_FILE
    if not path.is_file():
        return [], []
    try:
        answers = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        return [
            Finding(f"{ANSWERS_FILE} cannot be read as YAML ({exc})", file=ANSWERS_FILE)
        ], []
    if not isinstance(answers, dict) or ANSWER not in answers:
        return [], [
            f"{ANSWERS_FILE} records no {ANSWER}: the template version it was rendered from "
            "does not ask, so the build it records is not compared"
        ]
    if answers[ANSWER] == "generated":
        return [], []
    return [
        Finding(
            f'{ANSWER} is {answers[ANSWER]!r} in {ANSWERS_FILE}, and deployment.json says '
            '"build": "generated" (allowed: generated, the build deployment.json declares)',
            "The next `copier update` reads the answer and would render the template's own "
            "build files over the generator's. Record one state in both files.",
            ANSWERS_FILE,
        )
    ], []


def release_note(declaration: Declaration) -> list[str]:
    """``terp release`` refuses a profile with no migration step and other than one api."""
    steps = [
        unit for unit in declaration.units
        if unit.kind is None and unit.role == "one-shot" and unit.command is None
    ]
    apis = [unit for unit in declaration.units if unit.kind is None and unit.role == "api"]
    if steps or len(apis) == 1:
        return []
    return [
        f"terp release will refuse this profile (ADR 0184 decision 9): it has no migration step "
        f"and {len(apis)} api units, so no one image runs the upgrade"
    ]


def check(project_root: pathlib.Path, declaration: Declaration, tables: Tables) -> Drift:
    """Everything this check finds for a generated *declaration* under *project_root*."""
    drift = Drift()
    name, missing = project_name(project_root)
    if name is None:
        drift.findings.extend(missing)
    else:
        files, refused = generate(
            declaration,
            name,
            tables=tables,
            frontend_lock=(project_root / FRONTEND_LOCK).is_file(),
        )
        drift.files = files
        drift.findings.extend(refused if refused else _drift(project_root, files))
    names = _loaded_env_files(declaration)
    drift.findings.extend(_docker_half(project_root, names))
    git_findings, git_notes = _git_half(project_root, names)
    answer_findings, answer_notes = _answers(project_root)
    drift.findings.extend([*git_findings, *answer_findings])
    drift.notes.extend([*git_notes, *answer_notes, *release_note(declaration)])
    return drift


__all__ = ["ANSWER", "ANSWERS_FILE", "DEPLOYMENT_FILE", "Drift", "RENDER_COMMAND", "check"]
