import type { CSSProperties, ReactNode } from "react";
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
  /** Link renderer for ancestor crumbs; pass the stack's `Link` (see {@link Breadcrumbs}). */
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

const pageStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "minmax(0, 1fr)",
  gap: "var(--space-4)",
  alignContent: "start",
  minWidth: 0,
};

const headerStyle: CSSProperties = { display: "grid", gap: "var(--space-2)" };

const crumbRowStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  justifyContent: "space-between",
  gap: "var(--space-3)",
  flexWrap: "wrap",
  minHeight: "2rem",
};

const actionsOnlyRowStyle: CSSProperties = {
  ...crumbRowStyle,
  justifyContent: "flex-end",
};

const titleStyle: CSSProperties = {
  margin: 0,
  fontSize: "var(--font-size-xl)",
  fontWeight: "var(--font-weight-bold)" as CSSProperties["fontWeight"],
  letterSpacing: "-0.01em",
  color: "var(--color-neutral-900)",
  lineHeight: 1.2,
};

/**
 * The base content-page frame: every routed view is constructed the same way — one
 * header row holding the breadcrumb trail (when there is a path back up through the
 * layers) on the left and the page's `actions` slot on the right, then the single
 * `h1` title, then the body. A root page omits the redundant current-page-only crumb.
 * `OverviewPage` and `DetailPage` specialise it for the standard overview -> detail
 * layering; a bespoke screen composes `Page` directly.
 *
 * The frame also owns the async body states: `error` (which wins, so a failed
 * query never hides behind a spinner) then `isLoading` replace the body while the
 * header stays put, so the user keeps their place in the layers.
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
    <article ref={articleRef} style={pageStyle}>
      <header style={headerStyle}>
        {hasAncestors || actions ? (
          <div style={hasAncestors ? crumbRowStyle : actionsOnlyRowStyle}>
            {hasAncestors ? <Breadcrumbs items={trail} renderLink={renderLink} /> : null}
            {actions}
          </div>
        ) : null}
        <h1 style={titleStyle}>{resolve(title)}</h1>
      </header>
      {/* Reset the slot for the body's own subtree, so nested content is never judged
          by an ancestor archetype's slot. */}
      <LayoutSlotContext.Provider value={null}>{body}</LayoutSlotContext.Provider>
    </article>
  );
}
