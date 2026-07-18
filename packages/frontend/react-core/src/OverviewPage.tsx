import type { ReactNode } from "react";

import type { BreadcrumbItem } from "./Breadcrumbs";
import { Page } from "./Page";
import type { PageProps } from "./Page";
import { LayoutSlotContext } from "./layoutContract";

export interface OverviewPageProps extends Omit<PageProps, "breadcrumbs"> {
  /** Optional parent layers for an overview nested below a hub or another overview. */
  parents?: readonly (BreadcrumbItem & { to: string })[];
}

/**
 * The overview (level-2) page archetype: a module's top-level listing screen. It is a `Page`
 * without a redundant current-page-only crumb; detail pages under it link back here — so every
 * module's overview is constructed the same. Compose the body from `ResourceList` (or any listing UI).
 * With a layout contract active (ADR 0079), the body slot accepts only the contract's
 * listing components (e.g. `DataView` / `ResourceList`) — refused fail closed otherwise.
 */
export function OverviewPage({ parents, ...page }: OverviewPageProps): ReactNode {
  return (
    <LayoutSlotContext.Provider value="OverviewPage">
      <Page breadcrumbs={parents} {...page} />
    </LayoutSlotContext.Provider>
  );
}
