"""Capability discovery fails closed on bad/duplicate entry points (H9).

``iter_capability_specs`` previously called ``entry_point.load()`` unguarded, kept
only ``isinstance(..., ModuleSpec)`` results, and never checked for name
collisions — so one broken capability crashed the boot with a bare traceback, a
mistyped entry point vanished silently, and two capabilities claiming one name
both mounted (router shadowing). Each of those is now a loud
``CapabilityDiscoveryError``.
"""

from __future__ import annotations

from collections.abc import Iterable

import pytest

from terp.core import ModuleSpec, Policy
from terp.core._internal import discovery
from terp.core._internal.discovery import (
    CapabilityDiscoveryError,
    iter_capability_specs,
)


class _FakeEntryPoint:
    def __init__(self, name: str, value: str, *, loaded: object = None, error: Exception | None = None) -> None:
        self.name = name
        self.value = value
        self._loaded = loaded
        self._error = error

    def load(self) -> object:
        if self._error is not None:
            raise self._error
        return self._loaded


def _patch_entry_points(
    monkeypatch: pytest.MonkeyPatch, entry_points: Iterable[_FakeEntryPoint]
) -> None:
    monkeypatch.setattr(
        discovery.importlib.metadata,
        "entry_points",
        lambda *, group: list(entry_points),
    )


def test_load_failure_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_entry_points(
        monkeypatch,
        [_FakeEntryPoint("broken", "pkg:module", error=ImportError("boom"))],
    )
    with pytest.raises(CapabilityDiscoveryError, match="failed to load"):
        iter_capability_specs()


def test_non_modulespec_entry_point_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_entry_points(
        monkeypatch, [_FakeEntryPoint("weird", "pkg:thing", loaded=object())]
    )
    with pytest.raises(CapabilityDiscoveryError, match="must resolve to"):
        iter_capability_specs()


def test_duplicate_capability_name_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    spec_a = ModuleSpec(name="dup", policy=Policy.default())
    spec_b = ModuleSpec(name="dup", policy=Policy.default())
    _patch_entry_points(
        monkeypatch,
        [
            _FakeEntryPoint("a", "pkg_a:module", loaded=spec_a),
            _FakeEntryPoint("b", "pkg_b:module", loaded=spec_b),
        ],
    )
    with pytest.raises(CapabilityDiscoveryError, match="must be unique"):
        iter_capability_specs()


def test_duplicate_entry_point_name_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_entry_points(
        monkeypatch,
        [
            _FakeEntryPoint("users", "pkg_a:module", loaded=ModuleSpec(name="users", policy=Policy.default())),
            _FakeEntryPoint(
                "users", "pkg_b:module", loaded=ModuleSpec(name="shadow_users", policy=Policy.default())
            ),
        ],
    )
    with pytest.raises(CapabilityDiscoveryError, match="entry point names must be unique"):
        iter_capability_specs(["users"])


def test_filtering_matches_entry_point_name_not_spec_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A loaded capability whose spec name differs from its entry-point name is not "missing"."""
    _patch_entry_points(
        monkeypatch,
        [
            _FakeEntryPoint(
                "terp-cap-users", "pkg:module", loaded=ModuleSpec(name="users", policy=Policy.default())
            )
        ],
    )
    assert [spec.name for spec in iter_capability_specs(["terp-cap-users"])] == ["users"]


def test_filtering_reports_missing_by_entry_point_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_entry_points(
        monkeypatch,
        [_FakeEntryPoint("users", "pkg:module", loaded=ModuleSpec(name="users", policy=Policy.default()))],
    )
    with pytest.raises(CapabilityDiscoveryError, match="not installed: webhooks"):
        iter_capability_specs(["users", "webhooks"])


def test_filtering_does_not_bypass_duplicate_name_guard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Shadowing duplicates stop the boot even when the filter excludes one of them."""
    spec_a = ModuleSpec(name="dup", policy=Policy.default())
    spec_b = ModuleSpec(name="dup", policy=Policy.default())
    _patch_entry_points(
        monkeypatch,
        [
            _FakeEntryPoint("a", "pkg_a:module", loaded=spec_a),
            _FakeEntryPoint("b", "pkg_b:module", loaded=spec_b),
        ],
    )
    with pytest.raises(CapabilityDiscoveryError, match="must be unique"):
        iter_capability_specs(["a"])


def test_filtering_returns_only_requested_entry_points(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_entry_points(
        monkeypatch,
        [
            _FakeEntryPoint("a", "pkg_a:module", loaded=ModuleSpec(name="alpha", policy=Policy.default())),
            _FakeEntryPoint("z", "pkg_z:module", loaded=ModuleSpec(name="zebra", policy=Policy.default())),
        ],
    )
    assert [spec.name for spec in iter_capability_specs(["a"])] == ["alpha"]


def test_filtered_discovery_against_real_entry_points() -> None:
    """Filtering works end-to-end against the actually installed capability entry points."""
    installed = {spec.name for spec in iter_capability_specs()}
    if "users" not in installed:
        pytest.skip("terp-cap-users is not installed in this environment")
    assert [spec.name for spec in iter_capability_specs(["users"])] == ["users"]


def test_valid_entry_points_load_sorted_by_name(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_entry_points(
        monkeypatch,
        [
            _FakeEntryPoint("z", "pkg_z:module", loaded=ModuleSpec(name="zebra", policy=Policy.default())),
            _FakeEntryPoint("a", "pkg_a:module", loaded=ModuleSpec(name="alpha", policy=Policy.default())),
        ],
    )
    assert [spec.name for spec in iter_capability_specs()] == ["alpha", "zebra"]
