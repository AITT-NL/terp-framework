# 0153 — Framework copy is one table, and the document says its language

- **Status:** Accepted and implemented. DataView's strings are `dataView*` keys of
  `TerpStrings`, and the wording for the platform's own error codes is `errorCode*` keys,
  all translated by `LOCALE_NL` and required of every non-English catalog; `LocaleProvider`
  keeps `<html lang>` on the active locale. Held by `locale.test.tsx`,
  `dataview/DataView.test.tsx`, `errorMessages.test.tsx`, `admin/admin.test.tsx`,
  `ssr.test.tsx` and `uiText.literals.test.ts` in `@terpjs/react-core`, and by
  `tests/architecture/test_template.py`.
- **Date:** 2026-09-27
- **Relates:** [ADR 0105](0105-localization-is-a-checked-contract.md) (framework chrome is
  `TerpStrings`, and a non-English locale supplies all of it or is refused — the rule this
  closes a hole in), [ADR 0103](0103-the-ideology-one-pattern-enforced-escapable-by-proof.md)
  (one pattern, enforced), [ADR 0112](0112-the-palette-is-on-the-document-before-the-first-paint.md)
  (the same split for the palette: the document declares the default, a provider owns it from
  mount)

---

## Context

ADR 0105 made framework chrome a checked contract. Every string react-core renders by itself
is a `TerpStrings` key; `LocaleCatalog.strings` is typed against that table; and both
`defineAppLocales` and `LocaleProvider` refuse a declared non-English locale whose catalog
leaves a key out, so an interface cannot come up half in English.

DataView was outside the table. Its strings were a separate `DataViewStrings` set with an
object of English defaults beside it, and the provider every DataView part read merged those
defaults with the per-instance `strings` prop and nothing else. So a locale catalog had no
typed place to put a DataView translation, the completeness check walked a table the strings
were not in, and the source scan that guards against untranslatable literals read the defaults
object line by line without a finding, because it looked for attribute values and `=`
defaults and a table entry is `key: "value"`. Under a Dutch locale every DataView rendered
"Search…", "Rows per page" and "1–20 of 45 results" — the framework's own users, groups and
audit screens included — while `LOCALE_NL`'s doc comment said it localised the whole chrome
and every gate agreed.

The parts were worse off than the whole. `DataViewToolbar`, `DataViewPagination` and the rest
are exported for hand-built compositions, and outside a `DataView` nothing provides the
context, so they read its default value: the English set, with a resolver that did not
consult the locale at all.

Looking for the same shape elsewhere found two more. The wording for the platform's own
error codes — `permission_denied`, `stale_data` and the rest — was `DEFAULT_ERROR_MESSAGES`,
an exported map of English strings that was the default value of its context; a plain string
resolves as-is, so every locale showed the English. And the audit screen's expanded row
labelled the request id with a literal written into the screen.

Separately, nothing set the document's language. `LocaleProvider` switched every string and
left `<html lang>` as the static file declared it, and the template's file declared `en`
while the template's own `i18n.json` puts `nl` first — the locale a generated app opens in.
A screen reader told the page is English reads a Dutch interface with English pronunciation
from start to finish, which is WCAG 3.1.1 (Language of Page) failed by default.

## Decision

1. **A string the framework renders by itself is a `TerpStrings` key.** DataView's join the
   table under a `dataView` prefix — `dataViewSearchPlaceholder`, `dataViewResultsRange` —
   the convention the table already uses for `combobox*`, `admin*` and `access*`. Keys that
   look like existing ones (`loading`, `errorTitle`, `moreActions`, `clearSelection`) stay
   separate: the English already differs, and a translation may want to. The error-code
   wording joins as `errorCode*` (`errorCodeStaleData`), read by `useErrorMessage` beneath
   whatever an app's `errorMessages` map says, so an app still overrides a platform code; the
   audit label joins as `requestLabel`.
2. **`DataViewStrings` stays, as the per-instance override and nothing more.** A DataView
   reads its defaults from the active `TerpStrings`, and its `strings` prop still wins over
   the locale for the keys it names. The context carries only those overrides, so it has no
   default string set to go stale, and a part rendered outside a `DataView` reads the locale
   exactly as one inside does.
3. **English defaults live once, in `DEFAULT_STRINGS`.** `DEFAULT_DATA_VIEW_STRINGS` and
   `DEFAULT_ERROR_MESSAGES` are removed rather than derived. Nothing in the tree read either
   except to seed its own context, and an English-only default set exported for callers is an
   invitation to the defect itself: anything built on it as a fallback renders English under
   every locale.
4. **The literal scan reads a table as well as a default.** A `key: "Literal"` whose key the
   same file declares as `UiText` fails `uiText.literals.test.ts`, the same as `key =
   "Literal"` already did. Put back, the removed DataView defaults object fails it. The scan
   is per file, so it would not have caught the error map (keyed by code, not by declared
   `UiText` names) or the audit label (whose `UiText` type is declared in `DetailList`); those
   two are held by behaviour tests under the Dutch catalog instead.
5. **`LocaleProvider` owns `<html lang>`.** An effect writes the active locale on mount and on
   every switch. An effect because it never runs on the server, where there is no `document`
   — which also makes a `typeof document` guard inside it a branch nothing can reach, so there
   is none; `ssr.test.tsx` renders the provider without a document to hold the placement.
6. **The static document declares the locale the app opens in.** That is what a reader meets
   before the bundle runs. The template's is `nl` and the example's `en`, each the first
   locale its `i18n.json` declares, and `test_template.py` holds both documents to that.

## Deliberately not in it

- **The admin area's sidebar entry.** Its label is a literal in the packaged module's
  manifest, and a manifest label is `UiText` resolved like an app's own: a descriptor's
  `message` is taken to be in the app's source locale, which framework English is not in an
  app whose source locale is Dutch. A framework-owned navigation label needs a decision about
  the manifest contract of its own; it is not made here, so under a Dutch locale that one
  entry still reads "Admin".
- **Restoring the previous `lang` on unmount.** The provider wraps the application for its
  whole life, like `ThemeProvider`, which does not restore `data-theme` either.
- **Choosing the language from the browser.** The app's catalog decides which locales exist
  and which one opens; `lang` reports that decision and does not make one.

## Consequences

- **A non-English catalog of an app's own must translate the new keys** — `dataView*`,
  `errorCode*` and `requestLabel`. One written against the previous table is refused by
  `defineAppLocales` and `LocaleProvider`, naming the missing keys. That is the rule ADR 0105
  already states, applied to strings that were escaping it, and it is the alternative to
  shipping the defect in every such app.
- An app on the built-in `LOCALE_NL` needs no change: it translates the new keys.
- `DEFAULT_DATA_VIEW_STRINGS` and `DEFAULT_ERROR_MESSAGES` are gone from the public surface.
  Their values are `DEFAULT_STRINGS.dataView*` and `DEFAULT_STRINGS.errorCode*`.
- An app that mapped a platform error code only to see it in its own language can drop that
  entry; one that maps it for different wording keeps it, and it still wins.
- A standalone DataView part now resolves `UiText` through the app's resolver and reads the
  app's locale, where it used to do neither.
- A generated app's document opens as `nl`. An existing project keeps the `index.html` it was
  generated with, so its `<html lang>` is corrected at mount but stays wrong until the bundle
  runs unless the project sets it to its own first locale.
