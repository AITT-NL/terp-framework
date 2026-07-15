"""``terp verify`` — the project's whole verification profile as one command.

The single source of truth for "what does green mean" (the gate a human, an
agent, CI, and a driving tool such as Terp Studio all run): a **profile** is a
named list of checks (id, category, command, input scope), declared here as
data and executed sequentially in the project root. Three profiles ratchet up:

* ``quick`` — static enforcement only (architecture gate, frontend boundary
  lint, frontend typecheck): cheap enough to run after every agent turn.
* ``full`` — the merge bar: quick plus the backend test suite, the delegated
  generic AppSec baseline (ruff ``S``, ADR 0085), and the production frontend
  build. This is exactly the template CI's blocking surface.
* ``release`` — full plus the dependency audits (pip-audit / npm audit — the
  spec's required ``dependency-audit`` assurance lane), the contract-drift
  checks and the black-box conformance suite (which needs the Docker workbench
  running; see the check's ``requires`` note in the manifest).

``--list`` prints the manifest without running anything — the seam a driving
tool reads so its gate DEFINITION comes from the project's own pinned
toolchain instead of a hardcoded copy. ``--only <id>`` runs a subset (the
change-scoped rerun seam). ``--format json`` emits the ``terp_verify``
envelope: per-check verdicts plus every Terp Standard check report
(``terp_check_report`` document, ``app-check-report.schema.json``) and legacy
findings envelope (``terp_findings``) the checks published on stdout — parsed
out and carried structurally, never re-derived by the consumer.
``--format assurance`` (release profile only) emits the spec's release-
assurance claim instead (``assurance-profile.schema.json``): the run's checks
composed into the normative evidence lanes, with the exit code following the
required lanes.
"""

from __future__ import annotations

import json
import os
import pathlib
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass

#: How much of a failing check's combined output the envelope keeps (fail-closed
#: on unbounded output; enough to show the actual errors).
_OUTPUT_TAIL_CHARS = 20_000


@dataclass(frozen=True)
class VerifyCheck:
    """One named check of a profile: a command tagged with an issue category.

    ``scope`` lists the ``/``-separated path globs that can affect the check's
    verdict (``dir/**`` = the whole subtree) — the input claim a change-aware
    driving tool uses to prove a rerun unnecessary. ``requires`` is a
    human-readable precondition (e.g. a running workbench) surfaced in the
    manifest, never checked here: the check itself fails visibly when unmet.
    """

    id: str
    category: str
    command: str
    scope: tuple[str, ...] = ()
    requires: str = ""
    #: In-process checks (the architecture gate) run as a callable instead of a
    #: subprocess — same verdict surface, no interpreter round-trip.
    runner: str = "subprocess"  # "subprocess" | "architecture" | "api-docs-drift"


_ARCHITECTURE = VerifyCheck(
    id="architecture",
    category="architecture",
    command="terp check --format check-report --budget escape-hatch-budget.json",
    scope=("app/**", "control_plane/**", "escape-hatch-budget.json"),
    runner="architecture",
)

_FRONTEND_BOUNDARIES = VerifyCheck(
    id="frontend-boundaries",
    category="frontend-boundaries",
    command="npm --prefix frontend run lint -- --format check-report",
    scope=("frontend/**", "escape-hatch-budget.json"),
)

_FRONTEND_TYPECHECK = VerifyCheck(
    id="frontend-typecheck",
    category="build",
    command="npm --prefix frontend run typecheck",
    scope=("frontend/**", "app/**"),
)

_BACKEND_TESTS = VerifyCheck(
    id="backend-tests",
    category="backend-tests",
    command="uv run pytest",
    scope=("app/**", "control_plane/**", "tests/**", "conformance/**"),
)

_APPSEC_BASELINE = VerifyCheck(
    id="appsec-baseline",
    category="architecture",
    command="uv run ruff check .",
    scope=("app/**", "control_plane/**", "tests/**"),
)

_FRONTEND_BUILD = VerifyCheck(
    id="frontend-build",
    category="build",
    command="npm --prefix frontend run build",
    scope=("frontend/**", "app/**"),
)

_API_DOCS_DRIFT = VerifyCheck(
    id="api-docs-drift",
    category="build",
    command="terp api-docs --out docs && git diff --exit-code -- docs",
    scope=("app/**", "docs/**"),
    runner="api-docs-drift",
)

# The dependency-audit assurance lane (the spec's required generic evidence):
# both dependency trees against known-vulnerability databases. Release-profile
# checks (not the merge bar): advisory databases move independently of the
# code, so a red here means "do not ship", not "this change broke something".
_DEPENDENCY_AUDIT_PYTHON = VerifyCheck(
    id="dependency-audit-python",
    category="architecture",
    command="uv run --with pip-audit pip-audit --progress-spinner off",
    scope=("pyproject.toml", "uv.lock"),
    requires="network access to the advisory databases",
)

_DEPENDENCY_AUDIT_NPM = VerifyCheck(
    id="dependency-audit-npm",
    category="architecture",
    command="npm --prefix frontend audit --audit-level=high",
    scope=("frontend/package.json", "frontend/package-lock.json"),
    requires="network access to the advisory databases",
)

_CONFORMANCE = VerifyCheck(
    id="conformance",
    category="conformance",
    command="npm --prefix conformance test",
    scope=("app/**", "frontend/**", "conformance/**"),
    requires="the Docker workbench running (docker compose up -d --wait api web seed)",
)

#: The profiles, cheapest first; each is a superset of the previous.
PROFILES: dict[str, tuple[VerifyCheck, ...]] = {
    "quick": (_ARCHITECTURE, _FRONTEND_BOUNDARIES, _FRONTEND_TYPECHECK),
    "full": (
        _ARCHITECTURE,
        _BACKEND_TESTS,
        _APPSEC_BASELINE,
        _FRONTEND_BOUNDARIES,
        _FRONTEND_TYPECHECK,
        _FRONTEND_BUILD,
    ),
    "release": (
        _ARCHITECTURE,
        _BACKEND_TESTS,
        _APPSEC_BASELINE,
        _DEPENDENCY_AUDIT_PYTHON,
        _DEPENDENCY_AUDIT_NPM,
        _FRONTEND_BOUNDARIES,
        _FRONTEND_TYPECHECK,
        _FRONTEND_BUILD,
        _API_DOCS_DRIFT,
        _CONFORMANCE,
    ),
}

#: The Terp Standard's assurance-lane vocabulary → (requirement, composing
#: release-profile check ids). The vocabulary and each lane's requirement
#: level are NORMATIVE in the spec (assurance-profile.schema.json + the
#: README's "Assurance profile" table) — these constants mirror them, held to
#: the pinned spec's schema by the framework gate. ``a11y`` is declared but
#: not realised by this toolchain yet: it is emitted ``not-run`` (a lane is
#: never dropped and never counted as passed without evidence).
ASSURANCE_LANES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("terp-standard", "required", ("architecture", "frontend-boundaries")),
    ("appsec-baseline", "required", ("appsec-baseline",)),
    (
        "dependency-audit",
        "required",
        ("dependency-audit-python", "dependency-audit-npm"),
    ),
    ("a11y", "recommended", ()),
    ("blackbox-conformance", "recommended", ("conformance",)),
)


def profile_ids() -> tuple[str, ...]:
    """The declared profile names (the ``--profile`` choices)."""
    return tuple(PROFILES)


def verify_manifest(profile: str) -> dict[str, object]:
    """The profile's check manifest as data (the ``--list --format json`` body).

    A driving tool configures its gate FROM this — the project's own pinned
    toolchain states what green means — instead of hardcoding a copy that
    drifts. ``command`` is the exact invocation ``terp verify`` itself runs.
    """
    checks = PROFILES.get(profile)
    if checks is None:
        raise SystemExit(f"unknown profile {profile!r}; expected one of {profile_ids()}")
    return {
        "terp_verify_manifest": 1,
        "profile": profile,
        "checks": [
            {
                "id": check.id,
                "category": check.category,
                "command": check.command,
                "scope": list(check.scope),
                **({"requires": check.requires} if check.requires else {}),
            }
            for check in checks
        ],
    }


def _json_documents(stdout: str) -> list[dict]:
    """Every top-level JSON object embedded in *stdout*, tolerantly.

    A check's stdout may interleave prose with one or more JSON documents (the
    single-line ``terp_findings`` envelope, the indented ``terp_check_report``).
    Anything unparseable is skipped — the consumer falls back to the raw tail.
    """
    documents: list[dict] = []
    decoder = json.JSONDecoder()
    index = 0
    while True:
        start = stdout.find("{", index)
        if start == -1:
            return documents
        try:
            payload, end = decoder.raw_decode(stdout[start:])
        except ValueError:
            index = start + 1
            continue
        if isinstance(payload, dict):
            documents.append(payload)
        index = start + max(end, 1)


def _reports_in(stdout: str) -> list[dict]:
    """The machine documents a check published: check reports + legacy envelopes."""
    return [
        document
        for document in _json_documents(stdout)
        if document.get("terp_check_report") is not None
        or document.get("terp_findings") is not None
    ]


def _run_subprocess(check: VerifyCheck, root: pathlib.Path) -> tuple[int, str]:
    """Run one manifest command (shell-less; ``&&`` composites never land here)."""
    argv = shlex.split(check.command)
    executable = shutil.which(argv[0]) or argv[0]
    try:
        completed = subprocess.run(  # noqa: S603 - fixed manifest argv, shell=False
            [executable, *argv[1:]],
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except FileNotFoundError:
        return 127, f"{argv[0]}: executable not found on PATH"
    return completed.returncode, completed.stdout + ("\n" + completed.stderr if completed.stderr else "")


def _run_architecture(root: pathlib.Path) -> tuple[int, str, list[dict]]:
    """The architecture gate in-process: the check report without a subprocess."""
    from terp.cli import check_report_envelope  # lazy: the package imports this module

    budget = root / "escape-hatch-budget.json"
    envelope = check_report_envelope(
        str(root), budget_path=str(budget) if budget.is_file() else None
    )
    ok = bool(envelope["ok"])
    summary = json.dumps(envelope, indent=2)
    return (0 if ok else 1), summary, [envelope]


def _run_api_docs_drift(root: pathlib.Path) -> tuple[int, str]:
    """Regenerate the API reference and fail on drift from the committed copy.

    A no-op success until the project commits ``docs/`` (the template CI pair
    behaves identically: the diff of an untracked directory is empty).
    """
    from terp.cli import api_docs

    docs = root / "docs"
    if not docs.is_dir():
        return 0, "docs/ not committed - drift check skipped (commit docs/ to enable)"
    previous = pathlib.Path.cwd()
    try:
        # api_docs writes relative to cwd through the live kernel import.
        os.chdir(root)
        written = [str(path) for path in api_docs(str(docs))]
    finally:
        os.chdir(previous)
    git = shutil.which("git") or "git"
    completed = subprocess.run(  # noqa: S603 - fixed argv, shell=False
        [git, "diff", "--exit-code", "--", "docs"],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    output = "\n".join(["\n".join(f"wrote {path}" for path in written), completed.stdout])
    if completed.returncode != 0:
        output += "\napi docs drifted from the committed copy - commit the regenerated docs/"
    return completed.returncode, output


def assurance_document(results: list[dict[str, object]]) -> dict[str, object]:
    """The release-assurance claim (``assurance-profile.schema.json``) from a
    release-profile run's per-check *results*.

    Lane verdicts compose from the named checks' verdicts: every composing
    check green ⇒ ``passed``, otherwise ``failed``; a lane this toolchain does
    not realise (``a11y``) is ``not-run``, never dropped. The claim (``ok``)
    follows the REQUIRED lanes only — the requirement mapping is the spec's,
    mirrored in :data:`ASSURANCE_LANES` — so a red recommended lane informs
    the reader without carrying the claim.
    """
    import importlib.metadata

    from terp.arch import SPEC_VERSION  # lazy: the package imports this module

    verdicts = {str(result["id"]): bool(result["ok"]) for result in results}
    lanes: list[dict[str, object]] = []
    ok = True
    for lane_id, requirement, check_ids in ASSURANCE_LANES:
        if not check_ids:
            status = "not-run"
        elif all(verdicts.get(check_id, False) for check_id in check_ids):
            status = "passed"
        else:
            status = "failed"
        if requirement == "required" and status != "passed":
            ok = False
        lanes.append({"id": lane_id, "status": status, "checks": list(check_ids)})
    try:
        version = importlib.metadata.version("terp-cli")
    except importlib.metadata.PackageNotFoundError:  # a source checkout (the platform repo)
        version = "0"
    return {
        "terp_assurance": 1,
        "spec_version": SPEC_VERSION,
        "toolchain": {"tool": "terp-verify", "version": version},
        "profile": "release",
        "ok": ok,
        "lanes": lanes,
    }


def run_verify_command(
    *,
    profile: str,
    root: str = ".",
    only: list[str] | None = None,
    list_only: bool = False,
    fmt: str = "text",
) -> int:
    """Run (or list) the profile; returns the process exit code.

    Human progress goes to stderr so ``--format json`` keeps stdout as one
    machine document (the same stdout/stderr split as ``terp-boundaries-lint``).
    ``--format assurance`` emits the release-assurance claim instead
    (``assurance-profile.schema.json``) and its exit code follows the claim:
    every REQUIRED lane passed = 0 — a red recommended lane does not fail the
    emission (the strict every-check gate remains ``--format text``/``json``).
    Assurance is only meaningful over the whole release profile, so it refuses
    any other profile, ``--only`` subsets, and ``--list`` (fail closed: a
    partial run can never quietly become a release claim).
    """
    if fmt == "assurance" and (profile != "release" or only or list_only):
        raise SystemExit(
            "--format assurance emits the release-assurance claim: it requires "
            "--profile release and refuses --only/--list — a partial run can "
            "never become a release claim"
        )
    manifest = verify_manifest(profile)
    checks = list(PROFILES[profile])
    selected = [name for name in (only or []) if name]
    if selected:
        known = {check.id for check in checks}
        unknown = sorted(set(selected) - known)
        if unknown:
            raise SystemExit(
                f"--only names no check of profile {profile!r}: {', '.join(unknown)} "
                f"(known: {', '.join(sorted(known))})"
            )
        checks = [check for check in checks if check.id in selected]

    if list_only:
        if fmt == "json":
            print(json.dumps(manifest, indent=2))
        else:
            print(f"profile {profile}:")
            for check in PROFILES[profile]:
                requires = f"  [requires {check.requires}]" if check.requires else ""
                print(f"  {check.id:<20} {check.command}{requires}")
        return 0

    project_root = pathlib.Path(root).resolve()
    results: list[dict[str, object]] = []
    all_ok = True
    for check in checks:
        print(f"verify: {check.id} ({check.command})", file=sys.stderr)
        reports: list[dict] = []
        if check.runner == "architecture":
            exit_code, output, reports = _run_architecture(project_root)
        elif check.runner == "api-docs-drift":
            exit_code, output = _run_api_docs_drift(project_root)
        else:
            exit_code, output = _run_subprocess(check, project_root)
            reports = _reports_in(output)
        ok = exit_code == 0
        all_ok = all_ok and ok
        print(
            f"verify: {check.id} {'ok' if ok else f'FAILED (exit {exit_code})'}",
            file=sys.stderr,
        )
        if not ok and fmt == "text":
            print(output[-_OUTPUT_TAIL_CHARS:], file=sys.stderr)
        results.append(
            {
                "id": check.id,
                "category": check.category,
                "command": check.command,
                "scope": list(check.scope),
                "ok": ok,
                "exit_code": exit_code,
                "output_tail": output[-_OUTPUT_TAIL_CHARS:],
                "reports": reports,
            }
        )

    if fmt == "json":
        print(
            json.dumps(
                {
                    "terp_verify": 1,
                    "profile": profile,
                    "ok": all_ok,
                    "checks": results,
                }
            )
        )
    elif fmt == "assurance":
        document = assurance_document(results)
        print(json.dumps(document, indent=2))
        verdict = "holds" if document["ok"] else "does NOT hold"
        print(f"verify: the release-assurance claim {verdict}", file=sys.stderr)
        return 0 if document["ok"] else 1
    else:
        verdict = "green" if all_ok else "RED"
        print(f"verify: profile {profile} is {verdict}", file=sys.stderr)
    return 0 if all_ok else 1
