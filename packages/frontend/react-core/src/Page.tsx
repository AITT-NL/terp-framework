import type { ReactNode } from "react";
import { Fragment, useContext, useEffect, useRef, useState } from "react";

import { Breadcrumbs } from "./Breadcrumbs";
import type { BreadcrumbItem, RenderBreadcrumbLink } from "./Breadcrumbs";
import { ErrorState } from "./ErrorState";
import {
  LayoutSlotContext,
  useLayoutContract,
  verifySlotChildren,
} from "./layoutContract";
import { LoadingState } from "./LoadingState";
import { usePageMarker } from "./pageMarker";
import { resolveUiTextNode, useUiText } from "./uiText";
import type { UiText, UiTextNode } from "./uiText";

export interface PageProps {
  /** The page heading (rendered as the single `h1`). */
  title: UiText;
  /** Ancestor breadcrumb trail, outermost first; the current page's crumb is appended automatically. */
  breadcrumbs?: readonly BreadcrumbItem[];
  /** Link renderer for ancestor crumbs; defaults to the surrounding router's `Link` (see {@link Breadcrumbs}). */
  renderLink?: RenderBreadcrumbLink;
  /** Optional page-level actions, rendered at the band's right edge (e.g. a primary `Button`). */
  actions?: ReactNode;
  /**
   * Status pill(s) for the page's subject, shown next to the title — an entity's state, a
   * visibility marker. Pass a `Badge` (or several) so the tone is the caller's choice; a
   * bare string is not accepted, because "which tone" is a decision this frame cannot make.
   *
   * Keep it to a handful of short labels. This is a badge row on a bounded band, not a place
   * for prose — that is what `description` is, and neither is a place for a paragraph.
   */
  badges?: ReactNode | readonly ReactNode[];
  /**
   * One short line about the page, shown after the badges and truncated to a single line.
   *
   * It is chrome, not content: the band has a height, so a lead line that would wrap is
   * clipped rather than allowed to set it. An explanation that does not fit is describing the
   * body and belongs in the body.
   *
   * `UiTextNode`, like `EmptyState`'s own description, rather than a bare `ReactNode`: this is
   * user-facing prose, so it goes through the localization seam. Typed as `ReactNode` it took
   * a plain string that never reached the resolver, which is the failure that does not
   * announce itself — every other string on the band translates and the lead line stays in the
   * source language.
   */
  description?: UiTextNode;
  /**
   * Cap the whole frame — header included — at a readable measure (default `"full"`).
   *
   * `"narrow"` is the single-column-of-controls shape: a create/edit form, a settings screen.
   * The header is capped WITH the body here, unlike the shell's own content measure, and that
   * asymmetry is the point rather than an inconsistency. A wide page with a narrow column wants
   * its title and actions spanning the full track, because the band is what tells you the page
   * is wider than its text. A form does not: a Save button floating a screen-width away from
   * the field it saves is worse than one sitting over it.
   *
   * `data-measure` is the same attribute name `Text` uses for the same concept, keyed per
   * marker, so there is one vocabulary for "measure" rather than two.
   *
   * `FormPage` and `SettingsPage` default it on; every other archetype leaves it `"full"`,
   * which stamps nothing.
   */
  measure?: "full" | "narrow";
  /** Show the loading state instead of the body (the header stays for orientation). */
  isLoading?: boolean;
  /** Loading slot; defaults to the standard {@link LoadingState} spinner block. */
  loadingState?: ReactNode;
  /**
   * The failure to surface instead of the body (e.g. the record 404'd or access was revoked).
   * Accepts the caught error itself (`ApiError`, `Error`, raw envelope) or a plain message;
   * pass `useResource`'s `cause ?? error` so the stable `code` reaches the code→copy map.
   * Takes precedence over `isLoading`, so a failed query never gets stuck on a spinner.
   */
  error?: unknown;
  /** Error slot; defaults to {@link ErrorState} rendering `error` through the error-code map. */
  errorState?: ReactNode;
  /** The page body. */
  children: ReactNode;
}

/**
 * The base content-page frame: every routed view is constructed the same way — one band
 * carrying the page's identity and its actions, then the body.
 *
 * **The band is one row, the row is the title, and the title is the trail's leaf.** Every
 * page renders a trail: its ancestors link up through the layers and its leaf is the view's
 * single `h1` (see `Breadcrumbs`' `currentAs`). An overview with no parents is a trail of
 * one, which is deliberately the same node in the same boxes as a detail's leaf — so
 * opening a record slides the name right behind its new parents instead of moving it between
 * two different layouts.
 *
 * The page's name therefore appears exactly ONCE, which is the defect this shape fixed: the
 * frame used to append `title` to the trail *and* render it as an `h1`, so every `DetailPage`
 * printed its own name twice, a couple of dozen pixels apart.
 *
 * `badges` and `description` sit after the title and `actions` at the right edge, all on that
 * one line. Inside a shell the band bleeds to the content column's edge and takes the app
 * header's own height and a bottom border, so the two read as one piece of chrome; standalone
 * — the workbench, the unit tests — it is the same row without the bleed. A `measure="narrow"`
 * frame (`FormPage`, `SettingsPage`) keeps the row and drops the chrome, because a form is
 * capped with its header (ADR 0098 §3).
 *
 * `OverviewPage` and `DetailPage` specialise it for the standard overview -> detail
 * layering; a bespoke screen composes `Page` directly.
 *
 * The frame also owns the async body states: `error` (which wins, so a failed
 * query never hides behind a spinner) then `isLoading` replace the body while the
 * header stays put, so the user keeps their place in the layers.
 *
 * It renders no inline styles: the frame's geometry and the title's type come from the
 * injected react-core sheet, matched on the `data-terp` markers stamped below (ADR 0094).
 */
export function Page({
  title,
  breadcrumbs,
  renderLink,
  actions,
  badges,
  description,
  measure = "full",
  isLoading,
  loadingState,
  error,
  errorState,
  children,
}: PageProps) {
  const resolve = useUiText();
  // Mark the routed view as archetype-framed (the runtime half of the page-archetype control).
  usePageMarker()?.();
  // The runtime half of the slot-typed layout contract control (ADR 0079): when the app
  // opted into a contract and the enclosing archetype declared a governed body slot
  // (OverviewPage / DetailPage), the rendered body's DOM children must each carry an
  // allowed component's data-terp marker — verified one macrotask after mount (like the
  // page-archetype check) and refused fail closed with the lint rule's directive message.
  const contract = useLayoutContract();
  const slotOwner = useContext(LayoutSlotContext);
  const articleRef = useRef<HTMLElement>(null);
  const [slotViolation, setSlotViolation] = useState<string | null>(null);
  const showsBody = (error === null || error === undefined) && !isLoading;
  useEffect(() => {
    if (contract === null || slotOwner === null || !showsBody) {
      return;
    }
    const timer = setTimeout(() => {
      const article = articleRef.current;
      if (article === null) {
        return;
      }
      const body = [...article.children].filter((child) => child.tagName !== "HEADER");
      setSlotViolation(verifySlotChildren(contract, slotOwner, body));
    }, 0);
    return () => clearTimeout(timer);
  });
  if (slotViolation !== null) {
    throw new Error(slotViolation);
  }
  // ALWAYS a trail, even of one, and that is the point rather than a simplification.
  // An overview's title has to be the same node in the same boxes as a detail's, or the name
  // moves the moment you open a record: one path rendered a bare h1 and the other rendered
  // the h1 inside nav > ol > li, so the text sat at two slightly different places and the
  // transition showed it. A trail of one is the overview's title; append an ancestor and the
  // same leaf slides right behind its parents, which is the only motion there should be.
  const trail: BreadcrumbItem[] = [...(breadcrumbs ?? []), { label: title }];
  // Normalised rather than branched at the site, so one badge and several take the same path
  // and the row exists or does not exist for one reason.
  //
  // Filtered on RENDERABILITY, not on undefined, and the difference is the whole bug it fixes:
  // the idiomatic call is `badges={isPublished && <Badge/>}`, which hands this `false` when the
  // condition fails. Testing `!== undefined` let `[false]` through, so the row existed, was
  // empty, and put a gap beside the title — the exact "absent is not an empty row"
  // invariant the band promises. `false`, `null`, `undefined` and `""` all mean absent here.
  const badgeList: readonly ReactNode[] = ([] as ReactNode[])
    .concat(badges ?? [])
    .filter((badge) => badge !== false && badge !== null && badge !== undefined && badge !== "");
  // Same test for the lead line, for the same reason: `description={error && error.message}`.
  const hasDescription =
    description !== undefined &&
    description !== null &&
    description !== false &&
    description !== "";
  const body =
    error !== null && error !== undefined ? (
      (errorState ?? <ErrorState error={error} />)
    ) : isLoading ? (
      (loadingState ?? <LoadingState />)
    ) : (
      children
    );
  // Hoisted, the density/collapsed idiom: the default stamps nothing, so the expression has a
  // branch, and a conditional written at the attribute is the form the marker scanner reads
  // every string literal out of.
  const measureAttribute = measure === "narrow" ? "narrow" : undefined;
  return (
    <article ref={articleRef} data-terp="page" data-measure={measureAttribute}>
      {/* A <header> ELEMENT, and it has to stay one. The slot check above drops the header
          from the body set by tagName, so re-rendering this as a marked <div> would put it
          back in and fail every governed OverviewPage / DetailPage closed. The marker is
          additive; the tag is load-bearing. For the same reason the body below takes no
          wrapper of its own — not even a display: contents one, since article.children is a
          DOM traversal and would see it. */}
      <header data-terp="page-header">
        <div data-terp="page-heading">
          {/* The trail carries the h1 as its leaf. No wrapper of its own any more: the crumb
              row it used to sit in existed to hold a 2rem floor above the title row, and
              there is no title row to be above. */}
          <Breadcrumbs items={trail} renderLink={renderLink} currentAs="h1" />
          {badgeList.length > 0 && (
            <div data-terp="page-badges">
              {badgeList.map((badge, index) => (
                <Fragment key={index}>{badge}</Fragment>
              ))}
            </div>
          )}
          {hasDescription && (
            <p data-terp="page-description">{resolveUiTextNode(description, resolve)}</p>
          )}
        </div>
        {actions}
      </header>
      {/* Reset the slot for the body's own subtree, so nested content is never judged
          by an ancestor archetype's slot. */}
      <LayoutSlotContext.Provider value={null}>{body}</LayoutSlotContext.Provider>
    </article>
  );
}
