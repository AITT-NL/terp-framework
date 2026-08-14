"""``terp routes`` — regenerate the app's route types from its module manifests.

The frontend's router is built at runtime from manifest data, so nothing checks a route
path or a param name (ADR 0092). This command runs the frontend's ``routes`` script —
``terp-routes`` from ``@terpjs/contract`` — which extracts the manifests' route literals
and writes the committed ``frontend/src/routes.gen.d.ts`` that makes a wrong path or
param name a typecheck error.

It is the routes half of the same generate-commit-gate shape ``terp openapi`` has for the
typed client: regenerate after changing a manifest route, commit the artifact, and let
``terp verify`` (the ``routes-drift`` check, ``--check`` mode) refuse a stale copy.
"""

from __future__ import annotations

import json
import pathlib
import shutil
import subprocess

#: The frontend package.json script the generator is wired to (the template ships it).
ROUTES_SCRIPT = "routes"

#: What an app that predates route types must add to opt in.
ADOPT_HINT = (
    'add "routes": "terp-routes" to frontend/package.json, run it, and commit '
    "frontend/src/routes.gen.d.ts to turn on route-type checking (ADR 0092)"
)


def routes_argv(frontend_dir: str = "frontend", *, check: bool = False) -> list[str]:
    """The exact argv this command runs — the same shape the verify check advertises."""
    argv = ["npm", "--prefix", frontend_dir, "run", ROUTES_SCRIPT]
    if check:
        # `npm run <script> -- --check` forwards the flag to the generator.
        argv += ["--", "--check"]
    return argv


def routes_script_wired(frontend: pathlib.Path) -> bool:
    """Whether *frontend*'s package.json declares the ``routes`` script.

    Route types are opt-in for an app that predates them (ADR 0092): the generator, the
    committed table and the drift gate arrive together when the app adds this script.
    Reading it is how the preflight and the gate stay a no-op until then, instead of
    breaking `terp dev` and `terp verify` for every app that merely upgraded.
    """
    manifest = frontend / "package.json"
    if not manifest.is_file():
        return False
    try:
        scripts = json.loads(manifest.read_text(encoding="utf-8")).get("scripts", {})
    except (OSError, json.JSONDecodeError):
        return False
    return isinstance(scripts, dict) and ROUTES_SCRIPT in scripts


def run_routes_command(
    *,
    root: str | pathlib.Path = ".",
    frontend_dir: str = "frontend",
    check: bool = False,
    optional: bool = False,
    run: object = None,
) -> str:
    """Regenerate (or, with *check*, verify) the app's route types; return the output.

    Fails closed with a clean CLI error: a missing frontend, an unwired script and a stale
    table are all reasons a caller must see, never a silent success. *optional* inverts the
    first two for a caller that merely offers the regeneration (the ``terp dev``
    preflight): an app that has not adopted route types is skipped with the hint, not
    failed. *run* is injected so the orchestration is testable without spawning npm.
    """
    root_path = pathlib.Path(root).resolve()
    frontend = root_path / frontend_dir
    if not frontend.is_dir():
        if optional:
            return f"skipped (no {frontend_dir}/)"
        raise SystemExit(
            f"terp routes found no frontend at {frontend} — pass --frontend-dir, or skip "
            "route types in a backend-only project"
        )
    if not routes_script_wired(frontend):
        if optional:
            return f"skipped (no {ROUTES_SCRIPT!r} script) — {ADOPT_HINT}"
        raise SystemExit(
            f"{frontend / 'package.json'} declares no {ROUTES_SCRIPT!r} script: {ADOPT_HINT}"
        )
    argv = routes_argv(frontend_dir, check=check)
    runner = run if run is not None else _run_npm
    exit_code, output = runner(argv, root_path)  # type: ignore[operator]
    if exit_code != 0:
        raise SystemExit(
            output.strip() or f"{' '.join(argv)} failed with exit code {exit_code}"
        )
    return output.strip()


def _run_npm(argv: list[str], cwd: pathlib.Path) -> tuple[int, str]:
    """Run *argv* from *cwd*, returning its exit code and combined output."""
    executable = shutil.which(argv[0]) or argv[0]
    completed = subprocess.run(  # noqa: S603 - fixed argv, shell=False
        [executable, *argv[1:]],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    return completed.returncode, f"{completed.stdout}{completed.stderr}"


__all__ = [
    "ADOPT_HINT",
    "ROUTES_SCRIPT",
    "routes_argv",
    "routes_script_wired",
    "run_routes_command",
]
