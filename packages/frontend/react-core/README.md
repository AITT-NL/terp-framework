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
  `@terpjs/contract` (`var(--color-*)`, `var(--space-*)`, `var(--font-*)`). The full list,
  with each token's per-theme values and the foreground/background pairings the contrast gate
  enforces, is published as `@terpjs/contract/tokens.manifest.json` — read it rather than
  inferring names from the compiled sheet.
- **The accent is two tokens, and mixing them up is a contrast bug.**
  `--color-brand-primary` is the accent as a *filled surface*, and the only thing that may sit
  on it is `--color-brand-primary-contrast`. `--color-fg-accent` is the accent as *ink or a
  boundary* against one of the app's own surfaces — accent text, a selected-tab underline, a
  focus ring, a checkbox's `accent-color`. One token cannot do both: in a dark theme the
  surface use needs a value dark enough to hold a white label and the ink use needs one light
  enough to read on a dark canvas, and there is no value satisfying both.
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
| `ThemeProvider`, `ThemeToggle`, `useTheme` | Theming over the shipped palettes — `light`, `dark`, `midnight`, `twilight`, `contrast` — plus `system` to follow the OS preference. Applies `data-theme` on `<html>` (the token stylesheet carries every palette) and persists the choice. `defaultTheme` is how an app ships on a named theme — declare it in `layout-contract.json` so a tool can read and rewrite it, or pass the bootstrap option; both is refused. `renderTerpApp` mounts it for every app; the shell header uses an icon-only, token-themed `variant="inline"` menu. |
| `LocaleProvider`, `LanguageSwitcher`, `useLocale`, `LOCALE_EN`, `LOCALE_NL` | The language seam over `UiTextProvider`: per-locale string catalogs, a persisted active locale, and an icon-only, token-themed menu in the shell header once an app declares a second locale. English and Dutch catalogs ship complete; `renderTerpApp({ locales })` wires them. |
| `UserMenu`, `userInitials` | The signed-in user's menu, pinned by `buildAppRouter` to the bottom of the sidebar: an initials avatar trigger opening the identity block, **Settings** (the built-in profile page) and sign-out. Collapses to the avatar in the icon rail. |
| `ProfileView` | The built-in profile / settings page (`/profile`): the server-validated identity, theme + language preferences, and sign-out. |

## Authorization gates (UI-side; the backend re-checks)

| Export | Use |
|---|---|
| `Authorized`, `useCan` | Gate UI on `can(module, action)` — write buttons, admin panels. |
| `usePermissions`, `useHasPermission` | The caller's **named** grants from `GET /me` (ADR 0096), for a screen whose write needs `definitions.publish` rather than a rank. `Authorized` takes an optional `permission` alongside `action`; both must pass, as the server's own guard does. Display only — the backend re-checks. |
| `canPerform`, `DEFAULT_RANK_THRESHOLDS` | The role-rank predicate behind the gate. |
| `visibleNav` | Filter nav items to what the current user may see. |

## Page archetypes (the three-level screen pattern)

Every routed view **must** render one of the archetypes (`Page`, or `OverviewPage` /
`DetailPage` / `HubPage` / `FormPage` / `SettingsPage` / `SplitPage`, which compose it) — `buildAppRouter` refuses an unframed view at
runtime, fail closed (ADR 0059), so every screen keeps the breadcrumb/title/error frame.

| Export | Use |
|---|---|
| `AppShell` | The responsive level-1 frame: a home-linked brand, icon/label nav and account footer. Desktop collapses to a persisted, scrollbar-free rail with one fixed icon slot; mobile becomes a scroll-locking drawer. The sticky header holds the sidebar toggle and icon-only preferences. Router-agnostic link renderers receive framework-owned expanded/collapsed geometry. |
| Shell geometry (tokens, not props) | `--shell-sidebar-width-expanded` / `-collapsed`, `--shell-header-height`, `--shell-content-max-width` and `--shell-brand-size` are published contract tokens: an app moves them from its own unlayered `theme.css` with no prop at all, and the Studio gets them from the manifest. |
| `logo` / `logoDark` (shell) | The brand mark, rendered in a box of `--shell-brand-size` so an asset larger than the 4rem icon rail is scaled rather than clipped — which is why there is no separate collapsed-mark slot: `logo` is the mark, `title` is the wordmark, and the rail already hides the second. `logoDark` is for a fixed-colour mark that cannot survive a dark theme; both render and the stylesheet shows one, switched on `--appearance-show-light` / `--appearance-show-dark`, which the token build emits from each theme's declared `appearance`. Resolving it in React would be wrong: the theme is `<html data-theme>` and an app may set it with no provider mounted. |
| `density` (shell) | App-wide `"comfortable"` or `"compact"`, stamped on the shell root; every control height and cell padding follows by token inheritance. **No default** — omitting it stamps nothing, so an app's own `data-density` on `<html>` still wins. A subtree may override it: a `DataView density="comfortable"` inside a compact shell really is comfortable, because comfortable now has named tokens and a rule rather than being the absence of an attribute. |
| Skip to content | The shell renders the skip link and owns the landmarks it skips: `main` carries `tabIndex={-1}` and a per-instance id, so activating the link *moves focus* rather than only scrolling and two shells on one page get two distinct targets. It is not rendered while the mobile drawer is open — the drawer is `aria-modal` and its target sits inside the `inert` column. |
| `defaultDrawerOpen` (shell) | Opens the mobile drawer on mount. A dev/specimen affordance — an app opening it on load shows every mobile user a menu they did not ask for — and the only way to render the drawer's own geometry and backdrop at all, since below the breakpoint the sidebar exists only while the drawer is open. |
| `headerActions` (shell) | Extra header content before the theme and language controls. Now forwarded by `renderTerpApp` and `buildAppRouter`; it was previously reachable only by dropping to `TerpProvider` + `buildAppRouter` by hand. |
| `permission` (nav + route) | A named grant from `CurrentUser.permissions`, **ANDed** with `role` — the same composition `Authorized` ships, because a server `Policy` carrying a `Permission` enforces the permission's role floor *and* the grant. Declared on both `NavItem` and `ModuleRoute`, so a hidden link never leaves a reachable route. Fails closed three ways: signed out, unknown name, and an app with no grant capability (empty list). Not a combinator — the server's own `AuthzRef` is one ref per read and one per write, so an any-of could express a gate no `Policy` can declare. |
| `activeNavPath` / `isNavItemActive` | Which nav item is current, as one predicate. Longest **segment-aligned** match wins across the set, because "at most one is current" cannot be decided one link at a time — a router marks every prefix-active link, so `/settings` and `/settings/users` are both current at `/settings/users`. `NavItem.exact` narrows a single item to itself. Search and hash are ignored: a tab's identity is its path, so filtering a list must not unhighlight it. |
| `groupNav` / `NavGroup` | The app declares named sections (`{ id, label, order }`); modules point items at them with `NavItem.group`, and `NavItem.order` sorts within one. A group spans modules, so no module can own its label or position — which is why this is the one part of the navigation model that is not on a module manifest. Additive: declare none and the sidebar is the flat list it is today. Absent `order` is 0 and the sort is stable (CSS `order` semantics), an item naming an undeclared group falls **open** into the ungrouped bucket rather than vanishing, a group left empty by `role`/`permission` filtering renders nothing at all, and the ungrouped bucket is emitted **last** so the packaged `/admin` entry stays where it already is. A `label: null` group renders no heading — pure positioning. Declare the groups in `layout-contract.json` under `shell.navGroups` (where `label: ""` is how a file spells `null`) so a tool can read and rewrite them, or pass the bootstrap option; both is refused. |
| `navPlacement` (shell) | Where the primary navigation lives on desktop: `"sidebar"` (default, stamps nothing) or `"header"` — a horizontal row in the header with no sidebar at all, for an app whose destinations are few enough that 15rem of permanent chrome is a tax. The header then *becomes* the sidebar surface, so every `--color-sidebar-*` an app themes carries over and no property is overridden. Below the mobile breakpoint both placements are the drawer. `defaultCollapsed` is `never` under `"header"`: with no sidebar there is nothing to collapse. Available on `AppShell`, `buildAppRouter` and `renderTerpApp`. |
| `contentWidth` (shell) | `"measured"` caps routed content at `--shell-content-max-width` while each page's own header keeps the full track — the subheader band. Default `"full"` stamps no attribute, so nothing moves until an app asks. Available on `AppShell`, `buildAppRouter` and `renderTerpApp`. |
| `NavIcon`, `Icon`, `TerpMark`, `ICON_GLYPHS`, `ICON_NAMES` | The dependency-free icon layer. `ICON_NAMES` is published by `@terpjs/contract` as data and `IconName` is derived from it, so `NavItem.icon` and `Icon`'s `name` are **checked names** — a typo is a typecheck error, not a picture of nothing. `NavIcon`'s `name` stays a plain `string` on purpose: its unknown-name behaviour is a designed, visible fallback (the label's initial in a tile), while `Icon` rendered an empty box. The glyph table is held to the name set exhaustively in both directions by `satisfies`, so a glyph without a name or a name without a glyph fails to compile. The bundled catalogue covers common UI, action, object and status glyphs (home, list, folder, users, plus, edit, trash, search, check, x, chevron-{left,right,down}, arrow-left, external, logout, user, bell, key, globe, lock, tag, mail, refresh, filter, download, upload, star, heart, database, code, truck, cart, wallet, map-pin, clock, link, grid, book, briefcase, building, clipboard, layers, send, phone, image, video, music, wrench, zap, …). `TerpMark` is the placeholder brand mark until an app passes its own `logo`. |
| `Page` | The base routed screen: optional breadcrumb row, then one compact `h1` + intrinsic-width actions row (title-first on narrow layouts), then the body with loading/error slots. |
| `HubPage`, `HubCard` | Responsive `auto-fit` landing grid. Cards share equal outer and internal tracks even when descriptions/stats differ; nested hubs use the ordinary breadcrumb contract via `parents`. |
| `OverviewPage` | A module's top-level listing screen (level 2); detail pages crumb back to it. |
| `DetailPage` | One record's screen (level 3); breadcrumb trail = ancestors + record title. |
| `FormPage` | A create-or-edit screen. `measure="narrow"` by default, so the whole frame — header, actions and all — caps at 32rem over a single column of controls. Its body slot takes the form container (`Stack as="form"`), plus `Grid` / `Card` / `Divider` / `Text`; a bare `Field` at the top level is refused, because a run of fields has no `<form>` and cannot be submitted. |
| `SettingsPage` | Preferences and account screens: `Card` sections, also `measure="narrow"`. No `DataView`, `DetailList` or `Tabs` — a settings screen whose body is a collection is an overview with the wrong chrome. `parents` is optional, unlike `FormPage`'s. |
| `SplitPage`, `SplitPane` | A list beside the record it selects. The archetype owns the pane row and admits **only** `SplitPane` in it (`HubPage`'s shape, not `DetailPage`'s), so the panes are the governed thing. `listWidth` is a step — `sm` / `md` / `lg` — not a length; a draggable divider waits for the preference seam. Each pane is a named `<section>`, and below the mobile breakpoint they stack list-first, so the reading order and the tab order agree at both widths. |
| `Breadcrumbs` | The trail itself (used by the archetypes; rarely composed directly). Ancestor crumbs use the router's `Link` by default — `renderLink` is only for rendering outside a Terp router. |
| `NavLinkContext`, `useNavLink` | The ambient link renderer `buildAppRouter` publishes (and the layout components default to); provide it yourself in a standalone story/test tree or a bespoke shell. |
| `useRouteParam` | Read one route param, fail closed: the declared param comes back as a string, an undeclared name throws a directive error instead of silently yielding `undefined`. Replaces the unchecked `useParams({ strict: false }) as {…}` cast (ADR 0092). Checked against the generated route table when the app has one. |
| `useRouteParams` | Read a whole declared route's params, typed exactly: `const { recordId } = useRouteParams("/records/:recordId")`. With a generated route table, a typo in the path *or* a param name is a typecheck error. |
| `useTerpNavigate` | Navigate by manifest path: `navigate({ to: "/records/:recordId", params: { recordId } })`. An undeclared path is a typecheck error and a parameterised route requires its params — a typo'd path used to be a dead link that shipped green. Takes the manifest's `:id` spelling and translates to the router's `$id`. |
| `useRouteSearch` | Read a declared route's query-string keys, typed: `const { status, page } = useRouteSearch("/records")` (ADR 0096). Every value is `string | undefined`, and an undeclared key is a typecheck error — so a filtered list screen stays inside the checked seam instead of reaching for the router's own `useSearch`. Declare them in the manifest: `search: ["status", "page"]`. |
| `ModuleNav` | Secondary horizontal tabs for intra-module sub-pages (real routes, not state). |
| `PageActions` | Primary action + overflow menu for a page header. |

### Typed route paths and params (generated, ADR 0092)

`buildAppRouter` realises routes at runtime from manifest data, which leaves TanStack
Router's type registry empty: nothing checks a route path or a param name, so a typo'd
path is a dead link and a typo'd param silently reads `undefined`. The manifests are
static data, so the check is generated from them:

```bash
npm --prefix frontend run routes     # or: uv run terp routes
```

`terp-routes` reads every `src/modules/<name>/module.tsx` manifest and writes a
**committed** `src/routes.gen.d.ts` that augments `TerpRouteTable`:

```ts
declare module "@terpjs/react-core" {
  interface TerpRouteTable {
    "/records": Record<never, never>;
    "/records/:recordId": { recordId: string };
  }
}
```

From then on `useRouteParams("/records/:recordId")` is exact, `useRouteParam` refuses a
param no route declares, `useRouteSearch` is keyed to the route's declared query-string
keys, and `useTerpNavigate` refuses an undeclared path (or an undeclared `search` key). Regenerate
after changing a manifest route — `terp verify`'s `routes-drift` check refuses a stale
table and names the command (it runs before the typecheck, so a stale table reads as
"regenerate", not as errors in your own screens). A route whose `path` is not a plain
string literal is refused with its file and line rather than silently omitted: a partial
table would turn a real path into a type error. Routes a packaged area mounts (the admin
area) are not keyed — the file stays a pure function of the app's own manifests. Without
a generated file every helper falls back to `string`, so adopting is opt-in: add the
`routes` script, generate, commit.

### Slot-typed layout contracts (opt-in, ADR 0079)

An app can ratchet the archetype control further with a named **layout contract**,
declared once in a checked-in `layout-contract.json` next to the frontend sources
(`{ "contract": "standard" }`) and read by both halves: the `terp/layout-contract` lint
rule finds the file on disk, and `main.tsx` imports it —
`renderTerpApp({ layout })`. The same file carries the palette the app opens on
(`defaultTheme`) and the shell's own shape under `shell` (`density`, `navPlacement`,
`contentWidth`, the `navGroups` a module's `NavItem.group` names by id, and the `brand` marks
as paths), which is what lets a tool read and rewrite those choices instead of them living
only in TypeScript. Declaring a key in the file AND
passing the matching bootstrap option is refused when the router is composed, with both
sources named; `layoutContract: "standard"` on its own still works for an app that would
rather write code than check in a file. Each governed archetype's body slot then accepts **only** the contract's
components — `standard`: hub bodies hold `HubCard` only; overview bodies hold
`DataView` / `ResourceList` / `ModuleNav` / `Stack` / `Card` / `Divider` / `Text` plus
the framework states (`EmptyState` / `ErrorState` / `LoadingState` / `Alert`) and
`ConfirmDialog`; detail bodies hold `DetailList` / `Stack` / `Tabs` / `ModuleNav` /
`DataView` / `Card` / `Grid` / `Divider` / `Text` plus the same states. The asymmetry is
deliberate and pinned by tests rather than left to the table: `Grid` joins **detail**
bodies only (an overview body is a collection, and a grid of summary cards is a hub,
which has its own archetype), while `Heading` joins **neither** — a heading in a governed
body must own its section, and `Card` is how a section is owned. The plain `Page` stays
unconstrained (the sanctioned home for a bespoke screen). Only the slot's **direct** children are governed — an allowed
container's own subtree (a `Card` body, a `Stack` of rows) is the app's to compose.
Enforcement is two-layer and fail-closed: the lint rule checks static JSX
children; the archetypes verify the rendered DOM (sanctioned components stamp a
`data-terp` marker) and refuse a non-conforming view with the **same directive
message** — contract, slot, what was found, what is allowed, and the fix — so a
failing check tells the author (human or agent) exactly how to build the screen.
`LAYOUT_CONTRACTS` exports the table; no config means no checks (fully backwards
compatible). Every exported archetype must appear in it or name its reason for not
appearing — an archetype missing from the table is silently ungoverned by both halves,
which used to be a green build. The one opt-out is a justified `// terp-allow-layout-contract: <reason>`
marker, counted by the escape-hatch budget.

## Data

| Export | Use |
|---|---|
| `DataView` + family | **The single sanctioned surface for data collections**: repository-driven table/card view with search, sorting, pagination, column management, selection + batch actions, row actions, expandable rows, persisted view preferences, and pointer/keyboard row activation for overview-to-detail navigation. See [`src/dataview/README.md`](src/dataview/README.md) for the full guide (client-side and server-side recipes). |
| `InMemoryDataViewRepository`, `HttpDataViewRepository` | Data repositories (client-side / server-side); `useServerDataView` keeps server query state in the URL. |
| `InMemoryViewStateRepository`, `LocalStorageViewStateRepository` | Preference persistence seam. |
| `useResource` | An async collection: rows + loading/error + reload + create-then-reload. |
| `useRecord` | The singleton counterpart of `useResource` — the one record a detail screen shows: `item` (or `null`) + loading/error + reload + mutate. Deletes the one-element-list wart (`list: async () => [unwrap(…)]` then `items[0]`). |
| `useRealtimeChannel` | The sanctioned typed SSE/WebSocket seam for the optional realtime capability: mints a short-lived one-use ticket via the authenticated generated client, validates every inbound JSON payload with the channel's runtime type guard, and exposes connection state / last message / WebSocket send. App modules never touch raw transports. |
| `ResourceList` | The standard simple CRUD list screen: titled section, write-gated create form, loading/error/empty states. Composable — screens needing more render their own React. |
| `unwrap`, `unwrapOptional`, `ApiError` | Turn a generated-client result into data-or-throw; `ApiError` carries the envelope's `code` / `status` / `requestId`, plus `fields` — the per-field reasons of a 422, keyed by dotted path, ready to hand to `Field`'s `error` prop (`{}` when the failure names no field). `unwrapOptional` returns `null` on a 404 instead — for resources whose absence is a normal state (a `/latest` snapshot not yet published), the client-side analog of `BaseService.find` beside `get`. |
| `useFormatDate`, `useFormatDateTime`, `useFormatNumber` (and locale-explicit `formatDate` / `formatDateTime` / `formatNumber`) | Render a date or a number in the **app's** locale. `toLocaleDateString()` with no argument asks the browser, so an app shipping one language renders its own tables in whatever the visitor's OS is set to. The hooks read `LocaleProvider` and are `useCallback`-stable, so a column list built in a `useMemo` can depend on one. An absent or unparseable value renders as an em dash rather than throwing. |
| `FileUpload`, `useFileDownload` | The files-capability surface (ADR 0056/0057): a token-styled attachment picker that uploads through the typed client, and an authenticated download helper (a raw `<a href>` would carry no bearer token). |
| `useEndpointDownload`, `saveBlob` | Download an artifact the backend **generates** — an evidence bundle, a CSV export — which has no stored file id (ADR 0096). Goes through the session client, so it carries the base URL and bearer token and rejects a non-2xx instead of saving the error body under the intended filename. |

## Feedback & states

| Export | Use |
|---|---|
| `LoadingState`, `InlineSpinner` | Full loading block (announces itself) / compact inline glyph. |
| `EmptyState` | The standard "nothing here yet" block, with an `action` slot for the next step. |
| `ErrorState`, `describeError` | Human-readable failure block for a caught error. |
| `ErrorMessagesProvider`, `useErrorMessage`, `DEFAULT_ERROR_MESSAGES` | Map stable backend error codes to copy; falls back to the envelope `detail`. |
| `ToastProvider`, `useToast` | Transient success/error feedback (no toast library). |
| `ConfirmDialog` | Accessible confirmation modal (native `<dialog>`); use before any destructive action. A modal is for a confirmation or an explicit post-action moment — an edit form or a detail view belongs in a routed page, or in an expanded row beside the thing it edits (ADR 0096 §4). |

## Forms & primitives

| Export | Use |
|---|---|
| `Button` | Token-styled command: `variant` (primary / secondary / danger / ghost), `size` (sm / md / lg, composing with density), `loading` (spinner in the icon slot, `aria-busy`, and disabled so a second click cannot start the request twice), `fullWidth` to fill the container instead of the label, and an optional leading `icon`. Content-sized by default. |
| `Input`, `Select`, `Textarea` | Token-styled controls with stable framework typography, independent of surrounding display text (raw elements are lint-refused). Numeric inputs suppress unthemeable browser steppers. `Input type="password"` grows a reveal toggle — the type decides, so there is no second export and no prop; an app could not add one itself, because the toggle needs a positioned wrapper and module files may use neither `style` nor `className`. |
| `Select` options (`SelectOption<T>`) | Two forms. Pass `options={[{ value, label, disabled? }]}` with `onValueChange` when the choices are data — `T` is inferred from the list, so a closed enum is checked at both ends and the `event.target.value as Status` cast goes away; `placeholder` renders the disabled empty-valued leading row. Or pass `<option>` children as before. The two are mutually exclusive at the type level, so neither can silently ignore the other. |
| `Combobox` | Accessible autocomplete/typeahead single-select: filterable options, controlled or uncontrolled value, loading state, disabled state, and ARIA combobox/listbox keyboard navigation. |
| `DatePicker`, `DateRangePicker` | Locale-aware calendar popover controls with keyboard-navigable month grids, min/max bounds, and range selection for ERP date filters. |
| `Checkbox` | Labelled checkbox with `checked` / `defaultChecked` and boolean `onChange`. |
| `Radio`, `RadioGroup` | Labelled radio and accessible grouped radio options with controlled or uncontrolled value. |
| `Switch` | Labelled boolean toggle (`role="switch"`) with `checked` / `defaultChecked` and boolean `onChange`. |
| `Tabs` | In-page (non-routed) tab set with `tablist` / `tab` / `tabpanel` roles, arrow-key navigation, and controlled or uncontrolled value. |
| `Avatar` | The initials tile: `from` (an email or a name) or explicit `initials`, and a closed `size` of `sm` (2rem, an account menu) or `md` (3.5rem, a profile header). `aria-hidden`, because the name it abbreviates is always rendered beside it. No `src`: `/me` carries no avatar URL, so an image slot would be a prop with nothing behind it. |
| `Badge` | Small status pill: `<Badge tone="success">Synced</Badge>` (or `label="Synced"`); `tone`: neutral / info / success / warning / danger. |
| `Tooltip` | Accessible focus/hover tooltip that describes its trigger with `aria-describedby`. |
| `Popover`, `Menu`, `MenuItem` | Shared anchored overlay and dropdown-menu primitives: body-portaled, viewport-aware panels that escape scroll/table clipping, with outside-click/Escape close, focus return, selected-item semantics, and roving keyboard navigation. |
| `Alert` | Inline banner for persistent feedback (`tone`: neutral / info / success / warning / danger); warnings and danger announce as `alert`, others as `status`. |
| `Markdown` | Safe, dependency-free markdown renderer for headings, paragraphs, bold, italic, inline code, code blocks, lists, and safe links; raw HTML is rendered as text and never passed through. |
| `Field` | Label + control + hint/error wrapper for one form field. The error is announced (`role="alert"`) as well as described, because `aria-describedby` alone is silent for a rejection that arrives after focus has left the control. |

## Layout

Modules never write `style={}` or CSS — the boundary lint refuses the `style`
attribute in `src/modules/**`. Layout comes from these primitives (gaps index the
token spacing scale, so spacing is themed centrally):

| Export | Use |
|---|---|
| `Stack` | The layout primitive: a flex container with a token gap. Vertical by default (forms, sections); `direction="row"` + `justify` for toolbars; `as="form"` etc. for semantics. `padding` insets on the same token scale; `direction` and `gap` also take a `{ narrow, wide }` pair, which changes over at the one viewport cutover the shell and the DataView already use. |
| `Grid` | The two-dimensional primitive, and the one that lifts a real ceiling — a two-column form could not be expressed at all before it. `columns` takes a fixed 1–4 or `"auto"` (the default), which reflows to whatever the **container** can hold with no breakpoint anywhere; `minColumn` is the track floor for `auto`; `gap` indexes the spacing scale; `align` is a closed four. Renders no inline style. No `span`, and therefore no twelve-column option — a span system needs a child component to carry it. |
| `Card` | A token-styled surface (border + background + padding) grouping one block of a page — the sanctioned visual separation between sections. Optional header row: `title` (semantic `<h3>`), muted `description`, `actions` slot. `variant="plain"` keeps the heading and drops the box, for a titled region inside something that is already a surface — a section whose body is a `DataView` gets a border inside a border otherwise. There is no separate `Section` or `Surface`: both are this element with declarations removed. |
| `Divider` | A rule between groups, as a semantic `<hr>` so the separation reaches the accessibility tree — `Separator` under its other name, shipped once. `orientation="vertical"` takes its height from its flex or grid line rather than inventing one, so it works between the items of a row `Stack` and is zero-height in a block parent. |
| `DetailList` | Token-styled label/value pairs as a semantic `<dl>` (record metadata, expanded-row summaries). A real grid: `layout="aligned"` puts every label in a shared column so the values line up, `"stacked"` puts the label above its value, and `columns` takes two pairs per row. Tracks are floored at zero and long values wrap, so a 64-character digest no longer pushes the list past its container. |
| `Heading` | A section heading inside a page body — `h2`–`h4`, with `size` a **separate** choice from `level` so a visually small `h2` is expressible without picking the wrong element. No level 1: `Page` renders the single `h1` of every routed view. |
| `Text` | Body copy with themeable ink — `tone` (default / muted / subtle), `size`, and an enumerable `measure` that caps the line length in `ch`. What a bare `<p>` in a module cannot be, since a bare element carries no marker for a rule to reach. |
| `Code` | An identifier or a snippet in the mono family. `block` wraps it in a focusable `<pre>`, which is what preserves the whitespace and what makes a long line scrollable by keyboard. |
| `Link` | A link with themeable ink, routing in-app paths through the surrounding router and degrading to a plain anchor outside one. An external `newTab` gets `rel="noreferrer"`. The boundary lint refuses a raw in-app `<a href="/…">`; this is the thing to use instead. |

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
