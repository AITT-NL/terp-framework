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
import { DEFAULT_STRINGS, Trans, usePlural, useStrings } from "./uiText";

afterEach(() => {
  cleanup();
  window.localStorage.clear();
  document.documentElement.removeAttribute("lang");
});

function SignOutLabel() {
  return <p>{useStrings().signOut}</p>;
}

const NL = LOCALE_NL;

/**
 * A complete framework catalog for *code* whose every value names its key: a plain string for
 * a plain key, and a count-bearing key in exactly the plural forms *code* uses.
 */
function completeCatalog(code: string, keys: readonly string[] = Object.keys(DEFAULT_STRINGS)) {
  const categories = new Intl.PluralRules(code).resolvedOptions().pluralCategories;
  return Object.fromEntries(
    keys.map((key) => [
      key,
      typeof DEFAULT_STRINGS[key as keyof typeof DEFAULT_STRINGS] === "string"
        ? `${code}:${key}`
        : Object.fromEntries(categories.map((category) => [category, `${code}:${key}:${category}`])),
    ]),
  );
}

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

    const germanStrings = completeCatalog("de");
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

  it("keeps <html lang> on the active locale, from mount and across a switch", () => {
    // A value neither locale has, so the assertion can only pass if the provider wrote it:
    // starting from "en" would let an effect that never ran pass the English half.
    document.documentElement.lang = "x-stale";
    render(
      <LocaleProvider locales={{ en: LOCALE_EN, nl: NL }} defaultLocale="nl">
        <LanguageSwitcher />
      </LocaleProvider>,
    );
    expect(document.documentElement.lang).toBe("nl");

    fireEvent.click(screen.getByRole("button", { name: "Taal" }));
    fireEvent.click(screen.getByRole("menuitemradio", { name: "English" }));
    expect(document.documentElement.lang).toBe("en");
  });

  it("refuses a catalog that translates the shell but not DataView", () => {
    // The upgrade path, pinned: a catalog complete against the key set before DataView's
    // strings joined it. Refused, and by name, because the alternative is the defect itself —
    // every table in the app back in English under a locale that claims to be complete.
    const shellOnly = completeCatalog(
      "de",
      Object.keys(DEFAULT_STRINGS).filter((key) => !key.startsWith("dataView")),
    );
    expect(() =>
      render(
        <LocaleProvider locales={{ en: LOCALE_EN, de: { strings: shellOnly } }}>
          <span />
        </LocaleProvider>,
      ),
    ).toThrow(/missing .* framework string translation.*dataViewSearchPlaceholder/);
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

describe("count-bearing framework strings", () => {
  // The check at render is structural: which categories a language uses comes from the
  // runtime's ICU data, which differs between browsers, so a check against it would pass a
  // catalog in one browser and blank the app in another. The shipped catalogs are held to
  // their languages' categories below, by tests that run where the ICU is fixed.
  function refuse(code: string, key: string, translated: unknown): () => void {
    return () =>
      render(
        <LocaleProvider
          locales={{ en: LOCALE_EN, [code]: { strings: { ...completeCatalog(code), [key]: translated } } }}
        >
          <span />
        </LocaleProvider>,
      );
  }

  function Range({ count }: { count: number }) {
    const plural = usePlural();
    return <p>{plural(useStrings().dataViewResultsRange, count)}</p>;
  }

  it("refuses a single string where the key takes a form per category", () => {
    expect(refuse("nl", "dataViewResultsRange", "{from}–{to} van {total} resultaten")).toThrow(
      /Locale "nl" framework string "dataViewResultsRange" counts something, so it takes one form per plural category/,
    );
  });

  it("refuses a catalog with no other form, or an empty form", () => {
    expect(refuse("nl", "accessUnexplainedRoutes", { one: "{count} actie" })).toThrow(
      /"accessUnexplainedRoutes" has no "other" form, which every language uses/,
    );
    expect(refuse("nl", "accessUnexplainedRoutes", { one: " ", other: "{count} acties" })).toThrow(
      /"accessUnexplainedRoutes" has no "one" form/,
    );
  });

  it("refuses a form named by something that is not a plural category", () => {
    expect(
      refuse("nl", "dataViewSelectAllResults", { one: "a", plural: "b", other: "c" }),
    ).toThrow(/"dataViewSelectAllResults" has a "plural" form, which is not a plural category/);
  });

  it("accepts a form the runtime's plural data does not select, and answers a missing one with other", () => {
    // French is one/other on some engines and one/many/other on newer ones: a catalog written
    // for either must work on both, so a stray category is harmless and a missing one falls
    // back. Here: Polish four is "few", which the catalog does not have.
    render(
      <LocaleProvider
        locales={{
          en: LOCALE_EN,
          pl: {
            strings: {
              ...completeCatalog("pl"),
              dataViewResultsRange: { one: "jeden", zero: "zero", other: "inne" },
            },
          },
        }}
        defaultLocale="pl"
      >
        <Range count={4} />
      </LocaleProvider>,
    );
    expect(screen.getByText("inne")).toBeInTheDocument();
  });

  it("refuses a locale code that is not a language tag, before anything renders a count", () => {
    // `Intl.PluralRules` throws on `en_US`, so without this the first DataView on the page
    // would fail with a RangeError instead of the app being told what to write.
    expect(() =>
      render(
        <LocaleProvider locales={{ en_US: LOCALE_EN }}>
          <span />
        </LocaleProvider>,
      ),
    ).toThrow(/Locale "en_US" is not a language tag \(BCP 47: "en-US", not "en_US"\)/);
  });

  it("chooses the form by the active locale's rules, not English's", () => {
    // Four is "few" in Polish and "other" in English, so this fails if LocaleProvider stops
    // handing its locale to the UiText seam. Dutch could not show it: for every integer, Dutch
    // and English choose the same form.
    render(
      <LocaleProvider
        locales={{ en: LOCALE_EN, pl: { strings: completeCatalog("pl") } }}
        defaultLocale="pl"
      >
        <Range count={4} />
      </LocaleProvider>,
    );
    expect(screen.getByText("pl:dataViewResultsRange:few")).toBeInTheDocument();
  });
});

describe("LOCALE_NL", () => {
  it("writes each count-bearing string in exactly the plural forms its language uses", () => {
    // The per-language half of the plural check, run where the ICU data is fixed rather than
    // in whatever browser renders the catalog. English is the defaults; Dutch is this catalog.
    const counted = Object.keys(DEFAULT_STRINGS).filter(
      (key) => typeof DEFAULT_STRINGS[key as keyof typeof DEFAULT_STRINGS] !== "string",
    );
    expect(counted.length).toBeGreaterThan(0);
    for (const [code, table] of [
      ["en", DEFAULT_STRINGS],
      ["nl", LOCALE_NL.strings ?? {}],
    ] as const) {
      const categories = [...new Intl.PluralRules(code).resolvedOptions().pluralCategories].sort();
      for (const key of counted) {
        const forms = (table as Record<string, unknown>)[key] as Record<string, string>;
        expect(Object.keys(forms).sort(), `${code} ${key}`).toEqual(categories);
      }
    }
  });

  it("translates every framework string (completeness drift-guard)", () => {
    // A new TerpStrings key without a Dutch translation fails here, so the
    // bundled catalog can never silently fall back to English for new chrome.
    expect(Object.keys(LOCALE_NL.strings ?? {}).sort()).toEqual(
      Object.keys(DEFAULT_STRINGS).sort(),
    );
  });
});
