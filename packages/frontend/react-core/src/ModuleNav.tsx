import { Link, useRouterState } from "@tanstack/react-router";
import type { CSSProperties } from "react";

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

const navStyle: CSSProperties = {
  borderBottom: "1px solid var(--color-neutral-200)",
};

const listStyle: CSSProperties = {
  listStyle: "none",
  margin: 0,
  padding: 0,
  display: "flex",
  flexWrap: "wrap",
  gap: "var(--space-3)",
};

const linkStyle: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  padding: "var(--space-2) 0",
  color: "var(--color-neutral-600)",
  textDecoration: "none",
  borderBottom: "2px solid transparent",
};

const activeLinkStyle: CSSProperties = {
  color: "var(--color-neutral-900)",
  borderBottomColor: "var(--color-brand-primary)",
};

/**
 * Secondary horizontal navigation for intra-module sub-pages.
 *
 * Each tab links to a real TanStack Router route so sub-pages keep their own URL,
 * lazy loading, and back-button behavior. The active tab is matched exactly.
 */
export function ModuleNav({ items, ariaLabel }: ModuleNavProps) {
  const strings = useStrings();
  const resolve = useUiText();
  const pathname = useRouterState({ select: (state) => state.location.pathname });

  if (items.length === 0) {
    return null;
  }

  return (
    <nav
      aria-label={resolve(ariaLabel ?? strings.moduleNavigationLabel)}
      data-terp="module-nav"
      style={navStyle}
    >
      <ul style={listStyle}>
        {items.map((item) => {
          const label = resolve(item.label);
          const isActive = pathname === item.to;
          return (
            <li key={item.to}>
              <Link
                to={item.to}
                activeOptions={{ exact: true }}
                aria-current={isActive ? "page" : undefined}
                style={{ ...linkStyle, ...(isActive ? activeLinkStyle : undefined) }}
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
