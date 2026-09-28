# 0164 — A string that counts has a form per plural category

- **Status:** Accepted and implemented. `TerpStrings` holds `PluralText` for its count-bearing
  keys, `LocaleProvider` and `defineAppLocales` hold each catalog to its locale's plural
  categories, and the form is chosen through the UiText seam. Held by `locale.test.tsx`,
  `uiText.test.tsx`, `dataview/DataView.test.tsx` and `admin/access.test.tsx` in
  `@terpjs/react-core`.
- **Date:** 2026-09-28
- **Relates:** [ADR 0105](0105-localization-is-a-checked-contract.md) (a non-English locale
  supplies all of the framework's copy or is refused — the check this widens from presence to
  grammar), [ADR 0153](0153-framework-copy-is-one-table-and-the-document-says-its-language.md)
  (framework copy is one table, and a manifest may name a key of it)

---

## Context

Three framework strings carry a count: a DataView's result range, its "select all" label, and
the access pane's warning about routes with no description. Each had one form for every count,
because `TerpStrings` typed every value as a string. So a table with one row said
"1–1 of 1 results", and under `LOCALE_NL` "1–1 van 1 resultaten". The access warning avoided
the question, "{count} action(s) … have" and "{count} actie(s) … hebben", which is still wrong
for one and reads as a form letter for any count. The framework's own admin test asserted the
Dutch "1–1 van 1 resultaten" verbatim, so the wrong grammar was pinned as expected output.

Nothing about this is Dutch. A second form keyed to "exactly one" would fix English and Dutch
and still be wrong for the languages whose plural categories are not about one: Polish has four,
and in Russian 21 takes the singular form.

## Decision

1. **A count-bearing framework string is a `PluralText`**: one form per CLDR plural category,
   `other` always required, the same `{placeholder}`s in every form. Each form is a whole
   sentence, and the placeholders stay in the `one` form too, because a category is a
   grammatical class and not a number.
2. **The shape is checked where a table arrives; the language is checked where the ICU is
   fixed.** `LocaleProvider`, `defineAppLocales` and a `UiTextProvider` given its strings
   directly refuse a count-bearing key written as one string, one with no `other` form, an
   empty form, and a form named by anything but a CLDR category. They do not check a
   catalog's categories against its language, because that answer comes from the runtime's
   ICU data, which differs between browsers and versions: French is `one`/`other` on some
   engines and `one`/`many`/`other` on newer ones, so a check against it would pass a catalog
   in one browser and blank the app in the next. The shipped catalogs are held to exactly
   their languages' categories by react-core's own tests instead, where the ICU is fixed. A
   category a catalog has no form for is answered by `other`. Completeness (ADR 0105) is
   unchanged: a key is present or it is missing.
3. **The form is chosen through the UiText seam.** `UiTextProvider` carries the locale whose
   rules apply, `LocaleProvider` passes its active one, and the root default is English. The
   framework's components choose by the count they render — the total for the range and the
   select-all label, the route count for the access warning — through `usePlural`, which is
   exported so that app code reading one of these strings from `useStrings` chooses the same
   way.
4. **A manifest's `FrameworkText` names plain strings only.** A navigation label has no count to
   choose a form by, so the type no longer admits a count-bearing key, and a manifest that was
   never typechecked is refused at render with a message saying why.
5. **A DataView's per-instance override stays one `UiText`.** It is the instance's own wording,
   and it is rendered as given, with no form chosen.

**Not taken: a second key per string (`dataViewResultsRangeOne`).** It is English-shaped, it
cannot express `few` or `many`, and no check can tell that two keys are one sentence's forms.

**Not taken: ICU message syntax inside the string.** It would need a message parser in
react-core, and the catalog check would have to parse every value to find what is missing. An
object keyed by category is checked by its structure.

## Consequences

- An app that supplies any of the three keys itself — in a catalog of any locale, English
  included, or to a `UiTextProvider` directly — writes them as forms, and is told what is
  wrong with the shape. `LOCALE_NL` ships them. An app on `LOCALE_EN` and `LOCALE_NL` that
  sets none of the three changes nothing. App code that renders one of them itself chooses the
  form with `usePlural`.
- A locale code must be a BCP 47 language tag. `Intl.PluralRules` throws on one that is not
  — `en_US` rather than `en-US` — and a code chooses a plural form now, so an app keyed that
  way would have met a `RangeError` the first time a page rendered a count. `LocaleProvider`
  and `defineAppLocales` refuse such a code when the catalogs are checked, with the spelling to
  use. `<html lang>`, which the code is written to, needed a tag all along.
- **Not covered, and recorded rather than implied:** app-authored copy has no plural form. A
  `UiText` descriptor carries one message, so a DataView override that renames "results" to
  "invoices" still reads "1 invoices". Giving descriptors plural forms is a change to the
  contract's `UiText`, the app catalog and the translation lint, and it is a separate decision.
