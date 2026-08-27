// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import {
  LOCALE_EN,
  LOCALE_NL,
  LOCALE_STORAGE_KEY,
  LanguageSwitcher,
  LocaleProvider,
  defineAppLocales,
} from "./locale";
import { DEFAULT_STRINGS, Trans, useStrings } from "./uiText";

afterEach(() => {
  cleanup();
  window.localStorage.clear();
});

function SignOutLabel() {
  return <p>{useStrings().signOut}</p>;
}

const NL = LOCALE_NL;

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
    fireEvent.click(screen.getByRole("button", { name: "Language" }));
    fireEvent.click(screen.getByRole("menuitemradio", { name: "Nederlands" }));
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
    fireEvent.click(screen.getByRole("button", { name: "Taal" }));
    expect(screen.getByRole("menuitemradio", { name: "English" })).toBeInTheDocument();
    expect(screen.getByRole("menuitemradio", { name: "Nederlands" })).toHaveAttribute("aria-checked", "true");
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

  it("offers an icon-only inline variant for the shell header", () => {
    render(
      <LocaleProvider locales={{ en: LOCALE_EN, nl: NL }}>
        <LanguageSwitcher variant="inline" />
      </LocaleProvider>,
    );
    expect(screen.getByRole("button", { name: "Language" })).toBeInTheDocument();
    // No visible label text in the inline variant.
    expect(screen.queryByText("Language")).not.toBeInTheDocument();
  });

  it("resolves app descriptors through the active locale catalog", () => {
    render(
      <LocaleProvider
        locales={{ en: LOCALE_EN, nl: { ...NL, messages: { greeting: "Hallo" } } }}
        defaultLocale="nl"
        sourceLocale="en"
      >
        <Trans id="greeting" message="Hello" />
      </LocaleProvider>,
    );
    expect(screen.getByText("Hallo")).toBeInTheDocument();
  });

  it("refuses a missing target translation instead of silently using source copy", () => {
    expect(() =>
      render(
        <LocaleProvider locales={{ en: LOCALE_EN, nl: NL }} defaultLocale="nl" sourceLocale="en">
          <Trans id="greeting" message="Hello" />
        </LocaleProvider>,
      ),
    ).toThrow(/Missing translation "greeting" for locale "nl"/);
  });

  it("refuses a copied source translation unless allowIdentical documents it", () => {
    expect(() =>
      render(
        <LocaleProvider
          locales={{ en: {}, nl: { ...LOCALE_NL, messages: { greeting: "Hello" } } }}
          defaultLocale="nl"
          sourceLocale="en"
        >
          <Trans id="greeting" message="Hello" />
        </LocaleProvider>,
      ),
    ).toThrow(/copies its source text/);

    render(
      <LocaleProvider
        locales={{
          en: {},
          nl: {
            ...LOCALE_NL,
            messages: { greeting: "Hello" },
            allowIdentical: ["greeting"],
          },
        }}
        defaultLocale="nl"
        sourceLocale="en"
      >
        <Trans id="greeting" message="Hello" />
      </LocaleProvider>,
    );
    expect(screen.getByText("Hello")).toBeInTheDocument();
  });

  it("refuses malformed locale configuration and descriptors", () => {
    expect(() =>
      render(
        <LocaleProvider locales={{ en: {} }} sourceLocale="nl">
          <span />
        </LocaleProvider>,
      ),
    ).toThrow(/Source locale "nl" is not present/);
    expect(() =>
      render(
        <LocaleProvider locales={{ en: {} }} defaultLocale="nl">
          <span />
        </LocaleProvider>,
      ),
    ).toThrow(/Default locale "nl" is not present/);
    expect(() =>
      render(
        <LocaleProvider locales={{ en: {} }}>
          <Trans id="" message="Hello" />
        </LocaleProvider>,
      ),
    ).toThrow(/non-empty id and message/);
  });

  it("merges checked-in app messages with framework catalogs", () => {
    expect(
      defineAppLocales(
        { sourceLocale: "nl", locales: { nl: {}, en: { messages: { greeting: "Hello" } } } },
        { en: LOCALE_EN, nl: LOCALE_NL },
      ).en.messages,
    ).toEqual({ greeting: "Hello" });
  });

  it("validates the checked-in declaration before merging it", () => {
    expect(() =>
      defineAppLocales({ sourceLocale: "nl", locales: { en: {} } }),
    ).toThrow(/Source locale "nl" is not present/);
    expect(() =>
      defineAppLocales({
        sourceLocale: "nl",
        locales: { nl: {}, en: { messages: { greeting: "" } } },
      }),
    ).toThrow(/empty or invalid message entry/);
    expect(() =>
      defineAppLocales(
        { sourceLocale: "en", locales: { en: {} } },
        { en: { strings: [] as never } },
      ),
    ).toThrow(/framework strings must be an object/);
    expect(() =>
      defineAppLocales(
        { sourceLocale: "en", locales: { en: {} } },
        "invalid" as never,
      ),
    ).toThrow(/Framework locale catalogs must be an object/);
  });

  it("refuses incomplete framework catalogs through LocaleProvider itself", () => {
    expect(() =>
      render(
        <LocaleProvider locales={{ en: LOCALE_EN, de: { messages: { greeting: "Hallo" } } }}>
          <span />
        </LocaleProvider>,
      ),
    ).toThrow(/missing .* framework string translation/);
  });

  it("refuses malformed labels and supplied framework strings", () => {
    expect(() =>
      render(
        <LocaleProvider locales={{ en: { label: "" } }}>
          <span />
        </LocaleProvider>,
      ),
    ).toThrow(/label must be a non-empty string/);
    expect(() =>
      render(
        <LocaleProvider
          locales={{ en: { strings: { ...LOCALE_NL.strings, signOut: "" } } }}
        >
          <span />
        </LocaleProvider>,
      ),
    ).toThrow(/empty or invalid framework string "signOut"/);
    expect(() =>
      render(
        <LocaleProvider locales={{ en: { strings: "invalid" as never } }}>
          <span />
        </LocaleProvider>,
      ),
    ).toThrow(/framework strings must be an object/);
  });

  it("refuses a target locale whose app copy is translated but framework chrome is not", () => {
    expect(() =>
      defineAppLocales(
        {
          sourceLocale: "en",
          locales: { en: {}, de: { messages: { greeting: "Hallo" } } },
        },
        { en: LOCALE_EN },
      ),
    ).toThrow(/missing .* framework string translation/);

    const germanStrings = Object.fromEntries(
      Object.keys(DEFAULT_STRINGS).map((key) => [key, `de:${key}`]),
    );
    expect(
      defineAppLocales(
        {
          sourceLocale: "en",
          locales: { en: {}, de: { messages: { greeting: "Hallo" } } },
        },
        { en: LOCALE_EN, de: { strings: germanStrings } },
      ).de.messages,
    ).toEqual({ greeting: "Hallo" });
  });

  it("always renders the descriptor fallback in the source locale", () => {
    render(
      <LocaleProvider
        locales={{ en: { messages: { greeting: "stale catalog value" } } }}
        sourceLocale="en"
      >
        <Trans id="greeting" message="Hello" />
      </LocaleProvider>,
    );
    expect(screen.getByText("Hello")).toBeInTheDocument();
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
