"""The single authority surface — declared once, validated at boot."""

from __future__ import annotations

from terp.core import AuditPolicy, ControlPlane, CorsPolicy, PermissionModel, SecurityConfig

from control_plane.operations import operation_catalog

control_plane = ControlPlane(
    permissions=PermissionModel.default(),
    security=SecurityConfig(cors=CorsPolicy.disabled(reason="server-to-server")),
    audit=AuditPolicy.default(),
    # Every route declares the operation it performs (ADR 0102); this is what
    # those declarations are checked against at boot.
    operations=operation_catalog,
)

__all__ = ["control_plane"]
