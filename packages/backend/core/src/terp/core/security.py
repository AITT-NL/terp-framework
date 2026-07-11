"""``SecurityConfig`` — the application's central security control plane.

One typed, validated object declares every HTTP cross-cutting security control:
response headers, CORS (deny-by-default), the request body-size cap, the
rate-limit, and the request-id header name. The composition root installs the
matching middleware from this single declaration, so two modules can never ship
divergent security postures (no drift), and a module cannot hand-roll its own
(enforced by the ``terp.arch`` ``no_adhoc_middleware`` rule).

Secure-by-default, with one deliberately *explicit* control: CORS denies all
cross-origin access by default, and a production boot **refuses** until the app
makes a conscious choice — declare an allowlist with :meth:`CorsPolicy.allow`, or
opt out with a reason via :meth:`CorsPolicy.disabled`. A control may be absent
only on purpose, never by accident.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:  # pragma: no cover - typing only
    from starlette.requests import Request

_DEFAULT_PERMISSIONS_POLICY: Final[str] = (
    "accelerometer=(), camera=(), geolocation=(), gyroscope=(), "
    "magnetometer=(), microphone=(), payment=(), usb=()"
)
_DEFAULT_CSP: Final[str] = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'"
_DEFAULT_HSTS: Final[str] = "max-age=63072000; includeSubDomains; preload"
_DEFAULT_CORS_METHODS: Final[tuple[str, ...]] = (
    "GET",
    "POST",
    "PUT",
    "PATCH",
    "DELETE",
    "OPTIONS",
)
_DEFAULT_CORS_HEADERS: Final[tuple[str, ...]] = (
    "Authorization",
    "Content-Type",
    "X-Request-ID",
)


@dataclass(frozen=True)
class SecurityHeaders:
    """The security-relevant response headers applied to every response.

    ``hsts`` is applied only outside local development (a plain-HTTP localhost
    must not be pinned to HTTPS); set it to ``None`` to disable entirely.
    """

    x_content_type_options: str = "nosniff"
    x_frame_options: str = "DENY"
    referrer_policy: str = "strict-origin-when-cross-origin"
    permissions_policy: str = _DEFAULT_PERMISSIONS_POLICY
    content_security_policy: str = _DEFAULT_CSP
    hsts: str | None = _DEFAULT_HSTS

    def as_headers(self, *, include_hsts: bool) -> dict[str, str]:
        """Render the configured headers (HSTS included only when *include_hsts*)."""
        headers = {
            "X-Content-Type-Options": self.x_content_type_options,
            "X-Frame-Options": self.x_frame_options,
            "Referrer-Policy": self.referrer_policy,
            "Permissions-Policy": self.permissions_policy,
            "Content-Security-Policy": self.content_security_policy,
        }
        if include_hsts and self.hsts:
            headers["Strict-Transport-Security"] = self.hsts
        return headers


@dataclass(frozen=True)
class CorsPolicy:
    """Cross-origin browser access — deny-by-default.

    The default (:meth:`deny_all`) blocks all cross-origin access *and* is marked
    unconfigured, so a production boot refuses until the app makes an explicit
    choice. ``allow_origins`` is never ``"*"`` together with credentials (a
    browser-rejected, dangerous combination) — that is a construction error.
    """

    allow_origins: tuple[str, ...] = ()
    allow_credentials: bool = False
    allow_methods: tuple[str, ...] = _DEFAULT_CORS_METHODS
    allow_headers: tuple[str, ...] = _DEFAULT_CORS_HEADERS
    expose_headers: tuple[str, ...] = ("X-Request-ID",)
    configured: bool = False
    disabled_reason: str | None = None

    def __post_init__(self) -> None:
        if self.is_wildcard and self.allow_credentials:
            raise ValueError(
                "CORS cannot combine a '*' origin with credentials; name explicit origins"
            )

    @classmethod
    def deny_all(cls) -> CorsPolicy:
        """The unset, secure default: no cross-origin access, not yet acknowledged."""
        return cls()

    @classmethod
    def disabled(cls, *, reason: str) -> CorsPolicy:
        """Run with no cross-origin access as a conscious, greppable opt-out."""
        if not reason or not reason.strip():
            raise ValueError("CorsPolicy.disabled(reason=...) requires a non-empty justification")
        return cls(configured=True, disabled_reason=reason.strip())

    @classmethod
    def allow(
        cls,
        origins: Iterable[str],
        *,
        allow_credentials: bool = False,
        allow_methods: Iterable[str] = _DEFAULT_CORS_METHODS,
        allow_headers: Iterable[str] = _DEFAULT_CORS_HEADERS,
        expose_headers: Iterable[str] = ("X-Request-ID",),
    ) -> CorsPolicy:
        """Allow a fixed allowlist of cross-origin browser origins."""
        normalized = tuple(origins)
        if not normalized:
            raise ValueError(
                "CorsPolicy.allow(origins) needs at least one origin; "
                "use CorsPolicy.disabled(reason=...) to run with no CORS"
            )
        return cls(
            allow_origins=normalized,
            allow_credentials=allow_credentials,
            allow_methods=tuple(allow_methods),
            allow_headers=tuple(allow_headers),
            expose_headers=tuple(expose_headers),
            configured=True,
        )

    @property
    def is_wildcard(self) -> bool:
        return "*" in self.allow_origins

    @property
    def enabled(self) -> bool:
        """True when an allowlist should actually be served by the CORS middleware."""
        return bool(self.allow_origins) and self.disabled_reason is None


@dataclass(frozen=True)
class RateLimit:
    """A fixed-window request-rate cap; ``requests <= 0`` disables it."""

    requests: int = 240
    window_seconds: int = 60

    def __post_init__(self) -> None:
        if self.window_seconds <= 0:
            raise ValueError("RateLimit.window_seconds must be positive")

    @property
    def enabled(self) -> bool:
        return self.requests > 0

    @classmethod
    def disabled(cls) -> RateLimit:
        """An explicitly disabled rate limit (rejected by production guardrails)."""
        return cls(requests=0)


@dataclass(frozen=True)
class SecurityConfig:
    """The single security declaration consumed by ``create_app``.

    A safe default is provided so existing apps boot unchanged; the one control
    that cannot be defaulted safely — *which* cross-origins to trust — must be
    declared before production (see :meth:`production_problems`).

    ``trusted_proxy_hops`` declares how many reverse-proxy hops in front of the app
    are trusted to append ``X-Forwarded-For`` entries. It defaults to ``0`` (the
    direct TCP peer identifies the caller — forwarding headers are attacker-supplied
    and ignored). A deployment behind one trusted proxy (e.g. the shipped nginx
    same-origin profile) sets ``1`` so per-caller controls — the rate limit, the
    OIDC callback throttle — key on the *real* client address instead of collapsing
    every caller onto the proxy's IP.
    """

    headers: SecurityHeaders = field(default_factory=SecurityHeaders)
    cors: CorsPolicy = field(default_factory=CorsPolicy.deny_all)
    rate_limit: RateLimit = field(default_factory=RateLimit)
    max_request_bytes: int = 1024 * 1024
    request_id_header: str = "X-Request-ID"
    trusted_proxy_hops: int = 0
    #: Serve the FastAPI docs endpoints (``/docs`` / ``/redoc`` / ``/openapi.json``)
    #: in PRODUCTION. Off by default (secure-by-default: a production API's full
    #: schema is not public information); development always serves them. The
    #: openapi document itself stays exportable via ``terp openapi`` either way.
    expose_api_docs: bool = False

    def __post_init__(self) -> None:
        if self.max_request_bytes <= 0:
            raise ValueError("SecurityConfig.max_request_bytes must be positive")
        if not self.request_id_header.strip():
            raise ValueError("SecurityConfig.request_id_header must be a non-empty header name")
        if self.trusted_proxy_hops < 0:
            raise ValueError("SecurityConfig.trusted_proxy_hops must be zero or positive")

    @classmethod
    def default(cls) -> SecurityConfig:
        """The compatibility security config: safe headers/limits, CORS unset."""
        return cls()

    def production_problems(self) -> list[str]:
        """Every reason this config is unsafe to boot in production (fail-fast).

        Returns an empty list when the config is production-safe. The composition
        root raises ``BootError`` when this is non-empty under
        ``ENVIRONMENT == "production"``.
        """
        problems: list[str] = []
        if not self.cors.configured:
            problems.append(
                "CORS is unset; declare CorsPolicy.allow([...]) or "
                "CorsPolicy.disabled(reason=...) before production"
            )
        if self.cors.is_wildcard:
            problems.append("CORS must not allow '*' in production")
        if not self.rate_limit.enabled:
            problems.append("rate limiting must be enabled in production")
        return problems


__all__ = [
    "CorsPolicy",
    "RateLimit",
    "SecurityConfig",
    "SecurityHeaders",
    "client_ip",
]


def client_ip(request: Request) -> str:
    """The caller's client address, honouring the app's trusted-proxy declaration.

    The one sanctioned way to identify a caller by network address (per-caller
    throttles, lockout keys, access logs). It reads the address the central
    ``ClientIpMiddleware`` resolved from ``SecurityConfig.trusted_proxy_hops`` —
    so behind a declared proxy it is the real client, never the proxy — and falls
    back to the direct TCP peer (or ``"anonymous"``) when the stack has not run
    (e.g. a bare test app). A module must never parse ``X-Forwarded-For`` itself:
    with no trust declaration the header is attacker-supplied.
    """
    resolved = getattr(request.state, "client_ip", None)
    if resolved:
        return str(resolved)
    if request.client is not None:
        return request.client.host
    return "anonymous"
