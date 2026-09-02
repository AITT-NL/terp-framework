"""Example-app control plane: the single authority surface.

Every cross-cutting decision this app makes is declared here rather than scattered
through its modules: the role ladder and named permissions, the security posture, the
audit policy, and the event, job and operation catalogs. Later slices add the realtime
and database registries in the same place.
"""

from __future__ import annotations

from terp.core import ControlPlane, PermissionModel

from control_plane.audit import audit
from control_plane.events import event_catalog
from control_plane.jobs import job_catalog
from control_plane.operations import operation_catalog
from control_plane.permissions import permission_model
from control_plane.security import security

control_plane = ControlPlane(
    permissions=permission_model,
    security=security,
    audit=audit,
    events=event_catalog,
    jobs=job_catalog,
    operations=operation_catalog,
)

base_control_plane = ControlPlane(
    # The bare ladder, deliberately: unlike the operations catalog below, a superset
    # permission model would be a claim rather than a harmless spare. The base profile
    # mounts no module that checks a named permission — `notes` is not in it — so
    # declaring `notes.delete` here would put a permission in `terp inspect access` and
    # in `terp grant`'s catalog that nothing in this profile could ever enforce.
    permissions=PermissionModel.default(),
    security=security,
    audit=audit,
    # Shares the same catalog as `control_plane`, strict coverage included: the base
    # profile mounts a subset of the same modules and capabilities (login/me, access,
    # audit, groups, users), and every route in that subset already declares an
    # operation (phase 5), so strict refuses nothing here either — a superset catalog
    # is harmless regardless, since strict only checks a MOUNTED route, never an
    # unused catalog entry.
    operations=operation_catalog,
)

__all__ = ["base_control_plane", "control_plane"]