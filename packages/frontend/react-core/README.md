# @terpjs/react-core

Stack A (React) of the Terp frontend contract: the provider/hooks that wire a tree to
`@terpjs/contract`, the auth session, the app shell + TanStack Router adapter, and the
**token-styled component surface** every app module composes its screens from.

This README is the catalog of that surface. Everything listed here is exported from
the package root (`import { … } from "@terpjs/react-core"`); each export also carries
JSDoc, so your editor shows the same guidance inline. **Never deep-import** from
`src/` or `dist/` — the boundary lint (`@terpjs/eslint-boundaries`) refuses it.

## Conventions (the lint enforces these)

- **Token-styled primitives only** — raw `<button>` / `<input>` / `<select>` /
  `<textarea>` are refused; use `Button` / `Input` / `Select` / `Textarea` plus the
  higher-level form primitives (`Checkbox`, `RadioGroup`, `Switch`).
- **Generated client + sanctioned realtime only** — raw `fetch` / `XMLHttpRequest` /
  `WebSocket` / `EventSource` / `navigator.sendBeacon` are refused; use
  `useTerpClient()` (typed from the backend OpenAPI) and `unwrap` for request/response,
  or `useRealtimeChannel()` for typed SSE/WebSocket subscriptions. The hook mints a
  one-use connection ticket through the generated client; bearer tokens never enter URLs.
- **Design tokens, not inline colours** — style with the CSS variables from
  `@terpjs/contract` (`var(--color-*)`, `var(--space-*)`, `var(--font-*)`).
- **User-facing text is `UiText`** — every text prop accepts a plain string or an
  `{id, message}` descriptor, so apps can localize via `UiTextProvider` without
  react-core taking an i18n dependency.
- **Dependency-free UI** — react-core ships no icon/toast/i18n libraries. Glyphs are
  inline SVG; transient feedback goes through `ToastProvider` / `useToast`.
- **Security defaults** — `dangerouslySetInnerHTML` and the DOM HTML-injection sinks
  (`innerHTML` / `outerHTML` / `insertAdjacentHTML` / `document.write`) are refused
  (render text, or use `Markdown` for rich content); `eval()` / `new Function()` are
  refused; `javascript:` URLs in `href`/`src` are refused; a static `target="_blank"`
  link needs `rel="noopener"`.

## Bootstrap & providers

| Export | Use |
|---|---|
| `renderTerpApp`, `collectModules`, `withAdminArea` | One-call app bootstrap: glob-import `modules/*/module.tsx`, merge the packaged admin area (opt out with `adminArea: false`, or select sections with `adminArea: { users, groups, audit }`; an app route claiming an admin path overrides that screen), build the router, mount provider + auth gate + shell. Options include `logo` (sidebar brand) and `footer`. |
| `TerpProvider`, `useAuth`, `useTerpClient` | The context root: session state + the typed API client. Drop to this + `buildAppRouter` when you need full control. |
| `buildAppRouter`, `DEFAULT_ROLE_RANKS`, `PROFILE_PATH` | TanStack Router adapter: realises stack-agnostic module manifests (routes + nav + roles) into a real router; throws at build time on a route referencing a missing view. Mounts the built-in `ProfileView` at `/profile` unless an app manifest claims that path. |
| `createAuthClient` | The auth/session contract implementation (login / refresh / currentUser) over the generated client. |
| `LoginView` | The standard sign-in screen: username/password, plus optional SSO provider buttons via `ssoProviders` and a dev-only credential-fill button via `devCredentials` (gate it on `import.meta.env.DEV`). |
| `useSso`, `parseSsoCallback`, `fetchSsoAuthorizationUrl`, `completeSsoCallback` | The SSO login seam (ADR 0058): `useSso().begin(provider)` opens an OIDC flow; `TerpProvider` completes the `/auth/callback/{provider}` redirect landing into a normal session on boot. `renderTerpApp({ ssoProviders })` wires the buttons in one line. |
| `RequireAuth` | Renders children only with a session; pairs with the router so the app mounts only when signed in. |
| `ThemeProvider`, `ThemeToggle`, `useTheme` | Light/dark/system theming: applies `data-theme` on `<html>` (the token stylesheet carries both palettes) and persists the choice. `renderTerpApp` mounts it for every app; the shell header uses an icon-only, token-themed `variant="inline"` menu. |
| `LocaleProvider`, `LanguageSwitcher`, `useLocale`, `LOCALE_EN`, `LOCALE_NL` | The language seam over `UiTextProvider`: per-locale string catalogs, a persisted active locale, and an icon-only, token-themed menu in the shell header once an app declares a second locale. English and Dutch catalogs ship complete; `renderTerpApp({ locales })` wires them. |
| `UserMenu`, `userInitials` | The signed-in user's menu, pinned by `buildAppRouter` to the bottom of the sidebar: an initials avatar trigger opening the identity block, **Settings** (the built-in profile page) and sign-out. Collapses to the avatar in the icon rail. |
| `ProfileView` | The built-in profile / settings page (`/profile`): the server-validated identity, theme + language preferences, and sign-out. |

## Authorization gates (UI-side; the backend re-checks)

| Export | Use |
|---|---|
| `Authorized`, `useCan` | Gate UI on `can(module, action)` — write buttons, admin panels. |
| `canPerform`, `DEFAULT_RANK_THRESHOLDS` | The role-rank predicate behind the gate. |
| `visibleNav` | Filter nav items to what the current user may see. |

## Page archetypes (the three-level screen pattern)

Every routed view **must** render one of the archetypes (`Page`, or `OverviewPage` /
`DetailPage` / `HubPage`, which compose it) — `buildAppRouter` refuses an unframed view at
runtime, fail closed (ADR 0059), so every screen keeps the breadcrumb/title/error frame.

| Export | Use |
|---|---|
| `AppShell` | The responsive level-1 frame: a home-linked brand, icon/label nav and account footer. Desktop collapses to a persisted, scrollbar-free rail with one fixed icon slot; mobile becomes a scroll-locking drawer. The sticky header holds the sidebar toggle and icon-only preferences. Router-agnostic link renderers receive framework-owned expanded/collapsed geometry. |
| `NavIcon`, `Icon`, `TerpMark`, `ICON_GLYPHS` | The dependency-free icon layer: manifest `NavItem.icon` names resolve to bundled inline-SVG glyphs (label-initial fallback), `Icon` renders any glyph by name (`<Icon name="plus" size="1em" />`) — the bundled catalogue covers common UI, action, object, and status glyphs (home, list, folder, users, plus, edit, trash, search, check, x, chevron-{left,right,down}, arrow-left, external, logout, user, bell, key, globe, lock, tag, mail, refresh, filter, download, upload, star, heart, database, code, truck, cart, wallet, map-pin, clock, link, grid, book, briefcase, building, clipboard, layers, send, phone, image, video, music, wrench, zap, …) — and `TerpMark` is the placeholder brand mark until an app passes its own `logo`. |
| `Page` | The base routed screen: optional breadcrumb row, then one compact `h1` + intrinsic-width actions row (title-first on narrow layouts), then the body with loading/error slots. |
| `HubPage`, `HubCard` | Responsive `auto-fit` landing grid. Cards share equal outer and internal tracks even when descriptions/stats differ; nested hubs use the ordinary breadcrumb contract via `parents`. |
| `OverviewPage` | A module's top-level listing screen (level 2); detail pages crumb back to it. |
| `DetailPage` | One record's screen (level 3); breadcrumb trail = ancestors + record title. |
| `Breadcrumbs` | The trail itself (used by the archetypes; rarely composed directly). |
| `ModuleNav` | Secondary horizontal tabs for intra-module sub-pages (real routes, not state). |
| `PageActions` | Primary action + overflow menu for a page header. |

### Slot-typed layout contracts (opt-in, ADR 0079)

An app can ratchet the archetype control further with a named **layout contract**:
`renderTerpApp({ layoutContract: "standard" })` (runtime half) plus a checked-in
`layout-contract.json` next to the frontend sources (`{ "contract": "standard" }`, the
`terp/layout-contract` lint half — keep the two in sync; the project template generates
both). Each governed archetype's body slot then accepts **only** the contract's
components — `standard`: hub bodies hold `HubCard` only; overview bodies hold
`DataView` / `ResourceList` / `ModuleNav` / `Stack` plus the framework states
(`EmptyState` / `ErrorState` / `LoadingState` / `Alert`) and `ConfirmDialog`; detail
bodies hold `DetailList` / `Stack` / `Tabs` / `ModuleNav` / `DataView` plus the same
states. The plain `Page` stays unconstrained (the sanctioned home for a bespoke
screen). Enforcement is two-layer and fail-closed: the lint rule checks static JSX
children; the archetypes verify the rendered DOM (sanctioned components stamp a
`data-terp` marker) and refuse a non-conforming view with the **same directive
message** — contract, slot, what was found, what is allowed, and the fix — so a
failing check tells the author (human or agent) exactly how to build the screen.
`LAYOUT_CONTRACTS` exports the table; no config means no checks (fully backwards
compatible). The one opt-out is a justified `// terp-allow-layout-contract: <reason>`
marker, counted by the escape-hatch budget.

## Data

| Export | Use |
|---|---|
| `DataView` + family | **The single sanctioned surface for data collections**: repository-driven table/card view with search, sorting, pagination, column management, selection + batch actions, row actions, expandable rows, persisted view preferences, and pointer/keyboard row activation for overview-to-detail navigation. See [`src/dataview/README.md`](src/dataview/README.md) for the full guide (client-side and server-side recipes). |
| `InMemoryDataViewRepository`, `HttpDataViewRepository` | Data repositories (client-side / server-side); `useServerDataView` keeps server query state in the URL. |
| `InMemoryViewStateRepository`, `LocalStorageViewStateRepository` | Preference persistence seam. |
| `useResource` | An async collection: rows + loading/error + reload + create-then-reload. |
| `useRealtimeChannel` | The sanctioned typed SSE/WebSocket seam for the optional realtime capability: mints a short-lived one-use ticket via the authenticated generated client, validates every inbound JSON payload with the channel's runtime type guard, and exposes connection state / last message / WebSocket send. App modules never touch raw transports. |
| `ResourceList` | The standard simple CRUD list screen: titled section, write-gated create form, loading/error/empty states. Composable — screens needing more render their own React. |
| `unwrap`, `ApiError` | Turn a generated-client result into data-or-throw; `ApiError` carries the envelope's `code` / `status` / `requestId`. |
| `FileUpload`, `useFileDownload` | The files-capability surface (ADR 0056/0057): a token-styled attachment picker that uploads through the typed client, and an authenticated download helper (a raw `<a href>` would carry no bearer token). |

## Feedback & states

| Export | Use |
|---|---|
| `LoadingState`, `InlineSpinner` | Full loading block (announces itself) / compact inline glyph. |
| `EmptyState` | The standard "nothing here yet" block, with an `action` slot for the next step. |
| `ErrorState`, `describeError` | Human-readable failure block for a caught error. |
| `ErrorMessagesProvider`, `useErrorMessage`, `DEFAULT_ERROR_MESSAGES` | Map stable backend error codes to copy; falls back to the envelope `detail`. |
| `ToastProvider`, `useToast` | Transient success/error feedback (no toast library). |
| `ConfirmDialog` | Accessible confirmation modal (native `<dialog>`); use before any destructive action. |

## Forms & primitives

| Export | Use |
|---|---|
| `Button` | Token-styled, content-sized command (`variant`: primary / secondary / danger / ghost; optional leading `icon`). Explicit `width: 100%` opts into full width. |
| `Input`, `Select`, `Textarea` | Token-styled controls with stable framework typography, independent of surrounding display text (raw elements are lint-refused). Numeric inputs suppress unthemeable browser steppers. |
| `Combobox` | Accessible autocomplete/typeahead single-select: filterable options, controlled or uncontrolled value, loading state, disabled state, and ARIA combobox/listbox keyboard navigation. |
| `DatePicker`, `DateRangePicker` | Locale-aware calendar popover controls with keyboard-navigable month grids, min/max bounds, and range selection for ERP date filters. |
| `Checkbox` | Labelled checkbox with `checked` / `defaultChecked` and boolean `onChange`. |
| `Radio`, `RadioGroup` | Labelled radio and accessible grouped radio options with controlled or uncontrolled value. |
| `Switch` | Labelled boolean toggle (`role="switch"`) with `checked` / `defaultChecked` and boolean `onChange`. |
| `Tabs` | In-page (non-routed) tab set with `tablist` / `tab` / `tabpanel` roles, arrow-key navigation, and controlled or uncontrolled value. |
| `Badge` | Small status pill (`tone`: neutral / info / success / warning / danger). |
| `Tooltip` | Accessible focus/hover tooltip that describes its trigger with `aria-describedby`. |
| `Popover`, `Menu`, `MenuItem` | Shared anchored overlay and dropdown-menu primitives: body-portaled, viewport-aware panels that escape scroll/table clipping, with outside-click/Escape close, focus return, selected-item semantics, and roving keyboard navigation. |
| `Alert` | Inline banner for persistent feedback (`tone`: neutral / info / success / warning / danger); warnings and danger announce as `alert`, others as `status`. |
| `Markdown` | Safe, dependency-free markdown renderer for headings, paragraphs, bold, italic, inline code, code blocks, lists, and safe links; raw HTML is rendered as text and never passed through. |
| `Field` | Label + control + hint/error wrapper for one form field. |

## Layout

Modules never write `style={}` or CSS — the boundary lint refuses the `style`
attribute in `src/modules/**`. Layout comes from these primitives (gaps index the
token spacing scale, so spacing is themed centrally):

| Export | Use |
|---|---|
| `Stack` | The layout primitive: a flex container with a token gap. Vertical by default (forms, sections); `direction="row"` + `justify` for toolbars; `as="form"` etc. for semantics. |
| `Card` | A token-styled surface (border + background + padding) grouping one block of a page — the sanctioned visual separation between sections. Optional header row: `title` (semantic `<h3>`), muted `description`, `actions` slot. |
| `DetailList` | Token-styled label/value pairs as a semantic `<dl>` (record metadata, expanded-row summaries). |

## The packaged admin area

Every Terp backend mounts the base-profile admin capabilities (users, groups +
access grants, audit); react-core ships the UI over them, so every app has a
working admin area on day one. `renderTerpApp` injects it by default: one
admin-gated **Admin** sidebar entry opens the `/admin` hub, whose cards lead to
the overviews; each overview breadcrumbs back to the hub (hub → overview →
detail, like every screen). Opt out with `adminArea: false`; ship only the
screens whose capabilities the app mounts with a sections object —
`adminArea: { groups: false }` is the users + audit profile, first-class (a
dropped section loses its routes, hub card and stat call) — or override a
single screen by claiming its path from an app module.

| Export | Use |
|---|---|
| `adminModule` | The whole area as a `TerpModule` (manifest + views) — spread it manually into an L2 `buildAppRouter` composition. |
| `AdminHub` | `/admin`: cards into users / groups / audit with live totals. |
| `UsersAdmin`, `UserCreate`, `UserDetail` | `/admin/users`: clickable account overview; `/new`: dedicated provisioning page; `/$userId`: details with header actions and confirmation-gated role, status and password changes. |
| `GroupsAdmin`, `GroupCreate`, `GroupDetail` | `/admin/groups`: clickable group overview; `/new`: dedicated creation page; `/$groupId`: details with header deletion, member management and permission grants (destructive changes use confirmation dialogs; deletion cascades memberships + grants, ADR 0074). |
| `AuditLogAdmin` | `/admin/audit`: the append-only trail, rows expanding to identifiers + payload. |

## Localization

| Export | Use |
|---|---|
| `UiTextProvider`, `useUiText`, `useStrings`, `resolveUiText`, `DEFAULT_STRINGS` | The `UiText` seam: override built-in strings and plug in a resolver (e.g. an i18n library) at the app root. `LocaleProvider` (above) is the batteries-included layer over it: per-locale catalogs + a persisted switcher. |

## Testing components

Component tests run under vitest with `// @vitest-environment jsdom` at the top of the
file plus an explicit `afterEach(cleanup)` (the default environment is node). Run:

```bash
npm run -w @terpjs/react-core typecheck && npm run -w @terpjs/react-core test
```

`vitest.setup.ts` polyfills `HTMLDialogElement.showModal/close` (jsdom lacks them), so
components may use the native `<dialog>` freely.
