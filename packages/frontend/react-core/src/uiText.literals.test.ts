// The hole the completeness guard cannot see.
//
// `locale.test.tsx` already asserts that every framework string is translated in every
// shipped locale, and it passes at 100%. It is only as wide as the string TABLE: a
// hardcoded `aria-label="Clear selection"` never becomes a `TerpStrings` key, so it is
// invisible to a check that walks keys — and "every framework string is translated" and
// "this control cannot be translated at all" were both true at the same time.
//
// This walks the SOURCE instead, so the two guards together cover the round trip: a
// user-facing string has to reach the table, and everything in the table has to be
// translated. Reported as "translations are not always present", which is exactly how it
// looks from an app — most of the chrome localises, a few controls stubbornly do not, and
// no gate anywhere goes red.
//
// Uses Vite's raw glob rather than an fs walk, the way the other scanning tests here do:
// this package's tsconfig declares no Node types on purpose.

import { describe, expect, it } from "vitest";

const sources = import.meta.glob("./**/*.{ts,tsx}", {
  query: "?raw",
  import: "default",
  eager: true,
}) as Record<string, string>;

/** Attributes whose value a user reads or hears. */
const USER_FACING_ATTRIBUTES = ["aria-label", "placeholder", "title", "alt", "aria-description"];

/**
 * Files where a bare literal is not a translation defect.
 *
 * Deliberately tiny, and each entry says why it is not one. This is NOT a migration
 * baseline: the framework's chrome is already routed through `TerpStrings`, so there is no
 * debt to ratchet down, and a growing list here would mean the opposite of what this test
 * is for.
 */
const ALLOWED: Record<string, string> = {
  "./uiText.tsx": "the string table itself — these ARE the source-language defaults",
  "./locale.tsx": "the shipped catalogues — every value here is a translation",
  "./styles.ts":
    "CSS in a template literal, so a match is an attribute SELECTOR " +
    '(data-placeholder="true"), never a string a user reads',
};

/**
 * A line that only *documents* code.
 *
 * These checks forbid a shape, and the clearest way to document a forbidden shape is to
 * write it down — so the prose explaining the fix contains the defect verbatim. The first
 * version of the widened default check duly reported DatePicker's own comment, which says
 * `placeholder = "Select date"` while the code beside it does the right thing. Skipping
 * comment-only lines is the fix; a literal inside a trailing comment on a line of real code
 * is still matched, which is the rarer shape and the one worth a false positive.
 */
function isComment(line: string): boolean {
  const trimmed = line.trimStart();
  return trimmed.startsWith("//") || trimmed.startsWith("*") || trimmed.startsWith("/*");
}

function scannable(): [string, string][] {
  return Object.entries(sources).filter(
    ([file]) => !/\.(test|spec)\.tsx?$/.test(file) && ALLOWED[file] === undefined,
  );
}

describe("user-facing strings", () => {
  it("never hardcodes an attribute a user reads", () => {
    const offenders: string[] = [];

    for (const [file, source] of scannable()) {
      source.split("\n").forEach((line, index) => {
        if (line.includes("i18n-ok") || isComment(line)) {
          return;
        }
        for (const attribute of USER_FACING_ATTRIBUTES) {
          // A double-quoted value starting with a letter — a literal a human reads. A
          // `{expression}` value is not matched, and that is the compliant shape: it
          // resolves a `UiText` or reads a `TerpStrings` key.
          const match = new RegExp(`${attribute}="([A-Za-z][^"]*)"`).exec(line);
          if (match !== null) {
            offenders.push(`${file}:${index + 1}  ${attribute}="${match[1]}"`);
          }
        }
      });
    }

    expect(
      offenders,
      "these strings are rendered to a user and cannot be translated: they never enter " +
        "TerpStrings, so locale.test.tsx's completeness guard passes over them and an app " +
        "has no way to override them. Add a TerpStrings key (with its translations) and " +
        "read it through useStrings() — or, for a caller-supplied string, take a UiText " +
        "prop and resolve it with useUiText(). A genuinely non-linguistic value (a test id, " +
        "a token name) takes an `i18n-ok` comment on the line.",
    ).toEqual([]);
  });

  it("never hides a literal inside a braced attribute value", () => {
    // The shape the check above is blind to by construction. Its comment claimed a
    // `{expression}` value "is the compliant shape: it resolves a UiText or reads a
    // TerpStrings key" — true of most, and not of a ternary, a `??` fallback or a default,
    // any of which carries the untranslatable literal straight through the braces. Not
    // hypothetical: `aria-label={multiple ? "Clear all selections" : "Clear selection"}`
    // shipped while this very file was being written to forbid it, and the two met in a
    // merge. Treating braces as proof of compliance makes the fix for one control the
    // loophole for the next.
    //
    // Same line only, which is a stated limit rather than a claim: the shapes that carry a
    // literal (ternary, fallback, default) fit on one line under this repo's formatting.
    const offenders: string[] = [];

    for (const [file, source] of scannable()) {
      source.split("\n").forEach((line, index) => {
        if (line.includes("i18n-ok") || isComment(line)) {
          return;
        }
        for (const attribute of USER_FACING_ATTRIBUTES) {
          // The name must stand alone: `data-placeholder={…}` is not `placeholder`, and
          // matching it as a substring reported a data attribute's `"true"` as prose.
          const opener = new RegExp(`(?<![\w-])${attribute}=\{`, "g");
          for (const opened of line.matchAll(opener)) {
            // Read to the MATCHING brace. Reading to end-of-line swept up whatever attribute
            // came next — `data-terp="breadcrumbs"` on the same element was reported as a
            // user-facing literal.
            const start = opened.index + opened[0].length;
            let cursor = start;
            let depth = 1;
            while (cursor < line.length && depth > 0) {
              if (line[cursor] === "{") depth += 1;
              else if (line[cursor] === "}") depth -= 1;
              if (depth === 0) break;
              cursor += 1;
            }
            for (const [literal, inner] of line.slice(start, cursor).matchAll(/"([A-Za-z][^"]*)"/g)) {
              // Inside an expression most literals are not prose: a discriminant
              // (`kind === "role"`), a placeholder token, a data value. Unlike the direct
              // `attribute="…"` position — where a literal is user-facing almost by
              // definition — this one asks whether the string LOOKS like a label.
              //
              // A heuristic, stated as one: a lowercase single-word label
              // (`aria-label={open ? "close" : "open"}`) slips through. Every user-facing
              // string this framework ships is a capitalised phrase, so that shape does not
              // exist here; if one lands, it wants the direct check's discipline rather than
              // a wider net here, which would flag every discriminant in the package.
              if (/^[A-Z]/.test(inner!) || inner!.includes(" ")) {
                offenders.push(`${file}:${index + 1}  ${attribute}={… ${literal} …}`);
              }
            }
          }
        }
      });
    }

    expect(
      offenders,
      "a user-facing attribute resolves an expression, and the expression still contains a " +
        "hardcoded English string — most often a ternary picking between two literals, or a " +
        "`??` fallback behind a translatable prop. Braces are not evidence of anything: move " +
        "every branch to a TerpStrings key and read them through useStrings().",
    ).toEqual([]);
  });

  it("never defaults a UiText prop to a bare string", () => {
    // The subtler half, and the one that looks fine in review. A `UiText` prop defaulted to
    // `"Select date"` IS overridable — and still untranslatable: a plain string resolves
    // as-is, so an app that does not pass the prop shows English in every locale. The fix is
    // not a descriptor default either; it is to fall back to a TerpStrings key at the use
    // site, so the app's own catalogue answers when the caller says nothing.
    const offenders: string[] = [];

    for (const [file, source] of scannable()) {
      const uiTextProps = new Set(
        [...source.matchAll(/^\s*(\w+)\??:\s*UiText[;\s|]/gm)].map((match) => match[1]!),
      );
      source.split("\n").forEach((line, index) => {
        if (line.includes("i18n-ok") || isComment(line)) {
          return;
        }
        // Anywhere on the line, NOT anchored to own it. Anchoring made this depend on
        // formatting: `removeLabel = "Remove"` inside a one-line destructuring
        // (`const { value, onChange, removeLabel = "Remove", ...rest } = props`) was
        // invisible, and became visible only when the line was split for unrelated reasons.
        // A check that a reformat can switch on and off is not a check.
        for (const assignment of line.matchAll(/(\w+)\s*=\s*"([A-Za-z][^"]*)"/g)) {
          if (uiTextProps.has(assignment[1]!)) {
            offenders.push(`${file}:${index + 1}  ${assignment[1]} = "${assignment[2]}"`);
          }
        }
      });
    }

    expect(
      offenders,
      "a UiText prop defaulted to a plain string renders that string in every locale for any " +
        "app that does not override it — the prop is translatable and its default is not. " +
        "Leave the default `undefined` and fall back to a TerpStrings key at the use site.",
    ).toEqual([]);
  });
});
