"""Template acceptance's build-state round trip: copier and ``terp deployment adopt``, both ways.

ADR 0187 decision 4 rests on how copier treats a recorded answer: an update renders the old
template version with the RECORDED answers, so with ``deploy_build: generated`` recorded the
three production build files read as the app's own and are left alone, a generator path the
app removed is not created again, and after adopting back to ``own`` the next update merges
the last render as the app's edits. This runs that, for real, against a copy of
``template/`` committed as a template repository of four revisions:

* ``v0`` -- the template as it was before it asked ``deploy_build``;
* ``v1`` -- the template as it is;
* ``v2`` and ``v3`` -- ``v1`` with a line added to each of the three build files and to the
  README, each time, standing in for a later framework release that changes them.

Three apps then go through it, and every step says exactly which files it changes:

1. **own, generated, own.** Copy ``v1`` with ``own``; adopt ``generated`` (only
   ``deployment.json`` and the answers file change, no build file); update to ``v1`` again
   (nothing); drop the web unit and render (``frontend/Dockerfile.prod`` goes); update to
   ``v2`` (the README and the answers, no build file, and the removed file stays removed);
   restore the web unit and render; adopt back to ``own`` (no build file); update to ``v3``
   (each build file takes ``v3``'s line and not ``v2``'s: the last render is merged as an
   own app's edit).
2. **A generated copy.** Copy ``v1`` with ``generated``: no build file until ``terp
   deployment render``, which writes the template's own, byte for byte.
3. **Scaffolding that predates the question.** Copy ``v0``; ``adopt --build generated`` is
   refused and writes nothing; update to ``v1``, which records ``deploy_build: own``; adopt
   again, and no build file changes.

Usage::

    python tools/copier_round_trip.py                 # uvx copier, this checkout's terp
    python tools/copier_round_trip.py --copier copier --work DIR

Needs copier, git and this repository's environment (``uv run``), nothing else.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import shlex
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Sequence

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
TEMPLATE = REPO_ROOT / "template"

#: The three files the generator owns (``terp.arch.deployment.generator.OWNED_PATHS``).
BUILD_FILES = ("Dockerfile.prod", "frontend/Dockerfile.prod", "docker-compose.prod.yml")
ANSWERS = ".copier-answers.yml"
DECLARATION = "deployment.json"
#: The lock a web unit is built from, which `npm install` writes and the template does not.
LOCK = "frontend/package-lock.json"

#: What each later revision adds, so a merge can be told apart from a re-render.
MARKERS = {
    "v2": "# round trip: a later release changed this file (v2)",
    "v3": "# round trip: a later release changed this file again (v3)",
}

#: This checkout's ``terp``, run by the interpreter running this script.
TERP = (sys.executable, "-c", "import sys; from terp.cli import main; main(sys.argv[1:])")

#: Git as every step runs it: no line-ending conversion, no identity from the machine.
GIT_ENV = {
    "GIT_CONFIG_COUNT": "1",
    "GIT_CONFIG_KEY_0": "core.autocrlf",
    "GIT_CONFIG_VALUE_0": "false",
    "GIT_AUTHOR_NAME": "round trip",
    "GIT_AUTHOR_EMAIL": "round-trip@example.invalid",
    "GIT_COMMITTER_NAME": "round trip",
    "GIT_COMMITTER_EMAIL": "round-trip@example.invalid",
}

Runner = Callable[..., subprocess.CompletedProcess[str]]


class RoundTripError(RuntimeError):
    """A step did not do what ADR 0187 says it does; the message says which, and how."""


def require(holds: bool, message: str) -> None:
    """Every check of the round trip: a step that did not do what ADR 0187 says stops it."""
    if not holds:
        raise RoundTripError(message)


class Trip:
    """The tools one round trip drives, and the one way it runs each."""

    def __init__(
        self, work: pathlib.Path, copier: Sequence[str], terp: Sequence[str], run: Runner
    ) -> None:
        self.work = work
        self.copier = list(copier)
        self.terp = list(terp)
        self._run = run
        self.env = {**os.environ, **GIT_ENV}

    def run(self, argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
        return self._run(list(argv), env=self.env, capture_output=True, text=True, check=False)

    def must(self, argv: Sequence[str]) -> str:
        done = self.run(argv)
        require(
            done.returncode == 0,
            f"`{shlex.join(argv)}` exited {done.returncode}:\n{done.stdout}{done.stderr}",
        )
        return done.stdout

    def git(self, root: pathlib.Path, *args: str) -> str:
        return self.must(["git", "-C", str(root), *args])

    def commit(self, root: pathlib.Path, message: str) -> None:
        self.git(root, "add", "-A")
        self.git(root, "commit", "-q", "--allow-empty", "-m", message)

    def changed(self, root: pathlib.Path) -> set[str]:
        out = self.git(root, "status", "--porcelain", "--untracked-files=all", "--no-renames")
        return {line[3:].strip().strip('"') for line in out.splitlines() if line.strip()}

    def copy(self, ref: str, dest: pathlib.Path, *data: str) -> None:
        extra = [arg for item in data for arg in ("--data", item)]
        self.must(
            [*self.copier, "copy", "--defaults", "--trust", "--vcs-ref", ref, *extra,
             str(self.work / "tpl"), str(dest)]
        )
        (dest / LOCK).write_text("{}\n", encoding="utf-8")
        self.git(dest, "init", "-q")
        self.commit(dest, f"render {ref}")

    def update(self, root: pathlib.Path, ref: str) -> None:
        self.must([*self.copier, "update", "--defaults", "--trust", "--vcs-ref", ref, str(root)])

    def adopt(self, root: pathlib.Path, build: str, *, refused: bool = False) -> str:
        argv = [*self.terp, "deployment", "adopt", "--build", build, "--root", str(root)]
        if not refused:
            return self.must(argv)
        done = self.run(argv)
        require(done.returncode != 0, f"`{shlex.join(argv)}` was not refused:\n{done.stdout}")
        return done.stdout

    def render(self, root: pathlib.Path, *check: str) -> None:
        self.must([*self.terp, "deployment", "render", "--root", str(root), *check])


def expect(trip: Trip, root: pathlib.Path, step: str, files: set[str]) -> None:
    """The step changed exactly *files*; commit them, so the next step starts clean."""
    changed = trip.changed(root)
    require(
        changed == files,
        f"{step}: changed {sorted(changed) or 'nothing'}, where ADR 0187 says "
        f"{sorted(files) or 'nothing'} (unexpected: {sorted(changed - files) or 'none'}; "
        f"missing: {sorted(files - changed) or 'none'})",
    )
    trip.commit(root, step)


def snapshot(root: pathlib.Path) -> dict[str, bytes | None]:
    """The build files' bytes, ``None`` for one that is absent."""
    return {
        path: (root / path).read_bytes() if (root / path).is_file() else None
        for path in BUILD_FILES
    }


def same_build(root: pathlib.Path, step: str, before: dict[str, bytes | None]) -> None:
    now = snapshot(root)
    moved = [path for path in BUILD_FILES if now[path] != before[path]]
    require(not moved, f"{step}: build files changed where ADR 0187 says none does: {moved}")


def answer(root: pathlib.Path) -> str | None:
    for line in (root / ANSWERS).read_text(encoding="utf-8").splitlines():
        if line.startswith("deploy_build:"):
            return line.split(":", 1)[1].strip()
    return None


def build(root: pathlib.Path) -> str:
    return json.loads((root / DECLARATION).read_text(encoding="utf-8"))["build"]


def state(root: pathlib.Path, step: str, wanted: str | None, declared: str) -> None:
    found = (answer(root), build(root))
    require(
        found == (wanted, declared),
        f"{step}: deploy_build is {found[0]!r} and build {found[1]!r}, where "
        f"{wanted!r} and {declared!r} are expected",
    )


# --- the template repository ------------------------------------------------------------


def _before_the_question(tpl: pathlib.Path) -> None:
    """Make *tpl* the template as it was before it asked ``deploy_build``."""
    import yaml  # noqa: PLC0415 - only this step reads YAML

    config = yaml.safe_load((tpl / "copier.yml").read_text(encoding="utf-8"))
    require("deploy_build" in config, "template/copier.yml no longer asks deploy_build")
    del config["deploy_build"]
    config["_exclude"] = [item for item in config["_exclude"] if "deploy_build" not in item]
    (tpl / "copier.yml").write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    seed = tpl / "project" / f"{DECLARATION}.jinja"
    text = seed.read_text(encoding="utf-8")
    require(
        "{{ deploy_build }}" in text, "the seed declaration no longer takes build from deploy_build"
    )
    seed.unlink()
    (tpl / "project" / DECLARATION).write_text(
        text.replace("{{ deploy_build }}", "own"), encoding="utf-8"
    )


#: Where each build file lives in the template: the profile is a ``.jinja`` for its slug.
SOURCES = {
    "Dockerfile.prod": "Dockerfile.prod",
    "frontend/Dockerfile.prod": "frontend/Dockerfile.prod",
    "docker-compose.prod.yml": "docker-compose.prod.yml.jinja",
}


def _later_release(tpl: pathlib.Path, ref: str) -> None:
    """A release that changes each build file and the README, each by one comment line."""
    marker = MARKERS[ref] + "\n"
    for source in SOURCES.values():
        path = tpl / "project" / source
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        # v2 appends; v3 writes four lines down, far from v2's, so the two never touch.
        at = len(lines) if ref == "v2" else 4
        path.write_text("".join([*lines[:at], marker, *lines[at:]]), encoding="utf-8")
    readme = tpl / "project" / "README.md.jinja"
    readme.write_text(readme.read_text(encoding="utf-8") + "\n" + marker, encoding="utf-8")


def template_repository(trip: Trip) -> pathlib.Path:
    """``template/`` as a repository tagged ``v0`` to ``v3``."""
    tpl = trip.work / "tpl"
    shutil.copytree(TEMPLATE, tpl, ignore=shutil.ignore_patterns("__pycache__", "node_modules"))
    config = (tpl / "copier.yml").read_bytes()
    seed = (tpl / "project" / f"{DECLARATION}.jinja").read_bytes()
    trip.git(tpl, "init", "-q")
    _before_the_question(tpl)
    trip.commit(tpl, "v0: before the question")
    trip.git(tpl, "tag", "v0")
    (tpl / "copier.yml").write_bytes(config)
    (tpl / "project" / DECLARATION).unlink()
    (tpl / "project" / f"{DECLARATION}.jinja").write_bytes(seed)
    trip.commit(tpl, "v1: the template")
    trip.git(tpl, "tag", "v1")
    for ref in ("v2", "v3"):
        _later_release(tpl, ref)
        trip.commit(tpl, f"{ref}: a later release")
        trip.git(tpl, "tag", ref)
    return tpl


# --- the three apps -----------------------------------------------------------------------


def own_generated_own(trip: Trip) -> tuple[list[str], dict[str, bytes | None]]:
    """The first app; also what ``copy v1`` rendered, which every other app is held to."""
    app = trip.work / "own-generated-own"
    done: list[str] = []
    trip.copy("v1", app)
    state(app, "copy v1", "own", "own")
    rendered = snapshot(app)
    missing = [path for path, data in rendered.items() if data is None]
    require(not missing, f"copy v1 with own rendered no {missing}")

    trip.adopt(app, "generated")
    same_build(app, "adopt --build generated", rendered)
    state(app, "adopt --build generated", "generated", "generated")
    expect(trip, app, "adopt --build generated", {ANSWERS, DECLARATION})
    trip.render(app, "--check")
    done.append("adopt --build generated: deployment.json and the answers file, no build file")

    trip.update(app, "v1")
    expect(trip, app, "update to v1 again", set())
    done.append("copier update to the same revision: nothing")

    declared = (app / DECLARATION).read_text(encoding="utf-8")
    document = json.loads(declared)
    document["units"] = [unit for unit in document["units"] if unit["role"] != "web"]
    (app / DECLARATION).write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    trip.render(app)
    expect(trip, app, "drop the web unit and render",
           {DECLARATION, "frontend/Dockerfile.prod", "docker-compose.prod.yml"})

    trip.update(app, "v2")
    without_web = snapshot(app)
    expect(trip, app, "update to v2 (generated)", {"README.md", ANSWERS})
    same_build(app, "update to v2 (generated)", without_web)
    trip.render(app, "--check")
    done.append(
        "copier update to v2 under generated: the README and the answers file; no build "
        "file, and the removed frontend/Dockerfile.prod is not created again"
    )

    (app / DECLARATION).write_text(declared, encoding="utf-8")
    trip.render(app)
    expect(trip, app, "restore the web unit and render",
           {DECLARATION, "frontend/Dockerfile.prod", "docker-compose.prod.yml"})
    same_build(app, "restore the web unit and render", rendered)

    trip.adopt(app, "own")
    same_build(app, "adopt --build own", rendered)
    state(app, "adopt --build own", "own", "own")
    expect(trip, app, "adopt --build own", {ANSWERS, DECLARATION})
    done.append("adopt --build own: deployment.json and the answers file, no build file")

    trip.update(app, "v3")
    expect(trip, app, "update to v3 (own)", {"README.md", ANSWERS, *BUILD_FILES})
    for path in BUILD_FILES:
        text = (app / path).read_text(encoding="utf-8")
        require(
            MARKERS["v3"] in text and MARKERS["v2"] not in text,
            f"update to v3 (own): {path} should take v3's line and keep v2's out, the last "
            "render merged as the app's own edit",
        )
        merged = (rendered[path] or b"").decode("utf-8").splitlines(keepends=True)
        merged.insert(4, MARKERS["v3"] + "\n")
        require(
            text == "".join(merged),
            f"update to v3 (own): {path} is not the last render with v3's line merged in",
        )
    done.append(
        "copier update to v3 under own: each build file is the last render with v3's change "
        "merged in, and v2's left out"
    )
    return done, rendered


def generated_copy(trip: Trip, rendered: dict[str, bytes | None]) -> list[str]:
    app = trip.work / "generated-copy"
    trip.copy("v1", app, "deploy_build=generated")
    state(app, "copy v1 with generated", "generated", "generated")
    require(
        all(data is None for data in snapshot(app).values()),
        "copy v1 with generated rendered a build file the generator owns",
    )
    trip.render(app)
    expect(trip, app, "render a generated copy", set(BUILD_FILES))
    same_build(app, "render a generated copy", rendered)
    trip.render(app, "--check")
    return [
        "a generated copy has no build file until terp deployment render writes the "
        "template's, byte for byte"
    ]


def before_the_question(trip: Trip) -> list[str]:
    app = trip.work / "before-the-question"
    trip.copy("v0", app)
    require(answer(app) is None, "copy v0 recorded deploy_build, which v0 does not ask")
    rendered = snapshot(app)
    refused = trip.adopt(app, "generated", refused=True)
    require(
        "records no deploy_build" in refused,
        "adopt --build generated on scaffolding that predates the question was refused for "
        f"another reason:\n{refused}",
    )
    expect(trip, app, "adopt refused before the question", set())
    trip.update(app, "v1")
    state(app, "update v0 to v1", "own", "own")
    expect(trip, app, "update v0 to v1", {ANSWERS})
    same_build(app, "update v0 to v1", rendered)
    trip.adopt(app, "generated")
    expect(trip, app, "adopt after the update", {ANSWERS, DECLARATION})
    same_build(app, "adopt after the update", rendered)
    return [
        "scaffolding that predates the question: adopt is refused and writes nothing; "
        "copier update records deploy_build: own; adopt then changes no build file"
    ]


def round_trip(trip: Trip) -> list[str]:
    template_repository(trip)
    done, rendered = own_generated_own(trip)
    return [*done, *generated_copy(trip, rendered), *before_the_question(trip)]


def main(argv: Sequence[str] | None = None, *, run: Runner = subprocess.run) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--copier", default="uvx copier", help="How to run copier")
    parser.add_argument(
        "--terp", help="How to run terp (default: this checkout's, by this interpreter)"
    )
    parser.add_argument("--work", type=pathlib.Path, help="An empty directory to work in")
    args = parser.parse_args(argv)
    # Resolved: copier compares the app's path with git's, which a short Windows name fails.
    work = (args.work or pathlib.Path(tempfile.mkdtemp(prefix="terp-round-trip-"))).resolve()
    terp = TERP if args.terp is None else tuple(shlex.split(args.terp))
    trip = Trip(work, shlex.split(args.copier), terp, run)
    try:
        done = round_trip(trip)
    except RoundTripError as exc:
        print(f"copier_round_trip: {exc}", file=sys.stderr)
        return 1
    for line in done:
        print(f"ok  {line}")
    return 0


if __name__ == "__main__":  # pragma: no cover - entry point
    raise SystemExit(main())
