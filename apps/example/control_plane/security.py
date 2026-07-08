"""Example-app security control plane: headers, CORS, limits — declared once.

The example API is exercised server-to-server in tests (Bearer JWTs, no browser
origin), so cross-origin access is explicitly turned off with a reason rather than
left unset. Everything else uses the secure defaults; a real app would name its
SPA origin via ``CorsPolicy.allow([...])``.
"""

from __future__ import annotations

from terp.core import CorsPolicy, SecurityConfig

security = SecurityConfig(
    cors=CorsPolicy.disabled(
        reason="example API is consumed server-to-server in tests; no browser origin"
    ),
)

__all__ = ["security"]
