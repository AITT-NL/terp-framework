"""The single authority surface — declared once, validated at boot."""

from __future__ import annotations

from terp.core import AuditPolicy, ControlPlane, CorsPolicy, PermissionModel, SecurityConfig

control_plane = ControlPlane(
    permissions=PermissionModel.default(),
    security=SecurityConfig(cors=CorsPolicy.disabled(reason="server-to-server")),
    audit=AuditPolicy.default(),
)

__all__ = ["control_plane"]
