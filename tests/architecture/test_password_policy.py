"""``PasswordPolicy`` — the Tier-B credential-strength control (ADR 0006/0032).

Two-layer cover: the **runtime** half is :func:`validate_password` (fail-closed at the
credential boundary, raising the uniform ``WeakPasswordError``); the **boot** half is
:meth:`PasswordPolicy.production_problems`, which ``create_app`` consults so a relaxed
policy refuses to start in production. No ``terp.arch`` rule applies — there is no
agent-authored code shape to police — so this kernel suite is the build-time half.
"""

from __future__ import annotations

import pytest

from terp.core import (
    AuditPolicy,
    BootError,
    ControlPlane,
    CorsPolicy,
    ModuleSpec,
    PasswordPolicy,
    Policy,
    SecurityConfig,
    WeakPasswordError,
    create_app,
    settings,
    validate_password,
)
from terp.core.passwords import (
    active_password_policy,
    configure_password_policy,
    reset_password_policy_runtime,
)


# --- default policy: length / classes / denylist ---------------------------- #
def test_default_accepts_a_strong_passphrase() -> None:
    assert PasswordPolicy.default().violations("correct horse battery") == []


def test_default_rejects_too_short() -> None:
    problems = PasswordPolicy.default().violations("Ab1!xy")
    assert any("at least 12" in p for p in problems)


def test_default_rejects_single_character_class() -> None:
    # 12 lowercase letters: long enough, but only one class.
    problems = PasswordPolicy.default().violations("abcdefghijkl")
    assert any("at least 2" in p for p in problems)


def test_default_rejects_a_common_password() -> None:
    problems = PasswordPolicy.default().violations("password1234")
    assert any("common" in p for p in problems)


def test_validate_raises_typed_weak_password_error() -> None:
    with pytest.raises(WeakPasswordError) as excinfo:
        PasswordPolicy.default().validate("short")
    assert excinfo.value.status_code == 422
    assert excinfo.value.code == "weak_password"


# --- consumer overrides values, not shape (Tier-B) -------------------------- #
def test_consumer_can_tighten_values() -> None:
    strict = PasswordPolicy(min_length=20, min_character_classes=3, denylist=("acme",))
    assert strict.violations("correct horse battery") != []  # under 20 / too few classes
    assert strict.violations("Acme-Corporation-9000!") != []  # denied term
    assert strict.violations("Tr0ubadour-Sphinx-9000!") == []


def test_invalid_construction_is_refused() -> None:
    with pytest.raises(ValueError):
        PasswordPolicy(min_length=0)
    with pytest.raises(ValueError):
        PasswordPolicy(min_character_classes=5)


# --- relaxed: the justified escape hatch ------------------------------------ #
def test_relaxed_requires_a_reason() -> None:
    with pytest.raises(ValueError):
        PasswordPolicy.relaxed(reason="  ")


def test_relaxed_allows_anything_but_flags_production() -> None:
    relaxed = PasswordPolicy.relaxed(reason="legacy import only")
    assert relaxed.violations("pw") == []
    assert relaxed.is_relaxed
    assert relaxed.production_problems()  # refused at production boot


def test_default_is_production_safe() -> None:
    assert PasswordPolicy.default().production_problems() == []


def test_below_floor_min_length_flags_production() -> None:
    assert PasswordPolicy(min_length=6).production_problems()


# --- runtime install + reset ------------------------------------------------ #
def test_configure_and_reset_swap_the_active_policy() -> None:
    configure_password_policy(PasswordPolicy.relaxed(reason="test"))
    validate_password("pw")  # relaxed: accepted
    reset_password_policy_runtime()
    assert active_password_policy().production_problems() == []
    with pytest.raises(WeakPasswordError):
        validate_password("pw")  # default restored


# --- boot fail-fast: a relaxed policy is refused in production -------------- #
def _prod_plane(passwords: PasswordPolicy) -> ControlPlane:
    # Security/audit are made explicitly production-safe so only the password policy
    # can trip the fail-fast — isolating the control under test.
    return ControlPlane(
        security=SecurityConfig(cors=CorsPolicy.disabled(reason="api only")),
        audit=AuditPolicy.disabled(reason="trail not required for this service"),
        passwords=passwords,
    )


def test_create_app_refuses_a_relaxed_policy_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    plane = _prod_plane(PasswordPolicy.relaxed(reason="legacy import"))
    with pytest.raises(BootError, match="password policy"):
        create_app([ModuleSpec(name="ok", policy=Policy.default())], control_plane=plane)


def test_create_app_boots_in_production_with_the_default_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    plane = _prod_plane(PasswordPolicy.default())
    app = create_app([ModuleSpec(name="ok", policy=Policy.default())], control_plane=plane)
    assert app.title == "Terp app"
