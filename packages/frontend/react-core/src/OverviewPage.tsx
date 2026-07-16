import type { ReactNode } from "react";

import { Page } from "./Page";
import type { PageProps } from "./Page";
import { LayoutSlotContext } from "./layoutContract";

export type OverviewPageProps = Omit<PageProps, "breadcrumbs">;

/**
 * The overview (level-2) page archetype: a module's top-level listing screen. It is a `Page`
 * without a redundant current-page-only crumb; detail pages under it link back here — so every
 * module's overview is constructed the same. Compose the body from `ResourceList` (or any listing UI).
 * With a layout contract active (ADR 0079), the body slot accepts only the contract's
 * listing components (e.g. `DataView` / `ResourceList`) — refused fail closed otherwise.
 */
export function OverviewPage(props: OverviewPageProps): ReactNode {
  return (
    <LayoutSlotContext.Provider value="OverviewPage">
      <Page {...props} />
    </LayoutSlotContext.Provider>
  );
}
