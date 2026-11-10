"""The CORS declaration as ``terp inspect control-plane`` shows it: one explicit mode."""

from __future__ import annotations

from terp.core import CorsPolicy


def cors_json(cors: CorsPolicy) -> dict[str, object]:
    """The CORS declaration as one of four explicit modes (never raw fields)."""
    if cors.disabled_reason is not None:
        return {"mode": "disabled", "reason": cors.disabled_reason}
    if cors.origins_from_environment:
        # The origins are each environment's own: what is listed is what this process
        # was composed with, so a plane inspected before create_app lists none.
        return {
            "mode": "from-environment",
            "variable": "BACKEND_CORS_ORIGINS",
            "origins": list(cors.allow_origins),
            "allow_credentials": cors.allow_credentials,
        }
    if cors.allow_origins:
        return {
            "mode": "allow",
            "origins": list(cors.allow_origins),
            "allow_credentials": cors.allow_credentials,
        }
    return {"mode": "deny-all", "configured": cors.configured}


def cors_label(cors: CorsPolicy) -> str:
    if cors.disabled_reason is not None:
        return f"disabled ({cors.disabled_reason})"
    if cors.origins_from_environment:
        named = ", ".join(cors.allow_origins) or "none named here"
        return f"from BACKEND_CORS_ORIGINS ({named})"
    if cors.allow_origins:
        return "allow " + ", ".join(cors.allow_origins)
    return "deny-all" + ("" if cors.configured else " (unconfigured)")
