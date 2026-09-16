"""The single authority surface — declared once, validated at boot."""

from __future__ import annotations

from terp.core import AuditPolicy, ControlPlane, CorsPolicy, PermissionModel, SecurityConfig

from control_plane.operations import operation_catalog

control_plane = ControlPlane(
    permissions=PermissionModel.default(),
    security=SecurityConfig(
        cors=CorsPolicy.disabled(reason="server-to-server"),
        # One hop, because this project ships one: `docker-compose.prod.yml` puts the
        # `web` container in front of the API and its nginx appends the caller to
        # `X-Forwarded-For`. The platform default is 0 — absent a trust declaration
        # that header is attacker-supplied — and leaving it at 0 here would resolve
        # every caller to the proxy's own address, making the rate limit and every
        # other per-caller control one shared bucket for the whole deployment. The
        # symptom is intermittent 429s under ordinary load, which reads as a limit set
        # too low rather than as this line. Change the number if you put another proxy
        # (a load balancer, an ingress, a CDN) in front of `web`; set it to 0 if you
        # remove `web` and expose the API directly.
        trusted_proxy_hops=1,
    ),
    audit=AuditPolicy.default(),
    # Every route declares the operation it performs (ADR 0102); this is what
    # those declarations are checked against at boot.
    operations=operation_catalog,
)

__all__ = ["control_plane"]
