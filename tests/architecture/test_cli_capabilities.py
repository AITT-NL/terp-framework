"""``terp inspect capabilities`` — the adoptable-capability surface cannot drift.

The command exists because the gate could only ever say *no*: nothing in a generated app
told its author that durable delivery, realtime push or shared multi-replica state were
already maintained packages one ``uv add`` away. That makes the registry an agent-facing
claim about what the platform offers, so it gets the same treatment as every other such
claim (test_docs_parity): it is pinned against the real capability packages, and a new
capability that ships without an entry here fails the build.
"""

from __future__ import annotations

import json
import pathlib
import sys

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_CLI_SRC = _REPO_ROOT / "packages" / "backend" / "cli" / "src"
sys.path.insert(0, str(_CLI_SRC))

from terp.cli import guide_choices, main  # noqa: E402  (import after sys.path setup)
from terp.cli import capabilities as capabilities_module  # noqa: E402
from terp.cli.capabilities import (  # noqa: E402
    CAPABILITIES,
    render_capabilities,
)

_CAPABILITY_PACKAGES = _REPO_ROOT / "packages" / "backend" / "capabilities"


def _built_capabilities() -> set[str]:
    return {
        path.name
        for path in _CAPABILITY_PACKAGES.iterdir()
        if path.is_dir() and (path / "pyproject.toml").exists()
    }


def test_registry_covers_every_built_capability_exactly_once() -> None:
    names = [capability.name for capability in CAPABILITIES]
    assert len(names) == len(set(names)), "duplicate capability entry"
    assert set(names) == _built_capabilities()


def test_kind_matches_whether_the_package_declares_a_router() -> None:
    # "routed" is a promise that `discover_capabilities=True` mounts it with no
    # composition-root edit; that promise is the package's `terp.capabilities` entry
    # point, so the two must agree or the wiring advice is wrong.
    for capability in CAPABILITIES:
        pyproject = (
            _CAPABILITY_PACKAGES / capability.name / "pyproject.toml"
        ).read_text(encoding="utf-8")
        routed = 'entry-points."terp.capabilities"' in pyproject
        assert capability.kind == ("routed" if routed else "library"), capability.name


def test_distribution_and_module_names_resolve_to_the_real_package() -> None:
    for capability in CAPABILITIES:
        pyproject = (
            _CAPABILITY_PACKAGES / capability.name / "pyproject.toml"
        ).read_text(encoding="utf-8")
        assert f'name = "{capability.distribution}"' in pyproject
        module_dir = (
            _CAPABILITY_PACKAGES
            / capability.name
            / "src"
            / "terp"
            / "capabilities"
            / capability.name
        )
        assert module_dir.is_dir(), capability.module


def test_declared_guide_topics_exist() -> None:
    for capability in CAPABILITIES:
        if capability.guide is not None:
            assert capability.guide in guide_choices(), capability.name


def test_text_output_separates_installed_from_adoptable_and_states_the_fix(
    monkeypatch,
) -> None:
    # In this repo's own venv every capability is installed, which exercises only half
    # the report. Force the adoptable branch — that is the half an app actually reads.
    text = render_capabilities()
    assert "Installed in this app" in text
    assert "Available to adopt" in text
    for capability in CAPABILITIES:
        assert capability.distribution in text

    monkeypatch.setattr(capabilities_module, "_is_installed", lambda capability: False)
    adoptable = render_capabilities()
    assert "(none)" in adoptable  # nothing installed
    for capability in CAPABILITIES:
        # Each entry is actionable on its own: the exact dependency and its wiring.
        assert f"uv add {capability.distribution}" in adoptable
        assert capability.wiring in adoptable


def test_json_output_is_machine_readable() -> None:
    payload = json.loads(render_capabilities(fmt="json"))
    entries = payload["capabilities"]
    assert len(entries) == len(CAPABILITIES)
    for entry in entries:
        assert set(entry) == {
            "name",
            "distribution",
            "module",
            "summary",
            "kind",
            "wiring",
            "guide",
            "installed",
        }
        assert isinstance(entry["installed"], bool)


def test_cli_dispatches_the_subcommand(capsys) -> None:
    main(["inspect", "capabilities"])
    assert "Available to adopt" in capsys.readouterr().out
    main(["inspect", "capabilities", "--format", "json"])
    assert json.loads(capsys.readouterr().out)["capabilities"]
