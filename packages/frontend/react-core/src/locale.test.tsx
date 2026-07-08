// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { LOCALE_EN, LOCALE_NL, LOCALE_STORAGE_KEY, LanguageSwitcher, LocaleProvider } from "./locale";
import { DEFAULT_STRINGS, useStrings } from "./uiText";

afterEach(() => {
  cleanup();
  window.localStorage.clear();
});

function SignOutLabel() {
  return <p>{useStrings().signOut}</p>;
}

const NL = { label: "Nederlands", strings: { signOut: "Uitloggen", language: "Taal" } };

describe("LocaleProvider + LanguageSwitcher", () => {
  it("feeds the active catalog's overrides through the UiText seam", () => {
    render(
      <LocaleProvider locales={{ en: LOCALE_EN, nl: NL }} defaultLocale="nl">
        <SignOutLabel />
      </LocaleProvider>,
    );
    expect(screen.getByText("Uitloggen")).toBeInTheDocument();
  });

  it("switches locale via the LanguageSwitcher and persists the choice", () => {
    render(
      <LocaleProvider locales={{ en: LOCALE_EN, nl: NL }}>
        <LanguageSwitcher />
        <SignOutLabel />
      </LocaleProvider>,
    );
    expect(screen.getByText("Sign out")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Language"), { target: { value: "nl" } });
    expect(screen.getByText("Uitloggen")).toBeInTheDocument();
    expect(window.localStorage.getItem(LOCALE_STORAGE_KEY)).toBe("nl");
    // The switcher itself follows the active catalog too.
    expect(screen.getByLabelText("Taal")).toBeInTheDocument();
  });

  it("restores a persisted locale and lists native names", () => {
    window.localStorage.setItem(LOCALE_STORAGE_KEY, "nl");
    render(
      <LocaleProvider locales={{ en: LOCALE_EN, nl: NL }}>
        <LanguageSwitcher />
      </LocaleProvider>,
    );
    const select = screen.getByLabelText("Taal");
    expect(select).toHaveValue("nl");
    expect(screen.getByRole("option", { name: "English" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Nederlands" })).toBeInTheDocument();
  });

  it("ignores a persisted locale the app no longer declares", () => {
    window.localStorage.setItem(LOCALE_STORAGE_KEY, "fr");
    render(
      <LocaleProvider locales={{ en: LOCALE_EN, nl: NL }}>
        <SignOutLabel />
      </LocaleProvider>,
    );
    expect(screen.getByText("Sign out")).toBeInTheDocument();
  });

  it("renders no switcher with a single locale, or outside a provider", () => {
    render(
      <LocaleProvider locales={{ en: LOCALE_EN }}>
        <LanguageSwitcher />
      </LocaleProvider>,
    );
    render(<LanguageSwitcher />);
    expect(screen.queryByLabelText("Language")).not.toBeInTheDocument();
  });

  it("offers an inline variant for the shell header (bare, aria-labelled select)", () => {
    render(
      <LocaleProvider locales={{ en: LOCALE_EN, nl: NL }}>
        <LanguageSwitcher variant="inline" />
      </LocaleProvider>,
    );
    expect(screen.getByLabelText("Language")).toBeInTheDocument();
    // No visible label text in the inline variant.
    expect(screen.queryByText("Language")).not.toBeInTheDocument();
  });
});

describe("LOCALE_NL", () => {
  it("translates every framework string (completeness drift-guard)", () => {
    // A new TerpStrings key without a Dutch translation fails here, so the
    // bundled catalog can never silently fall back to English for new chrome.
    expect(Object.keys(LOCALE_NL.strings ?? {}).sort()).toEqual(
      Object.keys(DEFAULT_STRINGS).sort(),
    );
  });
});
