import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";

import { Icon } from "./icons";
import { Menu, MenuItem } from "./ui/Menu";
import { useStrings } from "./uiText";

/**
 * The visual theme: an explicit choice, or "system" to follow the OS preference.
 *
 * The token stylesheet (`@terpjs/contract/tokens.css`) carries every palette: it applies
 * each named theme's colours under `<html data-theme="<name>">` and — with no attribute —
 * applies the dark palette under `@media (prefers-color-scheme: dark)`, so "system" simply
 * removes the attribute.
 *
 * The names are the stylesheet's, so this union is a restatement of a published contract
 * and could drift from it silently — a theme the sheet ships that no app can select, or one
 * this offers that resolves to nothing. `theme.themes.test.ts` holds it against the token
 * manifest. The union is written out rather than derived from the manifest at runtime because
 * react-core publishes unbuilt source and imports nothing but React: resolving a JSON module
 * from a sibling package would add a requirement to every consumer's bundler and tsconfig,
 * which is the consumption-model change the framework spends real effort avoiding.
 */
export type Theme = "light" | "dark" | "midnight" | "twilight" | "contrast" | "system";

const THEMES: readonly Theme[] = [
  "light",
  "dark",
  "midnight",
  "twilight",
  "contrast",
  "system",
];

const THEME_ICONS: Record<Theme, string> = {
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

function readStoredTheme(): Theme {
  try {
    const stored = window.localStorage.getItem(THEME_STORAGE_KEY);
    return THEMES.includes(stored as Theme) ? (stored as Theme) : "system";
  } catch {
    return "system";
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
 * nothing else — since it applies until the user chooses otherwise.
 */
export function ThemeProvider({ defaultTheme = "system", children }: ThemeProviderProps) {
  const [theme, setThemeState] = useState<Theme>(() => {
    const stored = readStoredTheme();
    return stored === "system" ? defaultTheme : stored;
  });

  useEffect(() => {
    const root = document.documentElement;
    if (theme === "system") {
      root.removeAttribute("data-theme");
    } else {
      root.setAttribute("data-theme", theme);
    }
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
