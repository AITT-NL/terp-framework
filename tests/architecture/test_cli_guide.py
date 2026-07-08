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

from terp.cli import guide, guide_topics, main  # noqa: E402  (import after sys.path setup)

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


def test_cli_migrate_delegates_to_the_runner(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # `terp migrate` forwards to terp.migrations; caps-only status on a fresh DB lists
    # each installed capability's history (no --app-root -> app modules are skipped).
    main(["migrate", "status", "--database-url", f"sqlite:///{tmp_path / 'cli.db'}"])
    assert "audit" in capsys.readouterr().out
