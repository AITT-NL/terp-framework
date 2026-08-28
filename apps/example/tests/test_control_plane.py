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

    Shaped like the completeness drift-guard `LOCALE_NL` already has for framework
    strings (`packages/frontend/react-core/src/locale.test.tsx`), keyed off this app's
    own `OperationCatalog` instead of a frontend `TerpStrings` export -- a new
    operation with no Dutch entry in `frontend/i18n.json`, or one that is just its
    English label copy-pasted, fails here.

    What this proves is narrower than it might sound: only that `frontend/i18n.json`
    itself is complete. It says nothing about whether anything actually *renders* that
    entry -- at the time this was written, the Studio's own viewer does not read this
    file at all and shows the English label regardless of locale (see ADR 0102's
    amendment). Closing that gap is separate, un-started work; this test cannot detect
    it either way, because it never leaves this file.
    """
    i18n = json.loads((_FRONTEND_ROOT / "i18n.json").read_text(encoding="utf-8"))
    dutch_messages: dict[str, str] = i18n["locales"]["nl"]["messages"]
    operation_ids = {definition.id: definition.label for definition in operation_catalog.operations}
    missing = set(operation_ids) - set(dutch_messages)
    assert not missing, f"operations with no Dutch translation: {sorted(missing)}"
    copied = sorted(
        op_id
        for op_id, english in operation_ids.items()
        if dutch_messages[op_id] == english
    )
    assert not copied, f"Dutch translation is just the English label, verbatim: {copied}"