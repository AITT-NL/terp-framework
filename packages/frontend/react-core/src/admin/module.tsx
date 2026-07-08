import { defineModuleManifest } from "@terp/contract";

import type { TerpModule } from "../bootstrap";

import { AdminHub } from "./AdminHub";
import { AuditLogAdmin } from "./AuditLogAdmin";
import { GroupDetail } from "./GroupDetail";
import { GroupsAdmin } from "./GroupsAdmin";
import { UsersAdmin } from "./UsersAdmin";

/**
 * The packaged administration area every Terp app ships: one admin-gated "Admin"
 * sidebar entry opening a hub (`/admin`) whose cards lead to the users, groups and
 * audit-log overviews — the UI over the base-profile capabilities the backend
 * mounts in every app (users, groups + access, audit; ADR 0074). The whole area is
 * `role: "admin"` end to end; the backend re-checks every call regardless.
 *
 * `renderTerpApp` injects it by default (`adminArea: false` opts out; an app
 * manifest claiming one of its paths overrides that screen). An L2 composition
 * (`buildAppRouter`) spreads it in explicitly: append `adminModule.manifest` to the
 * manifests and merge `adminModule.views` into the views map.
 */
export const adminModule: TerpModule = {
  manifest: defineModuleManifest({
    name: "terp-admin",
    routes: [
      { path: "/admin", view: "TerpAdminHub", role: "admin" },
      { path: "/admin/users", view: "TerpAdminUsers", role: "admin" },
      { path: "/admin/groups", view: "TerpAdminGroups", role: "admin" },
      { path: "/admin/groups/$groupId", view: "TerpAdminGroupDetail", role: "admin" },
      { path: "/admin/audit", view: "TerpAdminAudit", role: "admin" },
    ],
    nav: [{ label: "Admin", to: "/admin", icon: "shield", role: "admin" }],
  }),
  views: {
    TerpAdminHub: AdminHub,
    TerpAdminUsers: UsersAdmin,
    TerpAdminGroups: GroupsAdmin,
    TerpAdminGroupDetail: GroupDetail,
    TerpAdminAudit: AuditLogAdmin,
  },
};
