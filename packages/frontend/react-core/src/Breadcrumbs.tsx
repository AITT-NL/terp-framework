import type { CSSProperties, ReactNode } from "react";

import { injectTerpStyles } from "./styles";
import { useStrings, useUiText } from "./uiText";
import type { UiText } from "./uiText";

injectTerpStyles();

/** One breadcrumb: a label plus, for ancestor levels, the path it links back to. */
export interface BreadcrumbItem {
  /** The crumb text (e.g. the module title, or the record's display name). */
  label: UiText;
  /** Destination path for ancestor crumbs; the current page's crumb omits it. */
  to?: string;
}

/** Turns an ancestor crumb into the active stack's link (keeps the trail router-agnostic). */
export type RenderBreadcrumbLink = (item: { label: string; to: string }) => ReactNode;

export interface BreadcrumbsProps {
  /** The trail, outermost first; the last item is the current page. */
  items: readonly BreadcrumbItem[];
  /** Link renderer for ancestor crumbs (default: a plain `<a href>`); pass the stack's `Link`. */
  renderLink?: RenderBreadcrumbLink;
}

const navStyle: CSSProperties = {
  fontSize: "var(--font-size-sm)",
  color: "var(--color-neutral-600)",
};

const listStyle: CSSProperties = {
  listStyle: "none",
  margin: 0,
  padding: 0,
  display: "flex",
  flexWrap: "wrap",
  alignItems: "center",
  gap: "var(--space-2)",
};

const currentStyle: CSSProperties = {
  color: "var(--color-neutral-900)",
  fontWeight: "var(--font-weight-medium)" as CSSProperties["fontWeight"],
};

const separatorStyle: CSSProperties = {
  display: "inline-flex",
  color: "var(--color-neutral-400)",
  lineHeight: 0,
};

function ChevronSeparator() {
  return (
    <svg
      aria-hidden="true"
      focusable={false}
      width="0.85em"
      height="0.85em"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="m9 6 6 6-6 6" />
    </svg>
  );
}

const defaultRenderLink: RenderBreadcrumbLink = (item) => <a href={item.to}>{item.label}</a>;

/**
 * The breadcrumb trail every page shows through the remaining layers (shell -> overview ->
 * detail). Accessible by construction: a `nav` landmark labelled "Breadcrumb", an ordered
 * list, and `aria-current="page"` on the final crumb. Router-agnostic — `renderLink` turns
 * an ancestor crumb into the active stack's link, exactly like `AppShell`'s `renderLink`.
 */
export function Breadcrumbs({ items, renderLink = defaultRenderLink }: BreadcrumbsProps) {
  const strings = useStrings();
  const resolve = useUiText();
  return (
    <nav aria-label={strings.breadcrumbsLabel} data-terp="breadcrumbs" style={navStyle}>
      <ol style={listStyle}>
        {items.map((item, index) => {
          const isLast = index === items.length - 1;
          const label = resolve(item.label);
          return (
            <li key={`${index}-${label}`} style={listStyle}>
              {!isLast && item.to !== undefined ? (
                renderLink({ label, to: item.to })
              ) : (
                <span aria-current={isLast ? "page" : undefined} style={isLast ? currentStyle : undefined}>
                  {label}
                </span>
              )}
              {!isLast && (
                <span aria-hidden="true" style={separatorStyle}>
                  <ChevronSeparator />
                </span>
              )}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}

