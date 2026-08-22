import { Link, useRouterState } from "@tanstack/react-router";

import { activeNavPath } from "./navActive";
import { useStrings, useUiText } from "./uiText";
import type { UiText } from "./uiText";

export interface ModuleNavTab {
  /** Display label. */
  label: UiText;
  /** Router path for the sub-page route. */
  to: string;
  /**
   * Match this tab's path exactly rather than as a segment-aligned prefix.
   *
   * The default is the prefix, so a tab stays current on the pages beneath it — a detail route
   * under `/records/mapping` keeps "Mapping" lit instead of blanking the strip. Set this on a
   * landing tab that also has siblings deeper in the same strip, where the prefix would keep it
   * lit alongside them; the shared predicate resolves that case by longest match anyway, so this
   * is for the narrower job of a tab owning only itself.
   */
  exact?: boolean;
}

export interface ModuleNavProps {
  items: readonly ModuleNavTab[];
  /** Accessible label for the secondary navigation landmark. */
  ariaLabel?: UiText;
}

/**
 * Secondary horizontal navigation for intra-module sub-pages.
 *
 * Each tab links to a real TanStack Router route so sub-pages keep their own URL,
 * lazy loading, and back-button behavior. The active tab is matched exactly.
 *
 * It renders no inline styles: the strip, the list and the links take their geometry and
 * ink from the injected react-core sheet (ADR 0094). The active tab is styled from
 * `data-active`, which this component alone writes, rather than from the `aria-current` it
 * also sets — a router `Link` merges its own `aria-current` last, so that attribute has a
 * second author and would be the breadcrumb mistake again.
 */
export function ModuleNav({ items, ariaLabel }: ModuleNavProps) {
  const strings = useStrings();
  const resolve = useUiText();
  const pathname = useRouterState({ select: (state) => state.location.pathname });
  // Resolved over the whole strip, not per tab, and through the same function the sidebar uses
  // (ADR 0097 §6, amended in 4e). Two tabs where one path prefixes the other would otherwise
  // both be current, and this component previously compared `pathname === item.to` raw — which
  // diverged from its own Link in both directions, as the sheet's comment on the active rule
  // says. Longest match wins, so `/records` does not steal from `/records/mapping`.
  const activeTo = activeNavPath(pathname, items);

  if (items.length === 0) {
    return null;
  }

  return (
    <nav aria-label={resolve(ariaLabel ?? strings.moduleNavigationLabel)} data-terp="module-nav">
      <ul data-terp="module-nav-list">
        {items.map((item) => {
          const label = resolve(item.label);
          const isActive = item.to === activeTo;
          return (
            <li key={item.to}>
              <Link
                to={item.to}
                // `exact` is ALWAYS true here, whatever the tab asked for, and the asymmetry is
                // the mechanism rather than an oversight. The tab's own `exact` governs the
                // component's predicate above; this governs when the ROUTER volunteers its own
                // `aria-current`, and the router decides per link with no knowledge of siblings.
                // Left non-exact it prefix-matches, so at `/tickets/projects` it would mark the
                // `/tickets` tab current too — a second current item the component never chose.
                // Exact matching means "the router thinks this is active" implies the path equals
                // the URL, which is the longest possible match, which is always the tab the
                // predicate picked. The router can only agree.
                //
                // includeSearch: false for the other half. It defaults to true and on an exact
                // link demands a full query-string match, so at `/tickets/projects?page=2` the
                // router's own `data-status` said inactive while this component said active.
                // Nothing paints from `data-status`, which is exactly why that could sit there
                // unnoticed.
                activeOptions={{ exact: true, includeSearch: false }}
                aria-current={isActive ? "page" : undefined}
                data-terp="module-nav-link"
                data-active={isActive ? "true" : undefined}
              >
                {label}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
