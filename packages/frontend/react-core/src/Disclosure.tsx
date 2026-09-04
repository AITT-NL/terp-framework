/**
 * One labelled toggle over one region — progressive disclosure for a single value.
 *
 * ADR 0099 refused an `Accordion` ("a policy over a disclosure set, and there is no
 * disclosure set to apply it to") and a `Collapsible` ("nothing in the framework has
 * anything to collapse"), and both readings still hold: `<details>`/`<summary>` are not
 * restricted elements, so an app was never blocked — only unstyled and unwired.
 *
 * What changed is that the framework turned out to own **half** of this pattern. Row
 * disclosure has a home (`DataView`'s `renderExpanded`); the single value next to it had
 * none, so "Technical details" was hand-built out of a `Button` carrying `aria-expanded`
 * and a body toggled beside it — twice, independently, in two codebases, each rewiring
 * the same three attributes. That is the "written twice" evidence ADR 0099's own
 * amendment accepted for `Combobox multiple`, and this is the narrow thing it justifies:
 * not a set, not a policy over one, just the control both hand-rolls actually were.
 *
 * **Not `<details>`.** Its open/close is the browser's, not React's, so a controlled
 * `open` fights the element; its `::marker` styling is still uneven across engines; and
 * `<summary>` is a focusable non-button whose keyboard contract differs per platform. A
 * button and a region cost three attributes and behave the same everywhere — and the
 * three attributes are precisely what each hand-roll had to get right on its own.
 *
 * **Controlled or not, but not both.** With `open` supplied the caller owns the state and
 * `onOpenChange` reports intent; with neither, the component keeps its own. Passing
 * `open` without `onOpenChange` yields a panel that cannot be closed, so that combination
 * is refused by the type rather than discovered in a browser — the same discriminated
 * union `Combobox multiple` uses for the same reason.
 */

import { useCallback, useId, useState } from "react";
import type { ReactNode } from "react";

import { ChevronDownGlyph, ChevronRightGlyph } from "./dataview/glyphs";
import { injectTerpStyles } from "./styles";
import { useUiText } from "./uiText";
import type { UiText } from "./uiText";

injectTerpStyles();

interface DisclosureBase {
  /** The toggle's own copy — always the app's, so this component ships no strings. */
  label: UiText;
  /** What the toggle reveals. Rendered only while open. */
  children: ReactNode;
  /** Open on first render, for the uncontrolled case. Ignored when `open` is supplied. */
  defaultOpen?: boolean;
}

export type DisclosureProps = DisclosureBase &
  (
    | { open: boolean; onOpenChange: (open: boolean) => void }
    | { open?: undefined; onOpenChange?: (open: boolean) => void }
  );

/**
 * The panel is unmounted while closed rather than hidden.
 *
 * Hidden content stays in the accessibility tree unless every branch remembers
 * `hidden`, and it keeps running whatever it renders — a disclosure over a live log or a
 * heavy diff then costs its work on every screen that has one, permanently, for a region
 * nobody has opened. Unmounting is also what the row-disclosure half already does.
 */
export function Disclosure({
  label,
  children,
  defaultOpen = false,
  open,
  onOpenChange,
}: DisclosureProps) {
  const resolve = useUiText();
  const panelId = useId();
  const [uncontrolled, setUncontrolled] = useState(defaultOpen);
  const controlled = open !== undefined;
  const isOpen = controlled ? open : uncontrolled;

  const toggle = useCallback(() => {
    const next = !isOpen;
    if (!controlled) setUncontrolled(next);
    onOpenChange?.(next);
  }, [controlled, isOpen, onOpenChange]);

  return (
    <div data-terp="disclosure" data-open={isOpen || undefined}>
      <button
        type="button"
        data-terp="disclosure-toggle"
        aria-expanded={isOpen}
        aria-controls={panelId}
        onClick={toggle}
      >
        {isOpen ? <ChevronDownGlyph /> : <ChevronRightGlyph />}
        <span>{resolve(label)}</span>
      </button>
      {/* `role="group"` rather than `region`: a region is a landmark, and a screen with
          four "Technical details" disclosures would put four unnamed landmarks in the
          rotor. The button's `aria-controls` is what ties the two together. */}
      {isOpen && (
        <div id={panelId} data-terp="disclosure-panel" role="group">
          {children}
        </div>
      )}
    </div>
  );
}
