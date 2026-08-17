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

import { ALL_SPECIMENS, SPECIMEN_GROUPS } from "./specimens";

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
// The theme comes from `?theme=light|dark`, applied to `<html>` directly rather than through
// `ThemeProvider`. That is for the visual suite: the provider persists to localStorage, so a
// toggled theme would leak between runs and make a baseline depend on run order. A URL that
// fully determines the render is the whole trick.

const THEMES = ["light", "dark"] as const;
type Theme = (typeof THEMES)[number];

/** The requested theme, defaulting to light for a bare visit. */
function requestedTheme(): Theme {
  const value = new URLSearchParams(window.location.search).get("theme");
  return THEMES.includes(value as Theme) ? (value as Theme) : "light";
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

function Workbench() {
  const other: Theme = theme === "light" ? "dark" : "light";
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
        {/* A plain anchor, not a router link and not a toggle: the theme must stay a
            property of the URL so a screenshot is reproducible from it alone. */}
        <a style={linkStyle} href={`?theme=${other}`}>
          Switch to {other}
        </a>
      </header>

      {SPECIMEN_GROUPS.map((group) => (
        <section key={group.id} data-group={group.id} style={{ marginBottom: "var(--space-8)" }}>
          <h2 style={groupTitleStyle}>{group.title}</h2>
          {group.specimens.map((specimen) => (
            // `data-specimen` is the visual suite's handle: it screenshots this element, not
            // the page, so a change to one component fails one baseline and names it.
            <div key={specimen.id} data-specimen={specimen.id} style={specimenStyle}>
              <p style={specimenTitleStyle}>{specimen.title}</p>
              {specimen.node}
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
