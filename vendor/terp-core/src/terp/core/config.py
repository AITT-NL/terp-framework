"""Typed application settings with production fail-fast guardrails.

The kernel keeps configuration minimal and company-agnostic. In
``ENVIRONMENT == "production"`` the settings object **refuses to construct**
when the configuration is unsafe (weak ``SECRET_KEY``, ``DEBUG`` on, SQLite, an
unverified database dialect, or permissive CORS), so an insecure app fails to
boot rather than serving traffic.

This is the runtime half of a two-layer control; the matching build-time test
lives in the architecture suite.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_PLACEHOLDER_SECRETS = {"", "changethis"}
_MIN_SECRET_LEN = 32


class Settings(BaseSettings):
    """Read-only typed settings. Modules read ``settings``; they never mutate it."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_ignore_empty=True,
        extra="ignore",
    )

    ENVIRONMENT: Literal["local", "staging", "production"] = "local"
    DEBUG: bool = False
    SECRET_KEY: str = "changethis"
    # Signing-key rotation (ADR 0076): ``SECRET_KEY`` signs every *new* credential;
    # the fallbacks only **verify**, so an already-issued access token survives a
    # rotation window instead of forcing every user out at the flip. Rotate by moving
    # the old key here, deploying, and dropping it once its longest-lived token has
    # expired. Verification order is SECRET_KEY first, then each fallback in order.
    SECRET_KEY_FALLBACKS: list[str] = []
    DATABASE_URL: str = "sqlite://"
    BACKEND_CORS_ORIGINS: list[str] = []
    PAGINATION_DEFAULT_LIMIT: int = 50
    PAGINATION_MAX_LIMIT: int = 200

    # Connection-pool tuning, applied to a server database (Postgres / MySQL / …);
    # SQLite (dev / test) keeps SQLAlchemy's default pool. See terp.core._internal.engine.
    DB_POOL_SIZE: int = Field(default=5, ge=1)
    DB_MAX_OVERFLOW: int = Field(default=10, ge=0)
    DB_POOL_TIMEOUT: int = Field(default=30, ge=1)
    DB_POOL_RECYCLE: int = Field(default=1800, ge=-1)  # -1 means 'never recycle' in SQLAlchemy
    DB_POOL_PRE_PING: bool = True

    # Per-session statement timeout, applied to a server database that supports it
    # (PostgreSQL, via `options=-c statement_timeout=<ms>` on every pooled connection),
    # so one runaway query cannot hold a worker + connection forever. 0 disables it
    # (dev/test only — production refuses 0 below). SQLite has no such knob and is
    # dev/test-only anyway.
    DB_STATEMENT_TIMEOUT_MS: int = Field(default=30_000, ge=0)

    # PostgreSQL is the *verified* production database: the dialect the CI conformance
    # lane, the deployment profile, and the Docker workbench actually test (ADR 0069).
    # Production boot refuses any other server dialect unless the deployment sets this
    # explicit acknowledgement; SQLite is always refused in production.
    DB_ALLOW_UNVERIFIED_DIALECT: bool = False

    # Physical table layout (ADR 0070). "flat" = every table in the default schema
    # (today's layout, any dialect). "per-module" = each package's tables live in a
    # PostgreSQL schema named after its migration label (notes, audit, …), created and
    # routed by `terp migrate` via the database-level search_path — the groundwork for
    # per-schema GRANTs. PostgreSQL-only: any other dialect fails closed at engine
    # construction, and the production guardrail below refuses the combination early.
    DB_SCHEMA_LAYOUT: Literal["flat", "per-module"] = "flat"

    # Refresh-token sessions (ADR 0054). A rotating opaque refresh token rides an httpOnly
    # cookie; only wired when the app supplies the refresh seams (else no cookie, no change).
    # TTLs are the per-token idle window and the absolute per-family session cap.
    REFRESH_TOKEN_TTL_SECONDS: int = Field(default=7 * 24 * 3600, ge=1)  # 7 days idle
    REFRESH_FAMILY_TTL_SECONDS: int = Field(default=14 * 24 * 3600, ge=1)  # 14 days absolute
    # Re-presenting a just-spent token within this window is treated as a benign race (two
    # tabs / a retried request), not theft: the rotation is honoured instead of killing the
    # family. Past the window a replay is the theft signal. 0 disables the grace entirely.
    REFRESH_ROTATION_GRACE_SECONDS: int = Field(default=60, ge=0)
    REFRESH_COOKIE_NAME: str = "terp_refresh"
    REFRESH_COOKIE_PATH: str = "/api/v1/auth"
    REFRESH_COOKIE_SAMESITE: Literal["strict", "lax", "none"] = "strict"
    # None → derive from environment: secure everywhere except local dev (which is http).
    REFRESH_COOKIE_SECURE: bool | None = None

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"

    @property
    def refresh_cookie_secure(self) -> bool:
        """Whether the refresh cookie carries the ``Secure`` flag.

        Explicit ``REFRESH_COOKIE_SECURE`` wins; otherwise secure-by-default everywhere
        except ``local`` (where the dev workbench is plain http and a ``Secure`` cookie
        would simply never be set).
        """
        if self.REFRESH_COOKIE_SECURE is not None:
            return self.REFRESH_COOKIE_SECURE
        return self.ENVIRONMENT != "local"

    @model_validator(mode="after")
    def _enforce_production_guardrails(self) -> Settings:
        if self.ENVIRONMENT != "production":
            return self

        problems: list[str] = []
        if self.SECRET_KEY in _PLACEHOLDER_SECRETS or len(self.SECRET_KEY) < _MIN_SECRET_LEN:
            problems.append(f"SECRET_KEY must be a strong value (>= {_MIN_SECRET_LEN} chars)")
        if any(
            key in _PLACEHOLDER_SECRETS or len(key) < _MIN_SECRET_LEN
            for key in self.SECRET_KEY_FALLBACKS
        ):
            problems.append(
                f"every SECRET_KEY_FALLBACKS entry must be a strong value "
                f"(>= {_MIN_SECRET_LEN} chars) — a weak fallback verifies tokens too"
            )
        if self.DEBUG:
            problems.append("DEBUG must be disabled")
        if self.DATABASE_URL.startswith("sqlite"):
            problems.append("a production database (not SQLite) is required")
        elif (
            not self.DATABASE_URL.startswith("postgresql")
            and not self.DB_ALLOW_UNVERIFIED_DIALECT
        ):
            problems.append(
                "PostgreSQL is the verified production database; running on an "
                "unverified dialect requires DB_ALLOW_UNVERIFIED_DIALECT=true"
            )
        if "*" in self.BACKEND_CORS_ORIGINS:
            problems.append("CORS must not allow '*'")
        if self.DB_SCHEMA_LAYOUT == "per-module" and not self.DATABASE_URL.startswith(
            "postgresql"
        ):
            problems.append(
                "DB_SCHEMA_LAYOUT='per-module' requires a PostgreSQL DATABASE_URL "
                "(schemas are a PostgreSQL feature)"
            )
        if self.DB_STATEMENT_TIMEOUT_MS <= 0:
            problems.append(
                "DB_STATEMENT_TIMEOUT_MS must be positive (a statement timeout is required)"
            )
        if not self.refresh_cookie_secure:
            problems.append("REFRESH_COOKIE_SECURE must be on (the refresh cookie is a credential)")
        if self.REFRESH_COOKIE_SAMESITE == "none" and not self.refresh_cookie_secure:
            problems.append("REFRESH_COOKIE_SAMESITE='none' requires REFRESH_COOKIE_SECURE")

        if problems:
            raise ValueError("Insecure production configuration: " + "; ".join(problems))
        return self


settings = Settings()


def get_settings() -> Settings:
    """Return the process-wide settings singleton."""
    return settings


__all__ = ["Settings", "get_settings", "settings"]
