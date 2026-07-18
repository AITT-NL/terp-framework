import { createContext, useCallback, useContext, useMemo, useState } from "react";
import type { ReactNode } from "react";

import { Icon } from "./icons";
import { Menu, MenuItem } from "./ui/Menu";
import { UiTextProvider, useStrings } from "./uiText";
import type { TerpStrings } from "./uiText";

/**
 * One locale's catalog: per-key overrides of the framework strings (missing keys fall
 * back to the bundled English defaults) plus an optional native display name for
 * language pickers. `{}` is a valid catalog — English needs no overrides.
 */
export interface LocaleCatalog {
  /** Native display name shown by {@link LanguageSwitcher} (default: the locale code). */
  label?: string;
  /** Framework-string overrides for this locale. */
  strings?: Partial<TerpStrings>;
}

/** The built-in English catalog — the bundled defaults, no overrides needed. */
export const LOCALE_EN: LocaleCatalog = { label: "English" };

/**
 * The built-in Dutch catalog: a complete translation of every framework string,
 * so `locales: { en: LOCALE_EN, nl: LOCALE_NL }` localises the whole chrome out
 * of the box (a completeness test pins it to the `TerpStrings` key set).
 */
export const LOCALE_NL: LocaleCatalog = {
  label: "Nederlands",
  strings: {
    loading: "Laden...",
    emptyList: "Nog niets te zien.",
    add: "Toevoegen",
    signOut: "Uitloggen",
    signIn: "Inloggen",
    signingIn: "Bezig met inloggen…",
    email: "E-mailadres",
    password: "Wachtwoord",
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
    errorTitle: "Er is iets misgegaan.",
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
    collapseSidebar: "Zijbalk inklappen",
    expandSidebar: "Zijbalk uitklappen",
    openNavigation: "Navigatie openen",
    closeNavigation: "Navigatie sluiten",
    theme: "Thema",
    themeLight: "Licht",
    themeDark: "Donker",
    themeSystem: "Systeem",
    language: "Taal",
    admin: "Beheer",
    adminUsers: "Gebruikers",
    adminUsersDescription: "Accounts aanmaken, rollen wijzigen, wachtwoorden resetten",
    adminGroups: "Groepen",
    adminGroupsDescription: "Bundel permissies; lidmaatschap past ze toe",
    adminAudit: "Auditlog",
    adminAuditDescription: "Elke wijziging: wat, wie, wanneer",
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
    saved: "Opgeslagen",
    requestFailed: "Het verzoek is mislukt. Probeer opnieuw.",
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
  children: ReactNode;
}

/**
 * The language seam over {@link UiTextProvider}: owns which locale is active, persists
 * the choice in `localStorage`, and feeds the active catalog's string overrides to the
 * `UiText` context — so every react-core component (and every `UiText` prop) follows the
 * switch with no per-component wiring. Adding a language to an app is one catalog entry.
 */
export function LocaleProvider({ locales, defaultLocale, children }: LocaleProviderProps) {
  const codes = Object.keys(locales);
  const fallback = defaultLocale !== undefined && codes.includes(defaultLocale)
    ? defaultLocale
    : codes[0];
  const [locale, setLocaleState] = useState<string>(() => {
    try {
      const stored = window.localStorage.getItem(LOCALE_STORAGE_KEY);
      return stored !== null && codes.includes(stored) ? stored : (fallback ?? "en");
    } catch {
      return fallback ?? "en";
    }
  });

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
      locale,
      locales: codes,
      labelOf: (code) => locales[code]?.label ?? code,
      setLocale,
    }),
    [locale, codes.join("\u0000"), setLocale, locales],
  );

  return (
    <LocaleContext.Provider value={value}>
      <UiTextProvider strings={locales[locale]?.strings}>{children}</UiTextProvider>
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
  const menu = (
    <Menu trigger={<Icon name="globe" size="1.15rem" />} triggerLabel={strings.language}>
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
  if (variant === "inline") {
    return menu;
  }
  return (
    <div style={{ display: "grid", justifyItems: "start", gap: "var(--space-1)", fontSize: "var(--font-size-sm)" }}>
      <span style={{ color: "var(--color-neutral-600)" }}>{strings.language}</span>
      {menu}
    </div>
  );
}
