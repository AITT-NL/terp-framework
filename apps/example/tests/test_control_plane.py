"""Example-app control-plane smoke tests."""

from __future__ import annotations

from terp.core import ControlPlane

from app.main import build
from control_plane import control_plane


def test_example_declares_control_plane() -> None:
    assert isinstance(control_plane, ControlPlane)
    assert [role.name for role in control_plane.permissions.roles] == [
        "viewer",
        "editor",
        "admin",
    ]


def test_example_build_uses_control_plane() -> None:
    app = build()
    assert app.title == "Terp example app"