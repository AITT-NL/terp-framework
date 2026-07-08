import { Link } from "@tanstack/react-router";

import type { BreadcrumbItem, RenderBreadcrumbLink } from "../Breadcrumbs";
import type { TerpStrings } from "../uiText";

/** The admin hub's crumb — every admin overview breadcrumbs back to `/admin`. */
export function adminCrumb(strings: TerpStrings): BreadcrumbItem {
  return { label: strings.admin, to: "/admin" };
}

/** Ancestor crumbs link through the TanStack router (no raw same-app anchors). */
export const renderAdminCrumb: RenderBreadcrumbLink = (item) => (
  <Link to={item.to}>{item.label}</Link>
);
