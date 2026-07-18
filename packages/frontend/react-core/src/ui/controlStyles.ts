import type { CSSProperties } from "react";

/** Stable typography for interactive controls, independent of surrounding display text. */
export const CONTROL_TEXT_STYLE: CSSProperties = {
  fontFamily: "var(--font-family-sans)",
  fontSize: "var(--font-size-sm)",
  fontWeight: "var(--font-weight-normal)" as CSSProperties["fontWeight"],
  lineHeight: 1.25,
};
