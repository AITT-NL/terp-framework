#!/usr/bin/env python3
"""Generate the plain-language rule pages (docs/rules/) from the catalog.

The catalog is data-first precisely so consumers can be generated from it;
this is the non-technical-reader consumer: one Markdown page per rule stating
what the rule is, why it exists, what to do instead, and how to opt out —
without reading JSON. The pages are checked in and held to the catalog by
``tests/architecture/test_rule_docs.py`` (regenerate-and-compare). The catalog
is split by surface (ADR 0203): the backend half ships with terp-arch, the
frontend half with @terpjs/eslint-boundaries.

Usage: python tools/generate_rule_docs.py   (from the repository root; stdlib only)
"""

from __future__ import annotations

import json
import os
import pathlib

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_ARCH = _ROOT / "packages" / "backend" / "arch"
_BOUNDARIES = _ROOT / "packages" / "frontend" / "eslint-boundaries"
_CATALOGS = {
    "backend": _ARCH / "src" / "terp" / "arch" / "catalog" / "backend",
    "frontend": _BOUNDARIES / "catalog" / "frontend",
}
_RESIDUALS = {
    "backend": _ARCH / "corpus" / "RESIDUALS.json",
    "frontend": _BOUNDARIES / "corpus" / "RESIDUALS.json",
}
_DOCS = _ROOT / "docs" / "rules"

_RUNTIME_LABEL = {
    "required": "Yes — the framework also enforces this while the app runs (fail closed).",
    "not-applicable": "No — this is a property of the written source only; the build-time check is the control, by recorded decision.",
    "deferred": "Not yet — a runtime control is planned; the gap is explicit and tracked.",
}

#: The escape-hatch governance rules: the ones whose missing opt-out is because they
#: govern the mechanism. Any other rule without an opt-out has its way out in its intent.
_GOVERNANCE_RULES = frozenset(
    {"backend/escape_hatch_budget", "backend/ungoverned_escape_hatch", "frontend/escape-hatch"}
)


def render(entry: dict, residuals: list[str] | None = None) -> str:
    """The Markdown page for one catalog entry (deterministic).

    *residuals* is the rule's entry in its corpus's ``RESIDUALS.json``. Those are held
    as data, for whoever writes the check; a person reading the rule could not see
    them, so the one place stating where a rule's detection ends was the one place a
    non-technical reader does not go. Publishing them here is what makes the boundary
    a statement rather than an omission — and the section says plainly that a residual
    is a limit of the *check*, not permission to write the form.
    """
    surface, name = entry["id"].split("/", 1)
    lines = [
        f"# `{entry['id']}`",
        "",
        f"**{entry['title']}**",
        "",
        "> Generated from the catalog by `tools/generate_rule_docs.py` — do not",
        "> edit by hand; the parity test holds this page to",
        f"> `{_CATALOGS[surface].joinpath(name + '.json').relative_to(_ROOT).as_posix()}`.",
        "",
        "## Why this rule exists",
        "",
        entry["intent"],
        "",
    ]
    if entry.get("reference"):
        # NOT "What to do instead". The `reference` field is reference-implementation
        # metadata, and across the catalog it carries two different kinds of sentence:
        # roughly half say what the compliant code looks like (remediation) and roughly
        # half say what the check flags and what it deliberately ignores (detection).
        # Published under a remediation heading, every entry of the second kind reads as
        # advice — `no_todo_fixme`'s page told the reader to "instead" do what is in fact
        # a description of the matcher. One heading that is true of both is a better
        # answer than a field split nothing downstream distinguishes: the finding
        # envelope's `fix_hint` is sourced from the rule's guide topic, not
        # from here.
        lines += [
            "## How Terp realises this",
            "",
            entry["reference"],
            "",
        ]
    lines += [
        "## If you really need an exception",
        "",
    ]
    if entry.get("opt_out"):
        lines += [
            "Add a justified marker on (or immediately above) the line, and record it",
            "in your app's escape-hatch budget:",
            "",
            "```",
            entry["opt_out"],
            "```",
            "",
            "An unjustified marker is itself a violation, and marker counts must",
            "exactly match the checked-in budget (which can only shrink).",
            "",
        ]
    elif entry.get("escape"):
        # A rule over a declaration that cannot carry a marker (a JSON document has no
        # comments). Its way out is a state of the declaration, and saying "add a marker"
        # here would send a reader looking for a comment syntax the file does not have.
        lines += [
            "This rule's subject is a checked-in declaration that cannot carry an",
            "inline marker, so there is no marker to add. The declaration itself",
            "states the exception:",
            "",
            entry["escape"],
            "",
        ]
    elif entry["id"] in _GOVERNANCE_RULES:
        lines += [
            "There is none. This rule governs the escape-hatch mechanism itself,",
            "so it cannot be waived by that mechanism.",
            "",
        ]
    else:
        # A rule whose way out is its own subject: what a reader does instead is the other
        # answer the rule allows, which its intent states, never a marker.
        lines += [
            "There is none, and no marker suppresses a finding: the way out is the",
            "other answer the rule itself allows, which the intent above states.",
            "",
        ]
    if residuals:
        lines += [
            "## What the check is not required to catch",
            "",
            "A check precise enough to have no false positives has limits. This",
            "rule's limits are recorded as data (its corpus's `RESIDUALS.json`), so",
            "where detection ends is a statement rather than a guess:",
            "",
        ]
        lines += [f"- {residual}" for residual in residuals]
        lines += [
            "",
            "**These are not exemptions.** The rule governs those forms exactly as it",
            "governs any other — a checker is simply not required to find them, so",
            "review is the control there. The list only shrinks: closing one means",
            "adding the corpus case that contracts it.",
            "",
        ]
    lines += [
        "## Enforcement",
        "",
        f"- Checked while the app runs? {_RUNTIME_LABEL[entry['runtime']['applicability']]}",
    ]
    for enforcement in entry["enforcement"]:
        lines.append(
            f"- `{enforcement['kind']}`: `{enforcement['tool']}` — `{enforcement['ref']}`"
        )
    lines.append("")
    return "\n".join(lines)


def generate() -> dict[pathlib.Path, str]:
    """Every page the catalog implies, as {absolute path: content}."""
    pages: dict[pathlib.Path, str] = {}
    for surface in ("backend", "frontend"):
        residuals = json.loads(_RESIDUALS[surface].read_text(encoding="utf-8"))["residuals"]
        for path in sorted(_CATALOGS[surface].glob("*.json")):
            entry = json.loads(path.read_text(encoding="utf-8"))
            pages[_DOCS / surface / f"{path.stem}.md"] = render(
                entry, residuals.get(entry["id"])
            )
    return pages


def main() -> None:
    pages = generate()
    for path, content in pages.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    print(f"wrote {len(pages)} rule pages under {os.path.relpath(_DOCS, _ROOT)}/")


if __name__ == "__main__":  # pragma: no cover - entry point
    main()
