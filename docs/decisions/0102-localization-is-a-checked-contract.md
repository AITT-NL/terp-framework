# 0102 — Localization is a checked contract

- **Status:** Accepted
- **Date:** 2026-08-27
- **Relates:** ADR 0080 (the Terp Standard catalog and corpus), ADR 0081
  (certified enforcement), and ADR 0096 (typed seams cover the common case).

---

## Context

`UiText` already let a component accept `{ id, message }`, and `LocaleProvider` already
translated react-core's own chrome. Neither property proved that application copy used that
seam or that every target locale contained the id. A plain JSX string was invisible to the
catalog; a descriptor missing from Dutch silently rendered its source message. The language
picker therefore promised more than the app delivered, and an agent could finish a feature
with a green gate while one language remained incomplete.

FAST-v2 makes both omissions build failures: static user-interface literals are inventoried
and every shipped catalog must be complete. Terp needs the same guarantees without coupling
its framework contract to Lingui or to one frontend stack.

## Decision

1. `frontend/i18n.json` declares `sourceLocale` and every locale's `messages`. The generated
   app merges this app-copy declaration with react-core's framework catalogs through
   `defineAppLocales`.
2. Static module copy uses `{ id, message }` where a component accepts `UiText`, and `Trans`
   for JSX bodies. Plain strings remain valid for dynamic business data, identifiers,
   commands and product names.
3. `frontend/no-untranslated-ui` rejects bare JSX copy, literal UI attributes and literal
   UI-bearing object properties across app-authored `src/**`, not only module folders. It also
   walks rendered conditional, logical, template, array and fragment expressions, so moving two
   literal branches behind an expression does not erase them from the inventory. Its source check
   is portable and belongs in the Standard.
4. `frontend/locale-catalogs-complete` checks every inline descriptor and `Trans` id against
   every non-source locale. Empty entries fail. A target equal to the source fails unless the
   id is explicitly listed in that locale's `allowIdentical`; that list records proper nouns
   and acronyms rather than becoming an implicit fallback.
5. `LocaleProvider` is the runtime half. The source locale uses the descriptor's message;
   a target locale without a non-empty entry, or with an undocumented verbatim source copy,
   throws an actionable error. Invalid source/default locale configuration is refused too.
   Dynamic ids and a bypassed build therefore cannot turn silent fallback back on.
6. Navigation labels are `UiText` in the stack-neutral contract and are resolved by the
   shell, so localization does not stop at page content.
7. App messages do not translate react-core chrome. Both `defineAppLocales` and the public
   `LocaleProvider` therefore refuse every declared non-English locale whose `TerpStrings`
   catalog is incomplete; supplied labels and framework strings are shape-checked too. A new
   language supplies both halves in the same bootstrap change instead of presenting translated
   pages in an English shell.

## Consequences

- A feature that adds copy must add every target translation in the same change.
- Generated project instructions tell coding agents the exact authoring forms and gate
  command; the starter itself demonstrates them and ships a complete English target.
- The Standard gains two corpus-backed frontend rules, and adapters can implement the same
  source contract without importing React or Lingui.
- Framework-only strings still use `TerpStrings`; application copy and framework chrome meet
  at one active resolver but remain separately owned.
