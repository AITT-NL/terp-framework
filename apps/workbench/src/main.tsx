import "@terpjs/contract/tokens.css";

import {
  LOCALE_EN,
  LOCALE_NL,
  LOCALE_STORAGE_KEY,
  LocaleProvider,
  THEME_STORAGE_KEY,
  ThemeProvider,
} from "@terpjs/react-core";
import { createRoot } from "react-dom/client";
import type { CSSProperties } from "react";
import type { Theme } from "@terpjs/react-core";

import { ALL_SPECIMENS, SPECIMEN_GROUPS } from "./specimens";
import { BASE_THEME, THEMES } from "./themes";

// The component workbench: every shipped component, every variant, both themes, on one page.
//
// It exists for two reasons. There was no catalog — the package README lists components in
// prose, so "what does this look like, and what states does it have" had no answer short of
// reading the source. And there was no way to see a styling change: the package ships no
// runnable surface, so a change to a token or a component was reviewed by reading a diff.
//
// It is a private workspace package, deliberately not part of `@terpjs/react-core`. The
// package sets no `files` field, so npm packs everything in its directory — a workbench
// inside it would ship to every consumer. Living outside it also means the workbench imports
// react-core by package name exactly as an app does, so it exercises the public export
// surface rather than reaching into `src/`.
//
// The theme comes from `?theme=<name>`, applied to `<html>` directly rather than through
// `ThemeProvider`. That is for the visual suite: the provider persists to localStorage, so a
// toggled theme would leak between runs and make a baseline depend on run order. A URL that
// fully determines the render is the whole trick. The list of names comes from the contract's
// token manifest (see `./themes`), so a theme added there is renderable here immediately.

/** The requested theme, falling back to the base theme for a bare or unrecognised visit. */
function requestedTheme(): Theme {
  const value = new URLSearchParams(window.location.search).get("theme");
  return THEMES.includes(value as Theme) ? (value as Theme) : BASE_THEME;
}

/**
 * The single specimen `?only=<id>` asks for, or null for the full catalog page.
 *
 * This exists for the visual suite, and it is what makes a per-specimen baseline actually
 * per-specimen. On the catalog page a specimen sits wherever the specimens above it leave
 * it, and that offset is usually fractional — `text-inputs` sat at y=2186.890625. Rendering
 * at a fractional device offset decides the subpixel phase every 1px border and glyph in
 * that box is rasterised at, so *adding a specimen anywhere above* moved unrelated
 * specimens onto a different phase and silently re-recorded their baselines. Measured, not
 * inferred: adding fifteen specimens shifted `text-inputs` to y=2457.703125 and repainted
 * 4846 pixels of it, while `button-variants` at an integer y=168 was untouched — six
 * baselines moved in total for a change to none of their components.
 *
 * That is the per-specimen promise failing in the one situation the promise is for. A
 * reviewer who sees six unrelated baselines change alongside a new specimen learns to
 * accept baseline updates wholesale, which is the same failure the per-specimen split and
 * the pinned threshold both exist to prevent.
 *
 * With `?only=`, every specimen renders alone at the same fixed origin, so its baseline
 * depends on the specimen and nothing else. The bare address still renders the whole
 * catalog, which is what a human opens.
 */
function requestedSpecimen(): string | null {
  return new URLSearchParams(window.location.search).get("only");
}

const theme = requestedTheme();
document.documentElement.setAttribute("data-theme", theme);

// `ThemeProvider` and `LocaleProvider` are mounted below so the chrome specimens
// (`ThemeToggle`, `LanguageSwitcher`) have the context they need — both render nothing
// without it. Both providers restore a previous choice from `localStorage`, which would
// override the theme the URL just asked for and make a baseline depend on whatever the last
// visit picked. Clearing the two keys first makes `defaultTheme` authoritative, so the
// address still fully determines the render.
try {
  window.localStorage.removeItem(THEME_STORAGE_KEY);
  window.localStorage.removeItem(LOCALE_STORAGE_KEY);
} catch {
  // A browser with storage denied is fine here: nothing was persisted to override.
}

const pageStyle: CSSProperties = {
  background: "var(--color-neutral-50)",
  color: "var(--color-neutral-900)",
  fontFamily: "var(--font-family-sans)",
  fontSize: "var(--font-size-base)",
  minHeight: "100vh",
  padding: "var(--space-6)",
};

const headerStyle: CSSProperties = {
  display: "flex",
  alignItems: "baseline",
  justifyContent: "space-between",
  gap: "var(--space-4)",
  flexWrap: "wrap",
  paddingBottom: "var(--space-4)",
  borderBottom: "1px solid var(--color-neutral-200)",
  marginBottom: "var(--space-6)",
};

const groupTitleStyle: CSSProperties = {
  fontSize: "var(--font-size-xl)",
  fontWeight: "var(--font-weight-semibold)",
  margin: "0 0 var(--space-4)",
};

const specimenStyle: CSSProperties = {
  background: "var(--color-neutral-0)",
  border: "1px solid var(--color-neutral-200)",
  borderRadius: "var(--radius-md)",
  padding: "var(--space-4)",
  marginBottom: "var(--space-4)",
};

const specimenTitleStyle: CSSProperties = {
  fontSize: "var(--font-size-sm)",
  fontWeight: "var(--font-weight-medium)",
  color: "var(--color-neutral-600)",
  margin: "0 0 var(--space-3)",
};

const linkStyle: CSSProperties = {
  color: "var(--color-brand-primary)",
  fontSize: "var(--font-size-sm)",
};

/** One specimen alone at a fixed origin — the visual suite's page (see `requestedSpecimen`). */
function SoloSpecimen({ id }: { id: string }) {
  const specimen = ALL_SPECIMENS.find((candidate) => candidate.id === id);
  if (specimen === undefined) {
    // A typo'd id must not render an empty page that screenshots as a valid baseline.
    throw new Error(`workbench: no specimen with id "${id}"`);
  }
  return (
    <div style={pageStyle}>
      <div data-specimen={specimen.id} style={specimenStyle}>
        <p style={specimenTitleStyle}>{specimen.title}</p>
        {specimen.node}
      </div>
    </div>
  );
}

/**
 * What the catalog page shows in place of an `overlay` specimen's node.
 *
 * An overlay specimen renders open, and three of the four ways a framework overlay escapes its
 * box are also hostile to a page holding sixty of them. A `ConfirmDialog` calls `showModal()` and locks
 * `document.body` scroll, so one open dialog makes the whole catalog inert and unscrollable —
 * and that page is exactly what the "every specimen is present exactly once" check reads, and
 * what a person opens to browse. An open `Menu` moves focus to its first item on mount, so
 * several would fight over the caret before a reader had touched anything. Toasts stack in the
 * corner over whatever is behind them. None of that is a problem on the solo page, where
 * `?only=` guarantees one specimen and both lanes already navigate that way.
 *
 * So the entry keeps its card and its `data-specimen` handle — the presence check still counts
 * it, and the link is the fastest route to the thing itself.
 */
function OverlayNotice({ id }: { id: string }) {
  return (
    <p style={{ margin: 0, color: "var(--color-neutral-600)", fontSize: "var(--font-size-sm)" }}>
      Renders open, which a page of fifty specimens cannot hold —{" "}
      <a style={linkStyle} href={`?only=${id}`}>
        open it alone
      </a>
      .
    </p>
  );
}

/**
 * What the catalog shows in place of a specimen that declares a viewport of its own.
 *
 * The same substitution as `OverlayNotice` for a different reason. A viewport specimen exists
 * because some declaration only applies at a width the catalog is not — the shell's mobile
 * variant, the sidebar's shrink between the breakpoint and wide — so rendering it here would
 * paint the desktop composition under a title announcing the narrow one. A reader would take
 * the picture at its word, which is worse than being sent one click away for the real thing.
 */
function ViewportNotice({ id, width, height }: { id: string; width: number; height: number }) {
  return (
    <p style={{ margin: 0, color: "var(--color-neutral-600)", fontSize: "var(--font-size-sm)" }}>
      Renders at {width}×{height}, which this page is not —{" "}
      <a style={linkStyle} href={`?only=${id}`}>
        open it alone
      </a>{" "}
      (and size the window to match).
    </p>
  );
}

function Workbench() {
  const only = requestedSpecimen();
  if (only !== null) {
    return <SoloSpecimen id={only} />;
  }
  return (
    <div style={pageStyle}>
      <header style={headerStyle}>
        <div>
          <h1 style={{ fontSize: "var(--font-size-xl)", margin: 0 }}>
            Terp component workbench
          </h1>
          <p
            style={{
              margin: "var(--space-1) 0 0",
              color: "var(--color-neutral-600)",
              fontSize: "var(--font-size-sm)",
            }}
          >
            {ALL_SPECIMENS.length} specimens across {SPECIMEN_GROUPS.length} groups, rendering
            the <code>{theme}</code> theme.
          </p>
        </div>
        {/* Plain anchors, not a router link and not a toggle: the theme must stay a
            property of the URL so a screenshot is reproducible from it alone. One per
            shipped theme, because comparing them is the point of having more than two. */}
        <nav style={{ display: "flex", flexWrap: "wrap", gap: "var(--space-3)" }}>
          {THEMES.filter((name) => name !== theme).map((name) => (
            <a key={name} style={linkStyle} href={`?theme=${name}`}>
              {name}
            </a>
          ))}
        </nav>
      </header>

      {SPECIMEN_GROUPS.map((group) => (
        <section key={group.id} data-group={group.id} style={{ marginBottom: "var(--space-8)" }}>
          <h2 style={groupTitleStyle}>{group.title}</h2>
          {group.specimens.map((specimen) => (
            // `data-specimen` is the visual suite's handle: it screenshots this element, not
            // the page, so a change to one component fails one baseline and names it.
            <div key={specimen.id} data-specimen={specimen.id} style={specimenStyle}>
              <p style={specimenTitleStyle}>{specimen.title}</p>
              {specimen.overlay === true ? (
                <OverlayNotice id={specimen.id} />
              ) : specimen.viewport !== undefined ? (
                <ViewportNotice id={specimen.id} {...specimen.viewport} />
              ) : (
                specimen.node
              )}
            </div>
          ))}
        </section>
      ))}
    </div>
  );
}

const container = document.getElementById("root");
if (!container) throw new Error("workbench: #root is missing from index.html");
createRoot(container).render(
  <ThemeProvider defaultTheme={theme}>
    <LocaleProvider locales={{ en: LOCALE_EN, nl: LOCALE_NL }} defaultLocale="en">
      <Workbench />
    </LocaleProvider>
  </ThemeProvider>,
);
