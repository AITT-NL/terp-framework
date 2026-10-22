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

import json
import uuid
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

_PLACEHOLDER_SECRETS = {"", "changethis"}
_MIN_SECRET_LEN = 32

#: A list of previous keys as the environment spells it: comma-separated, which is what a
#: deploy tool writes into an env file, or the JSON list ADR 0076 documented first.
#: ``NoDecode`` hands the raw string to ``Settings._split_key_list`` rather than to the
#: settings source's JSON decoder, which would refuse the comma-separated form.
_KeyList = Annotated[list[str], NoDecode]


def _entries(positions: list[int]) -> str:
    """``entry 2`` or ``entries 1, 3``: where in a list, never what is there."""
    label = "entry" if len(positions) == 1 else "entries"
    return f"{label} {', '.join(str(position) for position in positions)}"


def _key_list_problems(name: str, keys: list[str], current: str, weak_reason: str) -> list[str]:
    """What is wrong with one list of previous keys, named by position and never by value.

    A weak entry is refused as a weak ``SECRET_KEY`` is, because it opens as much as the
    current key does. An entry equal to ``SECRET_KEY``, or one listed twice, is a rotation
    with a slip in it: the old key copied into the list and the new one never set, or one
    key pasted twice and the one really retired left out. The first leaves the "rotated"
    key in use; the second loses whatever only the missing key opens once the app runs.
    """
    weak = [
        position
        for position, key in enumerate(keys, start=1)
        if key in _PLACEHOLDER_SECRETS or len(key) < _MIN_SECRET_LEN
    ]
    current_again = [position for position, key in enumerate(keys, start=1) if key == current]
    repeated = [
        position for position, key in enumerate(keys, start=1) if key in keys[: position - 1]
    ]
    problems: list[str] = []
    if weak:
        problems.append(
            f"every {name} entry must be a strong value (>= {_MIN_SECRET_LEN} chars) — "
            f"{weak_reason} ({_entries(weak)})"
        )
    if current_again:
        problems.append(
            f"{name} holds SECRET_KEY itself ({_entries(current_again)}) — a fallback is "
            "a previous key, and the new one goes in SECRET_KEY"
        )
    if repeated:
        problems.append(
            f"{name} lists a key more than once ({_entries(repeated)}) — list each "
            "previous key once"
        )
    return problems


class Settings(BaseSettings):
    """Read-only typed settings. Modules read ``settings``; they never mutate it."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_ignore_empty=True,
        extra="ignore",
        # A refused value is never echoed back. Pydantic prints the input beside each
        # error, shortened in the middle, which for this object means the tail of a
        # DATABASE_URL (its password) or most of a key in one of the lists below. The
        # error names the field and the rule; the value stays where it came from.
        hide_input_in_errors=True,
    )

    ENVIRONMENT: Literal["local", "staging", "production"] = "local"
    DEBUG: bool = False
    SECRET_KEY: str = "changethis"
    # Key rotation (ADR 0076 §2, amended by ADR 0189). ``SECRET_KEY`` signs and seals
    # everything new; nothing is ever signed or sealed with a previous key. Previous keys
    # live in two lists because what each keeps readable lasts for a different time:
    #
    # - SECRET_KEY_FALLBACKS only VERIFIES a signature (an access token, the digest a
    #   refresh session is looked up by), and only inside that signature's own lifetime.
    #   Drop it once the longest of those lifetimes has passed since the deploy that
    #   added it.
    # - SECRET_KEY_DECRYPT_FALLBACKS only DECRYPTS a value sealed at rest (sealed config,
    #   webhook signing secrets, MFA enrolments). Drop it once `terp secrets reseal`
    #   reports nothing left under it.
    #
    # A rotation puts the old key in both. Each list is tried in order, after SECRET_KEY.
    SECRET_KEY_FALLBACKS: _KeyList = []
    SECRET_KEY_DECRYPT_FALLBACKS: _KeyList = []
    DATABASE_URL: str = "sqlite://"
    # The principal a job's writes are stamped with when no user originated the work
    # (ADR 0125 requires one; ADR 0129 makes this the way it arrives). A deployment
    # fact, not a source constant: the same image runs against databases whose service
    # principals have different ids, so the id cannot live in the code that is built
    # once. `ControlPlane(job_system_actor_id=...)` still wins where an app resolves it
    # some other way; this is the conventional address, so that declaring the
    # requirement does not oblige every app to hand-roll the same env read, UUID parse
    # and error path. `None` keeps the production refusal exactly as it was.
    JOB_SYSTEM_ACTOR_ID: uuid.UUID | None = None
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

    @field_validator("SECRET_KEY_FALLBACKS", "SECRET_KEY_DECRYPT_FALLBACKS", mode="before")
    @classmethod
    def _split_key_list(cls, value: object) -> object:
        """A key list from the environment: comma-separated, or a JSON list.

        A blank segment is dropped, so a trailing comma is not an empty key. A JSON entry
        that is empty stays in the list, where the production guardrail refuses it.
        """
        if not isinstance(value, str):
            return value
        text = value.strip()
        if text.startswith("["):
            return json.loads(text)
        return [part.strip() for part in text.split(",") if part.strip()]

    @model_validator(mode="after")
    def _enforce_production_guardrails(self) -> Settings:
        if self.ENVIRONMENT != "production":
            return self

        problems: list[str] = []
        if self.SECRET_KEY in _PLACEHOLDER_SECRETS or len(self.SECRET_KEY) < _MIN_SECRET_LEN:
            problems.append(f"SECRET_KEY must be a strong value (>= {_MIN_SECRET_LEN} chars)")
        problems += _key_list_problems(
            "SECRET_KEY_FALLBACKS", self.SECRET_KEY_FALLBACKS, self.SECRET_KEY,
            "a weak fallback verifies tokens too",
        )
        problems += _key_list_problems(
            "SECRET_KEY_DECRYPT_FALLBACKS", self.SECRET_KEY_DECRYPT_FALLBACKS, self.SECRET_KEY,
            "a weak fallback decrypts sealed values too",
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
