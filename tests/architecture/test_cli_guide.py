"""``terp guide`` — the deterministic, agent-readable authoring guide surface.

An agent in a consumer repo can run ``terp guide`` (no third-party reading needed),
learn the canonical module shape + the golden rules the architecture gate enforces,
then ``terp guide <topic>`` for a copy-pasteable recipe.
"""

from __future__ import annotations

import pathlib
import sys

import pytest

# terp-cli is not pip-installed in the dev venv; inject its src (as test_cli_inspect does).
_CLI_SRC = pathlib.Path(__file__).resolve().parents[2] / "packages" / "backend" / "cli" / "src"
sys.path.insert(0, str(_CLI_SRC))

from terp.cli import guide, guide_choices, guide_topics, main  # noqa: E402  (import after sys.path setup)

# Derived from the live CLI registry — not hand-duplicated — so a new topic is covered
# automatically (and the rules topic is generated; see test_docs_parity.py).
_TOPICS = guide_topics()


def test_overview_lists_the_shape_and_golden_rules() -> None:
    text = guide()
    assert "Canonical module shape" in text
    assert "Golden rules" in text
    assert "business_filters" in text
    # The overview advertises every available topic.
    for topic in _TOPICS:
        assert topic in text


@pytest.mark.parametrize("topic", _TOPICS)
def test_each_topic_returns_a_nonempty_recipe(topic: str) -> None:
    assert guide(topic).strip()


def test_migrations_topic_carries_the_autogenerate_recipe() -> None:
    """The wall an author hits twice must be answered once, in the guide.

    ``terp migrate make`` on a fresh checkout fails on the in-memory default, then
    on "not at head". Both errors now print the fix, but an author who reads the
    guide first should never meet either.
    """
    text = guide("migrations")
    assert "sqlite:///./.migrate-scratch.db" in text
    assert "terp migrate upgrade" in text
    assert "$env:DATABASE_URL" in text  # the Windows spelling is not left as an exercise


def test_service_topic_shows_how_a_validator_reaches_another_module_s_fact() -> None:
    """Purity has a cost; the guide prices it instead of leaving it to be rediscovered.

    A validator that needs a published vocabulary from a sibling table is the
    common case. Without the pattern written down, the tempting answer is to hand
    the validator a session — which puts a read outside the chokepoint and makes it
    untestable without a database.
    """
    text = guide("service")
    assert "another module" in text.lower()
    assert "ModuleSpec(requires=...)" in text


@pytest.mark.parametrize("rule", sorted(set(guide_choices()) - set(_TOPICS)))
def test_each_rule_returns_an_exact_nonempty_recipe(rule: str) -> None:
    text = guide(rule)
    assert text.startswith(f"Rule: {rule}\n")
    assert "Related authoring pattern" in text


def test_recipes_carry_their_key_markers() -> None:
    assert "BaseService" in guide("service")
    assert "Permission" in guide("policy")
    assert "TenantScopedMixin" in guide("tenancy")
    assert "terp migrate" in guide("migrations")
    assert "OwnedMixin" in guide("ownership")
    # The frontend recipes teach the boundary-lint-compliant surface.
    assert "DataView" in guide("frontend")
    assert "useTerpClient" in guide("frontend")
    assert "InMemoryDataViewRepository" in guide("dataview")
    assert "ConfirmDialog" in guide("forms")
    # The rules topic is generated from the live terp-arch registry.
    assert "no_manual_ownership_checks" in guide("rules")


def test_changelog_topic_reports_the_release_notes_and_the_current_version() -> None:
    """An app cannot judge an upgrade it cannot read about.

    Before this, the only pointer the platform gave an app was the template's
    "see the platform CHANGELOG" — a dead reference to a document that shipped
    nowhere. The notes are now answered in the app's own checkout, headed by the
    version that checkout is actually on.

    The header must also say where the notes *end*: the shipped copy cannot
    describe a release newer than itself, and a reader weighing an upgrade who
    is not told that reads 0.5.x notes as if they covered 0.6.0 — or goes
    hunting for the repository. The escape hatch (an ephemeral CLI at the
    target version) is printed right there.
    """
    text = guide("changelog")
    assert "Terp release notes" in text
    assert "in lockstep" in text
    assert "Changelog" in text
    assert "These notes end at" in text
    assert "uvx --from terp-cli==<version> terp guide changelog" in text


def test_the_shipped_release_notes_match_the_repository_changelog() -> None:
    """The notes ship as a checked-in copy inside terp-core, because a
    force-include reaching outside the package cannot survive the sdist round-trip
    the PyPI wheel is built from (see test_prod_profile). A copy can drift, so it
    is held to its source here — the objection to a mirror is answerable with a
    test; the objection to the force-include was not answerable at all.

    Refresh with: Copy-Item CHANGELOG.md packages/backend/core/src/terp/core/
    """
    root = pathlib.Path(__file__).resolve().parents[2]
    shipped = root / "packages" / "backend" / "core" / "src" / "terp" / "core" / "CHANGELOG.md"
    assert shipped.is_file(), (
        "terp-core must ship the release notes — `terp guide changelog` is the "
        "only way an installed app can read what changed"
    )
    assert shipped.read_text(encoding="utf-8") == (root / "CHANGELOG.md").read_text(
        encoding="utf-8"
    ), (
        "the release notes shipped in terp-core have drifted from CHANGELOG.md — "
        "copy the root file over packages/backend/core/src/terp/core/CHANGELOG.md"
    )


def test_the_shipped_copy_wins_over_the_checkout_walk(tmp_path: pathlib.Path) -> None:
    """The wheel copy is the delivery path for every consumer; the upward walk is
    only a convenience for the platform's own checkout. If the walk could win, a
    developer would be reading notes the installed platform does not carry."""
    from terp.cli import _read_release_notes

    shipped = tmp_path / "shipped"
    shipped.mkdir()
    (shipped / "CHANGELOG.md").write_text("from the wheel", encoding="utf-8")
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    (checkout / "CHANGELOG.md").write_text("from the checkout", encoding="utf-8")

    assert _read_release_notes(shipped, checkout) == "from the wheel"
    empty = tmp_path / "no-wheel-copy"
    empty.mkdir()
    assert _read_release_notes(empty, checkout) == "from the checkout"


def test_absent_release_notes_say_so_instead_of_failing(tmp_path: pathlib.Path) -> None:
    from terp.cli import _read_release_notes

    assert _read_release_notes(tmp_path, tmp_path) is None


def test_a_partial_install_without_notes_names_the_cause(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The guide must degrade to an explanation, never to a traceback — an
    editable or partial install is exactly when someone is already debugging."""
    import terp.cli

    monkeypatch.setattr(terp.cli, "_read_release_notes", lambda *_: None)
    text = guide("changelog")
    assert "not available" in text
    assert "terp-core wheel" in text


def test_the_release_notes_travel_inside_the_wheel() -> None:
    """The fallback for the platform's own checkout must not become the delivery
    mechanism: an installed app has no repository to walk up into, so terp-core
    force-includes the notes. Pinned here because losing that line would leave
    the topic silently working for us and broken for every consumer."""
    pyproject = (
        pathlib.Path(__file__).resolve().parents[2]
        / "packages"
        / "backend"
        / "core"
        / "pyproject.toml"
    ).read_text(encoding="utf-8")
    assert "force-include" in pyproject
    assert "terp/core/CHANGELOG.md" in pyproject


def test_outbound_http_rule_guide_is_truthful_and_preserves_the_feature() -> None:
    text = guide("no_raw_outbound_http")
    assert "SSRF protection, allowlists, egress auditing, and timeout" in text
    assert "no generic outbound-fetch" in text
    assert "returning static/local data" in text
    assert "stop and report the missing capability" in text
    assert "Do not create an app-local helper package" in text
    assert "terp-cap-webhooks" in text
    assert "no_raw_outbound_http" in guide_choices()


def test_jobs_guide_refuses_to_trade_ownership_for_scheduled_maintenance() -> None:
    text = guide("jobs")
    assert "CANNOT update or delete a user's OwnedMixin row" in text
    assert "Predicates can narrow authority but never grant" in text
    assert "Cross-owner maintenance requires a reviewed maintenance-authority" in text
    assert "remove OwnedMixin or author a destructive owner-column migration" in text


def test_cli_guide_prints_overview(capsys: pytest.CaptureFixture[str]) -> None:
    main(["guide"])
    out = capsys.readouterr().out
    assert "authoring guide" in out
    assert "Golden rules" in out


def test_cli_guide_topic_prints_recipe(capsys: pytest.CaptureFixture[str]) -> None:
    main(["guide", "service"])
    out = capsys.readouterr().out
    assert "BaseService" in out
    assert "business_filters" in out


def test_cli_guide_rule_prints_exact_remediation(
    capsys: pytest.CaptureFixture[str],
) -> None:
    main(["guide", "no_raw_outbound_http"])
    out = capsys.readouterr().out
    assert "Compliant decision path for outbound HTTP" in out
    assert "missing capability" in out


def test_cli_guide_refuses_an_unknown_topic_or_rule() -> None:
    # Validated on dispatch (not argparse choices), so the rule registry stays
    # off the common CLI path — and the refusal names both discovery commands.
    with pytest.raises(SystemExit, match=r"unknown topic or rule 'made_up'") as excinfo:
        main(["guide", "made_up"])
    assert "terp guide rules" in str(excinfo.value)


def test_cli_migrate_delegates_to_the_runner(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # `terp migrate` forwards to terp.migrations; caps-only status on a fresh DB lists
    # each installed capability's history (no --app-root -> app modules are skipped).
    main(["migrate", "status", "--database-url", f"sqlite:///{tmp_path / 'cli.db'}"])
    assert "audit" in capsys.readouterr().out
