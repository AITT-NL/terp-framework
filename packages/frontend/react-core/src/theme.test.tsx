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
    expect(screen.getByLabelText("Theme")).toHaveValue("system");
  });

  it("applies an explicit choice to <html data-theme> and persists it", () => {
    render(
      <ThemeProvider>
        <ThemeToggle />
      </ThemeProvider>,
    );
    fireEvent.change(screen.getByLabelText("Theme"), { target: { value: "dark" } });
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe("dark");
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
    fireEvent.change(screen.getByLabelText("Theme"), { target: { value: "system" } });
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
    expect(screen.getByLabelText("Theme")).toHaveValue("system");
  });
});
