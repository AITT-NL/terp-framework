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

import pytest

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
#: The AGENTS.md a generated app actually carries (copier renders from `template/project`).
_DELIVERED_AGENTS_MD = _REPO_ROOT / "template" / "project" / "AGENTS.md.jinja"
_TESTS_ROOT = _REPO_ROOT / "tests"


def _rule_names() -> set[str]:
    """Every architecture rule, by the bare name the docs use (no ``check_`` prefix)."""
    return {rule.__name__.removeprefix("check_") for rule in _ALL_RULES}


def _full_guide_text() -> str:
    """The entire `terp guide` surface: the overview + every topic body."""
    return "\n".join([guide(), *(guide(topic) for topic in guide_topics())])


def _doc_surfaces() -> dict[str, str]:
    """Every surface an agent reads, INCLUDING the one that ships into an app.

    `template/AGENTS.md` is the bootstrap pointer for someone browsing this repository.
    `template/project/AGENTS.md.jinja` is the file copier actually delivers — copier's
    `_subdirectory` is `project`, so the former never reaches a generated app at all.
    Only the pointer was held to these claims, which is how the delivered file came to
    describe an app with two palettes while the pointer beside it named five.
    """
    return {
        "AGENTS.md": _AGENTS_MD.read_text(encoding="utf-8"),
        "template/AGENTS.md": _TEMPLATE_AGENTS_MD.read_text(encoding="utf-8"),
        "template/project/AGENTS.md.jinja": _DELIVERED_AGENTS_MD.read_text(encoding="utf-8"),
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


def test_generated_agents_md_lists_every_guide_topic() -> None:
    # The topic list a *generated app's* AGENTS.md advertises is the only index an agent
    # in that repo ever sees — and it was hand-written, so it silently fell behind the
    # CLI: five shipped topics (access, files, jobs, layouts, passwords) existed that no
    # agent could discover. A capability the author cannot find is a capability the
    # author re-implements by hand. Pin the list to the live registry.
    text = (_REPO_ROOT / "template" / "project" / "AGENTS.md.jinja").read_text(
        encoding="utf-8"
    )
    match = re.search(r"(?ms)^  Topics: (.+?)\.$", text)
    assert match is not None, "AGENTS.md.jinja no longer declares a `Topics:` list"
    advertised = tuple(
        sorted(topic.strip() for topic in match.group(1).replace("\n", " ").split(","))
    )
    assert advertised == guide_topics()


# --------------------------------------------------------------------------- #
# (2) no dangling claims — every rule-/test-reference resolves (design §8)
# --------------------------------------------------------------------------- #
# Legitimate references that look like a rule/test claim but resolve to neither an
# _ALL_RULES member nor a real test. Drift-guarded by
# test_reference_allowlist_has_no_stale_entries (a stale entry fails), mirroring
# test_every_built_capability_is_covered.
_REFERENCE_ALLOWLIST: dict[str, str] = {
    # Tests in the GENERATED app, not in this repository. `template/project/tests/` is
    # rendered into someone else's checkout, so these names are real and this suite is
    # structurally unable to resolve them — the alternative is release notes that cannot
    # say what a generated project gains, which is the thing the notes are for.
    "test_architecture": "template/project/tests/test_architecture.py, in a generated app",
    "test_migrations_reverse_cleanly": (
        "template/project/tests/test_architecture.py, in a generated app"
    ),
}

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


# --------------------------------------------------------------------------- #
# (4) control-plane declaration coverage — a refused boot must have a recipe
# --------------------------------------------------------------------------- #
# The trait/seam guard above reaches model primitives and capability seams. It never
# reached a CONTROL-PLANE DECLARATION, which is the one class of thing `create_app`
# refuses a production boot over — so a field could be added to `SecurityConfig`, ship,
# be refused at someone's deploy, and be explained nowhere, with nothing going red.
#
# Scoped to the STATIC topic bodies rather than `_full_guide_text()`, and the distinction
# is load-bearing rather than pedantic: `changelog` is a generated topic whose body is the
# entire release notes, and the release notes name every one of these classes. A guard
# built on the full text would pass today with no topic written at all.


def _static_guide_text() -> str:
    """Every AUTHORED topic body — not the generated ones (`changelog`).

    A guard over the generated text asserts that something was once released, which is
    not the same claim as "an author can find out how to declare this".
    """
    from terp.cli.__init__ import _GUIDE_TOPICS

    return "\n".join(_GUIDE_TOPICS.values())


def _declarations_refused_at_boot() -> list[type]:
    """Every public `terp.core` declaration that owns a `production_problems()`.

    That method IS the definition of this class of thing: it is what `create_app` reads
    to decide whether the app may boot, and what the production-readiness verify lane
    reads to say so first.
    """
    import terp.core

    return [
        obj
        for name in _CORE_ALL
        if isinstance(obj := getattr(terp.core, name), type)
        and callable(getattr(obj, "production_problems", None))
    ]


def _undeclared_declaration_fields(text: str) -> dict[str, list[str]]:
    """Declaration class -> the fields of it the guide never names."""
    import dataclasses

    undocumented: dict[str, list[str]] = {}
    for cls in _declarations_refused_at_boot():
        if not dataclasses.is_dataclass(cls):  # pragma: no cover - all of them are today
            continue
        missing = [
            declared.name
            for declared in dataclasses.fields(cls)
            if declared.name not in text
        ]
        if cls.__name__ not in text:
            missing.append(cls.__name__)
        if missing:
            undocumented[cls.__name__] = sorted(missing)
    return undocumented


def test_every_declaration_that_refuses_a_boot_is_explained_in_the_guide() -> None:
    undocumented = _undeclared_declaration_fields(_static_guide_text())
    assert undocumented == {}, (
        "a control-plane declaration `create_app` can refuse a production boot over must "
        "be taught in `terp guide`, field by field — otherwise the next field added to it "
        "lands unexplained and is first met at someone's deploy. Missing: "
        f"{undocumented}"
    )


def test_the_declaration_guard_finds_the_classes_it_is_about() -> None:
    """Fails closed if `production_problems()` is renamed: an empty set of subjects
    would make the guard above vacuously true."""
    names = {cls.__name__ for cls in _declarations_refused_at_boot()}
    assert {"SecurityConfig", "PasswordPolicy", "ControlPlane"} <= names, (
        f"the production-refusal declarations are no longer discoverable: found {names}"
    )


def test_declaration_coverage_fails_closed_on_an_unexplained_field() -> None:
    """A field the guide does not name is reported — the guard bites."""
    undocumented = _undeclared_declaration_fields(
        _static_guide_text().replace("trusted_proxy_hops", "")
    )
    assert undocumented == {"SecurityConfig": ["trusted_proxy_hops"]}


def test_the_boot_refusal_routes_to_its_own_recipe() -> None:
    """A refusal that does not name where the answer is written is half a control.

    The same move a rule violation already makes when it prints `terp guide <topic>`.
    """
    app_source = (
        _REPO_ROOT / "packages" / "backend" / "core" / "src" / "terp" / "core" / "app.py"
    ).read_text(encoding="utf-8")
    assert "terp guide security" in app_source
    assert "terp guide passwords" in app_source


# --------------------------------------------------------------------------- #
# (5) the base profile — stated in three documents, installed by one manifest
# --------------------------------------------------------------------------- #
_TEMPLATE_PYPROJECT = _REPO_ROOT / "template" / "project" / "pyproject.toml.jinja"
_CAPABILITY_PACKAGES = _REPO_ROOT / "packages" / "backend" / "capabilities"


def _base_profile() -> set[str]:
    """The capabilities EVERY scaffolded app installs, read from the template manifest.

    Ground truth, not a fourth restatement: a ``terp-cap-*`` requirement outside every
    ``{% if use_* %}`` block is unconditional, and unconditional is what "base" means.
    """
    names: set[str] = set()
    depth = 0
    for line in _TEMPLATE_PYPROJECT.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("{%") and " if " in stripped:
            depth += 1
            continue
        if stripped.startswith("{%") and "endif" in stripped:
            depth -= 1
            continue
        if depth == 0:
            match = re.search(r'"terp-cap-([a-z-]+)==', stripped)
            if match:
                names.add(match.group(1).replace("-", "_"))
    assert len(names) >= 4, f"parsed {names} as the base profile — the reader is broken"
    return names


def _shipped_capabilities() -> set[str]:
    """Every capability package that exists in this repository."""
    names = {
        path.name
        for path in _CAPABILITY_PACKAGES.iterdir()
        if path.is_dir() and (path / "pyproject.toml").exists()
    }
    assert len(names) > 10, f"found only {names} — the capability scan is broken"
    return names


#: Where the base profile is described in prose, and the sentence that describes it.
#:
#: Three documents, three different lists, and one of them named ``projects`` — a
#: capability that has never existed. An agent reading ``terp guide capability`` would
#: have gone looking for it, and an agent reading any of the three would have believed
#: its app had no group membership. The lists are checked against the manifest that
#: installs them, so the next edit to one of the three cannot silently disagree.
_BASE_PROFILE_CLAIMS = (
    ("terp guide capability", lambda: guide("capability")),
    (
        "packages/backend/capabilities/README.md",
        lambda: (_CAPABILITY_PACKAGES / "README.md").read_text(encoding="utf-8"),
    ),
    (
        "template/project/AGENTS.md.jinja",
        lambda: _DELIVERED_AGENTS_MD.read_text(encoding="utf-8"),
    ),
)


@pytest.mark.parametrize("label,read", _BASE_PROFILE_CLAIMS, ids=lambda value: getattr(value, "__name__", str(value)))
def test_every_base_profile_claim_names_the_capabilities_that_are_installed(
    label: str, read
) -> None:
    """Each document must name every capability a scaffolded app actually gets."""
    text = read()
    missing = sorted(name for name in _base_profile() if name not in text)
    assert not missing, (
        f"{label} describes the base profile without naming {missing}; "
        f"template/project/pyproject.toml.jinja installs it unconditionally"
    )


def test_no_agent_surface_invents_a_capability() -> None:
    """A capability named in the docs must be a package that exists.

    ``terp guide capability`` promised "auth + access + identity + users (+ projects)".
    There is no ``terp-cap-projects``. A capability an author cannot find is one they
    re-implement by hand, which is the exact failure the capability guide exists to
    prevent — so the guide inventing one is worse than the guide being silent.
    """
    shipped = _shipped_capabilities()
    for label, text in _doc_surfaces().items():
        named = {
            match.group(1).replace("-", "_")
            for match in re.finditer(r"terp-cap-([a-z][a-z-]*)", text)
        }
        ghosts = sorted(named - shipped)
        assert not ghosts, f"{label} names capabilities that do not exist: {ghosts}"


def test_the_example_catalog_imports_only_capabilities_the_image_installs() -> None:
    """A catalog entry costs nothing; the import that fills it costs everything.

    `control_plane/operations.py` folded in two capabilities the app does not
    mount, on the reasoning that a superset is free under OFF coverage. True of
    the catalog, false of the import: neither is installed in the production
    image, so the module raised ModuleNotFoundError before uvicorn could serve a
    request and the container never became healthy — while the workspace, where
    every package is present, imported it happily. Nothing caught the difference.
    """
    import re

    dockerfile = (_REPO_ROOT / "apps" / "example" / "Dockerfile").read_text(
        encoding="utf-8"
    )
    installed = set(re.findall(r"packages/backend/capabilities/(\w+)", dockerfile))
    assert installed, "the image must install some capabilities"

    source = (
        _REPO_ROOT / "apps" / "example" / "control_plane" / "operations.py"
    ).read_text(encoding="utf-8")
    imported = set(re.findall(r"from terp\.capabilities\.(\w+) import", source))

    missing = sorted(imported - installed)
    assert not missing, (
        f"control_plane/operations.py imports {', '.join(missing)}, which "
        f"apps/example/Dockerfile does not install — the app cannot start in "
        f"production, and only in production"
    )


def test_every_installed_capability_brings_its_capability_dependencies() -> None:
    """A capability that depends on another must not be installed without it.

    The sibling test above checks what the app *imports*. This checks what the
    installed packages themselves *require*, which is a different failure and a
    later one: the image lists packages one by one, so a capability that grows a
    dependency on another capability makes the resolver fail inside a Docker layer
    rather than in the suite.

    That is exactly how it went wrong. Webhooks moved its SSRF denylist into the
    egress capability and declared the dependency; every workspace install was fine,
    because a workspace has every package present, and the image — which does not —
    failed with "conclude that terp-cap-webhooks==0.18.0 cannot be used" a minute
    into a build. Same shape as the import gap: true in the workspace, false in the
    image, invisible until something is built.
    """
    import re
    import tomllib

    caps = _REPO_ROOT / "packages" / "backend" / "capabilities"
    for name in ("Dockerfile", "Dockerfile.prod"):
        dockerfile = (_REPO_ROOT / "apps" / "example" / name).read_text(encoding="utf-8")
        installed = set(re.findall(r"packages/backend/capabilities/(\w+)", dockerfile))
        assert installed, f"{name} must install some capabilities"

        for capability in sorted(installed):
            manifest = caps / capability / "pyproject.toml"
            data = tomllib.loads(manifest.read_text(encoding="utf-8"))
            required = {
                # `terp-cap-jobs-celery` is the distribution; `jobs_celery` the directory.
                dependency.split("==")[0].removeprefix("terp-cap-").replace("-", "_")
                for dependency in data["project"].get("dependencies", ())
                if dependency.startswith("terp-cap-")
            }
            missing = sorted(required - installed)
            assert not missing, (
                f"{name} installs the {capability!r} capability but not {missing}, "
                f"which it declares as a dependency — the image cannot resolve, and "
                f"only the image"
            )


def test_the_guide_lists_exactly_the_rules_a_companion_root_is_held_to() -> None:
    """``terp guide package-boundaries`` names the travelling rules; the registry decides them.

    The topic tells an author which rules reach a second deployable, and it does so as a
    hand-written list — the one shape in this file's subject that rots on its own, because
    reclassifying a rule in ``RULE_ROOT_KINDS`` changes the truth without touching the
    prose. The failure is the bad direction too: an author reads a rule's name in the
    guide, believes their worker is held to it, and it is not.

    Pinned rather than generated because the sentence around the list is doing work a
    projection could not — it explains *why* these travel — and the projection is one
    ``sorted()`` away in the test, which is the cheaper half to own.
    """
    from terp.arch import EVERY_ROOT, RULE_ROOT_KINDS, root_kinds_for

    topic = guide("package-boundaries")
    travelling = {
        rule
        for rule in RULE_ROOT_KINDS
        if root_kinds_for(rule) == EVERY_ROOT
        and rule not in {"escape_hatch_budget", "ungoverned_escape_hatch"}
    }
    listed = {rule for rule in travelling if f"`{rule}`" in topic}
    missing = sorted(travelling - listed)
    assert not missing, (
        "terp guide package-boundaries lists the rules a companion root is held to, and "
        f"these are held to it but not listed: {missing} — add them to the topic, or "
        "reclassify them in RULE_ROOT_KINDS"
    )
    overclaimed = sorted(
        rule
        for rule in RULE_ROOT_KINDS
        if rule not in travelling and f"`{rule}`" in _companion_bullet(topic)
    )
    assert not overclaimed, (
        "terp guide package-boundaries names these in its companion-rule list, but a "
        f"companion root is NOT held to them: {overclaimed} — an author would believe "
        "their worker is covered by a rule that never runs there"
    )


def _companion_bullet(topic: str) -> str:
    """The `WHAT THE COMPANION IS HELD TO` bullet alone, so the pin reads the right list."""
    start = topic.index("- WHAT THE COMPANION IS HELD TO")
    return topic[start : topic.index("\n- ", start + 1)]
