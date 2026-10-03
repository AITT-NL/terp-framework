import type { AnchorHTMLAttributes, ReactNode } from "react";

import { Icon } from "./icons";
import { useNavLink } from "./navLink";
import { fillPlaceholders, useStrings, useUiText } from "./uiText";
import type { UiText } from "./uiText";

/** One neighbour of the current page: what it is called, and where it lives. */
export interface PageSequenceLink {
  /** The neighbour's own name — the record, the column, the step — shown on the link. */
  label: UiText;
  /** The neighbour's in-app path. */
  to: string;
}

/**
 * The ordered series a page is one item of, so a reader can step through it without going
 * back to the list: a record among the results that opened it, a column among a table's
 * columns, a step among a procedure's steps.
 *
 * Data rather than elements, and that is the point of the prop. Handed descriptions, the
 * frame renders the neighbours as real links (the router's, so middle-click and "open in a
 * new tab" work and `rel` says which way each one points), puts them in the same places on
 * every page of the series, and words the position in the active locale. Handed elements, it
 * could do none of those — the same reason `PageActions` takes `secondaryActions` as tuples.
 */
export interface PageSequence {
  /**
   * What the series is, as the accessible name of its `nav` landmark — "Columns",
   * "Invoices". Required: a page already has a breadcrumb landmark, and two navigation
   * landmarks a screen reader cannot tell apart are one too many.
   */
  label: UiText;
  /** The item before this one. Absent on the first: its place stays empty rather than closing up. */
  previous?: PageSequenceLink;
  /** The item after this one. Absent on the last. */
  next?: PageSequenceLink;
  /**
   * This page's place in the series, counted from 1 — rendered as "4 of 23". Omit it when the
   * total is not known; an unknown total is shown as nothing, never guessed.
   */
  position?: { current: number; total: number };
}

/**
 * The sequence bar `Page` renders after its article when given a `sequence`.
 *
 * **A sibling of the article, not a child of it.** The layout contract's runtime check reads
 * the article's children as the body and exempts only the header; a bar inside it would fail
 * every governed `DetailPage` closed, and exempting it there by tag would let any app `<nav>`
 * through the contract. Outside the article the check never sees it.
 *
 * **A `nav`, not a `footer`.** Outside a sectioning element a `<footer>` is the page's
 * `contentinfo` landmark, which belongs to the shell's own footer. A bar of links to sibling
 * pages is navigation, and is named for its series.
 *
 * **Three cells, always.** The previous link, the position and the next link each keep their
 * cell whether or not they are present, so "next" sits at the same spot on the first page of
 * a series as on the fortieth — a reader stepping through it never has to find the control
 * again.
 */
export function PageSequenceBar({ sequence }: { sequence: PageSequence }) {
  const strings = useStrings();
  const resolve = useUiText();
  const navLink = useNavLink();
  const { previous, next, position } = sequence;

  const renderStep = (step: PageSequenceLink, direction: "prev" | "next"): ReactNode => {
    const label = resolve(step.label);
    // The direction is in the accessible name, and the visible label is inside it (WCAG 2.5.3):
    // a screen reader hears "Previous: Order 1016", a voice user can still say "Order 1016".
    const attributes: Omit<AnchorHTMLAttributes<HTMLAnchorElement>, "href"> = {
      rel: direction,
      "aria-label": fillPlaceholders(
        direction === "prev" ? strings.pageSequencePrevious : strings.pageSequenceNext,
        { label },
      ),
    };
    const children = (
      <>
        {direction === "prev" && <Icon name="chevron-left" />}
        <span data-terp="page-sequence-label">{label}</span>
        {direction === "next" && <Icon name="chevron-right" />}
      </>
    );
    // The router's link where there is one, so a step is a client-side navigation; a plain
    // anchor outside a Terp router, like every other layout component that renders a link.
    return navLink === null ? (
      <a {...attributes} href={step.to}>
        {children}
      </a>
    ) : (
      navLink({ to: step.to, children, attributes })
    );
  };

  return (
    <nav data-terp="page-sequence" aria-label={resolve(sequence.label)}>
      <span data-terp="page-sequence-previous">
        {previous !== undefined && renderStep(previous, "prev")}
      </span>
      <span data-terp="page-sequence-position">
        {position !== undefined &&
          fillPlaceholders(strings.pageSequencePosition, {
            current: position.current,
            total: position.total,
          })}
      </span>
      <span data-terp="page-sequence-next">
        {next !== undefined && renderStep(next, "next")}
      </span>
    </nav>
  );
}
