import type { ReactNode } from "react";

import { injectTerpStyles } from "./styles";
import { useNavLink } from "./navLink";
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
  /**
   * What element the current (last) crumb renders as. Default `"span"`.
   *
   * `"h1"` is the page band's case (see `Page`): there the trail IS the page title, so its
   * leaf is the view's single heading rather than a second copy of the same string sitting
   * under the trail. It carries `data-terp="page-title"` instead of `breadcrumbs-current`,
   * because the two mean different things to the sheet: one is a trail's end, the other is a
   * heading that happens to sit at the trail's end and is styled as such.
   *
   * The heading lands inside the list item, which is deliberate rather than convenient. `li`
   * takes flow content, so it is valid; it keeps the separator logic in one place instead of
   * asking the caller to draw a chevron; and it leaves `aria-current="page"` on the same node
   * a screen reader reads as the heading.
   */
  currentAs?: "span" | "h1";
  /**
   * Link renderer for ancestor crumbs. Defaults to the surrounding router's `Link`
   * (published by `buildAppRouter`), falling back to a plain `<a href>` only outside a
   * Terp router — a crumb inside an app must never full-page-reload.
   */
  renderLink?: RenderBreadcrumbLink;
}

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

const anchorRenderLink: RenderBreadcrumbLink = (item) => <a href={item.to}>{item.label}</a>;

/**
 * The breadcrumb trail every page shows through the remaining layers (shell -> overview ->
 * detail). Accessible by construction: a `nav` landmark labelled "Breadcrumb", an ordered
 * list, and `aria-current="page"` on the final crumb. Router-agnostic — `renderLink` turns
 * an ancestor crumb into the active stack's link, exactly like `AppShell`'s `renderLink`.
 */
export function Breadcrumbs({ items, renderLink, currentAs = "span" }: BreadcrumbsProps) {
  const navLink = useNavLink();
  const renderCrumbLink =
    renderLink ??
    (navLink === null
      ? anchorRenderLink
      : (item: { label: string; to: string }) => navLink({ to: item.to, children: item.label }));
  const strings = useStrings();
  const resolve = useUiText();
  return (
    <nav aria-label={strings.breadcrumbsLabel} data-terp="breadcrumbs">
      <ol>
        {items.map((item, index) => {
          const isLast = index === items.length - 1;
          const label = resolve(item.label);
          return (
            <li key={`${index}-${label}`}>
              {!isLast && item.to !== undefined ? (
                renderCrumbLink({ label, to: item.to })
              ) : isLast && currentAs === "h1" ? (
                // Two spelled-out branches rather than one element with a computed tag and a
                // computed marker, and the marker scanner is the reason rather than taste: it
                // reads string literals out of a data-terp attribute, so a ternary there
                // published "h1" as a marker and hid breadcrumbs-current from the inventory.
                // The sheet records the same idiom for the same scanner ("a conditional
                // written at the attribute is the form the marker scanner reads every string
                // literal out of"); spelling both out keeps one literal per element.
                <h1 aria-current="page" data-terp="page-title">
                  {label}
                </h1>
              ) : isLast ? (
                <span aria-current="page" data-terp="breadcrumbs-current">
                  {label}
                </span>
              ) : (
                // An ancestor with no `to`: plain text, never a dead link, and never the
                // heading either — `currentAs` describes the LEAF, and an intermediate layer
                // that happens to be unlinked is not the page.
                <span>{label}</span>
              )}
              {!isLast && (
                <span aria-hidden="true" data-terp="breadcrumbs-separator">
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

