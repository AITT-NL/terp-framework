"""The rule catalog is self-consistent (ADR 0080, ADR 0203).

The catalog's own discipline, carried over from terp-spec when the rules moved here (ADR 0203).
``test_rule_catalog`` holds the catalog to the live implementations; this holds it to itself:

* every entry validates against the one catalog schema, under one id namespace;
* the escape-hatch contract is uniform, and runtime applicability is coherent per rule;
* the refused surface is well-formed, and every key of it is claimed by a rule;
* the corpus flag matches the cases on disk, and the two shrink-only ratchets
  (``PENDING.json`` and ``RESIDUALS.json``, one pair per surface) match the catalog;
* the normative prose (title, intent, escape) states the invariant without the
  implementation's vocabulary, and a runtime ref names a public symbol.
"""

from __future__ import annotations

import json
import re

from terp_spec import spec_dir

from terp.arch.deployment._jsonschema import check_schema, validate
from tests.architecture.rule_layout import (
    CATALOG_SCHEMA,
    RESTRICTED_SURFACE,
    SURFACES,
    catalog_dir,
    corpus_dir,
    corpus_root,
    entries,
)


def _problems(instance: object, schema: dict, where: str) -> list[str]:
    return [f"{where}{'.' + problem.path if problem.path else ''}: {problem.detail}" for problem in validate(instance, schema)]


# --------------------------------------------------------------------------- #
# schema validity: every entry validates against the one catalog schema
# --------------------------------------------------------------------------- #
def test_every_catalog_entry_validates_against_the_catalog_schema() -> None:
    schema = json.loads(CATALOG_SCHEMA.read_text(encoding="utf-8"))
    check_schema(schema)
    for surface in SURFACES:
        for name, entry in entries(surface).items():
            assert _problems(entry, schema, f"{surface}/{name}") == []
            assert entry["surface"] == surface, f"{surface}/{name}: wrong surface"
            kinds = [enforcement["kind"] for enforcement in entry["enforcement"]]
            assert kinds[0] == "build-time", (
                f"{surface}/{name}: the first enforcement entry is the build-time reference"
            )


def test_rule_names_are_unique_across_surfaces() -> None:
    """One id namespace: a rule name means one rule, whichever package ships it."""
    backend, frontend = set(entries("backend")), set(entries("frontend"))
    assert backend & frontend == set(), f"names used on both surfaces: {sorted(backend & frontend)}"


# --------------------------------------------------------------------------- #
# the escape-hatch contract is uniform: a marker names the CATALOG RULE NAME
# (never a tool-internal rule id — the suppression analogue of findings
# attribution), and the governance rules themselves carry no opt-out
# --------------------------------------------------------------------------- #
_GOVERNANCE_RULES_WITHOUT_OPT_OUT = {
    "backend/escape_hatch_budget",
    "backend/ungoverned_escape_hatch",
    "frontend/escape-hatch",
}

#: Rules whose subject is a checked-in declaration that cannot carry an inline marker - a
#: JSON document has no comments - so their one governed way out is a state of the
#: declaration itself, stated in the entry's `escape` field. The render rule's subject is the
#: build files a declaration makes generated: a marker in a file the generator rewrites would
#: be erased by the next render, so the declaration's own state is the way out there too.
#: Listed by name: an entry cannot grant itself this by declaring `escape`.
_RULES_ESCAPED_BY_THEIR_DECLARATION = {
    "backend/deployment_declaration_is_readable",
    "backend/deployment_declaration_tells_the_truth",
    "backend/deployment_generated_files_match_their_render",
}

#: Rules with no way out at all, because the way out is the rule's own subject: a migration
#: revision that needs an operation off the expand list declares that it is not expand-only.
#: Listed by name: an entry cannot grant itself this by omitting `opt_out`.
_RULES_WITHOUT_A_WAY_OUT = {
    "backend/expand_revisions_only_expand",
}

_OPT_OUT_TEMPLATES = {
    "backend": "# arch-allow-{name}: <reason>",
    "frontend": "// terp-allow-{name}: <reason>",
}


def test_opt_outs_derive_from_the_catalog_rule_name() -> None:
    """Every opt-out marker spelling is the rule's own catalog name (backend snake_case
    rendered with dashes), so a marker can never waive a sibling rule that happens to share
    a tool-internal rule id; the escape-hatch governance rules declare no opt-out, because
    governance cannot be waived by the mechanism it governs; and a rule over a declaration
    that cannot carry a marker declares its `escape` instead, never beside an opt_out."""
    for surface in SURFACES:
        for name, entry in entries(surface).items():
            rule_id = f"{surface}/{name}"
            opt_out = entry.get("opt_out")
            escape = entry.get("escape")
            if rule_id in _RULES_ESCAPED_BY_THEIR_DECLARATION:
                assert opt_out is None and escape, (
                    f"{rule_id}: a rule escaped by its declaration states that escape in "
                    "`escape` and declares no opt_out marker it could never carry"
                )
                continue
            assert escape is None, (
                f"{rule_id}: only a rule listed as escaped by its declaration may declare "
                "`escape` — every other rule's way out is its marker"
            )
            if rule_id in _GOVERNANCE_RULES_WITHOUT_OPT_OUT:
                assert opt_out is None, (
                    f"{rule_id}: an escape-hatch governance rule must not declare an "
                    "opt_out — waiving governance with governance is refused"
                )
                continue
            if rule_id in _RULES_WITHOUT_A_WAY_OUT:
                assert opt_out is None, (
                    f"{rule_id}: a rule whose way out is its own subject declares no "
                    "opt_out marker"
                )
                continue
            expected = _OPT_OUT_TEMPLATES[surface].format(name=name.replace("_", "-"))
            assert opt_out == expected, (
                f"{rule_id}: opt_out must name the catalog rule ({expected!r}), got {opt_out!r}"
            )


# --------------------------------------------------------------------------- #
# runtime applicability: every rule states whether the two-layer discipline pairs
# it with a fail-closed runtime control, and the statement is coherent (ADR 0084)
# --------------------------------------------------------------------------- #
def test_runtime_applicability_is_coherent() -> None:
    for surface in SURFACES:
        for name, entry in entries(surface).items():
            runtime = entry["runtime"]
            applicability = runtime["applicability"]
            kinds = {enforcement["kind"] for enforcement in entry["enforcement"]}
            if applicability == "required":
                assert "runtime" in kinds, (
                    f"{surface}/{name}: runtime.applicability is 'required' but no "
                    "enforcement entry has kind 'runtime' — declare the fail-closed "
                    "runtime control (tool + ref), or reclassify with a rationale"
                )
            else:
                assert "runtime" not in kinds, (
                    f"{surface}/{name}: a kind 'runtime' enforcement entry exists but "
                    f"runtime.applicability is {applicability!r} — a declared runtime "
                    "control means the rule is 'required'"
                )
                assert runtime.get("rationale", "").strip(), (
                    f"{surface}/{name}: runtime.applicability {applicability!r} is an "
                    "exemption from the two-layer discipline and must carry a non-empty "
                    "rationale"
                )
            if applicability == "deferred":
                assert runtime.get("tracking", "").strip(), (
                    f"{surface}/{name}: a deferred runtime control is an explicit, reviewed "
                    "gap and must carry a 'tracking' reference naming where it is tracked"
                )
            else:
                assert "tracking" not in runtime, (
                    f"{surface}/{name}: runtime.tracking is the deferral lifecycle field "
                    f"and is meaningless for {applicability!r}"
                )


# --------------------------------------------------------------------------- #
# the refused surface is well-formed, and every key of it is claimed by a rule
# (the adapter-side parity lives in eslint-boundaries/src/surface.test.js)
# --------------------------------------------------------------------------- #
_SURFACE_LIST_KEYS = (
    "restrictedElements",
    "restrictedAttributes",
    "restrictedGlobals",
    "restrictedMemberCalls",
    "styleImportExtensions",
    "deepImportPathSegments",
)


def test_the_refused_surface_is_well_formed() -> None:
    surface = json.loads(RESTRICTED_SURFACE.read_text(encoding="utf-8"))
    for key in _SURFACE_LIST_KEYS:
        values = surface[key]
        assert isinstance(values, list) and values, f"{key}: must be a non-empty array"
        assert all(isinstance(v, str) and v.strip() for v in values), (
            f"{key}: entries must be non-empty strings"
        )
        assert values == sorted(values) and len(values) == len(set(values)), (
            f"{key}: entries must be sorted and unique"
        )


def test_catalog_citations_of_the_refused_surface_resolve() -> None:
    """A rule's ``restricted_surface`` field lists the refused-surface keys it realises;
    every key must be claimed by some rule (an unclaimed key is dead data), and a prose
    mention in ``intent`` must agree with the field, which is authoritative."""
    cited: set[str] = set()
    for surface in SURFACES:
        for name, entry in entries(surface).items():
            declared = set(entry.get("restricted_surface", []))
            assert declared <= set(_SURFACE_LIST_KEYS), (
                f"{surface}/{name}: restricted_surface cites unknown keys "
                f"{sorted(declared - set(_SURFACE_LIST_KEYS))}"
            )
            cited |= declared
            for match in re.finditer(r"restricted-surface\.json \(([A-Za-z, ]+)\)", entry["intent"]):
                prose = {part.strip() for part in match.group(1).split(",")}
                assert prose <= declared, (
                    f"{surface}/{name}: intent prose cites refused-surface keys "
                    f"{sorted(prose - declared)} the restricted_surface field does not "
                    "declare — the field is the structural citation; keep them in agreement"
                )
    assert cited == set(_SURFACE_LIST_KEYS), (
        "every refused-surface key must be claimed by a catalog entry's restricted_surface "
        f"field (an unclaimed key is dead data): unclaimed {sorted(set(_SURFACE_LIST_KEYS) - cited)}"
    )


def test_the_layout_declaration_is_claimed_by_a_rule() -> None:
    """The layout declaration is a contract in the shared package (ADR 0203), and the rule
    that enforces the contract an app opts into must cite it, or the two drift apart."""
    claimants = [
        f"frontend/{name}"
        for name, entry in entries("frontend").items()
        if "layout-declaration.schema.json" in entry.get("reference", "")
        or "layout-declaration.schema.json" in entry["intent"]
    ]
    assert claimants, "no catalog entry cites layout-declaration.schema.json"


# --------------------------------------------------------------------------- #
# the corpus: flags match the cases on disk, and the coverage ratchet matches
# --------------------------------------------------------------------------- #
def test_corpus_flags_match_the_corpus_directories() -> None:
    for surface in SURFACES:
        catalogued = entries(surface)
        cases_root = corpus_dir(surface)
        on_disk = {p.name for p in cases_root.iterdir() if p.is_dir()}
        flagged = {name for name, entry in catalogued.items() if entry["corpus"]}
        assert on_disk - set(catalogued) == set(), (
            f"{surface}: corpus directories without a catalog entry: {sorted(on_disk - set(catalogued))}"
        )
        assert flagged == on_disk, (
            f"{surface}: corpus flags disagree with {cases_root} — flagged but missing "
            f"{sorted(flagged - on_disk)}, present but unflagged {sorted(on_disk - flagged)}"
        )
        for name in on_disk:
            cases = {p.name for p in (cases_root / name).iterdir() if p.is_dir()}
            assert any(case.startswith("violation-") for case in cases), (
                f"{surface}/{name}: corpus needs at least one violation-* case"
            )
            assert any(case.startswith("compliant-") for case in cases), (
                f"{surface}/{name}: corpus needs at least one compliant-* case"
            )
            assert all(case.startswith(("violation-", "compliant-")) for case in cases), (
                f"{surface}/{name}: unexpected case directories {sorted(cases)}"
            )


def test_the_pending_corpus_ratchet_matches_the_catalog() -> None:
    """Each surface's ``PENDING.json`` lists exactly its rules still without corpus cases,
    and only shrinks: a rule without cases is listed explicitly, never silently."""
    for surface in SURFACES:
        pending = set(json.loads((corpus_root(surface) / "PENDING.json").read_text(encoding="utf-8"))["pending"])
        uncovered = {f"{surface}/{name}" for name, entry in entries(surface).items() if not entry["corpus"]}
        assert pending == uncovered, (
            f"{surface}: PENDING.json disagrees with the catalog — seeded but still listed: "
            f"{sorted(pending - uncovered)}; uncovered but unlisted: {sorted(uncovered - pending)}"
        )


def test_every_portable_backend_rule_has_corpus_cases() -> None:
    """The corpus is each rule's executable meaning, so every static-portable backend rule
    ships cases; the pending ratchet governs only the bespoke remainder."""
    uncovered = [
        name
        for name, entry in entries("backend").items()
        if entry["layer"] == "static-portable" and not entry["corpus"]
    ]
    assert uncovered == [], f"static-portable backend rules without corpus cases: {sorted(uncovered)}"


def test_the_residual_ratchets_are_well_formed() -> None:
    """``RESIDUALS.json`` records the forms a precise, low-false-positive checker deliberately
    does not catch, per rule, as shrink-only data. Closing one means seeding the corpus case
    that contracts it and deleting the entry, never silently."""
    for surface in SURFACES:
        residuals = json.loads((corpus_root(surface) / "RESIDUALS.json").read_text(encoding="utf-8"))["residuals"]
        catalogued = {f"{surface}/{name}" for name in entries(surface)}
        assert list(residuals) == sorted(residuals), f"{surface}: residual rule ids must be sorted"
        for rule, forms in residuals.items():
            assert rule in catalogued, (
                f"{surface}/RESIDUALS.json names {rule!r}, which is not a {surface} catalog rule"
            )
            assert isinstance(forms, list) and forms, (
                f"{rule}: residuals must be a non-empty array (an empty list is a closed "
                "residual — delete the key)"
            )
            assert all(isinstance(form, str) and form.strip() for form in forms), (
                f"{rule}: each residual is a non-empty description of the out-of-contract form"
            )
            assert len(forms) == len(set(forms)), f"{rule}: duplicate residual entries"


def test_expected_findings_manifests_are_coherent() -> None:
    """A corpus case MAY ship ``expected-findings.json``: the exact findings (path and line)
    the checker emits for the rule under test, in the finding format, a contract read from
    the shared package. Every manifest is held to that shape and to the case it sits in."""
    findings_schema = json.loads((spec_dir() / "findings.schema.json").read_text(encoding="utf-8"))
    for surface in SURFACES:
        root = corpus_root(surface)
        for manifest in sorted(root.glob("*/*/*/expected-findings.json")):
            case_dir = manifest.parent
            rule_id = f"{case_dir.parent.parent.name}/{case_dir.parent.name}"
            findings = json.loads(manifest.read_text(encoding="utf-8"))
            assert _problems(findings, findings_schema, str(manifest.relative_to(root))) == []
            assert case_dir.name.startswith("violation-"), (
                f"{manifest}: only a violation-* case carries expected findings"
            )
            assert findings, f"{manifest}: a violation case's manifest must be non-empty"
            for finding in findings:
                assert finding["rule"] == rule_id, (
                    f"{manifest}: finding attributed to {finding['rule']!r}, but the case "
                    f"belongs to {rule_id!r}"
                )
                assert (case_dir / finding["path"]).is_file(), (
                    f"{manifest}: finding path {finding['path']!r} does not exist in the case"
                )
                assert "line" in finding, f"{manifest}: an expected finding pins the violating line"


# --------------------------------------------------------------------------- #
# the normative prose names the invariant, not the implementation: title, intent
# and escape are what a rule page and `terp guide` show a person, and they stay
# true across a refactor only while they cite no symbol, path or marker
# --------------------------------------------------------------------------- #
_REFERENCE_VOCABULARY: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"``"), "RST literal markup — write plain prose"),
    (re.compile(r":[a-z]+:`"), "a Sphinx role — write plain prose"),
    (re.compile(r"\bterp\.[a-z_]"), "a terp.* package path — belongs in reference / enforcement"),
    (re.compile(r"@terpjs?/"), "an @terpjs/* package path — belongs in reference / enforcement"),
    (re.compile(r"\bterp +(?:check|guide|migrate)\b"), "the CLI — belongs in reference"),
    (re.compile(r"(?:arch|terp)-allow"), "a marker spelling — belongs in opt_out / reference"),
    (re.compile(r"\bADR +\d"), "an ADR pointer — the intent states the reason itself"),
    (
        re.compile(
            r"\b(?:BaseService|BaseTable|BaseSchema|BaseUpdateSchema|ModuleSpec|SessionDep"
            r"|create_app|FastAPI|SQLModel|sqlmodel|SQLAlchemy|sqlalchemy|Alembic|alembic"
            r"|base_query|business_filters|response_model|TenantScopedService|TenantScopedMixin"
            r"|SoftDeleteMixin|OwnedMixin|ActorStampedMixin|FileRef|WriteGuardedSession"
            r"|ControlPlane|EventDefinition|JobDefinition|LifecycleEventMap|PaginationDep"
            r"|SecurityConfig|configure_logging|basicConfig|dictConfig|fileConfig"
            r"|dependency_overrides|add_middleware|BaseHTTPMiddleware|assert_app_clean"
            r"|ArchViolation|assert_migrations_current|create_all|httpx|Celery|APScheduler"
            r"|React)\b"
        ),
        "an implementation symbol — belongs in reference / enforcement",
    ),
    (
        re.compile(r"Page\[|Policy\.[a-z_]|Roles\.[A-Z]"),
        "an implementation API shape — belongs in reference / enforcement",
    ),
]


def test_normative_prose_carries_no_implementation_vocabulary() -> None:
    """``title``, ``intent`` and ``escape`` state the invariant; ``enforcement``,
    ``reference``, ``opt_out`` and ``guide_topic`` carry how this framework realises it.
    Sibling rules are cited by catalog rule name, which is catalog vocabulary, so rule
    names are removed before matching. This checks words, not portability: the rules are
    written against this framework's architecture (ADR 0203)."""
    rule_names = sorted(
        (name for surface in SURFACES for name in entries(surface)), key=len, reverse=True
    )
    problems: list[str] = []
    for surface in SURFACES:
        for name, entry in entries(surface).items():
            if entry["intent"].strip() == entry["title"].strip():
                problems.append(f"{surface}/{name}: intent merely repeats the title — say why the rule exists")
            for field in ("title", "intent", "escape"):
                if field not in entry:
                    continue
                text = entry[field]
                for token in rule_names:
                    text = text.replace(token, " ")
                for pattern, why in _REFERENCE_VOCABULARY:
                    match = pattern.search(text)
                    if match:
                        problems.append(f"{surface}/{name}.{field}: {match.group(0)!r} is {why}")
    assert problems == [], "normative prose must name the invariant, not the implementation:\n" + "\n".join(problems)


def test_no_runtime_ref_names_a_private_symbol() -> None:
    """A ``runtime`` enforcement ref is what a rule page and the catalog cite as the control,
    so it names a stable, public seam. A private name says "this may be renamed without
    notice" about the very symbol the catalog cites. A class name is fine where the control
    is a method on a public class: the class is the nameable seam."""
    offenders = [
        f"{entry['id']} -> {enforcement['ref']}"
        for surface in SURFACES
        for entry in entries(surface).values()
        for enforcement in entry.get("enforcement", [])
        if enforcement.get("kind") == "runtime"
        and (enforcement["ref"].startswith("_") or "._" in enforcement["ref"])
    ]
    assert offenders == [], (
        f"these rules cite a private symbol as their runtime enforcement ref: {offenders} — "
        "promote the symbol, or name the public class that carries it"
    )


def test_every_catalog_directory_holds_only_entries() -> None:
    """A stray file in a catalog directory is either an entry with the wrong name or data no
    test reads; both are refused."""
    for surface in SURFACES:
        stray = sorted(p.name for p in catalog_dir(surface).iterdir() if p.suffix != ".json")
        assert stray == [], f"{catalog_dir(surface)} holds files that are not entries: {stray}"
