import { Page } from "./Page";
import type { PageProps } from "./Page";
import type { BreadcrumbItem } from "./Breadcrumbs";
import { LayoutSlotContext } from "./layoutContract";

export interface DetailPageProps extends Omit<PageProps, "breadcrumbs"> {
  /**
   * The overview (and any intermediate layers) this record lives under, outermost first.
   * Every ancestor crumb must link back up, so `to` is required — a detail page is never
   * orphaned from its overview.
   */
  parents: readonly (BreadcrumbItem & { to: string })[];
}

/**
 * The detail (level-3) page archetype: one record's screen, reached from an overview. It is a
 * `Page` whose breadcrumb trail is the ancestor layers plus the record itself (`title`), so
 * users can always navigate back up — the shell -> overview -> detail layering by construction.
 * With a layout contract active (ADR 0079), the body slot accepts only the contract's record
 * components (e.g. `DetailList` / `Stack` / `Tabs`) — refused fail closed otherwise.
 */
export function DetailPage({ parents, ...page }: DetailPageProps) {
  return (
    <LayoutSlotContext.Provider value="DetailPage">
      <Page breadcrumbs={parents} {...page} />
    </LayoutSlotContext.Provider>
  );
}
