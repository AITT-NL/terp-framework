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
- **`terp inspect capabilities`** — every maintained `terp-cap-*` package: what this
  app already has, what it can adopt, and the wiring each expects. Read it before
  building infrastructure by hand.

## Golden rules (the gate enforces these — follow them and it stays green)

1. Table models inherit `BaseTable`; never redeclare `id` / `created_at` /
   `updated_at` / `version`.
2. Services subclass `BaseService`; CRUD is inherited. Add always-on read filters via
   `business_filters()`, and per-request ones by declaring `filterable` / `sortable`
   and passing `list(..., filters=..., sort=...)`; **never override `base_query`** (it
   would silently drop the soft-delete / tenant scope).
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

Screens compose the **`@terpjs/react-core` component surface** — the full catalog is in
`node_modules/@terpjs/react-core/README.md` (bootstrap/providers, page archetypes
`AppShell`/`Page`/`OverviewPage`/`DetailPage`/`HubPage`/`DashboardPage`/`FormPage`/`SettingsPage`/`SplitPage`/`WorkspacePage`, data via `DataView` +
`useResource`/`ResourceList`, feedback via `ToastProvider`/`ConfirmDialog`/
`EmptyState`/`ErrorState`/`Alert`/`Badge`/`Tooltip`, form primitives `Button`/`Input`/
`Select`/`Textarea`/`Checkbox`/`RadioGroup`/`Switch`/`Field`/`Combobox`/
`DatePicker`/`DateRangePicker`, overlay primitives `Popover`/`Menu`, plus `Tabs`
for in-page tab sets and `Markdown` for safe rich text).

Start a frontend with the user's main task and the standard component that serves it.
Use the existing app or house design as the baseline. Give an app-owned layout a specific
job, such as putting a source document beside the decision that depends on it. Keep the
platform's controls, readable measure, theme pairs and responsive defaults where they fit.
Apply scoped classes to native layout elements. Configure controls through their supported props.
If two directions serve the task equally well and the preference matters, offer one short
choice. When asked to choose, pick a direction and record the rationale in the app README.
Check the rendered screen at desktop and mobile widths. Verify that the main action is easy
to find and reach by keyboard, and measure text against its actual background in every shipped
theme, including hover and focus. If an action disappears, check where keyboard focus lands.
At narrow widths, use `expectControlFitsHorizontally` from `@terpjs/conformance` on
the inputs and buttons the task needs. A page can fit while a container clips a control. For an unusual layout, compare it with the
standard composition using the same content before making it the app's default.

1. Token-styled primitives only — never raw `<button>` / `<input>` / `<select>` /
   `<textarea>` / `<table>` / `<dialog>` / `<form>`; use `Button` / `Input` / `Select` /
   `Textarea` / `DataView` / `ConfirmDialog` / `Stack as="form"`.
2. The generated typed client only (`useTerpClient()` + `unwrap`) — never raw `fetch` /
   `XMLHttpRequest` / `WebSocket` / `EventSource` / `navigator.sendBeacon`.
3. Data collections render via `DataView` (repository-driven; see
   `node_modules/@terpjs/react-core/src/dataview/README.md`).
4. Choose the layout for the user’s task. Compose existing controls and use the body of
   a plain `Page` when a screen needs its own layout. A component can import a sibling
   `./Board.module.css` with a static default import and use `className={styles.board}`.
   Use local class selectors and theme tokens for colors, typography and spacing.
   Responsive rules can use `@media` or `@container`. Keep keyboard focus visible and
   check the layout in narrow viewports and each supported theme. No `style={}`, no
   `className` but the module's own class, on a native element (a framework control takes
   its props), and no other stylesheet in any `src/` file: `src/main.tsx` alone loads the
   global token pipeline. Prose goes through `Text` and `Code`, which carry the theme's
   typography.
5. Every routed view renders a page archetype (`Page` / `OverviewPage` / `DetailPage` /
   `FormPage` / `SettingsPage` / `SplitPage` / `DashboardPage` /
   `HubPage` / `WorkspacePage`) — the router refuses an unframed view at runtime. In-app links go through
   the router's `Link`, never a raw `<a href="/...">`. Generated apps also opt into the
   `standard` slot-typed layout contract, declared once in
   `frontend/layout-contract.json` and read by both halves — the lint rule finds the file,
   `main.tsx` imports it: each archetype's body slot accepts only the contract's
   components, enforced at lint time and runtime with a message that states the fix —
   recipe: `uv run terp guide layouts`. Compose a page from the shape of its data
   (ADR 0169): the figures it is about in a `StatGroup` in its `summary` band, one figure as a
   `Stat` (at most one per page marked `headline`), a collection as a `DataView`, a section
   beside another as `Grid template="2:1"` — never a colour of your own to make a block stand
   out. Alternate framed and unframed blocks: the frame is for the data a reader works with —
   a collection, a chart, a lone figure — a boxed `Card` for a group of controls or a record's
   section, and a `StatGroup`, a `DetailList`, a `Timeline` or a line of `Text` needs none.
6. Import from `@terpjs/*` package roots only — no deep `src/` / `dist/` imports.
7. A module's UI is wired by its `module.tsx` manifest (routes + nav + views) — no
   central registry to edit.
8. Security defaults, each its own error: `dangerouslySetInnerHTML` and DOM
   HTML-injection sinks (`innerHTML` / `outerHTML` / `insertAdjacentHTML` /
   `document.write`) are refused — render text, or `Markdown` for rich text;
   `eval()` / `new Function()` are refused; `javascript:` URLs in `href`/`src` are
   refused; a static `target="_blank"` link needs `rel="noopener"`.
9. Theming and language are platform concerns, already wired: the token stylesheet
   carries the palettes `midday`, `twilight`, `evening`, `night` and `contrast` (the
   built-in sidebar `UserMenu` offers all of them plus `system`), and
   `renderTerpApp({ locales })` declares the language catalogs (the menu shows a picker
   once a second locale exists). Keep user-facing text as `UiText` props so it follows
   the language switch. To ship on a palette other than the default, name it as
   `defaultTheme` in `frontend/layout-contract.json` — do not restyle to imitate one, and
   do not also pass the bootstrap option, which is refused as one fact declared twice.

There are no lint modes: every violation is an error. The one governed opt-out is a
justified `// terp-allow-<rule>: <reason>` marker on (or above) the violating line, whose
counts must exactly match `frontend/escape-hatch-budget.json` — a rise needs a justified
budget bump in the same change (`npm run lint` runs the ratchet).

Write a module by filling the fixed slots `models` / `schemas` / `service` /
`router` / `module`; `terp guide module` shows the 10-minute path. When in doubt, run
`terp guide` and let the gate guide you.
