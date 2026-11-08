"""``terp verify --only locks`` — are the committed locks the ones the images can install?

The template's production images install exactly the committed locks: the backend image
runs ``uv sync --locked --no-dev``, the web image ``npm ci`` over ``frontend/``, and a static
site's image ``npm ci`` over ``site/`` (ADR 0062, amended; ADR 0198). Each refuses a lock that
is missing or that no longer answers its manifest, so a dependency added to
``pyproject.toml`` or a ``package.json`` without re-locking is an image that cannot be built,
and the first anyone hears of it is a deploy. This check says it on the gate, naming the
file and the command that fixes it. The npm locks it asks about are the ones a release reads:
the generator's two (:data:`terp.cli.release._locks.NPM_LOCKS`) where their ``package.json`` is,
and every lock a web image is built from by the release plan's own rule
(:func:`terp.cli.release._plan.web_npm_locks`), such as an own app's ``www/package-lock.json``.

Whether a lock answers its manifest is the package manager's question, and each is asked
it in its own words rather than through a second reading of its file format: ``uv lock
--check`` (offline: a lock that matches is checked without the network, and one that does
not is refused either way) and ``npm ci --dry-run`` (offline, no scripts, no change to
``node_modules``), the very install the web image runs.

It refuses only a **managed** app: one whose ``deployment.json`` declares units for a
deploy tool to build (ADR 0184), because that tool builds the committed Dockerfiles from
the committed locks. An app with no declaration, or one that declares itself
``unmanaged``, is told the same facts as a note and never turned red: its deploy is its
own business, and an upgrade must not redden a gate over a file the app has not adopted.
A ``deployment.json`` that cannot be read is held as managed, since only a file that
reads as ``unmanaged`` says otherwise.

It is its own check rather than part of ``--only deployment``. That one is a
truth-about-self check whose red list ADR 0184 closes (a file that cannot be read, a
field under an unknown role, a claim the profile or the app contradicts); a stale lock
contradicts nothing the declaration says. Its inputs are the manifests and the locks,
not the profile and the source, and its fix is a command, not an edit to the file.
"""

from __future__ import annotations

import pathlib
from dataclasses import dataclass

from terp.cli.release._locks import NPM_LOCKS, npm_manifest, npm_workspace

#: How many trailing lines of the package manager's own answer a refusal quotes.
_TOOL_LINES = 8


@dataclass(frozen=True)
class Lock:
    """One committed lock, the manifest it answers, and how its tool checks the pair."""

    manifest: str
    lock: str
    #: Exits 0 exactly when the lock still answers the manifest; changes nothing.
    check: tuple[str, ...]
    #: What the production image runs over it.
    install: str
    #: The command that writes it again from the manifest.
    fix: str


def _npm(npm_lock: str) -> Lock:
    """The check of *npm_lock*: ``npm ci``'s own answer in the workspace it lies in, offline."""
    workspace = npm_workspace(npm_lock)
    return Lock(
        manifest=npm_manifest(npm_lock),
        lock=npm_lock,
        check=(
            "npm",
            "--prefix",
            workspace,
            "ci",
            "--dry-run",
            "--offline",
            "--ignore-scripts",
            "--no-audit",
            "--no-fund",
        ),
        install="npm ci",
        fix=f"npm --prefix {workspace} install",
    )


#: The backend's lock, then the generator's two npm locks: each held only where its manifest
#: exists. :func:`held` adds the lock of every web image the release plan builds.
LOCKS: tuple[Lock, ...] = (
    Lock(
        manifest="pyproject.toml",
        lock="uv.lock",
        check=("uv", "lock", "--check", "--offline"),
        install="uv sync --locked --no-dev",
        fix="uv lock",
    ),
    *(_npm(npm_lock) for npm_lock in NPM_LOCKS),
)


def held(project_root: pathlib.Path) -> list[Lock]:
    """Every lock the production images install: :data:`LOCKS` where its manifest is, then the
    lock of each web image the release plan builds, which its image installs whether or not the
    manifest beside it is there."""
    from terp.arch.deployment import published_table
    from terp.cli.release._plan import web_npm_locks

    present = [lock for lock in LOCKS if (project_root / lock.manifest).is_file()]
    known = {lock.lock for lock in present}
    planned = web_npm_locks(project_root, published_table())
    return present + [_npm(npm_lock) for npm_lock in planned if npm_lock not in known]


def _managed(project_root: pathlib.Path) -> str | None:
    """Why the app is NOT held to its locks, or None when it is (a managed app)."""
    from terp.arch.deployment import DEPLOYMENT_FILE, Unmanaged, published_table, readable

    if not (project_root / DEPLOYMENT_FILE).is_file():
        return f"no {DEPLOYMENT_FILE}: no deploy tool builds this app from its locks"
    declared, findings = readable(project_root, published_table())
    if not findings and isinstance(declared, Unmanaged):
        return f"{DEPLOYMENT_FILE} declares this app unmanaged: {declared.reason}"
    return None


def _tail(output: str) -> list[str]:
    lines = [line for line in output.splitlines() if line.strip()]
    return [f"    {line}" for line in lines[-_TOOL_LINES:]]


def _problem(project_root: pathlib.Path, lock: Lock) -> list[str]:
    """What is wrong with *lock*, as message lines, or [] when it answers its manifest.

    Only asked about a lock whose manifest exists: no manifest, nothing to lock.
    """
    from terp.cli.verify import _NOT_FOUND, _run_argv

    then =f"Fix: {lock.fix}, then commit {lock.lock}."
    if not (project_root / lock.lock).is_file():
        return [
            f"- {lock.lock} is missing. The production image installs exactly it "
            f"(`{lock.install}`), so the image cannot be built.",
            f"  {then}",
        ]
    completed = _run_argv(list(lock.check), project_root)
    if completed.returncode == 0:
        return []
    command = " ".join(lock.check)
    output = completed.stdout + completed.stderr
    if completed.returncode == _NOT_FOUND:
        return [
            f"- {lock.check[0]} is not on PATH, so whether {lock.lock} answers "
            f"{lock.manifest} cannot be established.",
            f"  Install {lock.check[0]} where the gate runs, or run `{command}` yourself.",
        ]
    return [
        f"- {lock.lock} is stale against {lock.manifest}: `{command}` refuses it, and the "
        f"image's `{lock.install}` would stop at the same point.",
        f"  {then}",
        f"  {lock.check[0]} said:",
        *_tail(output),
    ]


def run_locks_check(project_root: pathlib.Path) -> tuple[int, str]:
    """The ``locks`` verify runner: ``(exit_code, output)``."""
    from terp.cli.verify import NOTE_PREFIX

    present = held(project_root)
    if not present:
        manifests = [lock.manifest for lock in LOCKS]
        return 0, f"no {', '.join(manifests[:-1])} or {manifests[-1]} - nothing is locked here"
    exempt = _managed(project_root)
    problems = [line for lock in present for line in _problem(project_root, lock)]
    if not problems:
        answered = ", ".join(f"{lock.lock} answers {lock.manifest}" for lock in present)
        return 0, f"{answered}: the locks the production images install"
    if exempt is None:
        return 1, "\n".join(
            [
                "A lock the production images install is missing or stale.",
                "",
                "deployment.json declares units a deploy tool builds from the committed",
                "Dockerfiles, and they install exactly the committed locks, so each line",
                "below is an image that cannot be built.",
                "",
                *problems,
            ]
        )
    return 0, "\n".join(
        [
            f"{NOTE_PREFIX}a lock the production images install is missing or stale "
            f"(never red here: {exempt})",
            *problems,
        ]
    )
