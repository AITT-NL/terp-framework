import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";

import { Icon } from "./icons";
import { Menu, MenuItem } from "./ui/Menu";
import { useStrings } from "./uiText";

/**
 * The visual theme: an explicit choice, or "system" to follow the OS preference.
 * The token stylesheet (`@terpjs/contract/tokens.css`) carries both palettes: it applies
 * the dark colours under `<html data-theme="dark">` and — with no attribute — under
 * `@media (prefers-color-scheme: dark)`, so "system" simply removes the attribute.
 */
export type Theme = "light" | "dark" | "system";

const THEMES: readonly Theme[] = ["light", "dark", "system"];
const THEME_ICONS: Record<Theme, string> = {
  light: "sun",
  dark: "moon",
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
 * Owns the light/dark theme choice: applies it as `data-theme` on `<html>` (the token
 * stylesheet does the rest — no component changes anywhere) and persists it in
 * `localStorage`. `renderTerpApp` mounts one for every app; pair with {@link ThemeToggle}
 * (the default {@link UserMenu} already includes it).
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
 * The standard theme control: a token-themed light/dark/system menu. Renders nothing
 * outside a {@link ThemeProvider}, so shared chrome (the shell header) can
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
    system: strings.themeSystem,
  };
  const menu = (
    <Menu
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
  if (variant === "inline") {
    return menu;
  }
  return (
    <div style={{ display: "grid", justifyItems: "start", gap: "var(--space-1)", fontSize: "var(--font-size-sm)" }}>
      <span style={{ color: "var(--color-neutral-600)" }}>{strings.theme}</span>
      {menu}
    </div>
  );
}
