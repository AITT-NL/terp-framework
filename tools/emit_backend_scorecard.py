"""Emit the Terp Standard conformance scorecard for ``terp.arch`` (the backend checker).

The scorecard (``scorecard.schema.json`` in the spec) turns "certified against
spec X.Y.Z" into a verifiable artifact instead of a claim: one entry per
catalog rule with its pass/fail verdict over the violation corpus, plus the
detector residuals the checker relies on (which must be a subset of the spec's
recorded ``corpus/RESIDUALS.json`` — claiming an unrecorded residual is a
conformance failure). A consumer re-runs the corpus and reproduces this file.

Run from the platform repo (the spec and the harness are installed there)::

    uv run python tools/emit_backend_scorecard.py --out scorecard-terp-arch.json

The verdicts here are the same contract ``tests/architecture/test_spec_corpus.py``
enforces test-by-test; the emitter self-validates against the checked-in schema
shape and refuses to write an invalid or failing scorecard (exit 1) — CI wires
it after the gate, so a published scorecard always describes a green harness.
"""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import pathlib
import re
import sys

import terp_spec

import terp.arch as arch

_SPEC = terp_spec.spec_dir()
_CATALOG = _SPEC / "catalog" / "backend"
_CORPUS = _SPEC / "corpus" / "backend"
_RULE_ID_RE = re.compile(r"^(backend/[a-z0-9_]+|frontend/[a-z0-9-]+)$")
_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")


def _run_rule(rule: str, app_root: pathlib.Path) -> list:
    """The reference check for *rule* (same dispatch as test_spec_corpus.py)."""
    if rule == "escape_hatch_budget":
        return arch.check_escape_hatch_budget(
            app_root, budget_path=app_root / "escape-hatch-budget.json"
        )
    if rule == "ungoverned_escape_hatch":
        return arch.ungoverned_marker_violations(app_root)
    return getattr(arch, f"check_{rule}")(app_root)


def _rule_passes(rule: str) -> bool:
    """The corpus contract for one rule: every violation case fires, every
    compliant case stays silent (attributed to this rule).

    Each case is copied to a scratch directory first (exactly as the corpus
    test does): the installed spec lives inside a ``.venv``/``site-packages``
    tree, whose path parts the arch scanner deliberately skips.
    """
    import shutil
    import tempfile

    for case in sorted((_CORPUS / rule).iterdir()):
        if not case.is_dir():
            continue
        with tempfile.TemporaryDirectory() as scratch:
            app_root = pathlib.Path(scratch) / "app"
            shutil.copytree(case, app_root)
            fired = {violation.rule for violation in _run_rule(rule, app_root)}
        if case.name.startswith("violation-") and rule not in fired:
            return False
        if case.name.startswith("compliant-") and rule in fired:
            return False
    return True


def build_scorecard() -> dict:
    """The terp-arch scorecard over the backend corpus (schema-shaped)."""
    residuals: dict[str, list[str]] = json.loads(
        (_SPEC / "corpus" / "RESIDUALS.json").read_text(encoding="utf-8")
    )["residuals"]
    try:
        version = importlib.metadata.version("terp-arch")
    except importlib.metadata.PackageNotFoundError:  # a source checkout
        version = "0"
    rules = []
    for path in sorted(_CATALOG.glob("*.json")):
        entry = json.loads(path.read_text(encoding="utf-8"))
        if not entry["corpus"]:
            continue
        claim: dict = {"rule": entry["id"], "pass": _rule_passes(path.stem)}
        claimed = residuals.get(entry["id"])
        if claimed:
            claim["residuals_claimed"] = list(claimed)
        rules.append(claim)
    return {
        "spec_version": terp_spec.spec_version(),
        "checker": {"tool": "terp-arch", "version": version},
        "rules": rules,
    }


def validate_scorecard(scorecard: dict) -> list[str]:
    """Hold the scorecard to its published contract (schema shape + residual
    subset + full-catalog coverage + a green harness); returns the problems."""
    problems: list[str] = []
    if not _SEMVER_RE.match(str(scorecard.get("spec_version", ""))):
        problems.append("spec_version is not a semver string")
    checker = scorecard.get("checker") or {}
    if not checker.get("tool") or not checker.get("version"):
        problems.append("checker must carry tool and version")
    rules = scorecard.get("rules") or []
    if not rules:
        problems.append("a scorecard without rule claims certifies nothing")
    residuals: dict[str, list[str]] = json.loads(
        (_SPEC / "corpus" / "RESIDUALS.json").read_text(encoding="utf-8")
    )["residuals"]
    catalogued = {
        json.loads(path.read_text(encoding="utf-8"))["id"]
        for path in _CATALOG.glob("*.json")
        if json.loads(path.read_text(encoding="utf-8"))["corpus"]
    }
    claimed_ids = set()
    for claim in rules:
        rule_id = str(claim.get("rule", ""))
        claimed_ids.add(rule_id)
        if not _RULE_ID_RE.match(rule_id):
            problems.append(f"bad rule id: {rule_id!r}")
        if not isinstance(claim.get("pass"), bool):
            problems.append(f"{rule_id}: pass must be a boolean")
        elif not claim["pass"]:
            problems.append(f"{rule_id}: the reference harness must pass its own corpus")
        for residual in claim.get("residuals_claimed", []):
            if residual not in residuals.get(rule_id, []):
                problems.append(f"{rule_id}: claims an unrecorded residual: {residual!r}")
    missing = catalogued - claimed_ids
    if missing:
        problems.append(f"corpus-covered rules missing a claim: {sorted(missing)}")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--out", default="", help="Write the scorecard here (default: stdout)"
    )
    args = parser.parse_args()
    scorecard = build_scorecard()
    problems = validate_scorecard(scorecard)
    if problems:
        for problem in problems:
            print(f"scorecard: {problem}", file=sys.stderr)
        return 1
    rendered = json.dumps(scorecard, indent=2) + "\n"
    if args.out:
        pathlib.Path(args.out).write_text(rendered, encoding="utf-8")
        print(
            f"wrote {args.out} ({len(scorecard['rules'])} rule claims, "
            f"spec {scorecard['spec_version']})",
            file=sys.stderr,
        )
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
