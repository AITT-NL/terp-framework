import { Link } from "@tanstack/react-router";
import type { RenderBreadcrumbLink } from "@terpjs/react-core";

export const ADMIN_PARENTS = [{ label: "Admin", to: "/admin" }] as const;

export const renderAdminCrumb: RenderBreadcrumbLink = (item) => (
  <Link to={item.to}>{item.label}</Link>
);