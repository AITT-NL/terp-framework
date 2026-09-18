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
    Capability,
    render_capabilities,
    unwired_seams,
    wiring_seams,
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

    monkeypatch.setattr(
        capabilities_module, "_installed_version", lambda capability: None
    )
    adoptable = render_capabilities()
    assert "(none)" in adoptable  # nothing installed
    for capability in CAPABILITIES:
        # Each entry is actionable on its own: the exact dependency and its wiring.
        assert f"uv add {capability.distribution}" in adoptable
        assert capability.wiring in adoptable


def test_the_adopt_line_is_pinned_to_the_lockstep_version(monkeypatch) -> None:
    """An unpinned ``uv add`` resolves to whatever is newest, which is exactly how an
    app ends up one release ahead of the rest of the set. This report is the surface
    that hands out the command, so it is the surface that must pin it."""
    from terp.cli.version import platform_version

    version = platform_version()
    assert version is not None
    # Every capability is installed in this repo's venv, so the adopt list — the half
    # that carries the command — is empty here. Force it.
    monkeypatch.setattr(
        capabilities_module, "_installed_version", lambda capability: None
    )
    text = render_capabilities()
    assert "lockstep" in text
    for capability in CAPABILITIES:
        assert f"uv add {capability.distribution}=={version}" in text


def test_installed_capabilities_report_their_version(monkeypatch) -> None:
    """"You're on 0.5.3" is the first half of "0.5.4 is out", and this surface — the one
    an app reads to see its platform profile — printed no version at all."""
    monkeypatch.setattr(
        capabilities_module, "_installed_version", lambda capability: "9.9.9"
    )
    text = render_capabilities()
    assert "9.9.9" in text
    payload = json.loads(render_capabilities(fmt="json"))
    assert payload["capabilities"][0]["version"] == "9.9.9"
    assert payload["capabilities"][0]["installed"] is True


def test_an_uninstalled_distribution_reads_as_adoptable_not_as_an_error(
    monkeypatch,
) -> None:
    # "Installed?" is answered by asking this environment, and the honest answer for a
    # distribution that is not here is "no" — never a PackageNotFoundError escaping into
    # a report whose whole job is to tell an app what it could adopt next.
    from terp.cli.capabilities import _installed_version

    installed = CAPABILITIES[0]
    assert _installed_version(installed) is not None

    missing = installed.__class__(
        name="does-not-exist",
        summary="a capability this environment has never heard of",
        kind="library",
        wiring="n/a",
    )
    assert _installed_version(missing) is None


def test_json_output_is_machine_readable() -> None:
    payload = json.loads(render_capabilities(fmt="json"))
    # The lockstep version the adopt lines pin to, so a tool need not parse the text.
    assert payload["platform_version"]
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
            "seams",
            "unwired_seams",
            "version",
        }
        assert isinstance(entry["installed"], bool)


def test_cli_dispatches_the_subcommand(capsys) -> None:
    main(["inspect", "capabilities"])
    assert "Available to adopt" in capsys.readouterr().out
    main(["inspect", "capabilities", "--format", "json"])
    assert json.loads(capsys.readouterr().out)["capabilities"]


# --------------------------------------------------------------------------- #
# Seam-granular discovery                                                       #
# --------------------------------------------------------------------------- #
#
# The registry answers "do I have this capability", and at that granularity an
# installed-and-mounted capability looks finished. So a seam the package grows AFTER an
# app adopts it is invisible from inside the project, permanently: the holder-heartbeat
# router shipped in 0.11.0 and an app on 0.24.0 still said in four places that no such
# endpoint existed. Thirteen releases, a 6,842-line changelog, and no consumer reads the
# delta — the one tool built to answer "what does the platform already offer" answered a
# package-shaped question.


def _capability(name: str):
    (found,) = [cap for cap in CAPABILITIES if cap.name == name]
    return found


def test_the_seam_scan_finds_something() -> None:
    """Discovery that quietly finds nothing reports "nothing unused" for every app —
    green, useless, and indistinguishable from a working scan."""
    total = sum(len(wiring_seams(cap)) for cap in CAPABILITIES)
    assert total > 10, (
        f"the wiring-seam vocabulary matched {total} names across every capability — "
        "it has stopped matching, and an empty scan reports every app fully wired"
    )


def test_the_seam_that_was_invisible_is_found() -> None:
    """The case this exists for, named. `build_holder_router` is how a holder outside
    the process keeps a lease alive; it shipped in 0.11.0 and stayed undiscoverable."""
    assert "build_holder_router" in wiring_seams(_capability("leases"))


def test_a_seam_is_a_wiring_point_not_every_export() -> None:
    """391 names are exported across the capabilities, most of them operation ids,
    error types and status literals. A report of 391 things is a report of nothing."""
    leases = wiring_seams(_capability("leases"))
    assert "LEASES_HEARTBEAT" not in leases, "an operation id is not a wiring point"
    assert all(not name.isupper() for name in leases), leases


def test_unwired_seams_reads_the_app_not_the_package(tmp_path: pathlib.Path) -> None:
    leases = _capability("leases")
    (tmp_path / "main.py").write_text(
        "from terp.capabilities.leases import DatabaseLeaseStore\n"
        "app = create_app(lease_store=DatabaseLeaseStore())\n",
        encoding="utf-8",
    )
    unwired = unwired_seams(leases, tmp_path)
    assert "DatabaseLeaseStore" not in unwired, "a seam the app wires is not unwired"
    assert "build_holder_router" in unwired, "a seam the app never names is unwired"


def test_an_uninstalled_capability_reports_no_seams() -> None:
    """Reading a package's surface needs the import, so an unadopted capability has
    nothing to say here — and the "available to adopt" section already says it."""

    phantom = Capability(
        name="not_a_real_capability",
        summary="—",
        kind="library",
        wiring="—",
    )
    assert wiring_seams(phantom) == ()
    assert unwired_seams(phantom, pathlib.Path(".")) == ()


def test_the_listing_names_the_unused_seams(tmp_path: pathlib.Path) -> None:
    text = render_capabilities(root=tmp_path)
    assert "not used here" in text
    assert "build_holder_router" in text, (
        "an app that wires nothing must be told about the seams it is not using — "
        "that is the whole report"
    )


def test_the_json_manifest_carries_both_halves(tmp_path: pathlib.Path) -> None:
    """A driving tool reads this; giving it only the unused half would leave it unable
    to tell "no seams" from "all seams wired"."""
    document = json.loads(render_capabilities(fmt="json", root=tmp_path))
    leases = [c for c in document["capabilities"] if c["name"] == "leases"][0]
    assert "build_holder_router" in leases["seams"]
    assert "build_holder_router" in leases["unwired_seams"]
