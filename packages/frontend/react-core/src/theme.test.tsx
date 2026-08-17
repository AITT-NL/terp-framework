// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { THEME_STORAGE_KEY, ThemeProvider, ThemeToggle } from "./theme";

afterEach(() => {
  cleanup();
  window.localStorage.clear();
  document.documentElement.removeAttribute("data-theme");
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
