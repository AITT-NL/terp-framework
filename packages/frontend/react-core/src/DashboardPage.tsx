import type { ReactNode } from "react";

import type { BreadcrumbItem } from "./Breadcrumbs";
import { Page } from "./Page";
import type { PageProps } from "./Page";
import { LayoutSlotContext } from "./layoutContract";

export interface DashboardPageProps extends Omit<PageProps, "breadcrumbs"> {
  /** Optional parent layers for a dashboard nested below a hub or an area. */
  parents?: readonly (BreadcrumbItem & { to: string })[];
}

/**
 * The dashboard archetype (ADR 0169 §4): a page that answers "how is the whole doing", where an
 * overview answers "how is each one doing".
 *
 * Its figures go in the `summary` band under the title; its body is composed from the shape of
 * its data — templated `Grid` sections holding charts and figures side by side, the collection
 * the figures summarise, an `Alert` where something needs action. With a layout contract active
 * (ADR 0079) the body accepts exactly those: `Grid`, `Stack`, `Card`, `DataView`, the figure
 * family (`Stat`, `StatGroup`), the chart family (`TrendChart`, `BarChart`, `ProportionBar`),
 * `Timeline`, `Divider`, `Text`, `Alert`, `ConfirmDialog` and the framework states — refused
 * fail closed otherwise. ADR 0098 named the condition for this archetype as "a `Grid` decision", and the
 * track templates were that decision.
 */
export function DashboardPage({ parents, ...page }: DashboardPageProps): ReactNode {
  return (
    <LayoutSlotContext.Provider value="DashboardPage">
      <Page breadcrumbs={parents} {...page} />
    </LayoutSlotContext.Provider>
  );
}
