# AGENTS.md

This application is built on **Terp** — a secure-by-default application platform. The
framework enforces authentication, authorization, audit, optimistic concurrency,
pagination, input caps and row scoping for you, through an **architecture gate** that
fails closed with precise, fixable messages.

> This file is the entry point. It is intentionally short: the authoritative,
> always-current instructions live in the `terp` CLI and the gate.

## Start here — how to find the instructions

- **`terp guide`** — the authoring guide. **`terp guide <topic>`** for a focused
  recipe (`module`, `service`, `policy`, `ownership`, `tenancy`, `events`,
  `capability`, `migrations`, `rules`).
- **`uv run pytest`** — the architecture gate is the source of truth. **Green means
  your code is compliant; red names the fix.** Run it before and after each change.
- **`terp inspect control-plane`** — your roles, permissions, and per-module
  authority map.

## Golden rules (the gate enforces these — follow them and it stays green)

1. Table models inherit `BaseTable`; never redeclare `id` / `created_at` /
   `updated_at` / `version`.
2. Services subclass `BaseService`; CRUD is inherited. Add read filters via
   `business_filters()`; **never override `base_query`** (it would silently drop the
   soft-delete / tenant scope).
3. Every write goes through the service (`create` / `update` / `delete`, or
   `self._save` / `self._remove`); never call `session.add` / `commit` / `execute`
   yourself — the audit trail is automatic and a raw write is refused at runtime.
4. Every module declares a `ModuleSpec` with a `Policy` (deny-by-default); a truly
   public route opts in with `Policy.public(reason="...")`.
5. Routes set `response_model` to a Read DTO (never the table model) and paginate
   lists with `Page[T]`.
6. Cap every input string with `Field(max_length=...)`.
7. Import only the `terp.core` public surface + your declared capabilities — never
   `terp.core._internal`, never a sibling module.
8. Never hand-roll an `owner_id` check; compose `OwnedMixin` for per-row write
   authorization (the `no_manual_ownership_checks` rule enforces it). See
   `terp guide ownership`.

## Frontend golden rules (the boundary lint enforces these)

Screens compose the **`@terp/react-core` component surface** — the full catalog is in
`node_modules/@terp/react-core/README.md` (bootstrap/providers, page archetypes
`AppShell`/`Page`/`OverviewPage`/`DetailPage`/`HubPage`, data via `DataView` +
`useResource`/`ResourceList`, feedback via `ToastProvider`/`ConfirmDialog`/
`EmptyState`/`ErrorState`/`Alert`/`Badge`/`Tooltip`, form primitives `Button`/`Input`/
`Select`/`Textarea`/`Checkbox`/`RadioGroup`/`Switch`/`Field`/`Combobox`/
`DatePicker`/`DateRangePicker`, overlay primitives `Popover`/`Menu`, plus `Tabs`
for in-page tab sets and `Markdown` for safe rich text).

1. Token-styled primitives only — never raw `<button>` / `<input>` / `<select>` /
   `<textarea>` / `<table>` / `<dialog>` / `<form>`; use `Button` / `Input` / `Select` /
   `Textarea` / `DataView` / `ConfirmDialog` / `Stack as="form"`.
2. The generated typed client only (`useTerpClient()` + `unwrap`) — never raw `fetch` /
   `XMLHttpRequest` / `WebSocket` / `EventSource` / `navigator.sendBeacon`.
3. Data collections render via `DataView` (repository-driven; see
   `node_modules/@terp/react-core/src/dataview/README.md`).
4. Style with design tokens (`var(--color-*)`, `var(--space-*)`) — no inline colours,
   no `style={}`, no `className`, no module-authored stylesheets: layout comes from
   `Stack` / `DetailList` / the page archetypes; theming from the app's token source.
5. Every routed view renders a page archetype (`Page` / `OverviewPage` / `DetailPage` /
   `HubPage`) — the router refuses an unframed view at runtime. In-app links go through
   the router's `Link`, never a raw `<a href="/...">`. Generated apps also opt into the
   `standard` slot-typed layout contract (`frontend/layout-contract.json` +
   `layoutContract` in `main.tsx`): each archetype's body slot accepts only the
   contract's components, enforced at lint time and runtime with a message that states
   the fix — recipe: `uv run terp guide layouts`.
6. Import from `@terp/*` package roots only — no deep `src/` / `dist/` imports.
7. A module's UI is wired by its `module.tsx` manifest (routes + nav + views) — no
   central registry to edit.
8. Security defaults, each its own error: `dangerouslySetInnerHTML` and DOM
   HTML-injection sinks (`innerHTML` / `outerHTML` / `insertAdjacentHTML` /
   `document.write`) are refused — render text, or `Markdown` for rich text;
   `eval()` / `new Function()` are refused; `javascript:` URLs in `href`/`src` are
   refused; a static `target="_blank"` link needs `rel="noopener"`.
9. Theming and language are platform concerns, already wired: the token stylesheet
   carries light *and* dark palettes (the built-in sidebar `UserMenu` offers the
   light/dark/system toggle), and `renderTerpApp({ locales })` declares the language
   catalogs (the menu shows a picker once a second locale exists). Keep user-facing
   text as `UiText` props so it follows the language switch.

There are no lint modes: every violation is an error. The one governed opt-out is a
justified `// terp-allow-<rule>: <reason>` marker on (or above) the violating line, whose
counts must exactly match `frontend/escape-hatch-budget.json` — a rise needs a justified
budget bump in the same change (`npm run lint` runs the ratchet).

Write a module by filling the fixed slots `models` / `schemas` / `service` /
`router` / `module`; `terp guide module` shows the 10-minute path. When in doubt, run
`terp guide` and let the gate guide you.
