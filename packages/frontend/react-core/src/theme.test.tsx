// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { THEME_STORAGE_KEY, ThemeProvider, ThemeToggle } from "./theme";

afterEach(() => {
  cleanup();
  window.localStorage.clear();
  document.documentElement.removeAttribute("data-theme");
  document.documentElement.style.removeProperty("color-scheme");
});

describe("ThemeProvider + ThemeToggle", () => {
  it("defaults to the system theme (no data-theme attribute)", () => {
    render(
      <ThemeProvider>
        <ThemeToggle />
      </ThemeProvider>,
    );
    expect(document.documentElement.hasAttribute("data-theme")).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "Theme" }));
    expect(screen.getByRole("menuitemradio", { name: "System" })).toHaveAttribute("aria-checked", "true");
  });

  it("applies an explicit choice to <html data-theme> and persists it", () => {
    render(
      <ThemeProvider>
        <ThemeToggle />
      </ThemeProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Theme" }));
    fireEvent.click(screen.getByRole("menuitemradio", { name: "Dark" }));
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe("dark");
  });

  it("hands back the pre-paint bootstrap's inline color-scheme", () => {
    // `public/theme-bootstrap.js` stamps the stored palette on <html> before the first paint
    // and declares its appearance inline with it, because in a dev server the token sheet
    // arrives with the bundle and the attribute alone has no palette to paint from. Inline
    // is what makes that work and also what makes it a loan: a style attribute outranks
    // every rule in every layer, so a viewer who loaded on a dark palette and then chose a
    // light one would keep dark scrollbars, a dark caret and a dark select popup for the
    // rest of the session, on a page that is no longer dark.
    document.documentElement.setAttribute("data-theme", "dark");
    document.documentElement.style.colorScheme = "dark";
    window.localStorage.setItem(THEME_STORAGE_KEY, "dark");

    render(
      <ThemeProvider>
        <ThemeToggle />
      </ThemeProvider>,
    );
    // Taken back on mount, while the palette it described is still the live one — so the
    // token sheet's own per-theme declaration is what governs from here.
    expect(document.documentElement.style.getPropertyValue("color-scheme")).toBe("");
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");

    // And it does not come back when the choice changes, which is the case it exists for.
    fireEvent.click(screen.getByRole("button", { name: "Theme" }));
    fireEvent.click(screen.getByRole("menuitemradio", { name: "Light" }));
    expect(document.documentElement.getAttribute("data-theme")).toBe("light");
    expect(document.documentElement.style.getPropertyValue("color-scheme")).toBe("");
  });

  it("applies a named theme beyond light and dark", () => {
    // The named themes are the reason the semantic token layer exists. They are compiled,
    // contrast-gated and published, and none of that reaches a user unless the control can
    // actually pin one — so the whole path is exercised for one of them.
    render(
      <ThemeProvider>
        <ThemeToggle />
      </ThemeProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Theme" }));
    fireEvent.click(screen.getByRole("menuitemradio", { name: "Midnight" }));
    expect(document.documentElement.getAttribute("data-theme")).toBe("midnight");
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe("midnight");
  });

  it("offers every shipped theme, not only light and dark", () => {
    // `theme.themes.test.ts` proves the list matches the contract's; this proves the list
    // reaches the menu, which is a different failure — a name in `THEMES` that never renders.
    render(
      <ThemeProvider>
        <ThemeToggle />
      </ThemeProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Theme" }));
    for (const label of ["Light", "Dark", "Midnight", "Twilight", "High contrast", "System"]) {
      expect(screen.getByRole("menuitemradio", { name: label })).toBeInTheDocument();
    }
  });

  it("accepts a named theme as the app default", () => {
    // How an app ships on a named theme: one prop, no other change anywhere.
    render(
      <ThemeProvider defaultTheme="contrast">
        <ThemeToggle />
      </ThemeProvider>,
    );
    expect(document.documentElement.getAttribute("data-theme")).toBe("contrast");
  });

  it("restores a persisted choice over the app default", () => {
    window.localStorage.setItem(THEME_STORAGE_KEY, "light");
    render(
      <ThemeProvider defaultTheme="dark">
        <ThemeToggle />
      </ThemeProvider>,
    );
    expect(document.documentElement.getAttribute("data-theme")).toBe("light");
  });

  it("restores a persisted SYSTEM choice over the app default", () => {
    // The one stored choice a declared default used to beat. `"system"` is a menu entry a
    // person can pick, and it is stored like any other — so reading it as "nothing stored"
    // put them back on the app's palette on the next load, while the menu reported that
    // palette as active. An app declaring a palette must not be able to overrule a person
    // who asked to follow their own platform.
    window.localStorage.setItem(THEME_STORAGE_KEY, "system");
    render(
      <ThemeProvider defaultTheme="midnight">
        <ThemeToggle />
      </ThemeProvider>,
    );
    expect(document.documentElement.hasAttribute("data-theme")).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "Theme" }));
    expect(screen.getByRole("menuitemradio", { name: "System" })).toBeChecked();
  });

  it("treats a stored theme this build does not ship as no choice at all", () => {
    // A theme removed by an upgrade must not leave a viewer pinned to a `data-theme` value
    // nothing styles — which is what the app's default is for.
    window.localStorage.setItem(THEME_STORAGE_KEY, "sepia");
    render(
      <ThemeProvider defaultTheme="contrast">
        <ThemeToggle />
      </ThemeProvider>,
    );
    expect(document.documentElement.getAttribute("data-theme")).toBe("contrast");
  });

  it("switching back to system removes the attribute (OS preference wins)", () => {
    render(
      <ThemeProvider defaultTheme="dark">
        <ThemeToggle />
      </ThemeProvider>,
    );
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
    fireEvent.click(screen.getByRole("button", { name: "Theme" }));
    fireEvent.click(screen.getByRole("menuitemradio", { name: "System" }));
    expect(document.documentElement.hasAttribute("data-theme")).toBe(false);
  });

  it("ThemeToggle renders nothing outside a ThemeProvider", () => {
    render(<ThemeToggle />);
    expect(screen.queryByLabelText("Theme")).not.toBeInTheDocument();
  });

  it("ignores a corrupt persisted value", () => {
    window.localStorage.setItem(THEME_STORAGE_KEY, "neon");
    render(
      <ThemeProvider>
        <ThemeToggle />
      </ThemeProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Theme" }));
    expect(screen.getByRole("menuitemradio", { name: "System" })).toHaveAttribute("aria-checked", "true");
  });
});
