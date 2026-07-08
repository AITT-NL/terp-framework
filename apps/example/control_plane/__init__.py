"""Example-app control plane: the single authority surface.

Phase A starts with the default permission model; Phase C adds the security
declaration; Phase D adds the audit policy and the event catalog. Later slices add
realtime and database registries here instead of scattering cross-cutting
decisions through modules.
"""

from __future__ import annotations

from terp.core import ControlPlane, PermissionModel

from control_plane.audit import audit
from control_plane.events import event_catalog
from control_plane.jobs import job_catalog
from control_plane.security import security

control_plane = ControlPlane(
    permissions=PermissionModel.default(),
    security=security,
    audit=audit,
    events=event_catalog,
    jobs=job_catalog,
)

base_control_plane = ControlPlane(
    permissions=PermissionModel.default(),
    security=security,
    audit=audit,
)

__all__ = ["base_control_plane", "control_plane"]