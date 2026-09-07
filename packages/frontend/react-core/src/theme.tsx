import type { IconName } from "@terpjs/contract";
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";

import { Icon } from "./icons";
import { THEMES } from "./themes";
import type { Theme } from "./themes";
import { Menu, MenuItem } from "./ui/Menu";
import { useStrings } from "./uiText";

/**
 * The theme names and the runtime list of them live in `themes.ts`, a leaf module with no
 * React and no DOM, because the layout-declaration resolver needs the same list to refuse a
 * palette an app's checked-in file names — and it must not import this file to get it.
 * Re-exported here so `ThemeProvider`'s own type stays where its props are documented.
 */
export type { Theme } from "./themes";

const THEME_ICONS: Record<Theme, IconName> = {
  light: "sun",
  dark: "moon",
  midnight: "moon-stars",
  twilight: "sunset",
  contrast: "contrast",
  system: "monitor",
};

/** The `localStorage` key {@link ThemeProvider} persists the choice under. */
export const THEME_STORAGE_KEY = "terp.theme";

interface ThemeContextValue {
  theme: Theme;
  setTheme: (theme: Theme) => void;
}

const ThemeContext = createContext<ThemeContextValue | null>(null);

/**
 * The theme this viewer chose, or `null` if they have not chosen one.
 *
 * `null` rather than `"system"` for the absent case, and the distinction is load-bearing.
 * `"system"` is a choice a person can make from the menu — it means "follow my platform" —
 * and it is stored like any other. Collapsing it into the absent case made a declared
 * `defaultTheme` beat it on every reload: the person picked System, the session honoured it,
 * and the next load silently put them back on the app's palette while the menu reported that
 * palette as active. The key documents itself as applying "until a person chooses another",
 * and this was the one choice it could not survive.
 *
 * A stored value this build does not ship also reads as no choice — a theme removed by an
 * upgrade must not leave a viewer pinned to a `data-theme` nothing styles.
 */
function readStoredTheme(): Theme | null {
  try {
    const stored = window.localStorage.getItem(THEME_STORAGE_KEY);
    return THEMES.includes(stored as Theme) ? (stored as Theme) : null;
  } catch {
    return null;
  }
}

export interface ThemeProviderProps {
  /** Starting theme when the user has not chosen one yet; default "system". */
  defaultTheme?: Theme;
  children: ReactNode;
}

/**
 * Owns the theme choice: applies it as `data-theme` on `<html>` (the token stylesheet does
 * the rest — no component changes anywhere) and persists it in `localStorage`.
 * `renderTerpApp` mounts one for every app; pair with {@link ThemeToggle} (the default
 * {@link UserMenu} already includes it).
 *
 * `defaultTheme` is how an app ships on a named theme — `defaultTheme="midnight"` and
 * nothing else — since it applies until the user chooses otherwise, INCLUDING when what they
 * choose is "system". Prefer declaring it in the app's own `frontend/layout-contract.json`,
 * which is the form a tool can read and rewrite.
 */
export function ThemeProvider({ defaultTheme = "system", children }: ThemeProviderProps) {
  const [theme, setThemeState] = useState<Theme>(() => readStoredTheme() ?? defaultTheme);

  useEffect(() => {
    const root = document.documentElement;
    if (theme === "system") {
      root.removeAttribute("data-theme");
    } else {
      root.setAttribute("data-theme", theme);
    }
    // And the pre-paint bootstrap's bridge comes back here.
    //
    // A generated app serves `public/theme-bootstrap.js` blocking in the document head, so a
    // stored choice reaches `<html>` before the first paint instead of arriving with this
    // effect — the reason being that the body is empty until React commits, so the browser
    // has already painted a light canvas by the time this runs. That script also declares
    // `color-scheme` INLINE, because the token sheet is imported by the entry point and in a
    // dev server therefore arrives with the bundle: without it the attribute is right and
    // there is still no palette to paint from.
    //
    // Inline is exactly why it has to be given back. A style attribute outranks every rule
    // in every layer, so the value the bootstrap wrote would go on governing the native
    // chrome for the whole session: pick a light palette after loading on a dark one and the
    // scrollbars, the caret and the select popup stay dark, against a page that is not.
    // Removing it hands `color-scheme` back to the theme blocks in the token sheet, which is
    // where it is declared per palette. A no-op on every load after the first.
    root.style.removeProperty("color-scheme");
  }, [theme]);

  const setTheme = useCallback((next: Theme) => {
    setThemeState(next);
    try {
      window.localStorage.setItem(THEME_STORAGE_KEY, next);
    } catch {
      // Private mode / quota: the choice still applies for this session.
    }
  }, []);

  const value = useMemo(() => ({ theme, setTheme }), [theme, setTheme]);
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

/** The active theme + setter, or `null` outside a {@link ThemeProvider}. */
export function useTheme(): ThemeContextValue | null {
  return useContext(ThemeContext);
}

export interface ThemeToggleProps {
  /**
   * `"stacked"` (default) renders a labelled icon menu for settings panels;
   * `"inline"` renders only the compact icon trigger used by the shell header.
   */
  variant?: "stacked" | "inline";
}

/**
 * The standard theme control: a token-themed menu over every shipped theme plus "system".
 * Renders nothing outside a {@link ThemeProvider}, so shared chrome (the shell header) can
 * include it unconditionally.
 */
export function ThemeToggle({ variant = "stacked" }: ThemeToggleProps) {
  const context = useTheme();
  const strings = useStrings();
  if (context === null) {
    return null;
  }
  const labels: Record<Theme, string> = {
    light: strings.themeLight,
    dark: strings.themeDark,
    midnight: strings.themeMidnight,
    twilight: strings.themeTwilight,
    contrast: strings.themeContrast,
    system: strings.themeSystem,
  };
  // Hoisted out of the attribute rather than inlined as `variant === "inline"`, and not for
  // readability: the marker inventory scanner reads every string literal inside a
  // `data-terp={…}` expression as a marker, so the comparison's own "inline" was picked up as
  // a component marker that nothing styles. Keep marker expressions to marker literals.
  const isInline = variant === "inline";
  const menu = (
    <Menu
      // The rendered root of the inline variant IS this Menu's popover wrapper — the
      // component adds no element of its own — so the marker has to travel through Menu to
      // land there. Both variants wear the same name because they are the same component;
      // data-variant is what tells them apart.
      // Claim the root ONLY when this Menu is the root, which is the inline variant. The
      // stacked variant renders its own div and puts the menu inside it, so stamping the
      // same marker unconditionally put it on BOTH elements — and the inner wrapper then
      // matched the stacked grid rule instead of the popover wrapper's geometry. The
      // baselines did not catch that: a one-child grid and a one-child inline-flex box
      // shrink-wrap to the same pixels, so it was wrong and invisible at the same time.
      data-terp={isInline ? "theme-toggle" : undefined}
      data-variant={isInline ? "inline" : undefined}
      // Unconditional, unlike the root marker: the panel is the same panel in both variants, so
      // a rule for it must reach both. Deriving the owner from the conditional root marker made
      // this panel "theme-toggle" when inline and "popover" when stacked.
      data-owner="theme-toggle"
      trigger={<Icon name={THEME_ICONS[context.theme]} size="1.15rem" />}
      triggerLabel={strings.theme}
    >
      {({ close }) => (
        <>
          {THEMES.map((theme) => (
            <MenuItem
              key={theme}
              label={labels[theme]}
              icon={<Icon name={THEME_ICONS[theme]} />}
              selected={theme === context.theme}
              onSelect={() => {
                context.setTheme(theme);
                close(true);
              }}
            />
          ))}
        </>
      )}
    </Menu>
  );
  if (isInline) {
    return menu;
  }
  return (
    <div data-terp="theme-toggle" data-variant="stacked">
      <span data-terp="theme-toggle-label">{strings.theme}</span>
      {menu}
    </div>
  );
}
