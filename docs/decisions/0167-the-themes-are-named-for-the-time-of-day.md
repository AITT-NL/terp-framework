# 0167 — The themes are named for the time of day, and keep the names they had

- **Status:** Accepted and implemented. Registered in `packages/frontend/contract/themes.json`
  (`aliases`), compiled by `scripts/build-tokens.mjs`, resolved by react-core's `resolveTheme`.
  Held by `tokens.themes.test.js` ("paints every earlier name exactly as the theme it now
  names"), `theme.test.tsx`, `layoutDeclaration.test.ts` and
  `tests/architecture/test_theme_bootstrap.py`.
- **Date:** 2026-10-02
- **Relates:** [ADR 0100](0100-the-layout-declaration-is-one-document.md) (`defaultTheme` in
  `layout-contract.json`, which must keep accepting a file written before this),
  [ADR 0112](0112-the-palette-is-on-the-document-before-the-first-paint.md) (the pre-paint
  bootstrap, which must resolve an earlier name the same way the provider does)

---

## Context

Four of the five palettes were a light theme and three darks, named `light`, `dark`, `midnight`
and `twilight`. The names described the palettes badly in two ways that showed in use. Three
darks called `dark`, `midnight` and `twilight` read as one colour and two moods, and `twilight`
— the one that was meant to be different — sat almost as low as `dark`: its canvas `#1a1622`
against dark's `#0f172a`, both effectively black. And the operating system's dark preference
selected `dark`, the slate palette, when the near-black `midnight` is the one that suits the
lighting a dark preference usually means.

Renaming a theme is not free. A theme's name is written in four places an app owns: a viewer's
stored choice in `localStorage`, `defaultTheme` in the app's `layout-contract.json` or bootstrap
options, `data-theme` on the app's own `<html>` (how an app ships on a palette without a flash),
and the per-palette selectors in the app's own `theme.css`. A clean rename breaks all four.

## Decision

**1. The palettes are named for the time of day they suit:** `midday` (the light base, formerly
`light`), `twilight`, `evening` (the slate dark, formerly `dark`) and `night` (the near-black dark,
formerly `midnight`). `contrast` is unchanged. Offered in that order, then `system`.

**2. The OS dark preference selects `night`.** `systemDark` moves from the slate palette to the
near-black one.

**3. Twilight is a dimmed dark, not a third near-black one.** Light text on violet-grey surfaces
— canvas `#312c3f`, surface `#3a3449` — between midday and evening, the way "dark dimmed" themes
sit elsewhere. Every declared text pairing still reaches AA and the control-boundary pairings
rise (the ratchet only lets them rise).

**4. The old names are aliases, not breaks.** Each renamed theme lists its earlier name under
`aliases` in `themes.json`, and an alias is honoured everywhere a theme is named:

- **The stylesheet** compiles each alias into its theme's OWN rule
  (`[data-theme='evening'], [data-theme='dark'] { … }`), so a `data-theme="dark"` on an app's
  `<html>` paints exactly what `evening` does — the same block, not a copy that could drift. The
  base needs no rule: it is `:root`, and an attribute no overlay matches leaves it standing.
- **react-core** resolves an alias to today's name in one place, `resolveTheme`: a stored choice,
  `ThemeProvider`'s `defaultTheme`, the bootstrap option and `layout-contract.json` all go
  through it. `LegacyTheme` types the old names so app code that passes one still compiles.
- **The pre-paint bootstrap** resolves a stored alias the same way, and counts every dark alias
  as dark, so an `index.html` that still says `data-theme="midnight"` opens dark with no flash.
- **The manifest** publishes `aliases` on every theme and the layout schema's enum lists the old
  names, so a tool reading either can map them.

**5. The translation keys keep their names.** `themeLight`, `themeDark` and `themeMidnight` now
carry "Midday", "Evening" and "Night". An app that ships its own language catalog must supply
every key, and renaming the keys would refuse every such catalog on load for a change no reader
sees. The key is an identifier; the value is the name.

## Consequences

- **An app's per-palette selectors must be renamed.** The theme control writes the new names,
  so `<html>` says `data-theme="evening"` and an app's own `[data-theme="dark"] { … }` in
  `theme.css` no longer matches. The aliases cannot cover this one: the old name is in the app's
  selector, not in the attribute. The upgrade note says so, and the template's and the guide's
  examples use the new names.
- **Apps on `system` see night, not the slate dark, under a dark OS preference.** That is the
  point of decision 2, and it is a visible change to every such app.
- **A theme added later has no aliases** and needs none; `aliases` exists for a rename, and the
  generator refuses an alias that collides with any other theme's name.
- **The workbench's screenshot lane photographs `midday` and `night`** (the base and the OS
  dark), so its baselines are named for them: the `light-*` pictures were renamed, and the
  `dark-*` pictures were replaced by `night-*` ones recorded fresh — a different palette.
