"""Coverage gate: exercise kernel internals + the typed permission model.

These are pure-unit tests targeting the fail-closed/edge paths that the
end-to-end reference tests do not reach, so the framework holds 100% line
coverage (the drift/incompleteness guard for the code itself).
"""

from __future__ import annotations

import pathlib
import uuid

import pytest

from terp.core import (
    ADMIN,
    EDITOR,
    VIEWER,
    AuthorizationRequirement,
    ControlPlane,
    ModuleSpec,
    Permission,
    PermissionModel,
    Policy,
    Principal,
    Roles,
    Settings,
    as_role,
)
from terp.core.config import get_settings, settings
from terp.core.db import get_session
from terp.core.permissions import (
    Role,
    requirement_from,
    role_from_rank,
)
from terp.core._internal.discovery import iter_domain_packages
from terp.core._internal.engine import get_engine, reset_engine


# --------------------------------------------------------------------------- #
# _internal/engine + db
# --------------------------------------------------------------------------- #
def test_get_engine_is_cached_and_resettable() -> None:
    reset_engine()
    first = get_engine()
    assert get_engine() is first  # cached on the module global
    reset_engine()
    assert get_engine() is not first  # disposed + recreated
    reset_engine()


def test_get_session_yields_a_session() -> None:
    reset_engine()
    generator = get_session()
    session = next(generator)
    try:
        assert session is not None
    finally:
        generator.close()
    reset_engine()


# --------------------------------------------------------------------------- #
# _internal/discovery
# --------------------------------------------------------------------------- #
def test_iter_domain_packages_walks_roots_and_skips_noise(tmp_path: pathlib.Path) -> None:
    app = tmp_path / "app"
    (app / "capabilities" / "billing").mkdir(parents=True)
    (app / "modules" / "notes").mkdir(parents=True)
    (app / "modules" / "_private").mkdir(parents=True)  # underscore → skipped
    (app / "modules" / "stray.py").write_text("x = 1", encoding="utf-8")  # file → skipped
    # `foundation` root is absent → skipped without error.

    packages = iter_domain_packages(app)
    found = {(pkg.root, pkg.name, pkg.import_path) for pkg in packages}
    assert found == {
        ("capabilities", "billing", "app.capabilities.billing"),
        ("modules", "notes", "app.modules.notes"),
    }


# --------------------------------------------------------------------------- #
# config — production fail-fast guardrails
# --------------------------------------------------------------------------- #
def test_get_settings_returns_singleton() -> None:
    assert get_settings() is settings


def test_is_production_property() -> None:
    assert Settings(ENVIRONMENT="local").is_production is False
    assert Settings(
        ENVIRONMENT="production",
        SECRET_KEY="x" * 40,
        DATABASE_URL="postgresql+psycopg://u:p@h/db",
    ).is_production is True


def test_production_guardrails_accept_safe_config() -> None:
    safe = Settings(
        ENVIRONMENT="production",
        SECRET_KEY="x" * 40,
        DATABASE_URL="postgresql+psycopg://u:p@h/db",
        DEBUG=False,
        BACKEND_CORS_ORIGINS=["https://app.example.com"],
    )
    assert safe.is_production is True


@pytest.mark.parametrize(
    ("kwargs", "needle"),
    [
        ({"SECRET_KEY": "short"}, "SECRET_KEY"),
        (
            {"SECRET_KEY": "x" * 40, "SECRET_KEY_FALLBACKS": ["short"]},
            "SECRET_KEY_FALLBACKS",
        ),
        ({"SECRET_KEY": "x" * 40, "DEBUG": True}, "DEBUG"),
        ({"SECRET_KEY": "x" * 40, "DATABASE_URL": "sqlite://"}, "SQLite"),
        ({"SECRET_KEY": "x" * 40, "DATABASE_URL": "mysql+pymysql://h/db"}, "unverified dialect"),
        (
            {"SECRET_KEY": "x" * 40, "DATABASE_URL": "mysql+pymysql://h/db",
             "DB_ALLOW_UNVERIFIED_DIALECT": True, "DB_SCHEMA_LAYOUT": "per-module"},
            "per-module",
        ),
        (
            {"SECRET_KEY": "x" * 40, "DATABASE_URL": "postgresql://h/db",
             "BACKEND_CORS_ORIGINS": ["*"]},
            "CORS",
        ),
        ({"SECRET_KEY": "x" * 40, "REFRESH_COOKIE_SECURE": False}, "REFRESH_COOKIE_SECURE"),
        ({"SECRET_KEY": "x" * 40, "DB_STATEMENT_TIMEOUT_MS": 0}, "DB_STATEMENT_TIMEOUT_MS"),
        (
            {"SECRET_KEY": "x" * 40, "REFRESH_COOKIE_SAMESITE": "none",
             "REFRESH_COOKIE_SECURE": False},
            "SAMESITE",
        ),
    ],
)
def test_production_guardrails_reject_unsafe_config(kwargs: dict, needle: str) -> None:
    base = {"ENVIRONMENT": "production", "DATABASE_URL": "postgresql://h/db"}
    with pytest.raises(ValueError, match=needle):
        Settings(**{**base, **kwargs})


def test_production_accepts_an_unverified_dialect_only_with_acknowledgement() -> None:
    # PostgreSQL is the verified production database (ADR 0069): another server
    # dialect fails closed at boot unless the deployment explicitly accepts the
    # unverified path — and SQLite stays refused regardless of the acknowledgement.
    acknowledged = Settings(
        ENVIRONMENT="production",
        SECRET_KEY="x" * 40,
        DATABASE_URL="mysql+pymysql://u:p@h/db",
        DB_ALLOW_UNVERIFIED_DIALECT=True,
    )
    assert acknowledged.is_production is True
    with pytest.raises(ValueError, match="SQLite"):
        Settings(
            ENVIRONMENT="production",
            SECRET_KEY="x" * 40,
            DATABASE_URL="sqlite:///prod.db",
            DB_ALLOW_UNVERIFIED_DIALECT=True,
        )


def test_production_accepts_the_per_module_layout_on_postgres() -> None:
    # The per-module schema layout (ADR 0070) is PostgreSQL-only; on the verified
    # dialect it is a legitimate production configuration.
    safe = Settings(
        ENVIRONMENT="production",
        SECRET_KEY="x" * 40,
        DATABASE_URL="postgresql+psycopg://u:p@h/db",
        DB_SCHEMA_LAYOUT="per-module",
    )
    assert safe.DB_SCHEMA_LAYOUT == "per-module"


def test_refresh_cookie_secure_is_explicit_override_then_environment_default() -> None:
    # Explicit setting wins…
    assert Settings(ENVIRONMENT="local", REFRESH_COOKIE_SECURE=True).refresh_cookie_secure is True
    # …otherwise: secure everywhere except local dev (plain http).
    assert Settings(ENVIRONMENT="local").refresh_cookie_secure is False
    assert Settings(
        ENVIRONMENT="production",
        SECRET_KEY="x" * 40,
        DATABASE_URL="postgresql+psycopg://u:p@h/db",
    ).refresh_cookie_secure is True


# --------------------------------------------------------------------------- #
# permissions — typed model edge/guard paths
# --------------------------------------------------------------------------- #
def test_role_and_permission_reject_bad_tokens() -> None:
    with pytest.raises(ValueError, match="Role.name"):
        Role("bad name", rank=10)
    with pytest.raises(ValueError, match="Permission.name"):
        Permission("bad name", min_role=VIEWER)
    with pytest.raises(ValueError, match="Permission.name"):
        Permission("billing..read", min_role=VIEWER)


def test_role_from_rank_unknown_raises() -> None:
    with pytest.raises(ValueError, match="rank 999"):
        role_from_rank(999)


def test_permission_model_rejects_duplicate_rank_and_unregistered_role() -> None:
    with pytest.raises(ValueError, match="duplicate role rank"):
        PermissionModel(roles=[VIEWER, Role("viewer2", rank=10)])
    orphan = Permission("x.read", min_role=Role("ghost", rank=99))
    with pytest.raises(ValueError, match="unregistered role"):
        PermissionModel(permissions=[orphan])


def test_permission_model_rejects_duplicate_permission() -> None:
    perm = Permission("billing.read", min_role=VIEWER)
    dupe = Permission("billing.read", min_role=EDITOR)
    with pytest.raises(ValueError, match="duplicate permission"):
        PermissionModel(permissions=[perm, dupe])


def test_permission_model_lookups() -> None:
    model = PermissionModel()
    assert model.role_for_rank(ADMIN.rank) is ADMIN
    with pytest.raises(ValueError, match="rank 7"):
        model.role_for_rank(7)
    assert model.has_requirement(AuthorizationRequirement("nonsense", "x", 0)) is False


def test_requirement_from_normalizes_all_supported_inputs() -> None:
    assert requirement_from(EDITOR).label == "role:editor"
    perm = Permission("billing.read", min_role=VIEWER)
    assert requirement_from(perm).label == "permission:billing.read"
    assert requirement_from(Roles.ADMIN).label == "role:admin"  # legacy enum
    with pytest.raises(TypeError, match="Role, Permission"):
        requirement_from("not-an-authority-object")


# --------------------------------------------------------------------------- #
# module_spec — Policy normalization edge cases
# --------------------------------------------------------------------------- #
def test_policy_rejects_conflicting_read_and_write_args() -> None:
    with pytest.raises(ValueError, match="read= or read_role="):
        Policy(read=VIEWER, read_role=Roles.VIEWER)
    with pytest.raises(ValueError, match="write= or write_role="):
        Policy(write=EDITOR, write_role=Roles.EDITOR)


def test_policy_tiers_sugar() -> None:
    policy = Policy.tiers(read=VIEWER, write=ADMIN)
    assert policy.read_requirement.label == "role:viewer"
    assert policy.write_requirement.label == "role:admin"
    # A permission requirement carries its name and its min_role rank floor.
    mid = Permission("billing.approve", min_role=Role("approver", rank=15))
    assert Policy(write=mid).write_requirement.label == "permission:billing.approve"
    assert Policy(write=mid).write_requirement.min_rank == 15


def test_control_plane_default_is_compatible() -> None:
    plane = ControlPlane.default()
    spec = ModuleSpec(name="notes", policy=Policy.default())
    assert plane.validation_errors([spec]) == ()


def test_kernel_get_principal_defaults_to_unauthenticated() -> None:
    from terp.core import get_principal

    assert get_principal() is None


def test_as_role_normalizes_role_and_legacy_enum() -> None:
    assert as_role(EDITOR) is EDITOR  # typed Role passes through
    assert as_role(Roles.ADMIN) is ADMIN  # legacy enum -> matching default Role
    with pytest.raises(TypeError, match="must be a Role"):
        as_role("not-a-role")


def test_principal_carries_typed_and_custom_roles() -> None:
    from terp.core.permissions import Role

    legacy = Principal(id=uuid.uuid4(), role=Roles.EDITOR)
    assert isinstance(legacy.role, Role) and legacy.role.rank == 20
    # A consumer-defined role outside the default three tiers is carried as-is —
    # the framework no longer collapses it to viewer/editor/admin.
    approver = Role("approver", rank=25)
    assert Principal(id=uuid.uuid4(), role=approver).role is approver
