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
2. **A catalog supplies exactly its locale's categories.** `LocaleProvider` and
   `defineAppLocales` read them from the locale's own `Intl.PluralRules` and refuse a single
   string where forms are due, a category the language uses and the catalog left out, and a form
   the language never selects. The check is as wide as the language: two forms for Dutch, four
   for Polish. Completeness (ADR 0105) is unchanged: a key is present or it is missing, and a
   present value has already been held to its shape.
3. **The form is chosen through the UiText seam.** `UiTextProvider` carries the locale whose
   rules apply, `LocaleProvider` passes its active one, and the root default is English. The
   framework's components choose by the count they render — the total for the range and the
   select-all label, the route count for the access warning.
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

- An app with a non-English catalog of its own supplies the three keys as forms, and is told
  exactly which form is missing or stray. `LOCALE_NL` ships them. An app on `LOCALE_EN` and
  `LOCALE_NL` changes nothing.
- A locale code must be a BCP 47 language tag. `Intl.PluralRules` throws on one that is not
  — `en_US` rather than `en-US` — and a code chooses a plural form now, so an app keyed that
  way would have met a `RangeError` the first time a page rendered a count. `LocaleProvider`
  and `defineAppLocales` refuse such a code when the catalogs are checked, with the spelling to
  use. `<html lang>`, which the code is written to, needed a tag all along.
- A `UiTextProvider` given `strings` directly is not checked. `other` answers there when the
  chosen form is absent, so an unchecked table still renders a sentence.
- **Not covered, and recorded rather than implied:** app-authored copy has no plural form. A
  `UiText` descriptor carries one message, so a DataView override that renames "results" to
  "invoices" still reads "1 invoices". Giving descriptors plural forms is a change to the
  contract's `UiText`, the app catalog and the translation lint, and it is a separate decision.
