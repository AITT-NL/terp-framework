import type { CSSProperties, ReactNode } from "react";

/**
 * The dependency-free icon layer: a small set of inline SVG glyphs the shell's
 * navigation (and hub cards) can reference **by name** through the manifest's
 * `NavItem.icon` field, with a deterministic fallback — the first letter of the
 * label in a rounded tile — so a nav item without an icon still has an icon-rail
 * representation. All strokes use `currentColor`, so the glyphs theme with the
 * design tokens; react-core takes no icon-library dependency (an app that wants
 * its own set passes any rendered node where a `ReactNode` icon slot exists).
 */

const svgProps = {
  width: "1.25em",
  height: "1.25em",
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.8,
  strokeLinecap: "round",
  strokeLinejoin: "round",
  "aria-hidden": true,
  focusable: false,
} as const;

/** The bundled glyphs, keyed by the names a manifest's `NavItem.icon` may use. */
export const ICON_GLYPHS: Record<string, ReactNode> = {
  home: (
    <svg {...svgProps}>
      <path d="M3 10.5 12 3l9 7.5" />
      <path d="M5.5 9.5V21h13V9.5" />
    </svg>
  ),
  list: (
    <svg {...svgProps}>
      <path d="M8 6h13M8 12h13M8 18h13" />
      <path d="M3.5 6h.01M3.5 12h.01M3.5 18h.01" />
    </svg>
  ),
  folder: (
    <svg {...svgProps}>
      <path d="M3 6.5A1.5 1.5 0 0 1 4.5 5h4l2 2.5h8A1.5 1.5 0 0 1 20 9v9.5a1.5 1.5 0 0 1-1.5 1.5h-14A1.5 1.5 0 0 1 3 18.5Z" />
    </svg>
  ),
  users: (
    <svg {...svgProps}>
      <circle cx="9" cy="8" r="3.25" />
      <path d="M3.5 19.5c0-3 2.5-5 5.5-5s5.5 2 5.5 5" />
      <path d="M15.5 5.5a3.25 3.25 0 0 1 0 5.5M17.5 14.8c1.8.7 3 2.2 3 4.7" />
    </svg>
  ),
  shield: (
    <svg {...svgProps}>
      <path d="M12 3 5 5.5v5c0 4.5 3 8.5 7 10 4-1.5 7-5.5 7-10v-5Z" />
    </svg>
  ),
  settings: (
    <svg {...svgProps}>
      <circle cx="12" cy="12" r="3" />
      <path d="M12 2.75v2.5M12 18.75v2.5M2.75 12h2.5M18.75 12h2.5M5.4 5.4l1.8 1.8M16.8 16.8l1.8 1.8M18.6 5.4l-1.8 1.8M7.2 16.8l-1.8 1.8" />
    </svg>
  ),
  document: (
    <svg {...svgProps}>
      <path d="M6 3h8l4 4v14H6Z" />
      <path d="M14 3v4h4" />
      <path d="M9 12h6M9 16h6" />
    </svg>
  ),
  chart: (
    <svg {...svgProps}>
      <path d="M4 20V4" />
      <path d="M4 20h16" />
      <path d="M8.5 16v-5M13 16V7.5M17.5 16v-3" />
    </svg>
  ),
  calendar: (
    <svg {...svgProps}>
      <rect x="4" y="5.5" width="16" height="15" rx="1.5" />
      <path d="M4 10h16M8.5 3.5v4M15.5 3.5v4" />
    </svg>
  ),
  inbox: (
    <svg {...svgProps}>
      <path d="M4 5h16v14H4Z" />
      <path d="M4 13h4.5l1.5 2.5h4L15.5 13H20" />
    </svg>
  ),
  audit: (
    <svg {...svgProps}>
      <circle cx="10.5" cy="10.5" r="6" />
      <path d="M15 15l5.5 5.5" />
      <path d="M8 10.5h5M10.5 8v5" />
    </svg>
  ),
  hub: (
    <svg {...svgProps}>
      <rect x="3.5" y="3.5" width="7" height="7" rx="1" />
      <rect x="13.5" y="3.5" width="7" height="7" rx="1" />
      <rect x="3.5" y="13.5" width="7" height="7" rx="1" />
      <rect x="13.5" y="13.5" width="7" height="7" rx="1" />
    </svg>
  ),
  plus: (
    <svg {...svgProps}>
      <path d="M12 5v14M5 12h14" />
    </svg>
  ),
  edit: (
    <svg {...svgProps}>
      <path d="M4 20h4l10-10-4-4L4 16v4Z" />
      <path d="M14 6l4 4" />
    </svg>
  ),
  trash: (
    <svg {...svgProps}>
      <path d="M4 7h16" />
      <path d="M9 7V4.5h6V7" />
      <path d="M6 7l1 13h10l1-13" />
      <path d="M10 11v6M14 11v6" />
    </svg>
  ),
  search: (
    <svg {...svgProps}>
      <circle cx="11" cy="11" r="6.5" />
      <path d="m16 16 4.5 4.5" />
    </svg>
  ),
  check: (
    <svg {...svgProps}>
      <path d="m5 12 5 5 9-11" />
    </svg>
  ),
  x: (
    <svg {...svgProps}>
      <path d="M6 6l12 12M18 6 6 18" />
    </svg>
  ),
  "chevron-down": (
    <svg {...svgProps}>
      <path d="m6 9 6 6 6-6" />
    </svg>
  ),
  "chevron-right": (
    <svg {...svgProps}>
      <path d="m9 6 6 6-6 6" />
    </svg>
  ),
  "chevron-left": (
    <svg {...svgProps}>
      <path d="m15 6-6 6 6 6" />
    </svg>
  ),
  "arrow-left": (
    <svg {...svgProps}>
      <path d="M20 12H4" />
      <path d="m10 6-6 6 6 6" />
    </svg>
  ),
  external: (
    <svg {...svgProps}>
      <path d="M14 4h6v6" />
      <path d="M20 4 10 14" />
      <path d="M20 14v5.5A1.5 1.5 0 0 1 18.5 21h-13A1.5 1.5 0 0 1 4 19.5v-13A1.5 1.5 0 0 1 5.5 5H11" />
    </svg>
  ),
  logout: (
    <svg {...svgProps}>
      <path d="M14 4h4.5A1.5 1.5 0 0 1 20 5.5v13a1.5 1.5 0 0 1-1.5 1.5H14" />
      <path d="M10 8 6 12l4 4" />
      <path d="M6 12h11" />
    </svg>
  ),
  user: (
    <svg {...svgProps}>
      <circle cx="12" cy="8" r="4" />
      <path d="M4 21c0-4 3.5-7 8-7s8 3 8 7" />
    </svg>
  ),
  bell: (
    <svg {...svgProps}>
      <path d="M6 17V11a6 6 0 0 1 12 0v6l1.5 2H4.5L6 17Z" />
      <path d="M10 20a2 2 0 0 0 4 0" />
    </svg>
  ),
  key: (
    <svg {...svgProps}>
      <circle cx="8" cy="15" r="4" />
      <path d="M11 12 21 2" />
      <path d="m17.5 5.5 3 3M15 8l3 3" />
    </svg>
  ),
  globe: (
    <svg {...svgProps}>
      <circle cx="12" cy="12" r="9" />
      <path d="M3 12h18" />
      <path d="M12 3c3 3.5 3 14 0 18-3-4-3-14.5 0-18Z" />
    </svg>
  ),
  lock: (
    <svg {...svgProps}>
      <rect x="4" y="10" width="16" height="11" rx="2" />
      <path d="M8 10V7a4 4 0 1 1 8 0v3" />
    </svg>
  ),
  tag: (
    <svg {...svgProps}>
      <path d="M3 12V4h8l10 10-8 8L3 12Z" />
      <circle cx="8" cy="9" r="1.5" />
    </svg>
  ),
  mail: (
    <svg {...svgProps}>
      <rect x="3" y="5" width="18" height="14" rx="2" />
      <path d="m3 7 9 7 9-7" />
    </svg>
  ),
  refresh: (
    <svg {...svgProps}>
      <path d="M4 10a8 8 0 0 1 14-4l2 2" />
      <path d="M20 4v4h-4" />
      <path d="M20 14a8 8 0 0 1-14 4l-2-2" />
      <path d="M4 20v-4h4" />
    </svg>
  ),
  filter: (
    <svg {...svgProps}>
      <path d="M4 5h16l-6 8v6l-4-2v-4L4 5Z" />
    </svg>
  ),
  download: (
    <svg {...svgProps}>
      <path d="M12 4v12" />
      <path d="m7 11 5 5 5-5" />
      <path d="M4 20h16" />
    </svg>
  ),
  upload: (
    <svg {...svgProps}>
      <path d="M12 20V8" />
      <path d="m7 13 5-5 5 5" />
      <path d="M4 4h16" />
    </svg>
  ),
  star: (
    <svg {...svgProps}>
      <path d="m12 3 2.7 5.7 6.3.9-4.6 4.4 1.1 6.2L12 17.3l-5.5 2.9 1.1-6.2L3 9.6l6.3-.9L12 3Z" />
    </svg>
  ),
  heart: (
    <svg {...svgProps}>
      <path d="M12 20s-7-4.5-7-10a4.5 4.5 0 0 1 7-3.5A4.5 4.5 0 0 1 19 10c0 5.5-7 10-7 10Z" />
    </svg>
  ),
  database: (
    <svg {...svgProps}>
      <ellipse cx="12" cy="5.5" rx="8" ry="2.5" />
      <path d="M4 5.5v13c0 1.4 3.6 2.5 8 2.5s8-1.1 8-2.5v-13" />
      <path d="M4 12c0 1.4 3.6 2.5 8 2.5s8-1.1 8-2.5" />
    </svg>
  ),
  code: (
    <svg {...svgProps}>
      <path d="m8 8-5 4 5 4" />
      <path d="m16 8 5 4-5 4" />
      <path d="m14 4-4 16" />
    </svg>
  ),
  truck: (
    <svg {...svgProps}>
      <path d="M3 7h11v10H3z" />
      <path d="M14 10h4l3 3v4h-7" />
      <circle cx="7" cy="18" r="2" />
      <circle cx="17" cy="18" r="2" />
    </svg>
  ),
  cart: (
    <svg {...svgProps}>
      <path d="M3 4h2l2 12h11l2-8H7" />
      <circle cx="9" cy="20" r="1.5" />
      <circle cx="17" cy="20" r="1.5" />
    </svg>
  ),
  wallet: (
    <svg {...svgProps}>
      <path d="M4 7a2 2 0 0 1 2-2h11v4" />
      <rect x="3" y="7" width="18" height="13" rx="2" />
      <circle cx="16.5" cy="13.5" r="1.2" />
    </svg>
  ),
  "map-pin": (
    <svg {...svgProps}>
      <path d="M12 21s-7-6-7-12a7 7 0 0 1 14 0c0 6-7 12-7 12Z" />
      <circle cx="12" cy="9" r="2.5" />
    </svg>
  ),
  clock: (
    <svg {...svgProps}>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7v5l3.5 2.5" />
    </svg>
  ),
  link: (
    <svg {...svgProps}>
      <path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1.3 1.3" />
      <path d="M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1.3-1.3" />
    </svg>
  ),
  grid: (
    <svg {...svgProps}>
      <rect x="4" y="4" width="7" height="7" rx="1" />
      <rect x="13" y="4" width="7" height="7" rx="1" />
      <rect x="4" y="13" width="7" height="7" rx="1" />
      <rect x="13" y="13" width="7" height="7" rx="1" />
    </svg>
  ),
  book: (
    <svg {...svgProps}>
      <path d="M5 4h11a3 3 0 0 1 3 3v13H8a3 3 0 0 1-3-3V4Z" />
      <path d="M5 17a3 3 0 0 1 3-3h11" />
    </svg>
  ),
  briefcase: (
    <svg {...svgProps}>
      <rect x="3" y="7" width="18" height="13" rx="2" />
      <path d="M9 7V5a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v2" />
      <path d="M3 13h18" />
    </svg>
  ),
  building: (
    <svg {...svgProps}>
      <path d="M5 21V4h14v17" />
      <path d="M9 8h2M13 8h2M9 12h2M13 12h2M9 16h2M13 16h2" />
      <path d="M3 21h18" />
    </svg>
  ),
  clipboard: (
    <svg {...svgProps}>
      <rect x="6" y="5" width="12" height="16" rx="1.5" />
      <path d="M9 5V3.5A1.5 1.5 0 0 1 10.5 2h3A1.5 1.5 0 0 1 15 3.5V5" />
    </svg>
  ),
  layers: (
    <svg {...svgProps}>
      <path d="m12 3 9 5-9 5-9-5 9-5Z" />
      <path d="m3 12 9 5 9-5" />
      <path d="m3 17 9 5 9-5" />
    </svg>
  ),
  send: (
    <svg {...svgProps}>
      <path d="M21 3 3 11l7 3 3 7 8-18Z" />
      <path d="m10 14 11-11" />
    </svg>
  ),
  phone: (
    <svg {...svgProps}>
      <path d="M5 4h4l2 5-2.5 1.5a11 11 0 0 0 5 5L15 13l5 2v4a2 2 0 0 1-2 2A15 15 0 0 1 3 6a2 2 0 0 1 2-2Z" />
    </svg>
  ),
  image: (
    <svg {...svgProps}>
      <rect x="3" y="4" width="18" height="16" rx="2" />
      <circle cx="9" cy="10" r="2" />
      <path d="m4 19 6-6 4 4 3-3 4 4" />
    </svg>
  ),
  video: (
    <svg {...svgProps}>
      <rect x="3" y="6" width="13" height="12" rx="2" />
      <path d="m16 10 5-3v10l-5-3z" />
    </svg>
  ),
  music: (
    <svg {...svgProps}>
      <path d="M9 18V5l11-2v13" />
      <circle cx="7" cy="18" r="2" />
      <circle cx="18" cy="16" r="2" />
    </svg>
  ),
  wrench: (
    <svg {...svgProps}>
      <path d="M14.7 3.3a5 5 0 0 1 6 6L17 13v6l-3 2-2-2v-4l-8-8 3-3 8 8 3.4-3.4a3 3 0 0 0-4-4L13 6" />
    </svg>
  ),
  zap: (
    <svg {...svgProps}>
      <path d="M13 3 4 14h6l-1 7 9-11h-6l1-7Z" />
    </svg>
  ),
};

const fallbackStyle: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  justifyContent: "center",
  width: "1.25em",
  height: "1.25em",
  borderRadius: "var(--radius-sm, 4px)",
  background: "var(--color-brand-primary-soft, var(--color-neutral-200))",
  color: "var(--color-brand-primary, var(--color-neutral-700))",
  fontSize: "0.7em",
  fontWeight: "var(--font-weight-medium)" as CSSProperties["fontWeight"],
  lineHeight: 1,
};

export interface NavIconProps {
  /** Glyph name (a `NavItem.icon` value); unknown / missing falls back to the initial. */
  name?: string;
  /** The item label the fallback tile derives its initial from. */
  label: string;
}

/**
 * Resolve a manifest icon name to its glyph, falling back to the label's first
 * letter in a tile — every nav item stays recognisable in the collapsed icon rail.
 */
export function NavIcon({ name, label }: NavIconProps) {
  const glyph = name !== undefined ? ICON_GLYPHS[name] : undefined;
  if (glyph !== undefined) {
    return <>{glyph}</>;
  }
  return (
    <span aria-hidden="true" style={fallbackStyle}>
      {(label[0] ?? "?").toUpperCase()}
    </span>
  );
}

export interface IconProps {
  /** Glyph name from {@link ICON_GLYPHS}; unknown names render nothing. */
  name: string;
  /**
   * CSS length applied to width & height (default `1em`, so the glyph tracks
   * the surrounding text size). All strokes use `currentColor`.
   */
  size?: string | number;
  /** Optional accessible label; when set the glyph is exposed with `role="img"`. */
  title?: string;
}

/**
 * Render a bundled glyph by name — the sibling of {@link NavIcon} for use
 * inside buttons, empty states, breadcrumbs and any place that needs a token-
 * coloured icon without knowing the glyph inventory. `size` accepts any CSS
 * length (e.g. `"1em"`, `16`, `"1.25rem"`). Unknown names render nothing —
 * the caller may fall back to a text label.
 */
export function Icon({ name, size = "1em", title }: IconProps) {
  const glyph = ICON_GLYPHS[name];
  if (glyph === undefined) {
    return null;
  }
  const px = typeof size === "number" ? `${size}px` : size;
  const labelled = title !== undefined;
  return (
    <span
      aria-hidden={labelled ? undefined : true}
      role={labelled ? "img" : undefined}
      aria-label={labelled ? title : undefined}
      style={{
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        width: px,
        height: px,
        lineHeight: 1,
        color: "inherit",
      }}
    >
      {glyph}
    </span>
  );
}

/**
 * The placeholder product mark: an abstract, token-coloured tile the shell shows
 * at the top of the sidebar until an app supplies its own `logo` (any rendered
 * node — an `<img>`, an inline SVG). Deliberately generic, so a generated app
 * looks intentional on day one and the replacement seam is obvious.
 */
export function TerpMark() {
  return (
    <svg
      width="28"
      height="28"
      viewBox="0 0 28 28"
      role="img"
      aria-hidden="true"
      focusable={false}
    >
      <rect width="28" height="28" rx="7" fill="var(--color-brand-primary)" />
      <path
        d="M7 10.5 14 6l7 4.5M9 12.5V21h10v-8.5"
        fill="none"
        stroke="var(--color-brand-primary-contrast)"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

