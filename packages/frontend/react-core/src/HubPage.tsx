import type { CSSProperties, ReactNode } from "react";
import { useEffect, useRef, useState } from "react";

import { Page } from "./Page";
import type { PageProps } from "./Page";
import { useLayoutContract, verifySlotChildren } from "./layoutContract";
import { injectTerpStyles } from "./styles";
import { useUiText } from "./uiText";
import type { UiText } from "./uiText";

injectTerpStyles();

export type HubPageProps = Omit<
  PageProps,
  "isLoading" | "loadingState" | "error" | "errorState"
>;

const gridStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fill, minmax(240px, 1fr))",
  gap: "var(--space-4)",
  listStyle: "none",
  margin: 0,
  padding: 0,
};

/**
 * The landing / hub page archetype: a `Page` whose body is a responsive grid of
 * {@link HubCard} links into the sub-areas of a domain. Use it as a module index that
 * adds discovery value (each card can carry a live `stat`, making the hub a lightweight
 * dashboard) — never as a mandatory speed-bump in front of a single frequently-used list.
 */
export function HubPage({ children, ...page }: HubPageProps) {
  // The runtime half of the slot-typed layout contract control (ADR 0079) for the hub
  // grid: with a contract active, every rendered child of the grid must be a HubCard
  // (its data-terp marker) — verified one macrotask after mount, refused fail closed.
  const contract = useLayoutContract();
  const gridRef = useRef<HTMLUListElement>(null);
  const [slotViolation, setSlotViolation] = useState<string | null>(null);
  useEffect(() => {
    if (contract === null) {
      return;
    }
    const timer = setTimeout(() => {
      const grid = gridRef.current;
      if (grid === null) {
        return;
      }
      setSlotViolation(verifySlotChildren(contract, "HubPage", [...grid.children]));
    }, 0);
    return () => clearTimeout(timer);
  });
  if (slotViolation !== null) {
    throw new Error(slotViolation);
  }
  return (
    <Page {...page}>
      <ul ref={gridRef} style={gridStyle}>
        {children}
      </ul>
    </Page>
  );
}

/** Wraps a card's content in the active stack's link (keeps the hub router-agnostic). */
export type RenderHubCardLink = (props: { to: string; children: ReactNode }) => ReactNode;

export interface HubCardProps {
  /** Destination path of the sub-area the card opens. */
  to: string;
  /** Card title (the sub-area's name). */
  title: UiText;
  /** Short explanation of the area. */
  description?: UiText;
  /** Optional leading icon (any rendered node — react-core takes no icon dependency). */
  icon?: ReactNode;
  /**
   * Optional live summary (e.g. "142 active - 3 inactive"). Turns the hub into a
   * lightweight dashboard rather than a duplicate of the sidebar.
   */
  stat?: ReactNode;
  /** Link renderer (default: a plain `<a href>`); pass the stack's `Link`, like `AppShell`. */
  renderLink?: RenderHubCardLink;
}

const cardStyle: CSSProperties = {
  display: "grid",
  gap: "var(--space-2)",
  padding: "var(--space-4)",
  border: "1px solid var(--color-neutral-200)",
  borderRadius: "var(--radius-lg)",
  background: "var(--color-neutral-0)",
  height: "100%",
  color: "var(--color-neutral-900)",
};

const cardTitleRowStyle: CSSProperties = {
  margin: 0,
  display: "flex",
  alignItems: "center",
  gap: "var(--space-3)",
};

const iconTileStyle: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  justifyContent: "center",
  width: "2.25rem",
  height: "2.25rem",
  flexShrink: 0,
  borderRadius: "var(--radius-md)",
  background: "var(--color-brand-primary-soft)",
  color: "var(--color-brand-primary)",
};

const titleTextStyle: CSSProperties = {
  color: "var(--color-neutral-900)",
  fontSize: "var(--font-size-base)",
  fontWeight: "var(--font-weight-semibold)" as CSSProperties["fontWeight"],
  transition: "color 150ms ease",
};

const descriptionStyle: CSSProperties = {
  margin: 0,
  color: "var(--color-neutral-600)",
  fontSize: "var(--font-size-sm)",
  lineHeight: 1.5,
};

const statStyle: CSSProperties = {
  color: "var(--color-neutral-900)",
  fontSize: "var(--font-size-sm)",
  fontWeight: "var(--font-weight-semibold)" as CSSProperties["fontWeight"],
};

const linkStyle: CSSProperties = {
  textDecoration: "none",
  color: "inherit",
  display: "block",
  height: "100%",
};

const defaultRenderLink: RenderHubCardLink = ({ to, children }) => (
  <a href={to} data-terp="hubcard-link" style={linkStyle}>
    {children}
  </a>
);

/**
 * A single navigable card inside a {@link HubPage}: icon + title, a short description of
 * the area, and an optional live `stat`. The whole card is one link, rendered through
 * `renderLink` so the hub stays router-agnostic.
 */
export function HubCard({
  to,
  title,
  description,
  icon,
  stat,
  renderLink = defaultRenderLink,
}: HubCardProps) {
  const resolve = useUiText();
  return (
    <li data-terp="hubcard" style={cardStyle}>
      {renderLink({
        to,
        children: (
          <span style={{ display: "grid", gap: "var(--space-2)" }}>
            <span style={cardTitleRowStyle}>
              {icon !== undefined && <span style={iconTileStyle}>{icon}</span>}
              <strong data-terp="hubcard-title" style={titleTextStyle}>
                {resolve(title)}
              </strong>
            </span>
            {description !== undefined && <span style={descriptionStyle}>{resolve(description)}</span>}
            {stat !== undefined && <span style={statStyle}>{stat}</span>}
          </span>
        ),
      })}
    </li>
  );
}

