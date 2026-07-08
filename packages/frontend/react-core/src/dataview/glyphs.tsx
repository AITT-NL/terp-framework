import type { CSSProperties } from "react";

// Decorative inline SVG glyphs for the DataView family (react-core ships no icon
// library). All are aria-hidden; interactive wrappers carry the accessible names.

interface GlyphProps {
  size?: number;
  style?: CSSProperties;
}

function glyphProps({ size = 16, style }: GlyphProps) {
  return {
    width: size,
    height: size,
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 2,
    strokeLinecap: "round",
    strokeLinejoin: "round",
    "aria-hidden": true,
    focusable: false,
    style,
  } as const;
}

export function ChevronDownGlyph(props: GlyphProps) {
  return (
    <svg {...glyphProps(props)}>
      <polyline points="6 9 12 15 18 9" />
    </svg>
  );
}

export function ChevronRightGlyph(props: GlyphProps) {
  return (
    <svg {...glyphProps(props)}>
      <polyline points="9 6 15 12 9 18" />
    </svg>
  );
}

export function SortAscGlyph(props: GlyphProps) {
  return (
    <svg {...glyphProps(props)}>
      <path d="M12 19V5" />
      <polyline points="5 12 12 5 19 12" />
    </svg>
  );
}

export function SortDescGlyph(props: GlyphProps) {
  return (
    <svg {...glyphProps(props)}>
      <path d="M12 5v14" />
      <polyline points="19 12 12 19 5 12" />
    </svg>
  );
}

export function SortNoneGlyph(props: GlyphProps) {
  return (
    <svg {...glyphProps(props)}>
      <polyline points="8 9 12 5 16 9" />
      <polyline points="8 15 12 19 16 15" />
    </svg>
  );
}

export function SearchGlyph(props: GlyphProps) {
  return (
    <svg {...glyphProps(props)}>
      <circle cx="11" cy="11" r="7" />
      <line x1="21" y1="21" x2="16.65" y2="16.65" />
    </svg>
  );
}

export function CloseGlyph(props: GlyphProps) {
  return (
    <svg {...glyphProps(props)}>
      <line x1="18" y1="6" x2="6" y2="18" />
      <line x1="6" y1="6" x2="18" y2="18" />
    </svg>
  );
}

export function EllipsisGlyph(props: GlyphProps) {
  return (
    <svg {...glyphProps(props)}>
      <circle cx="5" cy="12" r="1.5" fill="currentColor" stroke="none" />
      <circle cx="12" cy="12" r="1.5" fill="currentColor" stroke="none" />
      <circle cx="19" cy="12" r="1.5" fill="currentColor" stroke="none" />
    </svg>
  );
}

export function ColumnsGlyph(props: GlyphProps) {
  return (
    <svg {...glyphProps(props)}>
      <rect x="3" y="4" width="18" height="16" rx="2" />
      <line x1="9" y1="4" x2="9" y2="20" />
      <line x1="15" y1="4" x2="15" y2="20" />
    </svg>
  );
}

export function TableGlyph(props: GlyphProps) {
  return (
    <svg {...glyphProps(props)}>
      <rect x="3" y="4" width="18" height="16" rx="2" />
      <line x1="3" y1="10" x2="21" y2="10" />
      <line x1="3" y1="15" x2="21" y2="15" />
    </svg>
  );
}

export function CardsGlyph(props: GlyphProps) {
  return (
    <svg {...glyphProps(props)}>
      <rect x="3" y="4" width="18" height="7" rx="2" />
      <rect x="3" y="14" width="18" height="7" rx="2" />
    </svg>
  );
}

export function ArrowUpGlyph(props: GlyphProps) {
  return (
    <svg {...glyphProps(props)}>
      <polyline points="6 14 12 8 18 14" />
    </svg>
  );
}

export function ArrowDownGlyph(props: GlyphProps) {
  return (
    <svg {...glyphProps(props)}>
      <polyline points="6 10 12 16 18 10" />
    </svg>
  );
}

export function PageFirstGlyph(props: GlyphProps) {
  return (
    <svg {...glyphProps(props)}>
      <polyline points="11 17 6 12 11 7" />
      <polyline points="18 17 13 12 18 7" />
    </svg>
  );
}

export function PagePrevGlyph(props: GlyphProps) {
  return (
    <svg {...glyphProps(props)}>
      <polyline points="15 18 9 12 15 6" />
    </svg>
  );
}

export function PageNextGlyph(props: GlyphProps) {
  return (
    <svg {...glyphProps(props)}>
      <polyline points="9 18 15 12 9 6" />
    </svg>
  );
}

export function PageLastGlyph(props: GlyphProps) {
  return (
    <svg {...glyphProps(props)}>
      <polyline points="13 17 18 12 13 7" />
      <polyline points="6 17 11 12 6 7" />
    </svg>
  );
}
