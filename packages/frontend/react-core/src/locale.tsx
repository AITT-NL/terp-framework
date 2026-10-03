import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import type { UiText } from "@terpjs/contract";

import { Icon } from "./icons";
import { Menu, MenuItem } from "./ui/Menu";
import { assertPluralShape, DEFAULT_STRINGS, UiTextProvider, useStrings } from "./uiText";
import type { TerpStrings } from "./uiText";

/**
 * One locale's catalog: framework strings, app messages, and an optional native display
 * name for language pickers. English locales may omit `strings` because react-core's
 * bundled defaults are English; every declared non-English locale must supply the complete
 * `TerpStrings` set so framework chrome cannot silently fall back to English.
 */
export interface LocaleCatalog {
  /** Native display name shown by {@link LanguageSwitcher} (default: the locale code). */
  label?: string;
  /** Framework-string overrides for this locale. */
  strings?: Partial<TerpStrings>;
  /** App-authored messages, keyed by the stable id carried by a `UiText` descriptor. */
  messages?: Record<string, string>;
  /** Message ids intentionally identical to their source copy (catalog-gate documentation). */
  allowIdentical?: readonly string[];
}

/** Checked-in, JSON-compatible app declaration consumed by {@link defineAppLocales}. */
export interface AppI18nDeclaration {
  sourceLocale: string;
  locales: Record<string, LocaleCatalog>;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/**
 * Refuse a locale code the runtime cannot read as a language tag.
 *
 * A code chooses a plural form through `Intl.PluralRules`, which throws on a code that is not
 * a BCP 47 tag — `en_US` rather than `en-US` — and it is written to `<html lang>`, which needs
 * one too. Refused here, with the spelling to use, rather than as a `RangeError` the first
 * time a page renders a count.
 */
function assertLanguageTag(code: string): void {
  try {
    new Intl.PluralRules(code);
  } catch {
    throw new Error(
      `Locale "${code}" is not a language tag (BCP 47: "en-US", not "en_US"). Its plural ` +
        "rules and <html lang> both need one.",
    );
  }
}

function assertLocaleCatalogs(
  locales: unknown,
  sourceLocale?: string,
): asserts locales is Record<string, LocaleCatalog> {
  if (!isRecord(locales) || Object.keys(locales).length === 0) {
    throw new Error("Locale catalogs must declare at least one locale.");
  }
  if (
    sourceLocale !== undefined &&
    (sourceLocale.trim() === "" || !Object.hasOwn(locales, sourceLocale))
  ) {
    throw new Error(`Source locale "${sourceLocale}" is not present in the locale catalogs.`);
  }
  for (const [code, value] of Object.entries(locales)) {
    if (code.trim() === "" || !isRecord(value)) {
      throw new Error("Locale entries must be non-empty codes mapped to catalog objects.");
    }
    assertLanguageTag(code);
    if (
      value.label !== undefined &&
      (typeof value.label !== "string" || value.label.trim() === "")
    ) {
      throw new Error(`Locale "${code}" label must be a non-empty string.`);
    }
    if (value.strings !== undefined && !isRecord(value.strings)) {
      throw new Error(`Locale "${code}" framework strings must be an object.`);
    }
    for (const [key, translated] of Object.entries(value.strings ?? {})) {
      if (!Object.hasOwn(DEFAULT_STRINGS, key)) {
        throw new Error(`Locale "${code}" has unknown framework string "${key}".`);
      }
      if (typeof DEFAULT_STRINGS[key as keyof TerpStrings] !== "string") {
        assertPluralShape(`Locale "${code}"`, key, translated);
        continue;
      }
      if (typeof translated !== "string" || translated.trim() === "") {
        throw new Error(`Locale "${code}" has an empty or invalid framework string "${key}".`);
      }
    }
    const messages = value.messages;
    if (messages !== undefined && !isRecord(messages)) {
      throw new Error(`Locale "${code}" messages must be an object.`);
    }
    for (const [id, translated] of Object.entries(messages ?? {})) {
      if (id.trim() === "" || typeof translated !== "string" || translated.trim() === "") {
        throw new Error(`Locale "${code}" has an empty or invalid message entry.`);
      }
    }
    const allowed = value.allowIdentical;
    if (
      allowed !== undefined &&
      (!Array.isArray(allowed) ||
        allowed.some((id) => typeof id !== "string" || id.trim() === ""))
    ) {
      throw new Error(`Locale "${code}" allowIdentical must be an array of non-empty ids.`);
    }
    if (allowed !== undefined && new Set(allowed).size !== allowed.length) {
      throw new Error(`Locale "${code}" allowIdentical contains duplicate ids.`);
    }
    const stale = allowed?.find((id) => typeof messages?.[id] !== "string");
    if (stale !== undefined) {
      throw new Error(`Locale "${code}" allowIdentical names missing message "${stale}".`);
    }
  }
}

function assertFrameworkStringsComplete(locales: Record<string, LocaleCatalog>): void {
  for (const [code, catalog] of Object.entries(locales)) {
    if (code.split("-")[0].toLowerCase() === "en") continue;
    // Present is enough: every value that is present was already held to its shape, a plain
    // string or its locale's plural forms, when the catalogs were checked.
    const missing = Object.keys(DEFAULT_STRINGS).filter(
      (key) => catalog.strings?.[key as keyof TerpStrings] === undefined,
    );
    if (missing.length > 0) {
      throw new Error(
        `Locale "${code}" is missing ${missing.length} framework string translation(s) ` +
          `(for example: ${missing.slice(0, 3).join(", ")}). ` +
          "Pass a complete framework catalog; app messages alone do not translate the shell.",
      );
    }
  }
}

/**
 * Merge app message catalogs with react-core's framework-string catalogs. This keeps one
 * checked-in `i18n.json` authoritative for app copy without duplicating LOCALE_EN/LOCALE_NL.
 */
export function defineAppLocales(
  declaration: AppI18nDeclaration,
  frameworkLocales: Record<string, LocaleCatalog> = {},
): Record<string, LocaleCatalog> {
  if (!isRecord(declaration) || typeof declaration.sourceLocale !== "string") {
    throw new Error("frontend/i18n.json must declare sourceLocale and a locales map.");
  }
  assertLocaleCatalogs(declaration.locales, declaration.sourceLocale);
  if (!isRecord(frameworkLocales)) {
    throw new Error("Framework locale catalogs must be an object.");
  }
  if (Object.keys(frameworkLocales).length > 0) {
    assertLocaleCatalogs(frameworkLocales);
  }
  const merged = Object.fromEntries(
    Object.entries(declaration.locales).map(([code, app]) => {
      const framework = frameworkLocales[code] ?? {};
      return [
        code,
        {
          ...framework,
          ...app,
          strings: { ...framework.strings, ...app.strings },
          messages: { ...framework.messages, ...app.messages },
        },
      ];
    }),
  );
  assertLocaleCatalogs(merged, declaration.sourceLocale);
  assertFrameworkStringsComplete(merged);
  return merged;
}

/** The built-in English catalog — the bundled defaults, no overrides needed. */
export const LOCALE_EN: LocaleCatalog = { label: "English" };

/**
 * The built-in Dutch catalog: a translation of every `TerpStrings` key, so
 * `locales: { en: LOCALE_EN, nl: LOCALE_NL }` translates every string react-core
 * reads from that table — the shell, the packaged admin area and its sidebar
 * entry, every `DataView`'s toolbar and footer, and the wording for the platform's
 * own error codes — with no catalog work in the app (a completeness test pins it to
 * the `TerpStrings` key set).
 */
export const LOCALE_NL: LocaleCatalog = {
  label: "Nederlands",
  strings: {
    clearSelection: "Selectie wissen",
    clearAllSelections: "Alle selecties wissen",
    comboboxRemove: "Verwijderen",
    comboboxLoading: "Laden…",
    comboboxNoOptions: "Geen opties",
    previousMonth: "Vorige maand",
    selectDate: "Kies een datum",
    selectDateRange: "Kies een periode",
    nextMonth: "Volgende maand",
    loading: "Laden...",
    emptyList: "Nog niets te zien.",
    add: "Toevoegen",
    signOut: "Uitloggen",
    signIn: "Inloggen",
    signingIn: "Bezig met inloggen…",
    email: "E-mailadres",
    password: "Wachtwoord",
    showPassword: "Wachtwoord tonen",
    hidePassword: "Wachtwoord verbergen",
    signInFailed: "Inloggen mislukt. Controleer je gegevens.",
    fillDevCredentials: "Vul dev-inloggegevens in",
    continueWith: "Doorgaan met",
    orSeparator: "of",
    ssoFailed: "Single sign-on mislukt. Probeer het opnieuw.",
    uploadFile: "Bestand uploaden",
    uploading: "Uploaden…",
    unauthorized: "Je hebt geen toegang tot deze pagina.",
    breadcrumbsLabel: "Kruimelpad",
    moduleNavigationLabel: "Modulenavigatie",
    moreActions: "Meer acties",
    pageSequencePrevious: "Vorige: {label}",
    pageSequenceNext: "Volgende: {label}",
    pageSequencePosition: "{current} van {total}",
    statFavourable: "gunstig",
    statUnfavourable: "ongunstig",
    statTrend: "Verloop: {points}",
    adminHubTotal: "Totaal",
    statusHistoryRuns: "{label}, oudste eerst: {runs}",
    recordHistory: "Geschiedenis",
    auditActionCreated: "Aangemaakt",
    auditActionUpdated: "Gewijzigd",
    auditActionDeleted: "Verwijderd",
    auditActionDisclosed: "Ingezien",
    errorTitle: "Er is iets misgegaan.",
    backendUnreachableTitle: "De applicatie kan de server niet bereiken.",
    backendUnreachableDescription:
      "Er kwam geen antwoord van de API. Mogelijk start deze nog op, of staat "
      + "hij uit. Vernieuw de pagina zodra hij draait.",
    confirm: "Bevestigen",
    cancel: "Annuleren",
    successTitle: "Gelukt",
    warningTitle: "Let op",
    dismiss: "Sluiten",
    accountMenu: "Accountmenu",
    settings: "Instellingen",
    profile: "Profiel",
    role: "Rol",
    home: "Start",
    primaryNavigationLabel: "Hoofdnavigatie",
    skipToContent: "Naar de inhoud",
    collapseSidebar: "Zijbalk inklappen",
    expandSidebar: "Zijbalk uitklappen",
    openNavigation: "Navigatie openen",
    closeNavigation: "Navigatie sluiten",
    theme: "Thema",
    themeLight: "Middag",
    themeDark: "Avond",
    themeMidnight: "Nacht",
    themeTwilight: "Schemering",
    themeContrast: "Hoog contrast",
    themeSystem: "Systeem",
    language: "Taal",
    admin: "Beheer",
    adminUsers: "Gebruikers",
    adminUsersDescription: "Accounts aanmaken, rollen wijzigen, wachtwoorden resetten",
    adminGroups: "Groepen",
    adminGroupsDescription: "Bundel permissies; lidmaatschap past ze toe",
    adminAudit: "Auditlog",
    adminAuditDescription: "Elke wijziging: wat, wie, wanneer",
    adminAccess: "Toegang",
    adminAccessDescription: "Welke rollen er zijn, en wat elke rol per module mag",
    accessNoRung: "Geen toegang",
    accessAdds: "Extra ten opzichte van de tier eronder",
    accessKindRead: "Bekijken",
    accessKindWrite: "Wijzigen",
    accessKindDelete: "Verwijderen",
    accessAddsNothing: "Niets extra ten opzichte van de tier eronder",
    accessNeverAssignable: "Nooit per module toe te kennen",
    accessNotAssignable: "Niet per module toe te kennen",
    accessUnexplainedRoutes: {
      one: "{count} actie in deze module heeft nog geen omschrijving",
      other: "{count} acties in deze module hebben nog geen omschrijving",
    },
    accessDeclaredOnly:
      "Dit is wat de applicatie vastlegt. Het laat niet zien wie welke rol heeft — open een persoon om dat te zien.",
    moduleAccessTitle: "Toegang per module",
    moduleAccessDescription:
      "Een rol hier geldt in die ene module en verhoogt de toegang, nooit omlaag. Modules die dit niet aanbieden staan er niet bij.",
    moduleAccessNoneAssignable:
      "Geen enkele module in deze applicatie accepteert een eigen rol, dus hier is niets in te stellen.",
    moduleAccessVia: "Hier ook {role}, via {name}",
    moduleAccessStale: "Vastgelegd, maar zonder effect: {reason}",
    moduleAccessFloor: "Overal al {role}, dus alles tot hier verandert niets",
    moduleAccessConfirmTitle: "{role} geven in {module}?",
    moduleAccessConfirm:
      "Dit is de meest verstrekkende rol die de module heeft. Alles van de tier eronder, plus wat op de tegel staat.",
    moduleAccessRevokeTitle: "De rol in {module} weghalen?",
    moduleAccessRevoke:
      "De toegang in deze module valt terug op wat de rol van deze persoon overal geeft.",
    moduleAccessOrphaned:
      "Staat nog op {role} in {module}, dat geen eigen rol meer accepteert. Het heeft geen effect; het weghalen is de enige wijziging die nog kan.",
    statusColumn: "Status",
    createdColumn: "Aangemaakt",
    statusActive: "Actief",
    statusDeactivated: "Gedeactiveerd",
    provisionUser: "Gebruiker aanmaken",
    roleViewer: "Lezer",
    roleEditor: "Redacteur",
    roleAdmin: "Beheerder",
    working: "Bezig…",
    makeRole: "Maak {role}",
    resetPassword: "Wachtwoord resetten",
    newPassword: "Nieuw wachtwoord",
    deactivate: "Deactiveren",
    reactivate: "Heractiveren",
    changeRoleConfirm: "De rol van deze gebruiker wijzigen naar {role}?",
    deactivateUserConfirm: "Dit account deactiveren? Actieve sessies worden ingetrokken.",
    reactivateUserConfirm: "Dit account heractiveren?",
    groupName: "Naam",
    description: "Omschrijving",
    members: "Leden",
    createGroup: "Groep aanmaken",
    deleteGroup: "Groep verwijderen",
    deleteGroupConfirm: "Deze groep verwijderen? Lidmaatschappen en permissies gaan mee.",
    addMember: "Lid toevoegen",
    removeMember: "Verwijderen",
    removeMemberConfirm: "Dit lid uit de groep verwijderen?",
    userField: "Gebruiker",
    userNotFound: "Geen account gevonden met dat e-mailadres.",
    permissions: "Permissies",
    grantPermission: "Permissie toekennen",
    permission: "Permissie",
    revoke: "Intrekken",
    revokeConfirm: "Deze permissie van de groep intrekken?",
    actionColumn: "Actie",
    actorColumn: "Uitvoerder",
    targetColumn: "Doel",
    whenColumn: "Wanneer",
    details: "Details",
    requestLabel: "Verzoek",
    saved: "Opgeslagen",
    requestFailed: "Het verzoek is mislukt. Probeer opnieuw.",
    dataViewSearchPlaceholder: "Zoeken…",
    dataViewClearSearch: "Zoekopdracht wissen",
    dataViewClearFilters: "Filters wissen",
    dataViewViewOptions: "Weergaveopties",
    dataViewColumns: "Kolommen",
    dataViewMoveUp: "Omhoog verplaatsen",
    dataViewMoveDown: "Omlaag verplaatsen",
    dataViewTableView: "Tabelweergave",
    dataViewCardView: "Kaartweergave",
    dataViewPageSize: "Rijen per pagina",
    dataViewResultsRange: {
      one: "{from}–{to} van {total} resultaat",
      other: "{from}–{to} van {total} resultaten",
    },
    dataViewPageOf: "Pagina {page} van {pages}",
    dataViewFirstPage: "Eerste pagina",
    dataViewPreviousPage: "Vorige pagina",
    dataViewNextPage: "Volgende pagina",
    dataViewLastPage: "Laatste pagina",
    dataViewSelectAllPage: "Alle rijen op deze pagina selecteren",
    dataViewSelectRow: "Rij selecteren",
    dataViewSelected: "{count} geselecteerd",
    dataViewSelectAllResults: {
      one: "{total} resultaat selecteren",
      other: "Alle {total} resultaten selecteren",
    },
    dataViewClearSelection: "Selectie wissen",
    dataViewMoreActions: "Meer acties",
    dataViewActions: "Acties",
    dataViewOpenRow: "Details openen: {label}",
    dataViewExpandRow: "Rij uitklappen",
    dataViewCollapseRow: "Rij inklappen",
    dataViewEmpty: "Niets om te tonen.",
    dataViewLoading: "Laden…",
    dataViewRefreshing: "Bijwerken…",
    dataViewErrorTitle: "De gegevens konden niet worden geladen.",
    dataViewResizeColumn: "Kolombreedte aanpassen",
    errorCodeBadRequest: "Het verzoek kon niet worden verwerkt.",
    errorCodeValidationFailed:
      "Sommige velden zijn ongeldig. Controleer het formulier en probeer het opnieuw.",
    errorCodeInvalidToken: "Je sessie is ongeldig. Log opnieuw in.",
    errorCodeAuthenticationRequired: "Log in om verder te gaan.",
    errorCodePermissionDenied: "Je hebt geen toestemming om dit te doen.",
    errorCodeNotFound: "Dit item kon niet worden gevonden.",
    errorCodeConflict:
      "Dit botst met de huidige stand van zaken. Vernieuw de pagina en probeer het opnieuw.",
    errorCodeStaleData:
      "Iemand anders heeft dit item intussen gewijzigd. Vernieuw de pagina en probeer het opnieuw.",
  },
};

/** The `localStorage` key {@link LocaleProvider} persists the choice under. */
export const LOCALE_STORAGE_KEY = "terp.locale";

interface LocaleContextValue {
  locale: string;
  locales: readonly string[];
  labelOf: (locale: string) => string;
  setLocale: (locale: string) => void;
}

const LocaleContext = createContext<LocaleContextValue | null>(null);

export interface LocaleProviderProps {
  /** The app's locales, keyed by BCP-47 code (e.g. `{ en: LOCALE_EN, nl: {...} }`). */
  locales: Record<string, LocaleCatalog>;
  /** Starting locale when the user has not chosen one; default: the first key. */
  defaultLocale?: string;
  /** Locale whose descriptor `message` is the authored fallback; default: the first key. */
  sourceLocale?: string;
  children: ReactNode;
}

/**
 * The language seam over {@link UiTextProvider}: owns which locale is active, persists
 * the choice in `localStorage`, and feeds the active catalog's string overrides to the
 * `UiText` context — so every react-core component (and every `UiText` prop) follows the
 * switch with no per-component wiring. Adding a language to an app is one catalog entry.
 * It also keeps `<html lang>` on the active locale, from mount and across every switch.
 */
export function LocaleProvider({
  locales,
  defaultLocale,
  sourceLocale,
  children,
}: LocaleProviderProps) {
  assertLocaleCatalogs(locales, sourceLocale);
  assertFrameworkStringsComplete(locales);
  const codes = Object.keys(locales);
  if (defaultLocale !== undefined && !codes.includes(defaultLocale)) {
    throw new Error(`Default locale "${defaultLocale}" is not present in the locale catalogs.`);
  }
  const resolvedSourceLocale = sourceLocale ?? codes[0];
  const fallback = defaultLocale ?? codes[0];
  const [locale, setLocaleState] = useState<string>(() => {
    try {
      const stored = window.localStorage.getItem(LOCALE_STORAGE_KEY);
      return stored !== null && codes.includes(stored) ? stored : (fallback ?? "en");
    } catch {
      return fallback ?? "en";
    }
  });
  const activeLocale = codes.includes(locale) ? locale : fallback;

  // The document says which language it is in, and it has to be the language on screen.
  // `index.html` can only declare the default; a reader who picked another one, or a stored
  // choice from an earlier visit, would otherwise have a Dutch interface announced to a screen
  // reader as English and read aloud with English pronunciation throughout (WCAG 3.1.1). An
  // effect rather than a write during render, because an effect never runs on the server:
  // there is no `document` there, and `ssr.test.tsx` renders this provider without one to hold
  // that.
  useEffect(() => {
    document.documentElement.lang = activeLocale;
  }, [activeLocale]);

  const setLocale = useCallback(
    (next: string) => {
      if (!codes.includes(next)) {
        return;
      }
      setLocaleState(next);
      try {
        window.localStorage.setItem(LOCALE_STORAGE_KEY, next);
      } catch {
        // Private mode / quota: the choice still applies for this session.
      }
    },
    [codes.join("\u0000")],
  );

  const value = useMemo<LocaleContextValue>(
    () => ({
      locale: activeLocale,
      locales: codes,
      labelOf: (code) => locales[code]?.label ?? code,
      setLocale,
    }),
    [activeLocale, codes.join("\u0000"), setLocale, locales],
  );

  const resolveText = useCallback(
    (text: UiText): string => {
      if (typeof text === "string") {
        return text;
      }
      if (text.id.trim() === "" || text.message.trim() === "") {
        throw new Error("UiText descriptors require non-empty id and message values.");
      }
      if (activeLocale === resolvedSourceLocale) {
        return text.message;
      }
      const catalog = locales[activeLocale];
      const translated = catalog?.messages?.[text.id];
      if (typeof translated === "string" && translated.trim() !== "") {
        if (translated === text.message && !catalog.allowIdentical?.includes(text.id)) {
          throw new Error(
            `Translation "${text.id}" for locale "${activeLocale}" copies its source text. ` +
              "Translate it or document an intentional proper noun/acronym in allowIdentical.",
          );
        }
        return translated;
      }
      throw new Error(
        `Missing translation "${text.id}" for locale "${activeLocale}". ` +
          "Add it to frontend/i18n.json and run the frontend lint gate.",
      );
    },
    [activeLocale, locales, resolvedSourceLocale],
  );

  return (
    <LocaleContext.Provider value={value}>
      <UiTextProvider
        strings={locales[activeLocale]?.strings}
        resolveText={resolveText}
        locale={activeLocale}
      >
        {children}
      </UiTextProvider>
    </LocaleContext.Provider>
  );
}

/** The active locale + the catalog codes + setter, or `null` outside a {@link LocaleProvider}. */
export function useLocale(): LocaleContextValue | null {
  return useContext(LocaleContext);
}

export interface LanguageSwitcherProps {
  /**
   * `"stacked"` (default) renders a labelled icon menu for settings panels;
   * `"inline"` renders only the compact icon trigger used by the shell header.
   */
  variant?: "stacked" | "inline";
}

/**
 * The standard language control: a token-themed menu over the app's locale catalogs.
 * Renders nothing outside a {@link LocaleProvider} or when only one locale is declared,
 * so shared chrome (the shell header) can include it unconditionally.
 */
export function LanguageSwitcher({ variant = "stacked" }: LanguageSwitcherProps) {
  const context = useLocale();
  const strings = useStrings();
  if (context === null || context.locales.length < 2) {
    return null;
  }
  // Hoisted out of the attribute rather than inlined as `variant === "inline"`, and not for
  // readability: the marker inventory scanner reads every string literal inside a
  // `data-terp={…}` expression as a marker, so the comparison's own "inline" was picked up as
  // a component marker that nothing styles. Keep marker expressions to marker literals.
  const isInline = variant === "inline";
  const menu = (
    <Menu
      // Claim the root ONLY when this Menu is the root, which is the inline variant. The
      // stacked variant renders its own div and puts the menu inside it, so stamping the
      // same marker unconditionally put it on BOTH elements — and the inner wrapper then
      // matched the stacked grid rule instead of the popover wrapper's geometry. The
      // baselines did not catch that: a one-child grid and a one-child inline-flex box
      // shrink-wrap to the same pixels, so it was wrong and invisible at the same time.
      data-terp={isInline ? "language-switcher" : undefined}
      data-variant={isInline ? "inline" : undefined}
      // Unconditional, unlike the root marker: the panel is the same panel in both variants, so
      // a rule for it must reach both. Deriving the owner from the conditional root marker made
      // this panel "language-switcher" when inline and "popover" when stacked.
      data-owner="language-switcher"
      trigger={<Icon name="globe" size="1.15rem" />}
      triggerLabel={strings.language}
    >
      {({ close }) => (
        <>
          {context.locales.map((code) => (
            <MenuItem
              key={code}
              label={context.labelOf(code)}
              selected={code === context.locale}
              onSelect={() => {
                context.setLocale(code);
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
    <div data-terp="language-switcher" data-variant="stacked">
      <span data-terp="language-switcher-label">{strings.language}</span>
      {menu}
    </div>
  );
}
