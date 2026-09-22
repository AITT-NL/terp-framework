"""Provider registry — one validated ``OIDCProviderConfig`` per named provider.

Fail-fast (ADR 0058): a config is validated at construction, so a misconfigured
provider refuses to boot instead of failing on the first login. The redirect URI is
the app's own explicit allowlisted value — it is signed into every authorize request
and echoed at the token exchange, so an attacker-supplied redirect can never enter
the flow (deny-by-default, mirroring the CORS stance). In production the issuer and
redirect URI must be ``https``; the scopes must include ``openid`` (without it the
IdP would run plain OAuth2 and return no ID token).

The ``client_secret`` may be a sealed ``enc:v1:`` value (ADR 0055); the capability
never decrypts it — see ``build_oidc_module``'s ``secret_resolver`` seam.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from terp.core import settings

_NAME_RE = re.compile(r"^[a-z][a-z0-9_-]*$")

_logger = logging.getLogger("terp.capabilities.oidc.config")


@dataclass(frozen=True)
class OIDCProviderConfig:
    """One OIDC provider: issuer + client credentials + the allowlisted redirect URI."""

    name: str
    issuer: str
    client_id: str
    client_secret: str
    redirect_uri: str
    scopes: tuple[str, ...] = ("openid", "email", "profile")

    def __post_init__(self) -> None:
        if not _NAME_RE.match(self.name):
            raise ValueError(
                f"OIDC provider name {self.name!r} must be a lowercase slug "
                "(it becomes a path segment)"
            )
        if "openid" not in self.scopes:
            raise ValueError(
                f"OIDC provider {self.name!r} must request the 'openid' scope; "
                "without it the IdP returns no ID token"
            )
        for label, url in (("issuer", self.issuer), ("redirect_uri", self.redirect_uri)):
            if not url.startswith(("https://", "http://")):
                raise ValueError(
                    f"OIDC provider {self.name!r} {label} must be an http(s) URL"
                )
        if not self.client_id:
            raise ValueError(f"OIDC provider {self.name!r} requires a client_id")

        # Decided by an environment-INDEPENDENT predicate so the answer exists somewhere
        # a gate can read it, not only inside a branch that runs on the production host.
        # Outside production the same state is said out loud rather than tolerated in
        # silence: permissive in the inner loop, never quiet (ADR 0128).
        problems = self.production_problems()
        if problems:
            if settings.is_production:
                raise ValueError("; ".join(problems))
            _logger.warning(
                "OIDC provider %r is configured over PLAINTEXT in this deployment: %s. A "
                "production boot is REFUSED in this state.",
                self.name,
                "; ".join(problems),
            )

    def production_problems(self) -> list[str]:
        """What a production boot refuses about this provider, environment-independent.

        The same shape ``ControlPlane`` uses, and for the same reason: "would this
        configuration boot in production" has to be answerable off the production host,
        from the declaration alone. A ``__post_init__`` that raises is the enforcement;
        it is not an answer anything else can ask for, which is how a tree can carry a
        green pre-ship gate into a deployment that will not start.
        """
        return [
            f"OIDC provider {self.name!r} {label} must be https in production "
            "(a plaintext redirect leaks the authorization code)"
            for label, url in (("issuer", self.issuer), ("redirect_uri", self.redirect_uri))
            if url.startswith("http://")
        ]


@dataclass(frozen=True)
class OIDCClaims:
    """The validated identity claims an SSO login hands to the identity seam.

    Only what the ``resolve_or_provision`` seam needs: the stable ``(issuer, subject)``
    pair links to a local user; the email pair gates JIT provisioning (a provisioner
    must refuse an unverified email — ADR 0058). The IdP's raw tokens never leave the
    capability.
    """

    issuer: str
    subject: str
    email: str | None = None
    email_verified: bool = False
    name: str | None = None
    raw: dict[str, object] = field(default_factory=dict)


__all__ = ["OIDCClaims", "OIDCProviderConfig"]
