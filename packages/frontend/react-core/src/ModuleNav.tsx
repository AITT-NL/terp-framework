import { Link, useRouterState } from "@tanstack/react-router";

import { useStrings, useUiText } from "./uiText";
import type { UiText } from "./uiText";

export interface ModuleNavTab {
  /** Display label. */
  label: UiText;
  /** Router path for an exact sub-page route. */
  to: string;
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

  if (items.length === 0) {
    return null;
  }

  return (
    <nav aria-label={resolve(ariaLabel ?? strings.moduleNavigationLabel)} data-terp="module-nav">
      <ul data-terp="module-nav-list">
        {items.map((item) => {
          const label = resolve(item.label);
          const isActive = pathname === item.to;
          return (
            <li key={item.to}>
              <Link
                to={item.to}
                activeOptions={{ exact: true }}
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
