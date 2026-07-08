"""Typed domain-exception hierarchy + the uniform error-envelope helper.

This is the single source of truth for the error responses a Terp app emits.
Module code raises a typed :class:`AppError` subclass; the composition root
renders it into a uniform JSON envelope::

    {"code": "<stable_machine_code>", "detail": "<message>", "request_id": "<id>"}

Design notes
------------
* **Consistent envelope.** Every error carries the same three keys so the
  frontend dispatches on a stable ``code`` instead of pattern-matching prose.
* **Locale-neutral defaults.** ``default_message`` strings are English and
  presentation-neutral. User-facing localisation is a frontend concern and is
  never baked into core.
* **No accidental leakage.** The default message is hand-written; the raw
  exception goes into ``log_context`` (logged, never serialised).

Add a new code by subclassing the closest parent and overriding ``code`` (a
stable snake_case slug) and ``default_message``. ``status_code`` lives only in
this module.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, ClassVar


class AppError(Exception):
    """Base class for every domain exception in a Terp app.

    Concrete subclasses override ``status_code`` (HTTP status), ``code`` (a
    stable snake_case slug the frontend dispatches on) and ``default_message``
    (English fallback). ``log_context`` attaches structured fields to the log
    line and is **never** serialised to the client.
    """

    status_code: ClassVar[int] = 400
    code: ClassVar[str] = "bad_request"
    default_message: ClassVar[str] = "The request could not be processed."

    def __init__(
        self,
        message: str | None = None,
        *,
        log_context: Mapping[str, Any] | None = None,
    ) -> None:
        self.message = message or self.default_message
        self.log_context: dict[str, Any] = dict(log_context or {})
        super().__init__(self.message)


class ValidationFailedError(AppError):
    """400 — business-rule violations that schema validation cannot express."""

    status_code = 400
    code = "validation_failed"
    default_message = "The submitted data is invalid."


class InvalidTokenError(AppError):
    """400 — a token (reset, invite, refresh, …) is malformed, expired, or used."""

    status_code = 400
    code = "invalid_token"
    default_message = "The token is invalid, expired, or already used."


class AuthenticationError(AppError):
    """401 — no valid authenticated principal."""

    status_code = 401
    code = "authentication_required"
    default_message = "Authentication is required."


class PermissionDeniedError(AppError):
    """403 — the principal is known but not allowed to perform this action."""

    status_code = 403
    code = "permission_denied"
    default_message = "You do not have permission to perform this action."


class NotFoundError(AppError):
    """404 — the requested resource does not exist (or is not visible)."""

    status_code = 404
    code = "not_found"
    default_message = "The requested resource was not found."


class ConflictError(AppError):
    """409 — the request conflicts with the current state of the resource."""

    status_code = 409
    code = "conflict"
    default_message = "The request conflicts with the current state of the resource."


class StaleDataError(ConflictError):
    """409 — optimistic-concurrency clash; the row changed since it was read."""

    code = "stale_data"
    default_message = "This item was changed by someone else. Refresh and try again."


def build_error_envelope(error: AppError, *, request_id: str) -> dict[str, str]:
    """Render *error* into the uniform ``{code, detail, request_id}`` envelope."""
    return {
        "code": error.code,
        "detail": error.message,
        "request_id": request_id,
    }


__all__ = [
    "AppError",
    "AuthenticationError",
    "ConflictError",
    "InvalidTokenError",
    "NotFoundError",
    "PermissionDeniedError",
    "StaleDataError",
    "ValidationFailedError",
    "build_error_envelope",
]
