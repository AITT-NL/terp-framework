import type { ReactNode } from "react";
import { useEffect, useRef, useState } from "react";

import { useLayoutContract, verifySlotChildren } from "./layoutContract";
import { Page } from "./Page";
import type { PageProps } from "./Page";
import { injectTerpStyles } from "./styles";
import { useUiText } from "./uiText";
import type { UiText } from "./uiText";

injectTerpStyles();

/** How much of the row the list pane takes — a step, not a length (ADR 0097 §4). */
export type SplitListWidth = "sm" | "md" | "lg";

export type SplitPageProps = Omit<PageProps, "children" | "measure"> & {
  /** Parent trail for a split screen nested below a hub; aliases `Page`'s `breadcrumbs`. */
  parents?: PageProps["breadcrumbs"];
  /**
   * The list pane's track (default `"md"`).
   *
   * Enumerable rather than a percentage or a length, which is the same call `Grid`'s
   * `minColumn` made and for the same reason: a CSS length here would be a measured value and
   * therefore an inline style on the panes element — a tenth entry in a ledger that admits only
   * two permanent kinds (ADR 0094 §3). Three steps cover the cases; an app wanting 37% cannot
   * have it, which is the trade `gap` already makes.
   *
   * A **draggable** divider is deliberately not offered: that is a measured value *and* a
   * per-user preference, so it waits for the preference seam rather than arriving as an inline
   * style with nowhere to persist.
   */
  listWidth?: SplitListWidth;
  /** The two panes — a `SplitPane role="list"` and a `SplitPane role="detail"`. */
  children: ReactNode;
};

/**
 * The split archetype: a list beside the record it selects — the master-detail screen.
 *
 * It is structured on `HubPage`, not on `DetailPage`, and that is the decision worth knowing.
 * The obvious shape for two panes is one body slot holding two children, but the layout
 * contract's runtime check takes a single slot owner and reads `article.children`, so two panes
 * would be two entries in one slot with nothing distinguishing them. Teaching the contract two
 * slots per archetype was the invasive option. Instead the panes are the governed thing:
 * `SplitPage` owns the row element and admits `SplitPane` in it and nothing else, exactly as
 * `HubPage` owns its grid and admits `HubCard`. `verifySlotChildren`, the mirrored table's
 * shape and the message builder are all untouched.
 *
 * It therefore provides **no** `LayoutSlotContext`, for the reason `HubPage` provides none: the
 * row element carries a marker that appears in no allow table, so a slot context above it would
 * refuse every split page on its own body.
 *
 * Below the mobile breakpoint the panes stack, in DOM order, list first — so the tab sequence is
 * the reading order in both layouts. That is the property `visual/keyboard.spec.ts` holds.
 */
export function SplitPage({
  parents,
  breadcrumbs,
  listWidth = "md",
  children,
  ...page
}: SplitPageProps) {
  // The runtime half of the slot-typed layout contract control (ADR 0079) for the pane row:
  // with a contract active, every rendered child of the row must be a SplitPane (its data-terp
  // marker) — verified one macrotask after mount, refused fail closed. Same shape as HubPage's.
  const contract = useLayoutContract();
  const panesRef = useRef<HTMLDivElement>(null);
  const [slotViolation, setSlotViolation] = useState<string | null>(null);
  useEffect(() => {
    if (contract === null) {
      return;
    }
    const timer = setTimeout(() => {
      const panes = panesRef.current;
      if (panes === null) {
        return;
      }
      setSlotViolation(verifySlotChildren(contract, "SplitPage", [...panes.children]));
    }, 0);
    return () => clearTimeout(timer);
  });
  if (slotViolation !== null) {
    throw new Error(slotViolation);
  }
  return (
    <Page {...page} breadcrumbs={parents ?? breadcrumbs}>
      <div ref={panesRef} data-terp="splitpage-panes" data-list-width={listWidth}>
        {children}
      </div>
    </Page>
  );
}

/** Which half of the split a pane is — the list, or the record it selects. */
export type SplitPaneRole = "list" | "detail";

export interface SplitPaneProps {
  /** Which half this is; decides which track it takes and nothing else. */
  role: SplitPaneRole;
  /**
   * The pane's accessible name.
   *
   * Required, because each pane is a `<section>` and therefore a landmark: two unnamed regions
   * side by side are two indistinguishable entries in a screen reader's landmark list, which is
   * worse than one region containing both.
   */
  label: UiText;
  children: ReactNode;
}

/**
 * One half of a {@link SplitPage} — the list, or the detail beside it.
 *
 * A named `<section>`, so the two halves are distinguishable landmarks, and the only component
 * the split's row admits. It renders no inline style: which track it takes comes from `role`,
 * one attribute with a rule each.
 */
export function SplitPane({ role, label, children }: SplitPaneProps) {
  const resolve = useUiText();
  return (
    <section data-terp="splitpane" data-role={role} aria-label={resolve(label)}>
      {children}
    </section>
  );
}
