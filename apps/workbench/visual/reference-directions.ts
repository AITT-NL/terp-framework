/**
 * Reference directions (ADR 0226): three looks deliberately unlike the framework's default and
 * unlike one another, each stated the way an app states its own, as tokens in an unlayered
 * sheet over the framework's (its `theme.css`). None sets a colour: a palette is held to its
 * own contrast gate, and these are about what the type and shape vocabulary can say.
 *
 * They are the cases the vocabulary is checked against. Every component change has to keep
 * reading the roles under all three, so a look that is not the default stays possible; and
 * what none of them can say is recorded in ADR 0226 as the vocabulary's known gaps.
 */
export interface ReferenceDirection {
  id: string;
  /** The kind of app that would choose it, in a few words. */
  purpose: string;
  /** Theme-invariant tokens, declared once in `:root` as an app's `theme.css` would. */
  tokens: Record<string, string>;
}

export const REFERENCE_DIRECTIONS: readonly ReferenceDirection[] = [
  {
    id: "console",
    purpose: "a tool people work in all day: square, tight and quiet",
    tokens: {
      // Written as an author would: a bare 0, which a length in min() does not accept, so the
      // multi-line cap has to survive it (it falls back to the initial corner, which is 0).
      "--radius-sm": "0",
      "--radius-md": "0.125rem",
      "--radius-lg": "0.125rem",
      "--radius-control": "var(--radius-md)",
      "--radius-container": "0",
      "--font-weight-heading": "var(--font-weight-semibold)",
    },
  },
  {
    id: "portal",
    purpose: "a portal people visit now and then: pill-shaped controls, soft cards, a rounded face",
    tokens: {
      "--radius-control": "var(--radius-full)",
      "--radius-container": "1.5rem",
      "--font-family-heading": 'ui-rounded, "SF Pro Rounded", system-ui, sans-serif',
      "--font-weight-heading": "var(--font-weight-bold)",
    },
  },
  {
    id: "editorial",
    purpose: "an app people mostly read and write in: serif headings at a light weight",
    tokens: {
      "--font-family-heading": 'ui-serif, Georgia, "Times New Roman", serif',
      "--font-weight-heading": "var(--font-weight-medium)",
      "--radius-control": "var(--radius-sm)",
      "--radius-container": "var(--radius-sm)",
    },
  },
];

/** The sheet an app would ship for `direction`: one unlayered `:root` block. */
export function directionSheet(direction: ReferenceDirection): string {
  const lines = Object.entries(direction.tokens).map(([name, value]) => `  ${name}: ${value};`);
  return `:root {\n${lines.join("\n")}\n}\n`;
}
