# 0153 — Framework copy is one table, and the document says its language

- **Status:** Accepted and implemented. DataView's strings are `dataView*` keys of
  `TerpStrings`, and the wording for the platform's own error codes is `errorCode*` keys,
  all translated by `LOCALE_NL` and required of every non-English catalog; `LocaleProvider`
  keeps `<html lang>` on the active locale; a packaged module's nav label names its
  `TerpStrings` key through the contract's `FrameworkText`. Held by `locale.test.tsx`,
  `dataview/DataView.test.tsx`, `errorMessages.test.tsx`, `admin/admin.test.tsx`,
  `ssr.test.tsx`, `uiText.test.tsx` and `uiText.literals.test.ts` in `@terpjs/react-core`, by
  `i18n.test.js` in `@terpjs/eslint-boundaries`, and by `tests/architecture/test_template.py`.
- **Date:** 2026-09-27
- **Amended:** 2026-09-28 — framework copy on a manifest (§7), which the record first left
  out.
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
7. **Amended 2026-09-28: framework copy on a manifest names its key.** This record first left
   the admin area's sidebar entry out. Its label was a literal in the packaged module's
   manifest, and a manifest is `@terpjs/contract` data, typed like an app's, whose only text
   type was `UiText`. Neither form of it fits framework copy. A string renders as-is in every
   locale. A `{ id, message }` descriptor takes its `message` as the app's source-locale text,
   so in an app whose source locale is Dutch the entry, opened in Dutch, would render the
   framework's English without consulting any catalog; and in every other locale its
   translation would have to sit in the app's own messages — framework copy in a catalog the
   app owns.

   So the contract gains `FrameworkText`, `{ framework: key }`, and `NavItem.label` accepts it
   beside `UiText`. It carries a key and no text. The key's type is `TerpFrameworkStrings`,
   an interface the contract leaves empty and react-core merges `TerpStrings` into — the
   declaration-merging shape `TerpAccessVocabulary` already uses, because a stack-agnostic
   contract cannot know a stack's table — so a misspelt key is a typecheck error at the
   manifest, and for a near miss (`"admn"`) TypeScript suggests the key that was meant.
   `useUiText` answers a `FrameworkText` from the same table `useStrings` returns, before the
   provider's resolver is reached, and a key the table does not own — a manifest built past
   the typecheck, or an inherited name such as `toString` — throws, naming it, rather than
   rendering an empty label. The admin entry is `{ framework: "admin" }`, so under
   `LOCALE_NL` it reads "Beheer" whatever the app's source locale is.

   Two other shapes were weighed. **A reserved id namespace on the descriptor**
   (`{ id: "terp:admin", message: "Admin" }`) leaves the type alone and changes what a
   descriptor means: its `message` becomes text nothing reads, and `id: string` cannot be
   narrowed to the table's keys, so only a typed helper would catch a misspelling and the raw
   literal would stay a second, unchecked way to write the same thing. An app writing that
   literal would also be asked by `locale-catalogs-complete` for an `i18n.json` entry the
   runtime never reads, unless the portable rule learned the namespace — a change to the
   Standard for a need of the framework's own. **Widening `UiText`** would let every `UiText`
   prop take a framework reference, a second way to render framework copy beside
   `useStrings()` in every component, and would reach every place that inspects `UiText` by
   shape. Only a manifest needs framework copy as data, and on a manifest only `NavItem.label`
   is text a packaged module writes: a `NavGroup` is declared by the app, and a route carries
   no text.

   An app gains nothing through it. A `FrameworkText` renders only framework copy, which
   `assertFrameworkStringsComplete` already requires of every declared non-English catalog, so
   there is no unchecked text for it to carry; and the same string is already one
   `useStrings()` away. In app source it is refused besides: `no-untranslated-ui` reads the
   key as a literal under `label`, which is what it is to that rule, and
   `locale-catalogs-complete` finds no id to ask a catalog entry for. An app's own nav entry
   keeps its own descriptor. The packaged manifest itself never meets the app lint, which runs
   over the app's own tree; react-core arrives under `node_modules`, which ESLint does not
   lint.

## Deliberately not in it

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
- `NavItem.label` is wider. Code of an app's own that narrows a nav label by hand
  (`typeof label === "string" ? label : label.message`) stops typechecking, which is the
  intended failure: it would render nothing for the admin entry. A label resolved through
  `useUiText()`, as the shell resolves it, needs no change.
- A future packaged module with a nav entry of its own labels it the same way, and the key
  it names must exist in `TerpStrings` — which puts its translation under the completeness
  check with no further wiring.
