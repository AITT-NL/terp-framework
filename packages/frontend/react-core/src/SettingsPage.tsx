import type { ReactNode } from "react";

import type { BreadcrumbItem } from "./Breadcrumbs";
import { LayoutSlotContext } from "./layoutContract";
import { Page } from "./Page";
import type { PageProps } from "./Page";

export interface SettingsPageProps extends Omit<PageProps, "breadcrumbs"> {
  /**
   * Optional parent layers, for a settings screen nested under an area rather than reached
   * from the account menu.
   *
   * Optional where `FormPage`'s is required, and the difference is real: a form is always
   * reached from the thing it writes into, while a preferences screen is often a destination in
   * its own right — the built-in profile page has no parent at all.
   */
  parents?: readonly (BreadcrumbItem & { to: string })[];
}

/**
 * The settings archetype: preferences and account screens — a stack of titled sections, each
 * owning a few controls.
 *
 * `measure="narrow"` by default, header included, for the reason `FormPage` has it: this is a
 * single column of controls, not a data surface. `ProfileView`'s own card carries exactly this
 * measure today, and 4b already named that card as a page measure wearing a card's clothes — so
 * this is the mechanism it was hand-rolling.
 *
 * **The body is `Card` sections and nothing that holds a collection.** No `DataView`, no
 * `DetailList`, no `Tabs`: a settings screen whose body is a table is an overview, and one with
 * tabs is a hub with the wrong chrome. `Card` is how a titled region is owned here — which is
 * what 4b decided when it refused to ship `Section`, and this slot is the first archetype to
 * depend on that decision rather than merely be compatible with it.
 *
 * Renders no element of its own, for the reason every non-hub archetype does not: a wrapper
 * around the body becomes the sole entry in `article.children` and fails every governed page
 * closed (ADR 0079).
 */
export function SettingsPage({
  parents,
  measure = "narrow",
  ...page
}: SettingsPageProps): ReactNode {
  return (
    <LayoutSlotContext.Provider value="SettingsPage">
      {/* Spread first, then the archetype's own props — see `FormPage` for why. */}
      <Page {...page} breadcrumbs={parents} measure={measure} />
    </LayoutSlotContext.Provider>
  );
}
