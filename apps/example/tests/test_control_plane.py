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
    English label copy-pasted, fails here. The copy-pasted check honors the same
    `locales.nl.allowIdentical` escape hatch `locale.tsx`'s identical JS-side check
    does (ids like `auth.dex.label` already use it): an id in that list may legitimately
    have the same Dutch and English text (a proper noun, an acronym), so it is exempt
    here too rather than forcing a fabricated paraphrase to pass this gate.

    What this proves is narrower than it might sound: only that `frontend/i18n.json`
    itself is complete. It says nothing about whether anything actually *renders* that
    entry -- at the time this was written, the Studio's own viewer does not read this
    file at all and shows the English label regardless of locale (see ADR 0102's
    amendment). Closing that gap is separate, un-started work; this test cannot detect
    it either way, because it never leaves this file.
    """
    i18n = json.loads((_FRONTEND_ROOT / "i18n.json").read_text(encoding="utf-8"))
    nl_locale = i18n["locales"]["nl"]
    dutch_messages: dict[str, str] = nl_locale["messages"]
    allow_identical: set[str] = set(nl_locale.get("allowIdentical", []))
    operation_labels = {definition.id: definition.label for definition in operation_catalog.operations}
    missing: list[str] = []
    copied: list[str] = []
    for op_id, english in operation_labels.items():
        dutch = dutch_messages.get(op_id)
        if dutch is None:
            missing.append(op_id)
        elif dutch == english and op_id not in allow_identical:
            copied.append(op_id)
    assert not missing, f"operations with no Dutch translation: {sorted(missing)}"
    assert not copied, (
        f"Dutch translation is just the English label, verbatim: {sorted(copied)} "
        "-- translate it, or document an intentional proper noun/acronym in "
        "frontend/i18n.json's locales.nl.allowIdentical"
    )