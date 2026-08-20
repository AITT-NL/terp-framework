import type { ReactNode } from "react";
import { useContext, useEffect, useRef, useState } from "react";

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
import { useUiText } from "./uiText";
import type { UiText } from "./uiText";

export interface PageProps {
  /** The page heading (rendered as the single `h1`). */
  title: UiText;
  /** Ancestor breadcrumb trail, outermost first; the current page's crumb is appended automatically. */
  breadcrumbs?: readonly BreadcrumbItem[];
  /** Link renderer for ancestor crumbs; defaults to the surrounding router's `Link` (see {@link Breadcrumbs}). */
  renderLink?: RenderBreadcrumbLink;
  /** Optional page-level actions, rendered on the heading row (e.g. a primary `Button`). */
  actions?: ReactNode;
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
 * The base content-page frame: every routed view is constructed the same way — one
 * header holding the breadcrumb trail (when there is a path back up through the
 * layers), then one row with the single `h1` title on the left and the page's
 * `actions` slot on the right, then the body. A root page omits the redundant
 * current-page-only crumb. Title-first DOM order keeps narrow layouts natural.
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
  const hasAncestors = breadcrumbs !== undefined && breadcrumbs.length > 0;
  const trail: BreadcrumbItem[] = hasAncestors ? [...breadcrumbs, { label: title }] : [];
  const body =
    error !== null && error !== undefined ? (
      (errorState ?? <ErrorState error={error} />)
    ) : isLoading ? (
      (loadingState ?? <LoadingState />)
    ) : (
      children
    );
  return (
    <article ref={articleRef} data-terp="page">
      {/* A <header> ELEMENT, and it has to stay one. The slot check above drops the header
          from the body set by tagName, so re-rendering this as a marked <div> would put it
          back in and fail every governed OverviewPage / DetailPage closed. The marker is
          additive; the tag is load-bearing. For the same reason the body below takes no
          wrapper of its own — not even a display: contents one, since article.children is a
          DOM traversal and would see it. */}
      <header data-terp="page-header">
        {hasAncestors && (
          <div data-terp="page-breadcrumbs">
            <Breadcrumbs items={trail} renderLink={renderLink} />
          </div>
        )}
        <div data-terp="page-heading">
          <h1 data-terp="page-title">{resolve(title)}</h1>
          {actions}
        </div>
      </header>
      {/* Reset the slot for the body's own subtree, so nested content is never judged
          by an ancestor archetype's slot. */}
      <LayoutSlotContext.Provider value={null}>{body}</LayoutSlotContext.Provider>
    </article>
  );
}
