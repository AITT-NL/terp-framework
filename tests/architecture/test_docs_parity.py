"""'Docs can't lie': the agent-facing surface cannot drift from the live registries.

This is the build-time **documentation-completeness** control for Terp's agent
experience (AGENTIC_PLATFORM_DESIGN §8 — the "Docs can't lie" parity test; the
ADR-0019 "docs can't lie" backlog item; ADR 0030). It mirrors the two completeness
guards the platform already trusts:

* the harness self-completeness meta-test
  (``test_arch_harness.test_harness_registers_and_tests_every_rule``), and
* the capability drift guard
  (``test_capability_arch.test_every_built_capability_is_covered``).

Apply that same instinct to what an *agent in a consumer repo* actually reads — its
``AGENTS.md`` and ``terp guide`` — so the gate refuses to go green when a new rule /
trait / seam ships undocumented, or a stale "enforced by X" claim rots.

Two-layer note (ADR 0006): the two-layer *runtime + build-time* discipline governs
**security** controls. This is a documentation-coverage control, so there is no
spurious "runtime half"; instead the structural guarantee is **generate, don't
duplicate** — the enforced-rules surface (`terp guide rules`) is a *projection* of
``terp.arch.rules._ALL_RULES``, so it cannot drift from the rules it documents. These
meta-tests guard the hand-written remainder (the recipes, the golden-rule lines).
"""

from __future__ import annotations

import ast
import pathlib
import re
import sys

# terp-cli is not pip-installed in the dev venv; inject its src (as the other CLI tests do).
_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_CLI_SRC = _REPO_ROOT / "packages" / "backend" / "cli" / "src"
sys.path.insert(0, str(_CLI_SRC))

from terp.arch.rules import _ALL_RULES  # noqa: E402  (import after sys.path setup)
from terp.cli import guide, guide_topics  # noqa: E402
from terp.core import __all__ as _CORE_ALL  # noqa: E402

# The three surfaces an agent actually reads (design §8 names AGENTS.md; the consumer
# bootstrap pointer is template/AGENTS.md; the live recipes are `terp guide`).
_AGENTS_MD = _REPO_ROOT / "AGENTS.md"
_TEMPLATE_AGENTS_MD = _REPO_ROOT / "template" / "AGENTS.md"
_TESTS_ROOT = _REPO_ROOT / "tests"


def _rule_names() -> set[str]:
    """Every architecture rule, by the bare name the docs use (no ``check_`` prefix)."""
    return {rule.__name__.removeprefix("check_") for rule in _ALL_RULES}


def _full_guide_text() -> str:
    """The entire `terp guide` surface: the overview + every topic body."""
    return "\n".join([guide(), *(guide(topic) for topic in guide_topics())])


def _doc_surfaces() -> dict[str, str]:
    return {
        "AGENTS.md": _AGENTS_MD.read_text(encoding="utf-8"),
        "template/AGENTS.md": _TEMPLATE_AGENTS_MD.read_text(encoding="utf-8"),
        "terp guide": _full_guide_text(),
    }


# --------------------------------------------------------------------------- #
# (1) generated rule surface — every rule is projected, with a headline
# --------------------------------------------------------------------------- #
_RULE_LINE_RE = re.compile(r"(?m)^\s*-\s+([a-z][a-z0-9_]+)$")


def _surfaced_rules(rules_topic: str) -> dict[str, str]:
    """Parse the generated ``terp guide rules`` topic into ``{rule_name: headline}``."""
    lines = rules_topic.splitlines()
    surfaced: dict[str, str] = {}
    for index, line in enumerate(lines):
        match = _RULE_LINE_RE.match(line)
        if match:
            headline = lines[index + 1].strip() if index + 1 < len(lines) else ""
            surfaced[match.group(1)] = headline
    return surfaced


def _unsurfaced_rules(rule_names: set[str], rules_topic: str) -> set[str]:
    """Rules absent from the generated surface, or surfaced with an empty headline."""
    surfaced = _surfaced_rules(rules_topic)
    return {name for name in rule_names if not surfaced.get(name)}


def test_every_rule_is_surfaced_in_the_generated_guide() -> None:
    # The rules topic is a projection of _ALL_RULES, so it is complete by construction;
    # this locks that contract — every rule appears with a non-empty headline.
    assert _unsurfaced_rules(_rule_names(), guide("rules")) == set()


def test_object_authz_rule_is_in_the_generated_surface() -> None:
    # The rule that shipped with no guide recipe (ADR 0029) now surfaces automatically.
    assert "no_manual_ownership_checks" in _surfaced_rules(guide("rules"))


def test_rule_surface_fails_closed_on_an_unsurfaced_rule() -> None:
    # A synthetic rule the generator did NOT emit is reported — the guard bites, so the
    # "generated => complete" contract cannot silently regress to a partial projection.
    assert _unsurfaced_rules({"a_synthetic_unwired_rule"}, guide("rules")) == {
        "a_synthetic_unwired_rule"
    }


# --------------------------------------------------------------------------- #
# (2) no dangling claims — every rule-/test-reference resolves (design §8)
# --------------------------------------------------------------------------- #
# Legitimate references that look like a rule/test claim but resolve to neither an
# _ALL_RULES member nor a real test. Drift-guarded by
# test_reference_allowlist_has_no_stale_entries (a stale entry fails), mirroring
# test_every_built_capability_is_covered.
_REFERENCE_ALLOWLIST: dict[str, str] = {}

# A snake_case token presented as "<name> rule" in prose claims a real arch rule.
_RULE_CLAIM_RE = re.compile(r"`?([a-z][a-z0-9]*(?:_[a-z0-9]+)+)`?\s+rules?\b")
# A `test_...` token (or a tests/**.py link) claims a real test.
_TEST_REF_RE = re.compile(r"\btest_[a-z0-9_]+\b")
# An "enforced by `X`" claim (the literal design-§8 form): the backticked X must resolve
# to a real rule or test. Bare prose ("enforced by fail-closed runtime controls") carries
# no backticked code reference, so it is deliberately not matched.
_ENFORCED_BY_RE = re.compile(r"[Ee]nforced by\s+`([a-z][a-z0-9_]*)`")


def _real_test_names() -> set[str]:
    """Every real test: module stems (``test_*.py``) + ``def test_*`` function names."""
    names: set[str] = set()
    for path in _TESTS_ROOT.rglob("test_*.py"):
        names.add(path.stem)
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names |= {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
            and node.name.startswith("test_")
        }
    return names


def _dangling_references(
    text: str, rule_names: set[str], test_names: set[str], allow: set[str]
) -> set[str]:
    """References in *text* that resolve to no real rule/test and aren't allowlisted."""
    dangling: set[str] = set()
    for match in _RULE_CLAIM_RE.finditer(text):
        token = match.group(1)
        if token not in rule_names and token not in allow:
            dangling.add(token)
    for match in _TEST_REF_RE.finditer(text):
        token = match.group(0)
        if token not in test_names and token not in allow:
            dangling.add(token)
    for match in _ENFORCED_BY_RE.finditer(text):
        token = match.group(1)
        if token not in rule_names and token not in test_names and token not in allow:
            dangling.add(token)
    return dangling


def test_no_dangling_claims_in_the_agent_surfaces() -> None:
    rule_names = _rule_names()
    test_names = _real_test_names()
    allow = set(_REFERENCE_ALLOWLIST)
    for label, text in _doc_surfaces().items():
        dangling = _dangling_references(text, rule_names, test_names, allow)
        assert dangling == set(), f"{label} cites a rule/test that does not exist: {sorted(dangling)}"


def test_reference_allowlist_has_no_stale_entries() -> None:
    # Drift guard: an allowlisted token must still appear in a surface, so the allowlist
    # can never silently accumulate dead exceptions (mirrors the capability drift guard).
    surfaces = "\n".join(_doc_surfaces().values())
    stale = {token for token in _REFERENCE_ALLOWLIST if token not in surfaces}
    assert stale == set(), f"remove stale reference-allowlist entries: {sorted(stale)}"


def test_dangling_detection_fails_closed_on_a_ghost_claim() -> None:
    text = (
        "writes are gated by the `ghost_authz_rule` rule, proven in test_made_up_thing; "
        "enforced by `ghost_guard`."
    )
    # A claimed rule / test / "enforced by" reference that does not exist is flagged — the
    # guard bites on all three reference shapes...
    assert _dangling_references(text, _rule_names(), _real_test_names(), set()) == {
        "ghost_authz_rule",
        "test_made_up_thing",
        "ghost_guard",
    }
    # ...unless each reference is explicitly (and legitimately) allowlisted.
    assert _dangling_references(
        text,
        _rule_names(),
        _real_test_names(),
        {"ghost_authz_rule", "test_made_up_thing", "ghost_guard"},
    ) == set()


# --------------------------------------------------------------------------- #
# (3) trait/seam coverage — agent must-know primitives appear in the guide
# --------------------------------------------------------------------------- #
# Always-on traits folded into BaseTable (an agent never composes them directly), so
# they need no separate recipe. Drift-guarded against the live must-know set by
# test_non_authored_trait_allowlist_is_not_stale.
_NON_AUTHORED_TRAITS = {"UUIDPrimaryKeyMixin", "TimestampMixin"}


def _must_know_traits_and_seams(core_all: list[str]) -> set[str]:
    """Public model traits (``*Mixin``) + capability seams (``register_*_predicate``)."""
    return {
        name
        for name in core_all
        if name.endswith("Mixin")
        or (name.startswith("register_") and name.endswith("_predicate"))
    }


def _undocumented_traits_seams(
    core_all: list[str], guide_text: str, allow: set[str]
) -> set[str]:
    return {
        name
        for name in _must_know_traits_and_seams(core_all) - allow
        if name not in guide_text
    }


def test_every_must_know_trait_and_seam_is_in_the_guide() -> None:
    undocumented = _undocumented_traits_seams(
        _CORE_ALL, _full_guide_text(), _NON_AUTHORED_TRAITS
    )
    assert undocumented == set(), (
        "every agent-facing model trait (*Mixin) and capability seam (register_*_predicate) "
        f"must be taught in `terp guide`; undocumented: {sorted(undocumented)}"
    )


def test_object_authz_trait_and_seam_are_documented() -> None:
    # The ADR-0029 primitives that shipped without a recipe now appear in the guide.
    text = _full_guide_text()
    assert "OwnedMixin" in text
    assert "register_object_authz_predicate" in text


def test_non_authored_trait_allowlist_is_not_stale() -> None:
    # Drift guard: an allowlisted trait must still be a live must-know primitive.
    stale = _NON_AUTHORED_TRAITS - _must_know_traits_and_seams(_CORE_ALL)
    assert stale == set(), f"remove stale non-authored-trait allowlist entries: {sorted(stale)}"


def test_trait_seam_coverage_fails_closed_on_an_undocumented_primitive() -> None:
    # A synthetic trait absent from the guide is reported — the guard bites.
    undocumented = _undocumented_traits_seams(
        [*_CORE_ALL, "SyntheticGhostMixin"], _full_guide_text(), _NON_AUTHORED_TRAITS
    )
    assert undocumented == {"SyntheticGhostMixin"}
