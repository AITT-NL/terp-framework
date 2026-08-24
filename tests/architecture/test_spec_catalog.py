"""'The spec can't lie': the Terp Standard catalog cannot drift from the live rules.

The implementation-parity half of the standard extraction (ADR 0080, extended by
ADRs 0081/0082): the spec's *self*-consistency (schema validity, versioning, the
refused surface's shape, the corpus ratchet) is validated by the spec's own
standalone suite (``spec/tests``); these meta-tests hold the catalog and the
*reference implementations* to each other, in both directions, following the same
completeness discipline as ``test_docs_parity`` and ``test_arch_harness``:

* every ``terp.arch`` rule (and the two budget rules) has exactly one backend
  catalog entry, and no backend entry outlives its rule;
* every named ``terp/*`` ESLint rule and every ``BOUNDARY_SPEC`` family the
  frontend catalog claims resolves to the real adapter/spec source;
* a ``runtime`` enforcement ref resolves to a real symbol in the cited package,
  and a ``black-box`` ref to a real ``@terpjs/conformance`` probe title.

The spec itself is consumed as a dependency (``terp-spec``), never a repo path —
the seam a repository split cuts along (ADR 0082).
"""

from __future__ import annotations

import json
import pathlib
import re

import pytest

from terp_spec import spec_dir

from terp.arch.rules import GUIDE_TOPIC_BY_RULE, _ALL_RULES

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_SPEC = spec_dir()
_CATALOG = _SPEC / "catalog"
_ESLINT_SRC = _REPO_ROOT / "packages" / "frontend" / "eslint-boundaries" / "src"
_CONFORMANCE = _REPO_ROOT / "packages" / "frontend" / "conformance"

# Where a `runtime` enforcement entry's tool lives — its ref must name a symbol
# defined in that source tree (the fail-closed runtime half of the two-layer rule).
_RUNTIME_TOOL_SOURCES = {
    "terp.core": _REPO_ROOT / "packages" / "backend" / "core" / "src" / "terp" / "core",
    "terp.migrations": _REPO_ROOT / "packages" / "backend" / "migrations" / "src" / "terp" / "migrations",
    "terp.capabilities.files": _REPO_ROOT / "packages" / "backend" / "capabilities" / "files" / "src" / "terp" / "capabilities" / "files",
    "@terpjs/react-core": _REPO_ROOT / "packages" / "frontend" / "react-core" / "src",
}


def _entries(surface: str) -> dict[str, dict]:
    entries: dict[str, dict] = {}
    for path in sorted((_CATALOG / surface).glob("*.json")):
        entry = json.loads(path.read_text(encoding="utf-8"))
        assert entry["id"] == f"{surface}/{path.stem}", (
            f"{path}: id {entry['id']!r} must match its path ({surface}/{path.stem})"
        )
        entries[path.stem] = entry
    return entries


def _backend_rule_names() -> set[str]:
    """The authoritative backend rule universe: _ALL_RULES + the two budget rules.

    ``GUIDE_TOPIC_BY_RULE`` is exactly that set — its own completeness against
    ``_ALL_RULES`` is already locked by the harness meta-tests.
    """
    in_registry = {rule.__name__.removeprefix("check_") for rule in _ALL_RULES}
    assert in_registry <= set(GUIDE_TOPIC_BY_RULE)
    return set(GUIDE_TOPIC_BY_RULE)


# --------------------------------------------------------------------------- #
# backend: catalog <-> terp.arch, both directions
# --------------------------------------------------------------------------- #
def test_backend_catalog_matches_the_rule_registry() -> None:
    rules = _backend_rule_names()
    catalogued = set(_entries("backend"))
    assert rules - catalogued == set(), (
        f"rules shipped without a spec/catalog/backend entry: {sorted(rules - catalogued)}"
    )
    assert catalogued - rules == set(), (
        f"catalog entries for rules that no longer exist: {sorted(catalogued - rules)}"
    )


def test_backend_entries_reference_real_checks_and_guide_topics() -> None:
    import terp.arch as arch

    for name, entry in _entries("backend").items():
        ref = entry["enforcement"][0]["ref"]
        assert hasattr(arch, ref), f"backend/{name}: enforcement ref {ref!r} is not on terp.arch"
        assert entry.get("guide_topic") == GUIDE_TOPIC_BY_RULE[name], (
            f"backend/{name}: guide_topic must match GUIDE_TOPIC_BY_RULE"
        )


def test_backend_opt_outs_are_the_live_suppression_tokens() -> None:
    """The catalog's `opt_out` spelling is the marker the harness actually honours.

    ``_apply_suppressions`` recognises exactly ``# {_rule_token(rule)}: <reason>``,
    so each entry's declared opt-out is held to that live derivation. An entry may
    omit ``opt_out`` only when it is an escape-hatch governance rule (whose
    violations are produced outside the suppression pass, so no marker can waive
    them — spec >= 0.6.0 omits exactly those).
    """
    from terp.arch.rules._support import _rule_token

    governance = {"escape_hatch_budget", "ungoverned_escape_hatch"}
    for name, entry in _entries("backend").items():
        opt_out = entry.get("opt_out")
        if opt_out is None:
            assert name in governance, (
                f"backend/{name}: only the escape-hatch governance rules may omit "
                "opt_out — every other rule declares its governed marker"
            )
            continue
        expected = f"# {_rule_token(name)}: <reason>"
        assert opt_out == expected, (
            f"backend/{name}: opt_out {opt_out!r} is not the live suppression token "
            f"({expected!r})"
        )


# --------------------------------------------------------------------------- #
# frontend: catalog <-> the ESLint adapter + BOUNDARY_SPEC, both directions
# --------------------------------------------------------------------------- #
_PLUGIN_RULE_RE = re.compile(r'^\s{4}"([a-z-]+)":\s', re.MULTILINE)


def _plugin_rule_ids() -> set[str]:
    """The named terp/* rules the ESLint plugin exports (parsed from its `rules:` map)."""
    source = (_ESLINT_SRC / "index.js").read_text(encoding="utf-8")
    match = re.search(r"\brules: \{\n((?:\s{4}\"[a-z-]+\":.*\n)+)\s*\},\n\};", source)
    assert match, "could not locate the plugin rules export in eslint-boundaries/src/index.js"
    return set(_PLUGIN_RULE_RE.findall(match.group(1)))


def test_frontend_catalog_covers_every_named_plugin_rule() -> None:
    entries = _entries("frontend")
    named = {
        name
        for name, entry in entries.items()
        if entry["enforcement"][0]["ref"].startswith("terp/")
    }
    plugin = _plugin_rule_ids()
    assert plugin - named == set(), (
        f"plugin rules without a spec/catalog/frontend entry: {sorted(plugin - named)}"
    )
    # A named entry outside the plugin map must still be a real reported rule id —
    # e.g. terp/escape-hatch is emitted by the suppression processor, not a plugin rule.
    index_source = (_ESLINT_SRC / "index.js").read_text(encoding="utf-8")
    for name in sorted(named - plugin):
        assert f'"terp/{name}"' in index_source, (
            f"catalog entry for a rule that is never reported: frontend/{name}"
        )
    for name in named:
        assert entries[name]["enforcement"][0]["ref"] == f"terp/{name}", (
            f"frontend/{name}: a named rule's ref must be terp/{name}"
        )


def test_frontend_family_entries_reference_real_spec_fields() -> None:
    spec_source = (_ESLINT_SRC / "spec.js").read_text(encoding="utf-8")
    for name, entry in _entries("frontend").items():
        ref = entry["enforcement"][0]["ref"]
        if ref.startswith("terp/"):
            continue
        field = ref.removeprefix("BOUNDARY_SPEC.")
        assert ref.startswith("BOUNDARY_SPEC.") and f"{field}:" in spec_source, (
            f"frontend/{name}: enforcement ref {ref!r} is not a BOUNDARY_SPEC field"
        )
        assert entry["enforcement"][0].get("reported_as"), (
            f"frontend/{name}: a family entry must say which ESLint rule it is reported_as"
        )


# --------------------------------------------------------------------------- #
# runtime + black-box enforcement refs resolve (the two-layer story is checkable)
# --------------------------------------------------------------------------- #
_DECLARATION_SCHEMA = _SPEC / "layout-declaration.schema.json"
_REACT_CORE_SRC = _REPO_ROOT / "packages" / "frontend" / "react-core" / "src"


def _resolver_vocabulary() -> tuple[set[str], dict[str, set[str]]]:
    """The top-level keys and per-key enums the reference resolver reads, from its source.

    Parsed as text for the reason the BOUNDARY_SPEC parity above is: this suite is
    Python and the resolver is TypeScript, and importing a bundler-resolved module
    to read two literals would buy nothing the regex does not.
    """
    source = (_REACT_CORE_SRC / "layoutDeclaration.ts").read_text(encoding="utf-8")
    top = re.search(r'new Set<string>\(\[([^\]]*)\]\)', source)
    assert top, "could not locate the top-level key set in layoutDeclaration.ts"
    keys = set(re.findall(r'"([a-zA-Z]+)"', top.group(1)))

    block = re.search(r"const SHELL_VALUES = \{\n(.*?)\n\} as const;", source, re.DOTALL)
    assert block, "could not locate SHELL_VALUES in layoutDeclaration.ts"
    values = {
        key: set(re.findall(r'"([a-z]+)"', listed))
        for key, listed in re.findall(r"(\w+): \[([^\]]*)\]", block.group(1))
    }
    return keys, values


def test_the_layout_declaration_vocabulary_matches_the_spec_schema() -> None:
    """Both directions, on every level, because each drift is a different defect.

    A key in the schema the resolver does not read is a declaration the standard
    promises and this stack silently ignores. A key the resolver reads that the
    schema does not name is this stack inventing normative vocabulary — the shape
    the standard's own linkage tests exist to refuse. And a value in one enum and
    not the other is worse than either: the app writes something the standard
    calls legal and the running app refuses, or the reverse, and the message
    blames the wrong side.

    Compared as SETS rather than sequences on purpose. The schema sorts its enums
    (its own well-formedness gate requires it, so a reader can scan them); the
    resolver lists them in the order a person would offer them — sidebar before
    header, because one is the default. Both orders are right for their audience
    and neither is normative.
    """
    if not _DECLARATION_SCHEMA.is_file():
        # The spec is pinned to one exact release (ADR 0086) and this schema lands in the
        # next one, so a pinned checkout legitimately predates it. Skipped with the reason
        # rather than asserted, because the alternative is pinning an unreleased spec to
        # satisfy a test — which is how a pin stops meaning "a release we shipped". The
        # moment the pin moves, this starts enforcing with no edit here.
        pytest.skip(
            f"the pinned terp-spec ships no layout-declaration.schema.json "
            f"({_DECLARATION_SCHEMA.parent}); it lands in the next spec release"
        )
    schema = json.loads(_DECLARATION_SCHEMA.read_text(encoding="utf-8"))
    keys, values = _resolver_vocabulary()

    assert keys == set(schema["properties"]), (
        "top-level layout declaration keys differ: "
        f"schema {sorted(set(schema['properties']))}, resolver {sorted(keys)}"
    )
    shell = schema["properties"]["shell"]["properties"]
    assert set(values) == set(shell), (
        f"shell keys differ: schema {sorted(shell)}, resolver {sorted(values)}"
    )
    for key in sorted(shell):
        assert values[key] == set(shell[key]["enum"]), (
            f"shell.{key} values differ: schema {sorted(shell[key]['enum'])}, "
            f"resolver {sorted(values[key])}"
        )


def test_runtime_enforcement_refs_resolve_to_real_symbols() -> None:
    """Every declared runtime ref names a real symbol in the cited package.

    This proves *nomination* — the named seam exists where the catalog says it
    lives — deliberately not behavior: the fail-closed conduct of each control
    is pinned by the framework's own behavioral suite (test_session_write_guard,
    test_jobs, test_core_app, test_object_authz, …), which is also what stops
    an adjacent namesake (e.g. an adapter method sharing the chokepoint's name)
    from silently standing in for a deleted control.
    """
    for surface in ("backend", "frontend"):
        for name, entry in _entries(surface).items():
            for enforcement in entry["enforcement"]:
                if enforcement["kind"] != "runtime":
                    continue
                source_root = _RUNTIME_TOOL_SOURCES.get(enforcement["tool"])
                assert source_root is not None, (
                    f"{surface}/{name}: unknown runtime tool {enforcement['tool']!r} "
                    f"(add it to _RUNTIME_TOOL_SOURCES)"
                )
                symbol = enforcement["ref"]
                pattern = re.compile(
                    rf"\b(?:class|(?:async\s+)?def|function)\s+{re.escape(symbol)}\b"
                )
                defined = any(
                    pattern.search(path.read_text(encoding="utf-8"))
                    for suffix in ("*.py", "*.ts", "*.tsx")
                    for path in source_root.rglob(suffix)
                )
                assert defined, (
                    f"{surface}/{name}: runtime ref {symbol!r} is not defined in "
                    f"{enforcement['tool']} sources"
                )


def test_black_box_enforcement_refs_resolve_to_conformance_probes() -> None:
    probe_titles = "\n".join(
        path.read_text(encoding="utf-8") for path in (_CONFORMANCE / "tests").glob("*.spec.ts")
    )
    black_box_layer_rules: set[str] = set()
    for surface in ("backend", "frontend"):
        for name, entry in _entries(surface).items():
            if entry["layer"] == "black-box":
                black_box_layer_rules.add(f"{surface}/{name}")
            for enforcement in entry["enforcement"]:
                if enforcement["kind"] != "black-box":
                    continue
                assert enforcement["tool"] == "@terpjs/conformance", (
                    f"{surface}/{name}: black-box enforcement runs via @terpjs/conformance"
                )
                assert f'"{enforcement["ref"]}"' in probe_titles, (
                    f"{surface}/{name}: black-box ref {enforcement['ref']!r} is not a "
                    "@terpjs/conformance test title"
                )
                black_box_layer_rules.discard(f"{surface}/{name}")
    assert black_box_layer_rules == set(), (
        "a rule classified layer=black-box must name its @terpjs/conformance probe "
        f"(a black-box enforcement entry): {sorted(black_box_layer_rules)}"
    )
