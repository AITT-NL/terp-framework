"""Example-app control-plane smoke tests."""

from __future__ import annotations

import json
import pathlib

from terp.core import ControlPlane

from app.main import build
from control_plane import control_plane
from control_plane.operations import operation_catalog

_FRONTEND_ROOT = pathlib.Path(__file__).resolve().parents[1] / "frontend"


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


def test_every_declared_operation_has_a_dutch_translation() -> None:
    """Phase 5.5 (ADR 0102, amending §3): the operation id IS the i18n message id.

    The same completeness drift-guard `LOCALE_NL` already has for framework strings
    (`packages/frontend/react-core/src/locale.test.tsx`), keyed off this app's own
    `OperationCatalog` instead of a frontend `TerpStrings` export -- a new operation
    with no Dutch entry in `frontend/i18n.json` fails here, so the catalog can never
    silently fall back to its English label for a route nobody translated.
    """
    i18n = json.loads((_FRONTEND_ROOT / "i18n.json").read_text(encoding="utf-8"))
    dutch_messages = set(i18n["locales"]["nl"]["messages"])
    operation_ids = {definition.id for definition in operation_catalog.operations}
    missing = operation_ids - dutch_messages
    assert not missing, f"operations with no Dutch translation: {sorted(missing)}"