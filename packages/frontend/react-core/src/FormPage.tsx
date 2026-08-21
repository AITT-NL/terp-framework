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
 * **The body is a form, so `Field` is deliberately not admitted directly.** A run of bare
 * fields is a form that cannot submit: Enter does nothing without a `<form>` element, and the
 * house spelling of one is `Stack as="form"`. Admitting `Field` at the top level would sanction
 * exactly the screen that looks finished and cannot be submitted by keyboard. So the slot takes
 * the form container, plus `Grid` for a two-column arrangement inside a wide form, `Card` for a
 * grouped section, `Divider` and `Text` between them, and the framework states.
 *
 * It renders no element of its own — the slot context and `Page`, nothing between them, because
 * a wrapper around the body would become the sole entry in `article.children` and fail every
 * governed page closed (ADR 0079).
 */
export function FormPage({ parents, measure = "narrow", ...page }: FormPageProps) {
  return (
    <LayoutSlotContext.Provider value="FormPage">
      <Page breadcrumbs={parents} measure={measure} {...page} />
    </LayoutSlotContext.Provider>
  );
}
