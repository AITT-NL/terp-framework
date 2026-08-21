import type { BreadcrumbItem } from "./Breadcrumbs";
import { LayoutSlotContext } from "./layoutContract";
import { Page } from "./Page";
import type { PageProps } from "./Page";

export interface FormPageProps extends Omit<PageProps, "breadcrumbs"> {
  /**
   * The layers this form sits under, outermost first — the list it was reached from, and
   * anything above that.
   *
   * Required, and for the reason `DetailPage`'s is: a create or edit screen is always reached
   * from somewhere, and a form with no way back is a dead end with unsaved work in it.
   */
  parents: readonly (BreadcrumbItem & { to: string })[];
}

/**
 * The form archetype: one create-or-edit screen, reached from the collection it writes into.
 *
 * It is a `Page` with two things fixed. The frame is `measure="narrow"` by default — header
 * included — because a form is a single column of controls and a Save button a screen-width
 * from its last field is worse than one sitting over it. And the body slot admits the shape a
 * form actually has rather than the shape a record screen has.
 *
 * **The body is a container, so `Field` is deliberately not admitted directly.** The slot takes
 * the form container, plus `Grid` for a two-column arrangement inside a wide form, `Card` for a
 * grouped section, `Divider` and `Text` between them, and the framework states.
 *
 * What that refusal does and does not buy is worth stating exactly, because the obvious claim is
 * too strong. It keeps fields out of the top level, so a form body is always a container — which
 * is the shape the archetype is for. It does **not** guarantee the form can be submitted: both
 * halves of the contract match on `data-terp` markers, and `Stack` renders the same marker
 * whether or not it was given `as="form"`. So `<Stack><Field/></Stack>` passes and is still
 * unsubmittable by Enter. Closing that would mean a second marker for the form case, which is
 * six more names describing the same DOM — the `Section` trade 4b already declined.
 *
 * It renders no element of its own — the slot context and `Page`, nothing between them, because
 * a wrapper around the body would become the sole entry in `article.children` and fail every
 * governed page closed (ADR 0079).
 */
export function FormPage({ parents, measure = "narrow", ...page }: FormPageProps) {
  return (
    <LayoutSlotContext.Provider value="FormPage">
      {/* Spread FIRST, then the archetype's own props — `HubPage`'s order, not
          `DetailPage`'s. `Omit<PageProps, "breadcrumbs">` removes the key from the type but not
          from a runtime object, and a JSX spread gets no excess-property check: a wrapper
          forwarding `{...props}` with a present-but-undefined `breadcrumbs` would otherwise
          overwrite `parents` and silently drop the trail this archetype requires.
          (`DetailPage` and `OverviewPage` still spread last. Same latent shape, pre-existing,
          and left for a change that can re-record their baselines rather than this one.) */}
      <Page {...page} breadcrumbs={parents} measure={measure} />
    </LayoutSlotContext.Provider>
  );
}
