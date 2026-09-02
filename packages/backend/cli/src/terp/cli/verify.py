"""``terp verify`` — the project's whole verification profile as one command.

The single source of truth for "what does green mean" (the gate a human, an
agent, CI, and a driving tool such as Terp Studio all run): a **profile** is a
named list of checks (id, category, command, input scope), declared here as
data and executed sequentially in the project root. Three profiles ratchet up:

* ``quick`` — static enforcement only (architecture gate, frontend boundary
  lint, frontend typecheck): cheap enough to run after every agent turn.
* ``full`` — the merge bar: quick plus the backend test suite, the delegated
  generic AppSec baseline (ruff ``S``, ADR 0085), the delegated dependency
  hygiene check (deptry — is every distribution this app imports declared?), and
  the production frontend build. This is exactly the template CI's blocking
  surface.
* ``release`` — full plus the dependency audits (pip-audit / npm audit — the
  spec's required ``dependency-audit`` assurance lane), the contract-drift
  checks and the black-box conformance suite (which needs the Docker workbench
  running; see the check's ``requires`` note in the manifest).

An app EXTENDS the profile through ``[[tool.terp.verify.checks]]`` in its own
``pyproject.toml`` (see :func:`app_declared_checks`): the platform's checks are
the floor, not the ceiling, and an app-specific check no longer has to live in a
pytest wrapper outside the one command that defines green.

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
import re
import shlex
import shutil
import subprocess
import sys
import tomllib
from dataclasses import dataclass

#: How much of a failing check's combined output the envelope keeps (fail-closed
#: on unbounded output; enough to show the actual errors).
_OUTPUT_TAIL_CHARS = 20_000

#: Marks output a check wants read even though it PASSED — an adoption hint, a skip
#: with a reason. A passing check is otherwise silent in text mode (its output is a
#: whole test log), which is how the routes-drift adoption hint came to be announced
#: only in `--format json`: an opt-in nobody is told about does not get adopted.
NOTE_PREFIX = "note: "

#: The issue categories a driving tool (Terp Studio's issue tabs) understands.
#: Built-in checks are held to it by the gate; an app-declared check is held to
#: it here, because a category outside this set is a check whose findings the
#: driving tool has nowhere to file — silently, which is the failure mode this
#: whole seam exists to remove.
CHECK_CATEGORIES: frozenset[str] = frozenset(
    {
        "architecture",
        "backend-tests",
        "frontend-boundaries",
        "build",
        "conformance",
    }
)

#: Where an app declares its own checks. A list of tables, so the shape reads the
#: same as ``[[tool.importlinter.contracts]]`` an app already writes next to it.
APP_CHECK_TABLE = "[[tool.terp.verify.checks]]"

#: The keys an app-declared check may carry. Unknown keys are REFUSED rather than
#: ignored: a typo'd ``profil`` that silently drops the check would be a new
#: instance of the exact bug this seam closes — a gate that looks green because a
#: check it was told about never ran.
_APP_CHECK_KEYS = frozenset(
    {"id", "command", "profile", "scope", "category", "requires"}
)

#: An app check id: the same lowercase-slug shape the built-in ids use, so the
#: two are indistinguishable in ``--only``, the manifest and the JSON envelope.
_APP_CHECK_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

#: Argv elements that are a command SEPARATOR and nothing else. No program takes
#: a bare ``&&`` or ``||`` as an argument, so one of these arriving as its own
#: argument is always an author expecting a shell that is not there.
#:
#: Deliberately just these two. Every other piece of shell syntax has a
#: legitimate bare-argument use — ``awk -F '|'``, ``find … -exec rm {} ;`` — and
#: two earlier versions of this check refused exactly those, failing an app's
#: whole table closed over a command that was correct. A guard whose false
#: positives are commands people really write is worse than the mistake it
#: catches.
_COMMAND_SEPARATORS = frozenset({"&&", "||"})


def _shell_separators_in(command: str) -> list[str]:
    """The command separators in *command* that are not inside quotes.

    A purpose-built scan rather than a lexer, after three attempts to borrow one
    and three different wrong answers. ``shlex.split`` strips quotes, so a literal
    ``grep -F '&&'`` looked like composition; non-POSIX lexing raised on a quote
    that does not start its token (``-F'|'``), which silently disabled the guard
    for everything after it; and matching whole argv elements missed ``a&&b``,
    where the separator is welded to its neighbours.

    A few lines that answer exactly one question — is this ``&&`` inside quotes? —
    and nothing here can be surprised by a lexer setting.

    The question is not "what argv does this produce" — ``shlex.split`` answers
    that, and it cannot tell a quoted ``&&`` from a bare one, since both arrive as
    the same bare element. The question is whether the AUTHOR meant it literally,
    and in a command line there are exactly two ways to say so: quote it, or
    escape it. Both are honoured here, and both are accepted; only a separator
    written plainly is refused.

    So a backslash escapes the next character in either state. Honouring it inside
    double quotes only was a fail-OPEN, not a rough edge: a ``\\"`` outside quotes
    opened a phantom quoted region that swallowed the rest of the line, so
    ``node --eval console.log(\\"hi\\") && rm -rf /tmp/x`` was accepted while the
    argv carried a real ``&&``.
    """
    found: set[str] = set()
    # Longest first, so a two-character separator is never read as a one-character
    # one. Derived from the set rather than assumed, because the previous version
    # hard-coded a two-character slice: adding ``;`` to the set would have made it
    # silently unmatchable, with every existing test still green.
    lengths = sorted({len(separator) for separator in _COMMAND_SEPARATORS}, reverse=True)
    quote: str | None = None
    index = 0
    while index < len(command):
        character = command[index]
        if character == "\\" and (quote is None or quote == '"'):
            index += 2  # the escaped character, whatever it is
            continue
        if quote is not None:
            if character == quote:
                quote = None
            index += 1
            continue
        if character in "'\"":
            quote = character
            index += 1
            continue
        for length in lengths:
            candidate = command[index : index + length]
            if candidate in _COMMAND_SEPARATORS:
                found.add(candidate)
                index += length
                break
        else:
            index += 1
    return sorted(found)


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
    # "subprocess" | "architecture" | "api-docs-drift" | "routes-drift"
    # | "platform-install" | "env-seams" | "api-client" | "package-boundaries"
    # | "dependency-hygiene" | "workbench"
    runner: str = "subprocess"


# Runs first in every profile, because it decides whether the rest of the run
# means anything. Terp ships as a lockstep set pinned by hand, so the natural
# failure is a forgotten pin leaving one package a release behind — and a gate
# run against a combination that was never released proves nothing about the
# app: a green is not evidence, and a red may belong to the mismatch rather than
# to the code. `terp --version` already detects this and warns; a warning inside
# a command nobody runs before shipping is not a control, so the verdict lands
# here, where it can fail.
_PLATFORM_INSTALL = VerifyCheck(
    id="platform-install",
    category="architecture",
    command="terp --version",
    scope=("pyproject.toml", "uv.lock", "**/package.json", "**/package-lock.json"),
    runner="platform-install",
)

# Runs early and costs a file read: it answers "will this app's configuration reach it at
# all", which decides what a later red means. Compose resolves `environment:` over
# `env_file:`, so a declared variable named in both is supplied by the developer's `.env`
# (or a compose default) and never by the `.app.env` Studio renders — silently, in every
# environment, with the app's own docs asserting the opposite.
_ENV_SEAMS = VerifyCheck(
    id="env-seams",
    category="architecture",
    command="terp verify --only env-seams",
    scope=(
        "environment.schema.json",
        ".app.env.example",
        "docker-compose*.yml",
    ),
    runner="env-seams",
)

# Costs a file read, and answers "can a workbench still find its way around this
# app". The compose file is edited constantly, increasingly by agents, and a small
# part of it is load-bearing: which service serves the interface, which serves the
# API, and through which variables the host ports arrive. Nothing recorded that,
# so nothing could tell an agent it had just broken it -- the symptom showed up
# much later as a preview that would not start. Checks the declaration against
# reality and nothing else: a service nobody declared is nobody's business.
_WORKBENCH = VerifyCheck(
    id="workbench",
    category="architecture",
    command="terp verify --only workbench",
    # The glob deliberately over-matches: it catches `docker-compose.prod.yml`
    # too, even though this check refuses to read a deploy profile at all. A
    # scope that triggers a check needlessly wastes a file read; a scope that
    # fails to trigger one lets drift land unnoticed until the next full run,
    # and an app may name its development compose file whatever it likes. So it
    # errs toward triggering. Do not "tidy" this to `docker-compose.yml`.
    scope=("workbench.json", "docker-compose*.yml"),
    runner="workbench",
)

_ARCHITECTURE = VerifyCheck(
    id="architecture",
    category="architecture",
    command="terp check --format check-report --budget escape-hatch-budget.json",
    scope=("app/**", "control_plane/**", "escape-hatch-budget.json"),
    runner="architecture",
)

# The app's OWN declared package graph, and it is here because the alternative was a
# documented contradiction. `terp guide package-boundaries` prescribes import-linter
# contracts plus `uv run lint-imports` in CI, while this profile is documented as exactly
# what CI enforces — both cannot be true for an app that followed the guide. Left outside,
# every such app writes the same pytest wrapper to shell out to the console script, or
# quietly forgets the command and ships a boundary nothing checks. Conditional on the app
# DECLARING contracts, so an app that never adopted them is unaffected.
_PACKAGE_BOUNDARIES = VerifyCheck(
    id="package-boundaries",
    category="architecture",
    command="lint-imports",
    scope=("pyproject.toml", "**/*.py"),
    runner="package-boundaries",
)

# "Is every distribution this app imports actually declared?" — the question no
# Terp rule can answer. The import-name to distribution-name mapping (`yaml` comes
# from PyYAML) needs installed metadata, and `terp.arch` reads source, never
# `pyproject.toml`; hand-rolling the mapping inside the gate would be a worse copy
# of a solved problem. So it is delegated, following the appsec-baseline precedent
# (ADR 0085, ADR 0033) — and it is BLOCKING, unlike the advisory run the platform
# does over its own packages. The failure it catches is a green gate over an
# undeclared driver import on a path no test reaches: the app works on the machine
# where a transitive dependency happens to be installed and fails on a clean one.
# Advisory is not a control.
#
# `full`, not `quick`: the question is a shipping property, not a per-turn one, and
# answering it needs a resolved environment that `quick` deliberately does not
# assume. Conditional on the app declaring `[tool.deptry]`, so an app that never
# adopted it is unaffected — and declared-but-unrunnable is a RED, not a skip.
_DEPENDENCY_HYGIENE = VerifyCheck(
    id="dependency-hygiene",
    category="architecture",
    command="uv run deptry .",
    scope=("pyproject.toml", "uv.lock", "**/*.py"),
    runner="dependency-hygiene",
)

_FRONTEND_BOUNDARIES = VerifyCheck(
    id="frontend-boundaries",
    category="frontend-boundaries",
    command="npm --prefix frontend run lint -- --format check-report",
    scope=("frontend/**", "escape-hatch-budget.json"),
)

# The routes half of generate-commit-gate (ADR 0092), and the reason it runs BEFORE the
# typecheck: a stale route table makes the typecheck fail on the app's own screens, where
# the real fault is one unregenerated artifact. `--check` compares the rendered table with
# the committed file, so it needs no git and reports the regeneration command.
_ROUTES_DRIFT = VerifyCheck(
    id="routes-drift",
    category="build",
    command="npm --prefix frontend run routes -- --check",
    scope=("frontend/**",),
    runner="routes-drift",
)

# The typed API client is GENERATED from the backend contract and gitignored (ADR 0041),
# so a fresh checkout does not have one -- and `npm run typecheck` is the only thing that
# reads it, because Vite erases type-only imports and `build` passes happily without it.
# That is why this is a profile check and not a CI step: as a step it lived in the
# scaffolded workflow, froze at the template version the app was rendered from, and the
# frontend half of the gate went quietly green on an app whose schema module could not
# resolve at all. Owned here, every driver of the profile gets it for free.
_API_CLIENT = VerifyCheck(
    id="api-client",
    category="build",
    command="terp verify --only api-client",
    scope=("app/**", "control_plane/**", "frontend/package.json"),
    runner="api-client",
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
    # Self-referential, like env-seams, and deliberately not the `&&` pair it used to
    # publish: a driving tool runs manifest commands as a fixed argv with no shell, so a
    # composite becomes a false red about the app instead of a verdict.
    command="terp verify --only api-docs-drift",
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
    requires=(
        "the Docker workbench running (docker compose up -d --wait api web "
        "&& docker compose run --rm seed)"
    ),
)

#: The profiles, cheapest first; each is a superset of the previous.
PROFILES: dict[str, tuple[VerifyCheck, ...]] = {
    "quick": (
        _PLATFORM_INSTALL,
        _ENV_SEAMS,
        _WORKBENCH,
        _ARCHITECTURE,
        _PACKAGE_BOUNDARIES,
        _FRONTEND_BOUNDARIES,
        _ROUTES_DRIFT,
        _API_CLIENT,
        _FRONTEND_TYPECHECK,
    ),
    "full": (
        _PLATFORM_INSTALL,
        _ENV_SEAMS,
        _WORKBENCH,
        _ARCHITECTURE,
        _PACKAGE_BOUNDARIES,
        _DEPENDENCY_HYGIENE,
        _BACKEND_TESTS,
        _APPSEC_BASELINE,
        _FRONTEND_BOUNDARIES,
        _ROUTES_DRIFT,
        _API_CLIENT,
        _FRONTEND_TYPECHECK,
        _FRONTEND_BUILD,
    ),
    "release": (
        _PLATFORM_INSTALL,
        _ENV_SEAMS,
        _WORKBENCH,
        _ARCHITECTURE,
        _PACKAGE_BOUNDARIES,
        _DEPENDENCY_HYGIENE,
        _BACKEND_TESTS,
        _APPSEC_BASELINE,
        _DEPENDENCY_AUDIT_PYTHON,
        _DEPENDENCY_AUDIT_NPM,
        _FRONTEND_BOUNDARIES,
        _ROUTES_DRIFT,
        _API_CLIENT,
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


def _declaration_error(message: str) -> SystemExit:
    return SystemExit(f"{APP_CHECK_TABLE} in pyproject.toml: {message}")


def _app_check_from(entry: object, index: int, known: frozenset[str]) -> VerifyCheck:
    """One declared table validated into a :class:`VerifyCheck`, or a refusal.

    Every branch here fails closed. The alternative — skip what does not parse —
    would hand an app a gate that passes because its own check was quietly
    dropped, which is the failure this seam was opened to remove and would be
    worse coming from the seam itself.
    """
    where = f"check #{index + 1}"
    if not isinstance(entry, dict):
        raise _declaration_error(f"{where} is not a table")
    unknown = sorted(set(entry) - _APP_CHECK_KEYS)
    if unknown:
        raise _declaration_error(
            f"{where} has unknown key(s) {', '.join(unknown)} "
            f"(allowed: {', '.join(sorted(_APP_CHECK_KEYS))})"
        )
    check_id = entry.get("id")
    if not isinstance(check_id, str) or not _APP_CHECK_ID.match(check_id):
        raise _declaration_error(
            f"{where} needs an `id` of lowercase words joined by hyphens, "
            f"got {check_id!r}"
        )
    if check_id in known:
        raise _declaration_error(
            f"{check_id!r} is already a Terp check. An app check may not take a "
            "platform check's id: `--only` could not tell them apart, and the "
            "assurance claim composes its lanes by id, so the shadowing check "
            "would report on a lane it never ran"
        )
    command = entry.get("command")
    if not isinstance(command, str):
        raise _declaration_error(f"{check_id!r} needs a non-empty `command` string")
    try:
        argv = shlex.split(command)
    except ValueError as exc:
        # `shlex.split` raises on an unbalanced quote. Uncaught, that is a
        # traceback out of `terp verify` about a file the user can fix in a second
        # — so it becomes a declaration error like every other defect here.
        raise _declaration_error(
            f"{check_id!r} has a `command` that cannot be read as a command "
            f"line ({exc})"
        ) from exc
    if not argv:
        raise _declaration_error(f"{check_id!r} needs a non-empty `command` string")
    # Manifest commands run as a fixed argv with shell=False, so a separator is
    # not composition here — it is an argument. `a && b` would run `a` with `&&`
    # and `b` as its arguments and report THAT verdict: a green for a check nobody
    # ran. Note what is not claimed — no shell syntax is interpreted at all, and
    # only the two unambiguous separators are refused.
    separators = _shell_separators_in(command)
    if separators:
        raise _declaration_error(
            f"{check_id!r} has {', '.join(separators)} in its command, but a check "
            "runs as a fixed argv with no shell, so that would be passed as an "
            "argument rather than composing two commands — and the check would "
            "report the first command's verdict. Declare each command as its own "
            "check, or put the composition in a script the check calls. If it is "
            "meant literally — an argument that really contains it — quote it, and "
            "this stops applying"
        )
    profile = entry.get("profile")
    if profile not in PROFILES:
        raise _declaration_error(
            f"{check_id!r} needs a `profile` naming the cheapest profile it joins, "
            f"one of {', '.join(profile_ids())}; got {profile!r}"
        )
    category = entry.get("category", "architecture")
    if category not in CHECK_CATEGORIES:
        raise _declaration_error(
            f"{check_id!r} has `category` {category!r}, which no driving tool can "
            f"file; use one of {', '.join(sorted(CHECK_CATEGORIES))}"
        )
    scope = entry.get("scope", ())
    if not isinstance(scope, list) or not all(isinstance(item, str) for item in scope):
        raise _declaration_error(f"{check_id!r} needs `scope` to be a list of globs")
    if not scope:
        raise _declaration_error(
            f"{check_id!r} needs a non-empty `scope`: it is the input claim a "
            "change-aware runner uses to prove a rerun unnecessary, and a check "
            "with no declared inputs can never be skipped safely"
        )
    requires = entry.get("requires", "")
    if not isinstance(requires, str):
        raise _declaration_error(f"{check_id!r} needs `requires` to be a string")
    return VerifyCheck(
        id=check_id,
        category=category,
        command=command,
        scope=tuple(scope),
        requires=requires,
    )


def app_declared_checks(root: pathlib.Path) -> tuple[tuple[VerifyCheck, str], ...]:
    """The app's own checks from ``[[tool.terp.verify.checks]]``, with their profiles.

    The profile table above is the platform's floor. It used to be the whole
    ceiling too — a literal dict no app could reach — so an app with a check of
    its own (a sidecar package's architecture scan, a domain invariant, a
    generated-artifact drift test) had two options: a pytest wrapper shelling out
    to the real command, or a CI step outside the one command documented as
    "what green means". Both put the app's own gate somewhere ``terp verify``
    does not look, which is how a check comes to be skipped by everyone driving
    the project through the manifest.

    Each entry names the CHEAPEST profile it joins and rides the ratchet from
    there, exactly as a built-in does: ``profile = "quick"`` also runs in ``full``
    and ``release``. Declared checks run AFTER the platform's, so a red from the
    floor still comes first, and they compose into **no assurance lane** — the
    lane vocabulary is normative in the spec, and an app may extend its own gate
    without touching a claim the spec defines. The seam is the generalisation of
    ``package-boundaries``: the same conditional-on-declaration adoption, now
    without the platform having to have anticipated the tool.
    """
    manifest = root / "pyproject.toml"
    if not manifest.is_file():
        return ()
    try:
        declared = tomllib.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise _declaration_error(
            f"pyproject.toml is unreadable ({exc}), so whether this app declares "
            "checks of its own cannot be established"
        ) from exc
    table = ((declared.get("tool") or {}).get("terp") or {}).get("verify") or {}
    if not isinstance(table, dict):
        raise _declaration_error("[tool.terp.verify] is not a table")
    unknown = sorted(set(table) - {"checks"})
    if unknown:
        raise _declaration_error(
            f"[tool.terp.verify] has unknown key(s) {', '.join(unknown)}; the only "
            "key is `checks`"
        )
    entries = table.get("checks", [])
    if not isinstance(entries, list):
        raise _declaration_error("`checks` must be a list of tables")
    known = frozenset(check.id for checks in PROFILES.values() for check in checks)
    resolved: list[tuple[VerifyCheck, str]] = []
    seen: set[str] = set()
    for index, entry in enumerate(entries):
        check = _app_check_from(entry, index, known)
        if check.id in seen:
            raise _declaration_error(f"{check.id!r} is declared twice")
        seen.add(check.id)
        resolved.append((check, str(entry["profile"])))
    return tuple(resolved)


def profile_checks(
    profile: str, root: pathlib.Path | None = None
) -> tuple[VerifyCheck, ...]:
    """The profile's checks: the platform's floor plus the app's own declarations.

    *root* is the project the checks run in; ``None`` asks for the platform floor
    alone (what the profile means before any app extends it).
    """
    checks = PROFILES.get(profile)
    if checks is None:
        raise SystemExit(
            f"unknown profile {profile!r}; expected one of {profile_ids()}"
        )
    if root is None:
        return checks
    order = profile_ids()
    reached = order.index(profile)
    return checks + tuple(
        check
        for check, declared_profile in app_declared_checks(root)
        if order.index(declared_profile) <= reached
    )


def verify_manifest(
    profile: str, root: pathlib.Path | None = None
) -> dict[str, object]:
    """The profile's check manifest as data (the ``--list --format json`` body).

    A driving tool configures its gate FROM this — the project's own pinned
    toolchain states what green means — instead of hardcoding a copy that
    drifts. ``command`` is the exact invocation ``terp verify`` itself runs.

    *root* includes the app's own ``[[tool.terp.verify.checks]]``, so a driving
    tool reading the manifest sees the whole gate rather than the platform half
    of it. Omitting it yields the platform floor.
    """
    checks = profile_checks(profile, root)
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


def _node_platform() -> tuple[str, str]:
    """This machine as npm names it — ``process.platform`` / ``process.arch``."""
    import platform as _platform

    system = {"win32": "win32", "darwin": "darwin"}.get(sys.platform, "linux")
    machine = _platform.machine().lower()
    arch = {
        "amd64": "x64",
        "x86_64": "x64",
        "aarch64": "arm64",
        "arm64": "arm64",
    }.get(machine, machine)
    return system, arch


def _node_libc(system: str) -> str | None:
    """This machine's libc flavour as npm names it, or None where npm ignores it.

    npm gates Linux binaries on ``libc`` as well as ``os``/``cpu``: a x64 Linux
    bundler ships a ``-gnu`` *and* a ``-musl`` binding and installs exactly one.
    Reading only ``os``/``cpu`` therefore reports the flavour this machine is not,
    turning a perfectly healthy tree red.
    """
    if system != "linux":
        return None
    return "musl" if any(pathlib.Path("/lib").glob("ld-musl-*.so.1")) else "glibc"


def _node_modules_problem(root: pathlib.Path) -> str | None:
    """Explain an unusable ``frontend/node_modules``, or None if it looks fine.

    An npm install is platform-specific: the native binaries a bundler needs are
    optional dependencies gated on ``os``/``cpu``, so a tree installed on the
    Windows host has no Linux binary, and running the gate in the container dies
    with a raw Node stack (``Cannot find module '@rolldown/binding-linux-x64-gnu'``)
    that names neither the cause nor the fix. Every Terp failure states the fix, so
    this is detected up front rather than left to the reader to decode.

    The lockfile already records which optional packages belong on which platform,
    so the check is exact and needs no list of native package names to maintain.
    """
    frontend = root / "frontend"
    if not (frontend / "package.json").is_file():
        return None
    modules = frontend / "node_modules"
    if not modules.is_dir():
        return (
            "frontend/node_modules is missing — the frontend checks cannot run.\n"
            "  Fix: npm --prefix frontend ci"
        )

    lockfile = frontend / "package-lock.json"
    if not lockfile.is_file():
        return None
    try:
        packages = json.loads(lockfile.read_text(encoding="utf-8")).get("packages", {})
    except (OSError, ValueError):
        return None

    system, arch = _node_platform()
    libc = _node_libc(system)
    missing = [
        name
        for name, entry in packages.items()
        if name.startswith("node_modules/")
        and isinstance(entry, dict)
        # Only packages this platform is *supposed* to have: an entry with no
        # os/cpu/libc constraint is platform-neutral, and one constrained elsewhere
        # is absent by design rather than by a bad install.
        and system in (entry.get("os") or [system])
        and arch in (entry.get("cpu") or [arch])
        and (libc is None or libc in (entry.get("libc") or [libc]))
        and (entry.get("os") or entry.get("cpu") or entry.get("libc"))
        and not (frontend / name).exists()
    ]
    if not missing:
        return None
    return (
        f"frontend/node_modules was installed for a different platform: "
        f"{len(missing)} package(s) this machine ({system}/{arch}) needs are absent, "
        f"e.g. {missing[0].removeprefix('node_modules/')}.\n"
        "  This happens when the tree is installed on the host and the gate runs in "
        "a container (or vice versa); native binaries are per-platform optional "
        "dependencies and do not travel.\n"
        "  Fix: npm --prefix frontend ci   (run it where the gate runs)"
    )


def _run_subprocess(check: VerifyCheck, root: pathlib.Path) -> tuple[int, str]:
    """Run one manifest command as a fixed argv, with no shell.

    No shell syntax is interpreted: a redirection, a pipe or a glob arrives as a
    literal argument. A declared check carrying ``&&`` or ``||`` unquoted is
    refused when it is read (:func:`_shell_separators_in`), because that one is
    always a mistake; the rest fail visibly at run time, on the command's own
    output, which is the right place for them.
    """
    argv = shlex.split(check.command)
    if argv and argv[0] == "npm":
        problem = _node_modules_problem(root)
        if problem is not None:
            return 1, problem
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
    return completed.returncode, completed.stdout + (
        "\n" + completed.stderr if completed.stderr else ""
    )


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


#: Shares the ``@terpjs/`` scope but is not part of the lockstep set: the npm
#: mirror of ``terp-spec``, released from the spec's own repository on its own
#: cadence (ADR 0082/0086) — the same exclusion ``installed_terp_versions``
#: makes for the backend spelling.
_INDEPENDENTLY_VERSIONED_NPM = frozenset({"@terpjs/spec"})

#: Directories whose package.json files describe someone else's package, not an
#: app manifest this gate should hold to the lockstep.
_MANIFEST_SKIP_DIRS = frozenset({"node_modules", ".venv", ".git", "dist", "build"})

_NPM_DEPENDENCY_KEYS = ("dependencies", "devDependencies", "peerDependencies")


def _terp_frontend_manifests(project_root: pathlib.Path) -> list[pathlib.Path]:
    """Every package.json in the app that declares a ``@terpjs/*`` dependency.

    Discovered, never a named list: the template ships ``@terpjs/*`` pins in TWO
    manifests (``frontend/package.json`` and ``conformance/package.json``), and a
    check that named only the frontend one would leave the other outside the
    ratchet — the exact hole the release gate already patched for its own tree.
    """
    manifests: list[pathlib.Path] = []
    for path in sorted(project_root.rglob("package.json")):
        if _MANIFEST_SKIP_DIRS & set(path.parts):
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue  # someone else's manifest problem, not a lockstep verdict
        if any(
            name.startswith("@terpjs/")
            for key in _NPM_DEPENDENCY_KEYS
            for name in (data.get(key) or {})
        ):
            manifests.append(path)
    return manifests


#: The npm scope Terp used before the rename to ``@terpjs/``. Nothing was ever
#: published under it, so a surviving declaration is not a stale pin that resolves
#: to an old release — it is a dependency that 404s the moment anyone installs it.
_LEGACY_NPM_SCOPE = "@terp/"


def _legacy_scope_problems(project_root: pathlib.Path) -> list[str]:
    """Every surviving ``@terp/*`` declaration (the scope before the rename).

    Read on its own rather than folded into the lockstep scan, which keys on
    ``@terpjs/*`` and therefore cannot see these: a manifest whose only Terp
    dependency is a legacy one declares no ``@terpjs/*`` at all, so
    ``_terp_frontend_manifests`` does not even collect it. That is how an app
    reaches CI with a ``conformance/package.json`` no registry can satisfy while
    this check — whose whole job is to refuse an install that was never a
    release — reports green and lets the rest of the profile run.
    """
    problems: list[str] = []
    for path in sorted(project_root.rglob("package.json")):
        if _MANIFEST_SKIP_DIRS & set(path.parts):
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue  # someone else's manifest problem, not a lockstep verdict
        rel = path.relative_to(project_root).as_posix()
        for key in _NPM_DEPENDENCY_KEYS:
            for name, declared in sorted((data.get(key) or {}).items()):
                if not name.startswith(_LEGACY_NPM_SCOPE):
                    continue
                renamed = f"@terpjs/{name[len(_LEGACY_NPM_SCOPE) :]}"
                problems.append(
                    f"{rel}: {name} is declared at {declared!r} under the "
                    f"pre-rename scope — use {renamed}"
                )
    return problems


def _frontend_lockstep_problems(project_root: pathlib.Path, platform: str) -> list[str]:
    """Every ``@terpjs/*`` declaration or installation not at *platform*."""
    problems: list[str] = []
    accepted = {f"^{platform}", platform}
    for manifest in _terp_frontend_manifests(project_root):
        rel = manifest.relative_to(project_root).as_posix()
        data = json.loads(manifest.read_text(encoding="utf-8"))
        for key in _NPM_DEPENDENCY_KEYS:
            for name, declared in sorted((data.get(key) or {}).items()):
                if not name.startswith("@terpjs/") or name in _INDEPENDENTLY_VERSIONED_NPM:
                    continue
                if declared not in accepted:
                    problems.append(
                        f"{rel}: {name} is declared at {declared!r} — pin ^{platform}"
                    )
                installed_manifest = (
                    manifest.parent / "node_modules" / name / "package.json"
                )
                if installed_manifest.is_file():
                    installed = json.loads(
                        installed_manifest.read_text(encoding="utf-8")
                    ).get("version")
                    if installed != platform:
                        problems.append(
                            f"{rel}: {name} is installed at {installed} — refresh "
                            "node_modules after repinning (npm install)"
                        )
    return problems


def _run_platform_install(project_root: pathlib.Path) -> tuple[int, str]:
    """Fail when the installed platform disagrees with itself — either half.

    Terp is versioned in lockstep (ADR 0063), so a set at two versions is not a
    supported combination — it is a pin someone forgot, and it fails in whatever
    way the skipped release happened to change. Verifying an app on such an
    install produces a verdict about a platform that was never released, in
    either direction, so this refuses rather than reports.

    The backend half reads the live environment (never a declared list), so a
    capability adopted after this was written is policed too. The frontend half
    reads every app manifest that declares a ``@terpjs/*`` package, plus the
    installed copy under its ``node_modules`` when present — because a frontend
    package left behind is the same mixed install by another route, and a check
    that read only ``metadata.distributions()`` passed it green: an app with
    ``@terpjs/react-core`` a release behind ``terp-core`` sailed through both
    this gate and the full profile. ``terp-spec`` / ``@terpjs/spec`` are
    excluded: released on their own cadence.
    """
    from terp.cli.version import (
        installed_terp_versions,
        platform_version,
        render_version,
    )

    versions = installed_terp_versions()
    if not versions:
        # The CLI running this is itself a terp-* distribution, so an empty set
        # means the environment cannot describe itself — not that Terp is absent.
        return 1, (
            "no terp-* distribution is visible in this environment, yet the terp "
            "CLI is running — its metadata is unreadable, so the platform version "
            "cannot be established.\n"
            "  Fix: uv sync --refresh"
        )
    if len(set(versions.values())) > 1:
        return 1, render_version()
    platform = platform_version(versions)
    legacy_problems = _legacy_scope_problems(project_root)
    if legacy_problems:
        return 1, (
            "the app declares npm packages under the pre-rename @terp/ scope:\n"
            + "".join(f"  {problem}\n" for problem in legacy_problems)
            + "Nothing was ever published under that scope, so these do not resolve "
            "to an older release — they 404 against the registry, and whichever job "
            "installs them dies before it verifies anything. The lockstep scan below "
            "cannot see them: it keys on @terpjs/*, so a manifest declaring only "
            "legacy names looks like it declares no Terp dependency at all.\n"
            f"  Fix: rename each to its @terpjs/* spelling pinned at ^{platform}, "
            "then reinstall the node_modules of that manifest."
        )
    frontend_problems = _frontend_lockstep_problems(project_root, platform)
    if frontend_problems:
        return 1, (
            f"the backend is consistent at terp {platform}, but the frontend half "
            "of the lockstep disagrees:\n"
            + "".join(f"  {problem}\n" for problem in frontend_problems)
            + "Terp releases backend and frontend packages from one tag; a "
            "@terpjs/* package left behind is a mixed install by another route, "
            "and it fails in whatever way the skipped release changed.\n"
            f"  Fix: pin every @terpjs/* package to ^{platform} in every manifest "
            "that declares one, then reinstall that manifest's node_modules."
        )
    manifest_count = len(_terp_frontend_manifests(project_root))
    return (
        0,
        f"terp {platform} ({len(versions)} distributions and "
        f"{manifest_count} frontend manifest(s), consistent)",
    )


def _run_routes_drift(root: pathlib.Path) -> tuple[int, str]:
    """Refuse a committed route table that no longer matches the module manifests.

    A no-op success until the app adopts route types (ADR 0092) — the same shape
    ``api-docs-drift`` has for an uncommitted ``docs/``. Upgrading the framework must not
    turn an app's gate red for a feature it has not wired yet; adding the ``routes``
    script is what turns the gate on.
    """
    from terp.cli.routes import ADOPT_HINT, routes_argv, routes_script_wired

    frontend = root / "frontend"
    if not frontend.is_dir():
        return 0, "no frontend/ - route types not applicable"
    if not routes_script_wired(frontend):
        # A note, not silence: this passes by SKIPPING, and the reader is the only one
        # who can turn it on. Announcing that only in `--format json` is how the opt-in
        # stayed unadopted.
        return (
            0,
            f"{NOTE_PREFIX}route types not adopted - drift check skipped ({ADOPT_HINT})",
        )
    problem = _node_modules_problem(root)
    if problem is not None:
        return 1, problem
    argv = routes_argv(check=True)
    executable = shutil.which(argv[0]) or argv[0]
    completed = subprocess.run(  # noqa: S603 - fixed manifest argv, shell=False
        [executable, *argv[1:]],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    return completed.returncode, f"{completed.stdout}{completed.stderr}"


#: What ``terp api-docs`` writes, relative to the output directory. Named here because the
#: adoption test below has to answer "is the generated pair tracked" BEFORE regenerating —
#: both so an unadopted project is not littered with two files it never asked for, and so
#: the diff can name them instead of the whole directory.
_API_DOCS_ARTIFACTS = ("platform-api.md", "terp_core.pyi")

_API_DOCS_ADOPT_HINT = "commit docs/platform-api.md + docs/terp_core.pyi to enable"


def _tracked(root: pathlib.Path, relative: str) -> bool:
    """Whether *relative* is a file git is tracking in *root*."""
    git = shutil.which("git") or "git"
    completed = subprocess.run(  # noqa: S603 - fixed argv, shell=False
        [git, "ls-files", "--error-unmatch", "--", relative],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    return completed.returncode == 0


def _run_api_docs_drift(root: pathlib.Path) -> tuple[int, str]:
    """Regenerate the API reference and fail on drift from the committed copy.

    A no-op success until the project **tracks** the generated pair — the same adoption
    shape ``routes-drift`` has, and for the same reason: upgrading the framework must not
    turn an app's gate red for a feature it never wired.

    "Tracked", specifically, and not "``docs/`` exists". The first version asked the
    directory question, then compared with ``git diff``, which reports nothing for an
    untracked file. Every app with a ``docs/`` directory of its own — which is most of
    them — therefore got a permanent green over a comparison that could not fail, plus
    two untracked files after every run. A check that cannot go red is worse than no
    check, because the profile counts it as evidence.

    Half-adopted is a **RED**, not a skip: with one of the pair tracked the diff silently
    covers half the surface, which is the same lie in miniature. And the diff names the
    two artifacts rather than ``docs/``, so an app's own uncommitted documentation edit is
    no longer reported as API drift.
    """
    from terp.cli import api_docs

    docs = root / "docs"
    if not docs.is_dir():
        return (
            0,
            f"{NOTE_PREFIX}no docs/ - api reference not adopted, drift check skipped "
            f"({_API_DOCS_ADOPT_HINT})",
        )
    relatives = [f"docs/{name}" for name in _API_DOCS_ARTIFACTS]
    tracked = [relative for relative in relatives if _tracked(root, relative)]
    if not tracked:
        return (
            0,
            f"{NOTE_PREFIX}api reference not tracked - drift check skipped "
            f"({_API_DOCS_ADOPT_HINT})",
        )
    if len(tracked) != len(relatives):
        missing = sorted(set(relatives) - set(tracked))
        return (
            1,
            "the api reference is half-tracked, so the drift check would cover half "
            f"the surface: {', '.join(missing)} is untracked. Commit it, or remove "
            f"{', '.join(tracked)} to opt out of the check entirely.",
        )
    previous = pathlib.Path.cwd()
    try:
        # api_docs writes relative to cwd through the live kernel import.
        os.chdir(root)
        written = [str(path) for path in api_docs(str(docs))]
    finally:
        os.chdir(previous)
    git = shutil.which("git") or "git"
    completed = subprocess.run(  # noqa: S603 - fixed argv, shell=False
        [git, "diff", "--exit-code", "--", *relatives],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    output = "\n".join(
        ["\n".join(f"wrote {path}" for path in written), completed.stdout]
    )
    if completed.returncode != 0:
        output += (
            "\napi docs drifted from the committed copy - commit the regenerated "
            f"{' + '.join(relatives)}"
        )
    return completed.returncode, output


def _run_package_boundaries(root: pathlib.Path) -> tuple[int, str]:
    """Run the app's own declared import contracts, if it declares any.

    ``terp guide package-boundaries`` tells an app to express a package boundary as
    import-linter contracts and run ``lint-imports`` in CI. This profile is documented as
    exactly what CI enforces, so leaving that command outside it made the two statements
    contradict each other — and the app is the half that pays: it writes a pytest wrapper
    shelling out to the console script, or forgets and ships a declared boundary that
    nothing verifies.

    Conditional on ``[tool.importlinter]``, read as TOML rather than matched as text: an
    app that declares only ``[[tool.importlinter.contracts]]`` still creates the table, and
    a substring test would also fire on the word inside a comment. An app with no contracts
    skips with a note, which is the same fail-open shape every other unadopted seam here
    has — upgrading the framework must never fail a gate for a feature the app never wired.

    Declared-but-unrunnable is a RED, not a skip. If contracts exist and ``lint-imports``
    is not installed, ``_run_subprocess`` answers 127 and names it: an app whose declared
    boundary cannot be checked has a broken gate, and reporting that as a pass is the
    failure this check exists to remove.
    """
    manifest = root / "pyproject.toml"
    if not manifest.is_file():
        return 0, "no pyproject.toml - package graph check not applicable"
    try:
        declared = tomllib.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        return 1, (
            f"pyproject.toml is unreadable ({exc}), so whether this app declares "
            "package boundaries cannot be established"
        )
    if not (declared.get("tool") or {}).get("importlinter"):
        return (
            0,
            f"{NOTE_PREFIX}no [tool.importlinter] in pyproject.toml - package graph "
            "check skipped (declare contracts to enable; see `terp guide "
            "package-boundaries`)",
        )
    return _run_subprocess(_PACKAGE_BOUNDARIES, root)


def _run_dependency_hygiene(root: pathlib.Path) -> tuple[int, str]:
    """Run deptry over the app, if the app declares it.

    Reads `[tool.deptry]` as TOML for the same reason `package-boundaries` reads
    `[tool.importlinter]`: declaring only `[tool.deptry.per_rule_ignores]` still
    creates the parent table, and a substring test would fire on the word in a
    comment.

    Not in any assurance lane. The spec's `dependency-audit` lane is normatively
    "both dependency trees against known-vulnerability databases" — a different
    question from "is what you import declared", and claiming this check there
    would widen a normative lane from the toolchain side. It carries the exit
    code instead, which is what makes it a control.
    """
    manifest = root / "pyproject.toml"
    if not manifest.is_file():
        return 0, "no pyproject.toml - dependency hygiene not applicable"
    try:
        declared = tomllib.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        return 1, (
            f"pyproject.toml is unreadable ({exc}), so whether this app declares "
            "dependency hygiene cannot be established"
        )
    # PRESENCE, not truthiness: `[tool.deptry]` with every setting left at its
    # default is an empty table, and an empty table is falsy. Testing the value
    # would silently skip the most ordinary way to adopt the tool — a fail-open
    # inside the check whose whole purpose is to stop a gate going green over
    # something nobody ran.
    if "deptry" not in (declared.get("tool") or {}):
        return (
            0,
            f"{NOTE_PREFIX}no [tool.deptry] in pyproject.toml - dependency hygiene "
            "skipped (declare it to enable: it answers whether every distribution "
            "this app imports is one it depends on; see `terp guide "
            "dependency-hygiene`)",
        )
    exit_code, output = _run_subprocess(_DEPENDENCY_HYGIENE, root)
    if exit_code != 0 and "deptry" in output and "not found" in output.lower():
        output += (
            "\n  This app declares [tool.deptry] but deptry is not installed, so the "
            "hygiene it declared is checked by nothing.\n"
            '  Fix: add "deptry>=0.20" to the dev dependency group.'
        )
    return exit_code, output


def _run_api_client(root: pathlib.Path) -> tuple[int, str]:
    """Generate the typed API client from the live backend contract.

    Not a drift check: the client is gitignored, so there is no committed copy to
    diff against. The verdict is whether it can be produced at all, and the
    artifact it leaves behind is what ``frontend-typecheck`` downstream of it
    reads — which is the whole reason it is ordered first. Skips with a note
    rather than a red for an app with no frontend or no ``generate`` script:
    upgrading the framework must not fail a gate for a seam the app never wired.
    """
    from terp.cli.openapi import export_openapi

    frontend = root / "frontend"
    if not frontend.is_dir():
        return 0, "no frontend/ - the API client is not applicable"
    manifest = frontend / "package.json"
    try:
        scripts = json.loads(manifest.read_text(encoding="utf-8")).get("scripts") or {}
    except (OSError, json.JSONDecodeError):
        return 1, (
            f"{manifest.relative_to(root).as_posix()} is unreadable, so whether this "
            "app generates an API client cannot be established"
        )
    if "generate" not in scripts:
        return (
            0,
            f"{NOTE_PREFIX}no `generate` script in frontend/package.json - API client "
            "codegen skipped (add one running openapi-typescript over ../openapi.json "
            "into ./src/api/schema.d.ts to enable)",
        )
    problem = _node_modules_problem(root)
    if problem is not None:
        return 1, problem
    previous = pathlib.Path.cwd()
    try:
        # export_openapi resolves the app package relative to its app_root.
        os.chdir(root)
        written = export_openapi(out="openapi.json", app_root=".")
    except SystemExit as refusal:  # an app ref that resolves to no FastAPI app
        return 1, f"could not export the OpenAPI document: {refusal}"
    finally:
        os.chdir(previous)
    argv = ["npm", "--prefix", "frontend", "run", "generate"]
    executable = shutil.which(argv[0]) or argv[0]
    completed = subprocess.run(  # noqa: S603 - fixed argv, shell=False
        [executable, *argv[1:]],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    output = f"wrote {written.name}\n{completed.stdout}{completed.stderr}"
    if completed.returncode != 0:
        output += (
            "\nthe API client could not be generated - the frontend typecheck "
            "downstream of this check reads what it writes, so its verdict would be "
            "about the missing client rather than about the app"
        )
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

    # Keyed by id over the NAMED composing checks only, so an app's declared
    # check contributes to no lane by construction: the lane vocabulary is the
    # spec's, and an app extending its own gate may not restate a normative
    # claim. Its verdict still carries the run's exit code in text/json.
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
    except (
        importlib.metadata.PackageNotFoundError
    ):  # a source checkout (the platform repo)
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
    project_root = pathlib.Path(root).resolve()
    resolved = profile_checks(profile, project_root)
    manifest = verify_manifest(profile, project_root)
    checks = list(resolved)
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
            for check in resolved:
                requires = f"  [requires {check.requires}]" if check.requires else ""
                print(f"  {check.id:<20} {check.command}{requires}")
        return 0

    results: list[dict[str, object]] = []
    all_ok = True
    for check in checks:
        print(f"verify: {check.id} ({check.command})", file=sys.stderr)
        reports: list[dict] = []
        if check.runner == "architecture":
            exit_code, output, reports = _run_architecture(project_root)
        elif check.runner == "platform-install":
            exit_code, output = _run_platform_install(project_root)
        elif check.runner == "api-docs-drift":
            exit_code, output = _run_api_docs_drift(project_root)
        elif check.runner == "api-client":
            exit_code, output = _run_api_client(project_root)
        elif check.runner == "package-boundaries":
            exit_code, output = _run_package_boundaries(project_root)
        elif check.runner == "dependency-hygiene":
            exit_code, output = _run_dependency_hygiene(project_root)
        elif check.runner == "routes-drift":
            exit_code, output = _run_routes_drift(project_root)
        elif check.runner == "env-seams":
            from terp.cli.envseams import run_env_seams_check

            exit_code, output = run_env_seams_check(project_root)
        elif check.runner == "workbench":
            from terp.cli.workbench import run_workbench_check

            exit_code, output = run_workbench_check(project_root)
        else:
            exit_code, output = _run_subprocess(check, project_root)
            reports = _reports_in(output)
        ok = exit_code == 0
        all_ok = all_ok and ok
        print(
            f"verify: {check.id} {'ok' if ok else f'FAILED (exit {exit_code})'}",
            file=sys.stderr,
        )
        if fmt == "text" and (not ok or output.startswith(NOTE_PREFIX)):
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
