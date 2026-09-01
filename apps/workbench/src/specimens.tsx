import {
  Alert,
  AppShell,
  Badge,
  Breadcrumbs,
  Button,
  Card,
  Checkbox,
  Code,
  Combobox,
  ConfirmDialog,
  DataView,
  DataViewCardList,
  DataViewColumnSettings,
  DataViewPagination,
  DataViewRowActions,
  DataViewTable,
  DataViewToolbar,
  DatePicker,
  DateRangePicker,
  DetailList,
  DetailPage,
  FormPage,
  Divider,
  EmptyState,
  ErrorState,
  Field,
  Grid,
  Heading,
  NavLinkContext,
  HubCard,
  HubPage,
  Icon,
  InlineSpinner,
  InMemoryDataViewRepository,
  Input,
  LanguageSwitcher,
  Link,
  LoadingState,
  LoginView,
  Markdown,
  Menu,
  MenuItem,
  ModuleNav,
  NavIcon,
  OverviewPage,
  Page,
  PageActions,
  Popover,
  ProfileView,
  Radio,
  RadioGroup,
  ResourceList,
  Select,
  SettingsPage,
  SplitPage,
  SplitPane,
  Stack,
  Switch,
  Text,
  Tabs,
  TerpProvider,
  Textarea,
  ThemeToggle,
  ToastProvider,
  Tooltip,
  UserCreate,
  useToast,
  UserMenu,
} from "@terpjs/react-core";
import type { BadgeTone, DataViewColumn, DataViewRepository, Resource } from "@terpjs/react-core";
import type { IconName, NavGroup, NavItem } from "@terpjs/contract";
import {
  createMemoryHistory,
  createRootRoute,
  createRoute,
  Link as RouterLink,
  createRouter,
  RouterProvider,
} from "@tanstack/react-router";
import { useEffect } from "react";
import type { ReactNode } from "react";

// The specimen registry: every component the framework ships, in every variant it has, as
// data rather than as a hand-laid-out page.
//
// Two consumers read this list. A person opens the workbench to see what exists — there is
// no other catalog; the README table is prose. And the visual suite screenshots one
// specimen at a time, keyed by `id`, so a regression names the component that moved instead
// of failing one page-sized baseline that changes whenever anything changes.
//
// Rules for entries, because both consumers depend on them:
//   - Deterministic. No `Date.now()`, no random ids, no live data. A specimen that renders
//     differently on two runs makes its baseline worthless and trains people to re-record.
//   - Controlled, not interactive. Every stateful control is rendered at a fixed value, so
//     the shot is the state named in the title. Interaction is the e2e suite's job.
//   - One concern per specimen. Splitting `button-variants` from `button-disabled` means a
//     disabled-state change cannot mask a variant change in the same baseline.

export interface Specimen {
  /** Stable, file-safe id — the screenshot name derives from it, so renaming re-records. */
  id: string;
  /** What a reader is looking at. */
  title: string;
  node: ReactNode;
  /**
   * This specimen paints OUTSIDE its own box, so neither lane can see it by default.
   *
   * Four framework surfaces do it, by four different mechanisms: `Popover` portals its panel
   * to `document.body` (so it is not even a descendant of the specimen), a native `<dialog>`
   * opened with `showModal()` renders in the top layer, the toast viewport is `position: fixed`
   * at the corner of the screen, and the `Combobox` listbox is merely `position: absolute` —
   * the plainest case, and the one most likely to be missed. The screenshot lane clips to the
   * specimen element's bounding box and the axe lane scopes to it, so an open panel is out
   * of frame for one and out of scope for the other — a baseline that gates nothing while
   * looking like coverage, and for `ConfirmDialog` specifically a shot of a dimmed empty
   * card, because the `::backdrop` covers the clip and the dialog does not.
   *
   * Flagging one changes both lanes (see `visual/specimens.spec.ts` and `visual/a11y.spec.ts`)
   * and makes it render its node **only on the solo page** — see `SoloSpecimen` in
   * `src/main.tsx` for why the catalog cannot hold an open one.
   */
  overlay?: true;
  /**
   * Render this specimen at a viewport of its own, rather than the pinned 1280x900.
   *
   * The config pins the viewport so a baseline cannot depend on a window size, which is
   * right, and it also puts a whole class of declaration out of reach of both lanes: anything
   * that only applies at a width the pin is not. `styles.test.ts` says so about the shell in
   * as many words — the mobile drawer needs 768 or less, the sidebar's `flex-shrink` bites
   * only between the breakpoint and wide — and those rules were asserted as *text* because
   * "no baseline can hold it" was true.
   *
   * A per-specimen viewport is still fully determined by the specimen, so the per-specimen
   * promise is untouched: the size is declared here, next to the node, rather than being a
   * property of the machine or the run. It composes with `overlay`.
   *
   * Like `overlay`, a specimen with one renders its node **only on the solo page** — at the
   * catalog's width the render would be the wrong one under a title claiming otherwise, which
   * is worse than a link.
   */
  viewport?: { width: number; height: number };
  /**
   * A selector that must be visible before a lane reads this specimen.
   *
   * For a specimen whose content arrives asynchronously — anything mounting `TerpProvider`, so
   * anything behind the workbench's mock auth boot, and anything loading through a repository.
   * Both lanes wait for `[data-specimen="<id>"]`, and that wrapper always contains the title
   * paragraph and is visible on first paint, so waiting for it proves nothing about the
   * component underneath.
   *
   * The screenshot lane mostly survives that by accident: `toHaveScreenshot` keeps shooting
   * until two consecutive frames match, so it settles on the loaded state on its own. **The axe
   * lane does not.** It calls `.analyze()` once, with no stability retry, so it audits whatever
   * frame it finds — and measured, `resource-list` holds 97 characters at that moment and 118 a
   * beat later. Its three row actions had never been read by axe at all: a clean run over a
   * loading frame, reported as coverage.
   *
   * So this is not a flake guard. It is the difference between auditing the component and
   * auditing the space where it will be.
   */
  ready?: string;
}

export interface SpecimenGroup {
  id: string;
  title: string;
  specimens: Specimen[];
}

/**
 * A visible cell for the grid specimens.
 *
 * Grid tracks are invisible by themselves, so a specimen of a grid needs something with an
 * edge in every cell or the picture is a paragraph of labels. `lines` makes a cell taller
 * than its neighbours, which is the only way the alignment rules paint differently from each
 * other at all.
 *
 * Inline styles, which is legal here and would not be in react-core: this is the workbench's
 * own scaffolding rather than a component, and `markers.test.ts` scans the package, not this
 * app. It is deliberately NOT a `Card` — a Card would put a real component's geometry between
 * the reader and the tracks being demonstrated.
 */
function GridCell({ label, lines = 1 }: { label: string; lines?: number }) {
  return (
    <div
      style={{
        background: "var(--color-neutral-100)",
        border: "1px solid var(--color-neutral-300)",
        borderRadius: "var(--radius-sm)",
        padding: "var(--space-2)",
        fontSize: "var(--font-size-xs)",
        color: "var(--color-neutral-700)",
      }}
    >
      {Array.from({ length: lines }, (_, index) => (
        <div key={index}>{index === 0 ? label : " "}</div>
      ))}
    </div>
  );
}

const BUTTON_VARIANTS = ["primary", "secondary", "danger", "ghost"] as const;
const TONES = ["neutral", "info", "success", "warning", "danger"] as const;

/** A fixed instant, so the date controls never re-record themselves overnight. */
const FIXED_DATE = new Date(Date.UTC(2026, 0, 15));
const FIXED_RANGE_END = new Date(Date.UTC(2026, 0, 22));

/**
 * A range that CROSSES a month boundary, for the open calendar.
 *
 * Not decoration: a day that is both outside the visible month and inside the range paints the
 * subtle ink on the accent wash, and that pairing failed WCAG AA in two of the five themes
 * until it was given the muted ink. An in-month range cannot produce the state, so the picture
 * of it — and the axe run over it — needs a range that spans two months. Shown from December,
 * so January 1-5 are the dimmed in-range cells.
 */
const FIXED_CROSS_START = new Date(Date.UTC(2025, 11, 28));
const FIXED_CROSS_END = new Date(Date.UTC(2026, 0, 5));

const SELECT_OPTIONS = [
  { value: "draft", label: "Draft" },
  { value: "published", label: "Published" },
  { value: "archived", label: "Archived" },
];

// `AppShell` takes `renderLink` as a prop precisely so it does not depend on a router, which
// is what lets the shell render here at all — a plain anchor is enough for a still image.
// A brand asset that does NOT theme, which is the case the light/dark pair exists for. Fixed
// hexes on purpose: the bundled icons all stroke in currentColor and need no pair at all, so a
// specimen drawn that way would paint the switch and prove nothing about it.
const BRAND_MARK_LIGHT = (
  <svg width="28" height="28" viewBox="0 0 28 28" role="img" aria-hidden="true" focusable={false}>
    <rect width="28" height="28" rx="7" fill="#0f172a" />
    <path d="M8 19 14 8l6 11Z" fill="#ffffff" />
  </svg>
);

const BRAND_MARK_DARK = (
  <svg width="28" height="28" viewBox="0 0 28 28" role="img" aria-hidden="true" focusable={false}>
    <rect width="28" height="28" rx="7" fill="#f8fafc" />
    <path d="M8 19 14 8l6 11Z" fill="#0f172a" />
  </svg>
);

const SHELL_NAV: readonly NavItem[] = [
  { label: "Overview", to: "/", icon: "home" },
  { label: "Records", to: "/records", icon: "list" },
  { label: "Reports", to: "/reports", icon: "layers" },
  { label: "Admin", to: "/admin", icon: "shield" },
];

// The same destinations, grouped. Deliberately the same four items as SHELL_NAV so the grouped
// baselines differ from the flat ones in exactly the thing being added, and deliberately leaving
// "Admin" ungrouped — that is the packaged admin entry's real shape (no app authors it, so no app
// can give it a `group`) and it is what puts the ungrouped bucket in the picture at all.
const SHELL_NAV_GROUPED: readonly NavItem[] = [
  { label: "Overview", to: "/", icon: "home", group: "work" },
  { label: "Records", to: "/records", icon: "list", group: "work" },
  { label: "Reports", to: "/reports", icon: "layers", group: "insight" },
  { label: "Admin", to: "/admin", icon: "shield" },
];

// Three groups declared and only two rendered: nothing references "archive", so it is emitted
// nowhere. That is the empty-group rule in a picture, and it is the reachable form of it — a
// specimen cannot empty a group by ROLE, because specimens hand `nav` straight to the shell and
// `visibleNav` only ever runs inside `buildAppRouter`.
const SHELL_NAV_GROUPS: readonly NavGroup[] = [
  { id: "work", label: "Werkruimte" },
  { id: "insight", label: "Inzicht" },
  { id: "archive", label: "Archief" },
];

// The auth-gated specimens (`UserMenu`, `ProfileView`, `ResourceList`'s write gate,
// `LoginView`) mount their own `TerpProvider` against the dev server, whose
// `workbench-mock-auth` middleware (see vite.config.ts) answers the boot with the same
// fixed administrator on every run — the determinism rule, applied to the session.
function SignedIn({ children }: { children: ReactNode }) {
  return <TerpProvider baseUrl="">{children}</TerpProvider>;
}

// DataView fixtures: a fixed row set through the package's own in-memory repository, so
// the collection specimens exercise the real toolbar/table/pagination composition with
// no fetch and no clock.
interface SyncRow {
  id: string;
  name: string;
  status: "ok" | "failed" | "paused";
  rows: number;
}

const SYNC_ROWS: SyncRow[] = [
  { id: "s1", name: "Customer master", status: "ok", rows: 1284 },
  { id: "s2", name: "Sales orders", status: "failed", rows: 407 },
  { id: "s3", name: "Warehouse stock", status: "paused", rows: 52 },
  { id: "s4", name: "Ledger entries", status: "ok", rows: 9310 },
];

const SYNC_TONES: Record<SyncRow["status"], BadgeTone> = {
  ok: "success",
  failed: "danger",
  paused: "warning",
};

const SYNC_COLUMNS: DataViewColumn<SyncRow>[] = [
  // The mobileSlot meta is what the card layout composes a default card from; without it
  // DefaultCardBody renders an empty card, which is why the card specimens below could
  // not have existed before it. It changes no table specimen: nothing else reads it.
  { id: "name", header: "Name", accessor: (row) => row.name, meta: { mobileSlot: "title" } },
  {
    id: "status",
    header: "Status",
    accessor: (row) => row.status,
    cell: (row) => <Badge tone={SYNC_TONES[row.status]} label={row.status} />,
    meta: { mobileSlot: "status" },
  },
  {
    id: "rows",
    header: "Rows",
    accessor: (row) => row.rows,
    meta: { mobileSlot: "subtitle" },
  },
];

const syncRepositoryOptions = {
  getRowId: (row: SyncRow) => row.id,
  getValue: (row: SyncRow, columnId: string) => row[columnId as keyof SyncRow],
  searchFields: ["name"],
};

const SYNC_REPOSITORY = new InMemoryDataViewRepository(SYNC_ROWS, syncRepositoryOptions);

/**
 * Four columns whose CONTENT is one character each, so nothing about the data can explain their
 * widths. Three declare a step and the fourth declares nothing, which is what makes the picture
 * readable: the declared tracks hold a floor a single digit could never justify, and the last
 * column takes whatever is left.
 *
 * The headers are two letters for the same reason. `th` is `white-space: nowrap`, and that is the
 * minimum the workbench already measured as the thing which actually sizes this table — nine long
 * headers put `dataview-wide` at 1447px. A long header here would size the column instead of the
 * step, and the specimen would gate the wrong mechanism.
 */
interface StepRow {
  id: string;
  xs: string;
  sm: string;
  md: string;
  auto: string;
}

const STEP_ROWS: StepRow[] = [
  { id: "1", xs: "1", sm: "2", md: "3", auto: "4" },
  { id: "2", xs: "5", sm: "6", md: "7", auto: "8" },
];

const STEP_REPOSITORY = new InMemoryDataViewRepository(STEP_ROWS, {
  getRowId: (row: StepRow) => row.id,
  getValue: (row: StepRow, column: string) => row[column as keyof StepRow],
});

const STEP_COLUMNS: DataViewColumn<StepRow>[] = [
  { id: "xs", header: "Xs", accessor: (row) => row.xs, meta: { width: "xs" } },
  { id: "sm", header: "Sm", accessor: (row) => row.sm, meta: { width: "sm" } },
  { id: "md", header: "Md", accessor: (row) => row.md, meta: { width: "md" } },
  { id: "auto", header: "No", accessor: (row) => row.auto },
];


/**
 * The split's list rows. Plain strings rendered as buttons: focusable, so the keyboard lane has
 * a tab sequence to assert, and long enough that the pane's track and its `min-width: 0` are
 * both under real content pressure. Nothing here waits on a session.
 */
const SPLIT_ROWS = ["Customer master", "Sales orders", "Warehouse stock", "Ledger entries"];

/**
 * A redacted audit payload, formatted the way `AuditLogAdmin` formats one
 * (`JSON.stringify(payload, null, 2)`), with two lines deliberately past the box's width.
 *
 * The long lines are the whole point: `code-block` declares `overflow-x: auto`, and a
 * `<pre>` whose longest line fits paints identically without it. 204 and 203 characters
 * including their indent, which is well past the 34rem container the specimen constrains them
 * to — see the audit-payload specimen for what happens when nothing constrains it. Written as a literal
 * rather than stringified from an object so the exact rendered characters — and therefore the
 * baseline — are fixed by this file and not by the runtime's key ordering.
 */
const AUDIT_PAYLOAD = `{
  "action": "update",
  "target_type": "sync_definition",
  "before": { "window": "01:00-03:00 UTC", "retention_days": 30, "target": "terp://ledger/customers", "source": "sap://prd/customers", "cursor": "0x00000000000004d2", "checksum": "9f2c1b7e4a83d015c6b2" },
  "after": { "window": "02:00-04:00 UTC", "retention_days": 90, "target": "terp://ledger/customers", "source": "sap://prd/customers", "cursor": "0x00000000000004d2", "checksum": "1a77e0c93b4d528fa610" },
  "redacted": ["credential_ref"]
}`;
const EMPTY_REPOSITORY = new InMemoryDataViewRepository<SyncRow>([], syncRepositoryOptions);

// The two repositories nothing else in the catalog can produce, and both are hand-built rather
// than InMemory instances because InMemory always resolves. `useDataViewQuery` starts both
// `isLoading` and `isFetching` at true and only a settled promise clears them, so the first-load
// and failed states ARE the promise — no clock, no timer, nothing to flake.
const NEVER_REPOSITORY: DataViewRepository<SyncRow> = {
  query: () => new Promise(() => {}),
  getRowId: (row) => row.id,
  capabilities: { serverSide: false, search: true, searchScope: false },
};

// A fresh rejection per call, not one module-scope rejected promise: the hook attaches its
// handler inside an effect, so a promise rejected at module load would be unhandled for a tick
// and Vite would log it. The message is fixed and there is no stack, which is what makes the
// shot deterministic — ErrorState derives its copy from the message.
const FAILING_REPOSITORY: DataViewRepository<SyncRow> = {
  query: () => Promise.reject(new Error("Sync service unavailable.")),
  getRowId: (row) => row.id,
  capabilities: { serverSide: false, search: true, searchScope: false },
};

// A table too wide for its box, and the width comes from the HEADERS. None of these nine columns
// declares a track, deliberately: this specimen exists to picture what `th { white-space: nowrap }`
// alone does, and a declared step would add a floor of its own and muddle the two. Measured at
// every step, because the lever that looks obvious does nothing: the table rule is `width: 100%`
// with `table-layout: auto`, so a specified column WIDTH is a *preference* the auto algorithm
// shrinks to fit — three columns hinted at 700px each recorded a baseline that fits the box
// exactly. That measurement is why `meta.width` is a `min-inline-size` step now rather than a
// width (see the dataview-column-steps specimen). What auto layout cannot shrink is a MINIMUM,
// and `th { white-space: nowrap }` is one, while the body cells wrap and clip and so contribute
// almost nothing. The specimen card leaves 1196px; nine un-wrappable uppercase headers put the
// table's min-content at 1447px, measured by squeezing the wrapper to 1px and reading its
// scrollWidth. Seven headers came to 1086 and fit — which is why the count is nine and not seven.
// Shortening a header here can silently make this specimen fit again, and a fitting table gates
// nothing: re-measure if one changes.
const WIDE_SYNC_COLUMNS: DataViewColumn<SyncRow>[] = [
  { id: "name", header: "Integration name", accessor: (row) => row.name },
  {
    id: "status",
    header: "Last run status",
    accessor: (row) => row.status,
    cell: (row) => <Badge tone={SYNC_TONES[row.status]} label={row.status} />,
  },
  { id: "rows", header: "Rows transferred", accessor: (row) => row.rows },
  { id: "source", header: "Source system endpoint", accessor: (row) => `sap://prd/${row.id}` },
  { id: "target", header: "Target system endpoint", accessor: (row) => `terp://ledger/${row.id}` },
  { id: "window", header: "Scheduled run window", accessor: () => "02:00–04:00 UTC" },
  { id: "rejected", header: "Records rejected on last run", accessor: (row) => row.rows % 7 },
  { id: "retention", header: "Retention policy in days", accessor: () => 90 },
  { id: "owner", header: "Responsible operations team", accessor: () => "Integrations" },
];

// ResourceList fixtures: a hand-built, already-loaded `Resource`, exactly the shape the
// hook returns — no timers, no state.
interface LinkItem {
  id: string;
  name: string;
}

const noop = async () => {};

const LINK_RESOURCE: Resource<LinkItem, string> = {
  items: [
    { id: "1", name: "Customer master" },
    { id: "2", name: "Sales orders" },
    { id: "3", name: "Warehouse stock" },
  ],
  loading: false,
  error: null,
  cause: null,
  reload: noop,
  create: noop,
  mutate: noop,
};

const EMPTY_RESOURCE: Resource<LinkItem, string> = {
  items: [],
  loading: false,
  error: null,
  cause: null,
  reload: noop,
  create: noop,
  mutate: noop,
};

// The failed create, and the only shape that paints ResourceList's `role="alert"` line: the
// items are still listed and the write-gated form is still there, because a create that
// failed changes neither. `cause` stays null so the copy is the resource's own string — the
// code-to-copy map is exercised by `dataview-error`, and pinning a code here would make this
// baseline depend on that table.
const FAILED_RESOURCE: Resource<LinkItem, string> = {
  items: LINK_RESOURCE.items,
  loading: false,
  error: "Could not save the link. Try again.",
  cause: null,
  reload: noop,
  create: noop,
  mutate: noop,
};

// `ModuleNav` reads the live pathname from TanStack Router (it marks the active tab), so
// its specimen renders inside a minimal memory router pinned to "/records" — which is also
// what puts the active-tab state in the picture. Everything else in the workbench stays
// router-free on purpose; this is the one component whose render requires one.
function moduleNavSpecimen(): ReactNode {
  const rootRoute = createRootRoute({
    component: () => (
      <ModuleNav
        items={[
          { label: "Overview", to: "/records" },
          { label: "Mapping", to: "/records/mapping" },
          { label: "History", to: "/records/history" },
        ]}
      />
    ),
  });
  const router = createRouter({
    routeTree: rootRoute,
    history: createMemoryHistory({ initialEntries: ["/records"] }),
  });
  return <RouterProvider router={router} />;
}

/**
 * Mounts a packaged admin screen the way the app does: a memory router whose route tree
 * carries the real `/admin/...` paths, inside the provider stack those screens read.
 *
 * All three pieces are load-bearing rather than defensive. `UserCreate` calls
 * `useNavigate`, so it cannot render without a router at all. Its breadcrumb trail renders
 * TanStack `Link`s at `/admin` and `/admin/users`, so those paths have to EXIST in the tree
 * or every render logs an unmatched-route warning — the specimen would still screenshot,
 * which is exactly why the routes are registered rather than left to warn. And `TerpProvider`
 * is here because the screen reads `useTerpClient`.
 *
 * What this screen does NOT do is fetch its own data: the form only POSTs on submit, and a
 * specimen never submits. It is not network-free — `TerpProvider` boots by exchanging the
 * refresh cookie and loading `/me`, two requests the dev server's own `workbench-mock-auth`
 * plugin answers with a fixed user (see vite.config.ts, which exists for exactly this). The
 * distinction that matters for a specimen is narrower than "no network": nothing the SCREEN
 * renders depends on a response arriving.
 */
function adminScreenSpecimen(node: ReactNode, path: string): ReactNode {
  const rootRoute = createRootRoute();
  const routes = ["/admin", "/admin/users", "/admin/users/new", "/admin/users/$userId"].map(
    (routePath) =>
      createRoute({
        getParentRoute: () => rootRoute,
        path: routePath,
        component: () => (routePath === path ? node : null),
      }),
  );
  const router = createRouter({
    routeTree: rootRoute.addChildren(routes),
    history: createMemoryHistory({ initialEntries: [path] }),
  });
  return (
    <TerpProvider baseUrl="">
      <ToastProvider>
        <RouterProvider router={router} />
      </ToastProvider>
    </TerpProvider>
  );
}

/**
 * `Link`'s in-app branch renders through the ambient `navLink` a Terp router publishes, so its
 * marker lands on a wrapper and the rule reaches the anchor by descending. Without a router
 * there is no `navLink` and the component falls back to a plain anchor — which is the OTHER
 * branch, so a specimen of the routed one needs a router exactly as `ModuleNav` does.
 */
function routedLinkSpecimen(): ReactNode {
  const rootRoute = createRootRoute({
    component: () => (
      <Text>
        An in-app <Link to="/records">routed link</Link> beside an{" "}
        <Link to="https://example.com" newTab>
          external one
        </Link>
        , both inside a paragraph so the ink and the underline are read in context.
      </Text>
    ),
  });
  const router = createRouter({
    routeTree: rootRoute,
    history: createMemoryHistory({ initialEntries: ["/records"] }),
  });
  return (
    <NavLinkContext.Provider
      value={({ to, children, attributes }) => (
        <RouterLink to={to} {...attributes}>
          {children}
        </RouterLink>
      )}
    >
      <RouterProvider router={router} />
    </NavLinkContext.Provider>
  );
}

/** Shared pairs, so the three layout specimens differ in exactly one thing. */
const RECORD_PAIRS = [
  { label: "Status", value: "Published" },
  { label: "Revision", value: "14" },
  { label: "Direction", value: "Source to destination" },
  { label: "Owner", value: "Integrations team" },
];

/** 64 hex characters with nothing to break on — the value the old `auto` track overflowed. */
const LONG_DIGEST = "9f2c1b7ae4d08c3f5a6b2e1d4c7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2c3d4e5f";

/** Long enough that the measure caps it — at two words the cap paints nothing. */
const LOREM =
  "A measure is the one typographic control that is about the container rather than the " +
  "text, which is why it is capped in ch: the readable line length is a count of characters " +
  "and follows the font size, so in rem it would stop being a measure the moment an app " +
  "changed the type scale.";

/** One line longer than the block, so the block's horizontal overflow is in the picture. */
const CODE_SAMPLE = [
  "renderTerpApp({",
  '  title: "Terp",',
  '  modules: import.meta.glob("./modules/*/module.tsx", { eager: true }),',
  '  layoutContract: "standard",',
  "});",
].join("\n");

const MARKDOWN_SAMPLE = [
  "## Connection notes",
  "",
  "A paragraph with **bold**, *italic*, `code` and a [link](https://example.com).",
  "",
  "- First item",
  "- Second item",
  "",
  "```",
  "const x = 1;",
  "```",
].join("\n");

export const SPECIMEN_GROUPS: SpecimenGroup[] = [
  {
    id: "actions",
    title: "Actions",
    specimens: [
      {
        id: "button-variants",
        title: "Button — every variant",
        node: (
          <Stack direction="row" gap={2} wrap>
            {BUTTON_VARIANTS.map((variant) => (
              <Button key={variant} variant={variant}>
                {variant}
              </Button>
            ))}
          </Stack>
        ),
      },
      {
        id: "button-disabled",
        title: "Button — disabled, every variant",
        node: (
          <Stack direction="row" gap={2} wrap>
            {BUTTON_VARIANTS.map((variant) => (
              <Button key={variant} variant={variant} disabled>
                {variant}
              </Button>
            ))}
          </Stack>
        ),
      },
      {
        // The three sizes side by side, which is the only way the middle one carries any
        // information: md is the base rule, so a specimen of it alone is
        // indistinguishable from `button-variants`. Baseline-relevant detail — the sizes
        // differ in height, horizontal padding AND label size, so all three have to be in
        // one shot for a change to any of them to name itself.
        id: "button-sizes",
        title: "Button — the three control sizes",
        node: (
          <Stack direction="row" gap={2} align="center" wrap>
            <Button size="sm">Small</Button>
            <Button>Standard</Button>
            <Button size="lg">Large</Button>
          </Stack>
        ),
      },
      {
        // Compact density beside the same three, because the sizes calc() off the density
        // token rather than declaring heights of their own — so this is the only picture of
        // the two dimensions composing, and the only thing that would notice if a size
        // stopped following density.
        id: "button-sizes-compact",
        title: "Button — the three sizes at compact density",
        node: (
          <div data-density="compact">
            <Stack direction="row" gap={2} align="center" wrap>
              <Button size="sm">Small</Button>
              <Button>Standard</Button>
              <Button size="lg">Large</Button>
            </Stack>
          </div>
        ),
      },
      {
        // Loading, with and without an icon of its own, because the spinner REPLACES the icon
        // rather than joining it — so the two cases are the same width and that is the claim.
        // Both are also `:disabled`, which is why the opacity here matches `button-disabled`.
        id: "button-loading",
        title: "Button — loading, replacing the icon slot",
        node: (
          <Stack direction="row" gap={2} align="center" wrap>
            <Button loading>Saving</Button>
            <Button loading icon={<Icon name="download" />}>
              Exporting
            </Button>
            <Button loading variant="secondary" size="sm">
              Checking
            </Button>
          </Stack>
        ),
      },
      {
        // Full width, in a box narrower than the specimen card so the fill is visible as a
        // fill rather than as the card's own width. Beside a default button, which shrink-wraps
        // its label — the pair is what makes `width: fit-content` and `width: 100%` legible as
        // a difference.
        id: "button-full-width",
        title: "Button — filling its container, beside one that does not",
        node: (
          <div style={{ width: "18rem" }}>
            <Stack gap={2}>
              <Button fullWidth>Full width</Button>
              <Button>Content width</Button>
            </Stack>
          </div>
        ),
      },
      {
        id: "button-with-icon",
        title: "Button — with a leading glyph",
        node: (
          <Stack direction="row" gap={2} wrap>
            <Button variant="primary">
              <Icon name="plus" /> New record
            </Button>
            <Button variant="secondary">
              <Icon name="download" /> Export
            </Button>
          </Stack>
        ),
      },
      {
        id: "popover",
        title: "Popover — closed trigger",
        node: (
          <Popover trigger={<Button variant="secondary">Open panel</Button>}>
            {() => <p style={{ margin: 0 }}>Panel body.</p>}
          </Popover>
        ),
      },
      {
        // The panel's whole appearance is inline in Popover.tsx and no rule in the sheet
        // touches [data-terp="popover-panel"], so until this specimen existed the most
        // migration-exposed surface in the library had no picture in either lane.
        id: "popover-open",
        title: "Popover — open panel",
        overlay: true,
        node: (
          <Popover defaultOpen trigger={<Button variant="secondary">Open panel</Button>}>
            {() => <p style={{ margin: 0 }}>Panel body.</p>}
          </Popover>
        ),
      },
      {
        id: "confirm-dialog",
        title: "ConfirmDialog — question and consequence",
        overlay: true,
        node: (
          <ConfirmDialog
            open
            onOpenChange={() => {}}
            onConfirm={() => {}}
            title="Publish this sync definition?"
            description="It starts moving records on the next scheduled run."
          />
        ),
      },
      {
        id: "confirm-dialog-destructive",
        title: "ConfirmDialog — destructive confirm",
        overlay: true,
        node: (
          <ConfirmDialog
            open
            onOpenChange={() => {}}
            onConfirm={() => {}}
            destructive
            confirmLabel="Delete"
            title="Delete this link?"
            description="Its mappings and its run history are removed with it."
          />
        ),
      },
    ],
  },
  {
    id: "status",
    title: "Status",
    specimens: [
      {
        id: "badge-tones",
        title: "Badge — every tone",
        node: (
          <Stack direction="row" gap={2} wrap>
            {TONES.map((tone) => (
              <Badge key={tone} tone={tone} label={tone} />
            ))}
          </Stack>
        ),
      },
      {
        id: "alert-tones",
        title: "Alert — every tone",
        node: (
          <Stack gap={2}>
            {TONES.map((tone) => (
              <Alert key={tone} tone={tone} title={`${tone} heading`}>
                The body explains what happened and what to do next.
              </Alert>
            ))}
          </Stack>
        ),
      },
      {
        id: "alert-untitled",
        title: "Alert — body only",
        node: <Alert tone="info">A single line, with no heading above it.</Alert>,
      },
    ],
  },
  {
    id: "containers",
    title: "Containers",
    specimens: [
      {
        id: "card-titled",
        title: "Card — title and description",
        node: (
          <Card title="Connection profile" description="How this app reaches the source system.">
            <p style={{ margin: 0 }}>Body content sits below the header.</p>
          </Card>
        ),
      },
      {
        // The pairing, and its absence is why a header defect shipped: `card-titled` has a title
        // and a description, the shells' cards carry titles and actions, and nothing anywhere put
        // all three in one picture — so the one arrangement in which the actions slot did not
        // behave was the one nothing was looking at. Both cards are here because the bug was the
        // INCONSISTENCY rather than either result: same prop, inline above, wrapped below, and
        // only the pair says so.
        //
        // The description has to be long enough to WRAP at the gallery's width, and that is a
        // constraint rather than a flourish. The old heading computed flex: 0 1 auto, so its
        // hypothetical main size was the description's *max-content* width — one unwrapped line.
        // While that fits beside the control the old sheet painted this correctly, so a short
        // description makes the specimen prove nothing. Two lines means max-content exceeds the
        // header, which is exactly the condition under which flex broke the line.
        id: "card-title-description-actions",
        title: "Card — an action beside a title, with and without a description",
        node: (
          <Stack gap={4}>
            <Card
              title="Connection profile"
              description="How this app reaches the source system, which credential it presents, the window it is allowed to run in, and what a run does when it overlaps the one before it. Every value here is read from the profile rather than from the connection."
              actions={
                <Button type="button" variant="secondary">
                  Edit
                </Button>
              }
            >
              <p style={{ margin: 0 }}>Body content sits below the header.</p>
            </Card>
            <Card
              title="Connection profile"
              actions={
                <Button type="button" variant="secondary">
                  Edit
                </Button>
              }
            >
              <p style={{ margin: 0 }}>The same header with the description removed.</p>
            </Card>
          </Stack>
        ),
      },
      {
        id: "card-bare",
        title: "Card — no header",
        node: (
          <Card>
            <p style={{ margin: 0 }}>A plain surface with padding and a border.</p>
          </Card>
        ),
      },
      {
        id: "detail-list",
        title: "DetailList — record metadata",
        node: (
          <DetailList
            items={[
              { label: "Status", value: <Badge tone="success" label="Published" /> },
              { label: "Revision", value: "14" },
              { label: "Fingerprint", value: "9f2c1b7ae4d08c3f5a6b2e1d4c7f8a9b0c1d2e3f" },
              { label: "Direction", value: "Source to destination" },
            ]}
          />
        ),
      },
      {
        // The variant's motivating case rather than a demonstration of it: a titled region whose
        // body is a DataView. Boxed, the table gets a border inside a border and loses the full
        // width its own scroll container gives it — frame inside a frame. The pair is what makes
        // that legible, so both are in one shot.
        id: "card-plain",
        title: "Card — plain beside boxed, each holding a table",
        node: (
          <Stack gap={4}>
            <Card title="Boxed" description="A border inside a border.">
              <DataView repository={SYNC_REPOSITORY} columns={SYNC_COLUMNS} variant="embedded" />
            </Card>
            <Card variant="plain" title="Plain" description="The heading, and no second box.">
              <DataView repository={SYNC_REPOSITORY} columns={SYNC_COLUMNS} variant="embedded" />
            </Card>
          </Stack>
        ),
      },
      {
        // Both orientations, and the vertical one needs the contrived row: it takes its height
        // from its flex line rather than inventing one, so in a block parent it is zero-height
        // and the rule would be in the sheet with nothing depending on it.
        id: "divider-orientations",
        title: "Divider — horizontal in a column, vertical in a row",
        node: (
          <Stack gap={4}>
            <Stack gap={3}>
              <span>Above the rule</span>
              <Divider />
              <span>Below it</span>
            </Stack>
            <Stack direction="row" gap={3} align="stretch">
              <span>Left</span>
              <Divider orientation="vertical" />
              <span>Middle</span>
              <Divider orientation="vertical" />
              <span>Right</span>
            </Stack>
          </Stack>
        ),
      },
      {
        // Padding, on both primitives, against a visible edge — without the border there is
        // nothing in the picture to measure the inset against. Two steps rather than all seven:
        // the roll-call in styles.test.ts is what holds every step, the same division the gap
        // rules already use.
        id: "layout-padding",
        title: "Stack and Grid — the inset they previously could not express",
        node: (
          <Stack gap={4}>
            {([2, 6] as const).map((step) => (
              <div key={step} style={{ border: "1px dashed var(--color-neutral-300)" }}>
                <Stack padding={step} gap={2}>
                  <GridCell label={`Stack padding ${step}`} />
                </Stack>
              </div>
            ))}
            {([2, 6] as const).map((step) => (
              <div key={step} style={{ border: "1px dashed var(--color-neutral-300)" }}>
                <Grid columns={2} padding={step} gap={2}>
                  <GridCell label={`Grid padding ${step}`} />
                  <GridCell label="two" />
                </Grid>
              </div>
            ))}
          </Stack>
        ),
      },
      {
        // The alignment the diagnosis asked for: every label in a shared column, so the values
        // line up down the list. The row wrapper goes display: contents for it, which is what
        // makes the dt and dd grid items of the dl itself.
        id: "detail-list-aligned",
        title: "DetailList — labels in a shared column",
        node: <DetailList layout="aligned" items={RECORD_PAIRS} />,
      },
      {
        // Label above value, which is what a narrow column or a long value wants — and the
        // layout in which the inline colon would be wrong, hence the colon living in the sheet.
        id: "detail-list-stacked",
        title: "DetailList — label above value",
        node: <DetailList layout="stacked" items={RECORD_PAIRS} />,
      },
      {
        id: "detail-list-two-column",
        title: "DetailList — two aligned pairs per row",
        node: <DetailList layout="aligned" columns={2} items={RECORD_PAIRS} />,
      },
      {
        // The other half of DetailList's cutover, and it needs a viewport of its own for the
        // reason `split-page-narrow` does: the aligned and two-column tracks live in the sheet's
        // single wide-viewport block, so at the lane's pinned 1280 they always apply and the
        // one-column shape is unreachable. 430x900 is a phone, well below the 768px breakpoint.
        //
        // What the picture is FOR is that a value gets its own line. Four tracks in ~370px met
        // `overflow-wrap: anywhere` — correct for an unbreakable digest, wrong as a way to fit a
        // label — and broke ordinary words mid-token. All three layouts are in one shot because
        // narrow they converge, which is the claim: below the cutover a labelled pair reads the
        // same way whatever the caller asked for above it.
        id: "detail-list-narrow",
        title: "DetailList — one column below the breakpoint",
        viewport: { width: 430, height: 900 },
        node: (
          // gap={8} rather than the usual 4: the rows inside each list are --space-3 apart, so at
          // a smaller step the three lists run together and a reader cannot see where one ends.
          <Stack gap={8}>
            {(["aligned", "stacked"] as const).map((layout) => (
              <DetailList key={layout} layout={layout} items={RECORD_PAIRS} />
            ))}
            <DetailList layout="aligned" columns={2} items={RECORD_PAIRS} />
          </Stack>
        ),
      },
      {
        // The gap prop, against the layout default it overrides. Two steps rather than all seven:
        // the roll-call in styles.test.ts holds every step, the same division the Stack and Grid
        // padding specimens already use. It is a ROW gap — the column gap is the label-to-value
        // distance and stays the layout's — so the picture to read is the vertical rhythm.
        id: "detail-list-gap",
        title: "DetailList — the distance between pairs",
        node: (
          <Stack gap={6}>
            {([1, 6] as const).map((step) => (
              <DetailList key={step} layout="aligned" gap={step} items={RECORD_PAIRS} />
            ))}
          </Stack>
        ),
      },
      {
        // The defect rather than the feature, and it needs the narrow box: an implicit grid
        // column is `auto`, which floors at min-content, so a 64-character digest with nothing
        // to break on widened its column and pushed the list past its container. At the
        // specimen's own width every value fits and the fix paints nothing — measured, the
        // whole suite passed the rewrite with zero diffs. This is the context that sees it.
        id: "detail-list-long-value",
        title: "DetailList — an unbreakable digest in a narrow container",
        node: (
          <Stack gap={4}>
            {(["inline", "aligned", "stacked"] as const).map((layout) => (
              <div key={layout} style={{ width: "22rem", border: "1px dashed var(--color-neutral-300)" }}>
                <DetailList
                  layout={layout}
                  items={[
                    { label: "Layout", value: layout },
                    { label: "Fingerprint", value: LONG_DIGEST },
                  ]}
                />
              </div>
            ))}
          </Stack>
        ),
      },
      {
        id: "markdown",
        title: "Markdown — blocks and inline marks",
        node: <Markdown source={MARKDOWN_SAMPLE} />,
      },
      {
        // The half of the boxless-wrapper claim the plain specimen above cannot prove. Nothing
        // in the repo puts Markdown inside a flex or grid parent, so "its blocks stay
        // individual items of any parent Stack" was an argument rather than a measurement:
        // with display: contents the blocks become real flex items and the Stack's gap falls
        // between each one, and without it they collapse into a single item with the gap once
        // around the lot. Two Stacks so the row/column cases are both in the picture.
        id: "markdown-in-stack",
        title: "Markdown — blocks as items of a parent Stack",
        node: (
          <Stack gap={4}>
            <Stack gap={2}>
              <Markdown source={MARKDOWN_SAMPLE} />
            </Stack>
            <Stack direction="row" gap={3} align="center" wrap>
              <Markdown source="One **bold** line." />
              <Badge tone="info" label="beside it" />
            </Stack>
          </Stack>
        ),
      },
      {
        id: "tabs",
        title: "Tabs — second tab active",
        node: (
          <Tabs
            label="Record sections"
            value="mapping"
            tabs={[
              { value: "overview", label: "Overview", content: <p style={{ margin: 0 }}>Overview panel.</p> },
              { value: "mapping", label: "Mapping", content: <p style={{ margin: 0 }}>Mapping panel.</p> },
              { value: "history", label: "History", content: <p style={{ margin: 0 }}>History panel.</p> },
            ]}
          />
        ),
      },
    ],
  },
  {
    id: "forms",
    title: "Form controls",
    specimens: [
      {
        id: "text-inputs",
        title: "Input, Select, Textarea — resting",
        // `aria-label` on each control, because a bare input with no accessible name is a
        // real WCAG failure and the a11y suite is right to refuse it. In an app the name
        // comes from a wrapping `Field` (see `field-states`); a specimen showing the control
        // alone has to supply one itself.
        node: (
          <Stack gap={3}>
            <Input aria-label="Single-line text" defaultValue="A single line of text" />
            <Select aria-label="Status" defaultValue="published">
              {SELECT_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </Select>
            <Textarea
              aria-label="Multi-line text"
              rows={3}
              defaultValue={"Several lines\nof text."}
            />
          </Stack>
        ),
      },
      {
        id: "text-inputs-disabled",
        title: "Input, Select, Textarea — disabled",
        node: (
          <Stack gap={3}>
            <Input aria-label="Single-line text" defaultValue="Not editable" disabled />
            <Select aria-label="Status" defaultValue="draft" disabled>
              {SELECT_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </Select>
            <Textarea aria-label="Multi-line text" rows={2} defaultValue="Not editable" disabled />
          </Stack>
        ),
      },
      {
        id: "text-inputs-invalid",
        title: "Input — flagged invalid",
        node: <Input aria-label="Contact email" defaultValue="not-an-email" aria-invalid />,
      },
      {
        id: "field-states",
        title: "Field — hint and error",
        node: (
          <Stack gap={4}>
            <Field label="Display name" hint="Shown to everyone in the workspace.">
              <Input defaultValue="Team Falcon" />
            </Field>
            {/* No aria-invalid here on purpose: a Field with an error supplies it, and that is
                what this baseline proves — the picture is byte-identical to the one recorded
                when the specimen passed it by hand. */}
            <Field label="Contact email" error="Enter an address with an @ in it.">
              <Input defaultValue="not-an-email" />
            </Field>
          </Stack>
        ),
      },
      {
        id: "toggles",
        title: "Checkbox and Switch — both states",
        node: (
          <Stack gap={3}>
            <Checkbox label="Checked" checked />
            <Checkbox label="Unchecked" checked={false} />
            <Checkbox label="Disabled" checked disabled />
            <Switch label="On" checked />
            <Switch label="Off" checked={false} />
            <Switch label="Disabled" checked disabled />
          </Stack>
        ),
      },
      {
        id: "radios",
        title: "RadioGroup and a bare Radio",
        node: (
          <Stack gap={4}>
            <RadioGroup
              label="Direction"
              value="pull"
              options={[
                { value: "pull", label: "Pull" },
                { value: "push", label: "Push" },
              ]}
            />
            <Radio label="Standalone, disabled" value="x" checked disabled />
          </Stack>
        ),
      },
      {
        id: "combobox",
        title: "Combobox — closed with a selection",
        node: (
          // Combobox wraps an input rather than owning a label, so the accessible name
          // comes from `aria-label` here; in a real screen a `Field` supplies it.
          <Combobox aria-label="Status" value="published" options={SELECT_OPTIONS} />


        ),
      },
      {
        id: "combobox-multiple",
        title: "Combobox — multiple, with tokens",
        // Two tokens and a third selectable, because the geometry this specimen exists to
        // record is the wrapping token row sharing a box with the filter input — one token
        // would not show that the field grows with the selection.
        node: (
          <Combobox
            multiple
            clearable
            aria-label="Source fields"
            defaultValue={["published", "draft"]}
            options={SELECT_OPTIONS}
          />
        ),
      },
      {
        id: "combobox-disabled-invalid",
        title: "Combobox — disabled and flagged invalid",
        // These two states had no specimen, and that gap is exactly how a migration
        // shipped a disabled Combobox painted identically to an enabled one: the
        // baselines only ever saw it at rest.
        node: (
          <Stack gap={3}>
            <Combobox aria-label="Status, disabled" value="published" options={SELECT_OPTIONS} disabled />
            <Combobox aria-label="Status, invalid" value="published" options={SELECT_OPTIONS} aria-invalid />
          </Stack>
        ),
      },
      {
        // The listbox has been styled from the sheet since stage 2c and painted by neither
        // lane in all that time, because `open` was internal state with no way in. Its
        // options are absolutely positioned past the specimen card's edge, so it needs the
        // viewport shot as much as a portalled panel does.
        id: "combobox-open",
        title: "Combobox — open listbox, cursor on the selection",
        overlay: true,
        node: <Combobox aria-label="Status" value="published" options={SELECT_OPTIONS} defaultOpen />,
      },
      {
        id: "date-picker",
        title: "DatePicker — fixed value",
        node: <DatePicker value={FIXED_DATE} />,
      },
      {
        // Sixteen calendar rules, shipped in stage 2c and never once painted. This is also
        // the first picture of the out-of-month treatment the ARIA-grid fix relit, and of the
        // roving cursor's focus ring — which lands on the selected day because the calendar
        // focuses it on mount.
        id: "date-picker-open",
        title: "DatePicker — open calendar",
        overlay: true,
        node: <DatePicker aria-label="Due date" value={FIXED_DATE} defaultOpen />,
      },
      {
        id: "date-picker-states",
        title: "DatePicker — placeholder, disabled and invalid",
        node: (
          <Stack gap={3}>
            <DatePicker aria-label="Date, empty" value={null} />
            <DatePicker aria-label="Date, disabled" value={FIXED_DATE} disabled />
            <DatePicker aria-label="Date, invalid" value={FIXED_DATE} aria-invalid />
          </Stack>
        ),
      },
      {
        id: "date-range-picker",
        title: "DateRangePicker — a selected range",
        node: (
          <DateRangePicker
            aria-label="Reporting period"
            value={{ start: FIXED_DATE, end: FIXED_RANGE_END }}
          />
        ),
      },
      {
        // The only surface that paints data-in-range, and the only one with two aria-selected
        // endpoints at once. The range crosses a month boundary on purpose — see
        // FIXED_CROSS_START: that is the only way to paint a day which is outside the visible
        // month AND inside the range, the combination whose contrast failed AA in two themes.
        id: "date-range-picker-open",
        title: "DateRangePicker — open calendar, range crossing a month boundary",
        overlay: true,
        node: (
          <DateRangePicker
            aria-label="Reporting period"
            value={{ start: FIXED_CROSS_START, end: FIXED_CROSS_END }}
            defaultOpen
          />
        ),
      },
    ],
  },
  {
    id: "collections",
    title: "Collections",
    specimens: [
      {
        id: "dataview-full",
        title: "DataView — toolbar, table and pagination",
        node: (
          <DataView
            repository={SYNC_REPOSITORY}
            columns={SYNC_COLUMNS}
            rowActions={() => [
              { label: "Retry", onClick: () => {} },
              { label: "Delete", variant: "destructive", onClick: () => {} },
            ]}
          />
        ),
      },
      {
        // The only specimen rendering the select column, and so the only baseline covering the
        // two system cells the table migration moved into the sheet. It is also a view with
        // focusable content in rows that nothing will open, which is the shape that made the
        // focus-within tint's data-clickable guard necessary.
        id: "dataview-selection",
        title: "DataView — selectable rows",
        node: <DataView repository={SYNC_REPOSITORY} columns={SYNC_COLUMNS} enableSelection />,
      },
      {
        // The only specimen in which the density tokens are observable. Comfortable is the
        // token sheet's :root value, so every other DataView specimen renders the same
        // geometry whether the tokens are read or hardcoded — which is how four of these
        // tokens came to be published with no reader at all.
        id: "dataview-compact",
        title: "DataView — compact density",
        node: (
          <DataView
            repository={SYNC_REPOSITORY}
            columns={SYNC_COLUMNS}
            density="compact"
            rowActions={() => [
              { label: "Retry", onClick: () => {} },
              { label: "Delete", variant: "destructive", onClick: () => {} },
            ]}
          />
        ),
      },
      {
        id: "dataview-embedded",
        title: "DataView — embedded variant",
        node: <DataView repository={SYNC_REPOSITORY} columns={SYNC_COLUMNS} variant="embedded" />,
      },
      {
        id: "dataview-row-tones",
        title: "DataView — row-level status tones",
        node: (
          <DataView
            repository={SYNC_REPOSITORY}
            columns={SYNC_COLUMNS}
            getRowTone={(row) => (row.status === "ok" ? null : SYNC_TONES[row.status])}
          />
        ),
      },
      {
        // The card layout renders in NO composed DataView specimen and cannot: the switch is
        // internal state, driven by a media query at 768px or by a toolbar click, and the
        // viewport is pinned at 1280. DataViewCardList is exported, so the specimen renders it
        // directly at fixed props — which is also how the two portalled menus and the expanded
        // row get their specimens, rather than by growing test-only props on DataView.
        id: "dataview-cards",
        title: "DataView — card layout, tones and selection",
        node: (
          <DataViewCardList
            rows={SYNC_ROWS}
            columns={SYNC_COLUMNS}
            getRowId={(row) => row.id}
            getRowLabel={(row) => row.name}
            onRowClick={() => {}}
            getRowTone={(row) => (row.status === "ok" ? null : SYNC_TONES[row.status])}
            selectionEnabled
            isSelected={(id) => id === "s1"}
            onToggleSelected={() => {}}
            isExpanded={() => false}
            onToggleExpanded={() => {}}
            rowActions={() => [{ label: "Retry", onClick: () => {} }]}
          />
        ),
      },
      {
        // The table's expand column and its detail row, neither of which any composed DataView
        // specimen renders: expansion is internal state with no prop on DataView to seed it,
        // while DataViewTable takes isExpanded as a prop. One row open and one shut, so both
        // chevron states sit in one shot.
        id: "dataview-expanded",
        title: "DataView — table with a row expanded",
        node: (
          <DataViewTable
            rows={SYNC_ROWS.slice(0, 3)}
            columns={SYNC_COLUMNS}
            getRowId={(row) => row.id}
            isMobile={false}
            sorting={[]}
            onToggleSort={() => {}}
            columnSizing={{}}
            onCommitColumnSizing={() => {}}
            selectionEnabled={false}
            isSelected={() => false}
            onToggleSelected={() => {}}
            allPageSelected={false}
            somePageSelected={false}
            onToggleSelectPage={() => {}}
            renderExpanded={(row) => <span>Last synced {row.rows} rows.</span>}
            isExpanded={(id) => id === "s2"}
            onToggleExpanded={() => {}}
            rowActionsLayout="menu"
          />
        ),
      },
      {
        // Separate from the cards above so an expansion change cannot mask a card change, and
        // because the expand toggle only renders when renderExpanded is supplied. One row open
        // and one shut, so both chevron states are in the same shot.
        id: "dataview-cards-expanded",
        title: "DataView — card layout, one row expanded",
        node: (
          <DataViewCardList
            rows={SYNC_ROWS.slice(0, 2)}
            columns={SYNC_COLUMNS}
            getRowId={(row) => row.id}
            isSelected={() => false}
            onToggleSelected={() => {}}
            selectionEnabled={false}
            renderExpanded={(row) => <span>Last synced {row.rows} rows.</span>}
            isExpanded={(id) => id === "s2"}
            onToggleExpanded={() => {}}
          />
        ),
      },
      {
        // The pagination controls render in NO composed DataView specimen, and it took reading
        // the component to notice: the fixture is four rows at a page size of ten, so pageCount
        // is 1 and the whole pager is behind a `pageCount > 1` guard. Four icon buttons and a
        // style factory had been migrating with zero baseline coverage. Page one of five, so the
        // shot carries both states at once — first and previous disabled, next and last live.
        id: "dataview-pagination",
        title: "DataView — pagination, page one of five",
        node: (
          <DataViewPagination
            pagination={{ pageIndex: 0, pageSize: 10 }}
            totalCount={42}
            onPaginationChange={() => {}}
          />
        ),
      },
      {
        // The inline row-action layout, which no composed specimen reaches: dataview-full uses
        // the default menu layout, so its actions live behind a closed panel. Three actions so
        // all three rules are in one shot — a plain control, a destructive one, and a disabled
        // one, the last of which also pins that disabled outranks destructive.
        id: "dataview-row-actions-inline",
        title: "DataView — inline row actions",
        node: (
          <DataViewRowActions
            row={SYNC_ROWS[0]}
            layout="inline"
            isMobile={false}
            actions={[
              // The icon and the custom control are not decoration: they are the only things
              // that render the two structural "> span" rules — an action's leading icon, and
              // the wrapper around a caller-supplied control. Without them both rules are in
              // the sheet, asserted by styles.test.ts, and painted by no specimen.
              { label: "Retry", icon: "↻", onClick: () => {} },
              { label: "Delete", variant: "destructive", onClick: () => {} },
              { label: "Archive", disabled: true, onClick: () => {} },
              { label: "Custom", render: () => <Badge tone="info" label="custom" /> },
            ]}
          />
        ),
      },
      {
        // And the panel, which portals to document.body and is therefore invisible to both an
        // element-clipped screenshot and an element-scoped axe run — hence overlay: true, the
        // same treatment the other open panels take.
        id: "dataview-row-actions-open",
        title: "DataView — row actions, menu open",
        overlay: true,
        node: (
          <DataViewRowActions
            row={SYNC_ROWS[0]}
            layout="menu"
            isMobile={false}
            defaultOpen
            actions={[
              { label: "Retry", onClick: () => {} },
              { label: "Duplicate", onClick: () => {} },
              { label: "Delete", variant: "destructive", onClick: () => {} },
            ]}
          />
        ),
      },
      {
        // The view-options panel, portalled and therefore overlay: true. One column hidden and
        // three visible, so the checkbox pair is covered, and the reorder arrows are disabled at
        // both ends of the list — which is a RESTING state, and the one place this commit's
        // intentional diff is visible: the arrows now wear the shared icon-button marker, so a
        // disabled arrow takes that marker's opacity in addition to the muted ink it always had.
        id: "dataview-column-settings-open",
        title: "DataView — view options, panel open",
        overlay: true,
        node: (
          <DataViewColumnSettings
            columns={SYNC_COLUMNS}
            columnVisibility={{ rows: false }}
            onColumnVisibleChange={() => {}}
            onMoveColumn={() => {}}
            defaultOpen
          />
        ),
      },
      {
        // Selection mode, which no composed specimen reaches: `dataview-selection` passes
        // `enableSelection` but selects no rows, so `selectedCount` is 0 and the toolbar takes its
        // normal branch. Rendered inside the frame a toolbar actually lives in — a DataView root's
        // surface — because the band's background and its two TOP radii are only observable
        // against a rounded neutral-0 box: a dropped radius looks like a squared corner sitting
        // over a rounded frame, and against the bare specimen card it looks like nothing.
        id: "dataview-toolbar-selection",
        title: "DataView toolbar — selection mode, batch actions",
        node: (
          <div
            style={{
              background: "var(--color-neutral-0)",
              border: "1px solid var(--color-neutral-200)",
              borderRadius: "var(--radius-lg)",
            }}
          >
            <DataViewToolbar<SyncRow>
              searchEnabled
              search=""
              onSearchChange={() => {}}
              hasActiveFilters={false}
              layout="table"
              selectedCount={3}
              totalCount={42}
              selectAllAcrossPages={false}
              onSelectAllAcrossPages={() => {}}
              onClearSelection={() => {}}
              onBatchAction={() => {}}
              isFetching={false}
              batchActions={[
                // The icon is not decoration: it is the only thing that renders the leading-glyph
                // box in a batch action. `inline: false` is the only thing that puts an action in
                // the overflow menu, so it is what makes the ellipsis trigger — and the group's
                // gap between a button and that trigger — render at all.
                { label: "Export", icon: <Icon name="download" />, onClick: () => {} },
                { label: "Retry", onClick: () => {} },
                { label: "Delete", variant: "destructive", onClick: () => {} },
                { label: "Archive", inline: false, onClick: () => {} },
              ]}
            />
          </div>
        ),
      },
      {
        // A non-empty search term, which nothing else in the catalog renders — every other
        // DataView starts with an empty box. It is the only thing that paints the clear-search
        // button, the only thing that satisfies the scope toggle's `search.trim() !== ""` guard,
        // and the only place the field's two padding reserves are measurable against real text.
        // `useViewSearch` seeds its input from the prop, so the term is there on first paint.
        //
        // It also shows Chrome's own `::-webkit-search-cancel-button` beside the component's
        // clear button. That is a browser default on `type="search"`, not a migration artefact.
        id: "dataview-toolbar-search-filled",
        title: "DataView toolbar — a search term, clear button and scope toggle",
        node: (
          <DataViewToolbar<SyncRow>
            searchEnabled
            search="ledger"
            onSearchChange={() => {}}
            searchScope={{
              broadened: false,
              onBroadenedChange: () => {},
              label: "Search everything",
              broadenedLabel: "Searching everything",
            }}
            hasActiveFilters={false}
            layout="table"
            selectedCount={0}
            totalCount={42}
            selectAllAcrossPages={false}
            onClearSelection={() => {}}
            onBatchAction={() => {}}
            isFetching={false}
          />
        ),
      },
      {
        // The band holding nothing but one trailing slot, on a page-coloured host. Both halves are
        // load-bearing and neither is covered anywhere else. The band's minimum height is inert in
        // every bar that holds a control (a comfortable one measures 3.25rem, a compact one exactly
        // 3.00rem), so this is the only place it decides anything. And the band's own background is
        // invisible against the neutral-0 specimen card: the embedded variant's root declares
        // nothing but a display, so neutral-50 is what actually sits behind a real embedded
        // toolbar, and it is the only host on which losing that background is a visible change.
        id: "dataview-toolbar-bare",
        title: "DataView toolbar — an empty band on a page surface",
        node: (
          <div style={{ padding: "var(--space-3)", background: "var(--color-neutral-50)" }}>
            <DataViewToolbar<SyncRow>
              searchEnabled={false}
              search=""
              onSearchChange={() => {}}
              hasActiveFilters={false}
              layout="table"
              selectedCount={0}
              totalCount={0}
              selectAllAcrossPages={false}
              onClearSelection={() => {}}
              onBatchAction={() => {}}
              isFetching={false}
              trailing={<span>Filters</span>}
            />
          </div>
        ),
      },
      {
        id: "dataview-empty",
        title: "DataView — empty result",
        node: (
          <DataView
            repository={EMPTY_REPOSITORY}
            columns={SYNC_COLUMNS}
            emptyMessage="No syncs defined yet."
          />
        ),
      },
      {
        // The first load, which every other DataView specimen resolves past in a microtask. The
        // full variant renders its toolbar unconditionally, so one specimen paints two surfaces
        // nothing else reaches: the fixed-height skeleton and the toolbar's "Refreshing…"
        // status, whose span is behind `isFetching` and therefore behind a resolved query
        // everywhere else.
        id: "dataview-loading",
        title: "DataView — first load, skeleton and refresh status",
        node: <DataView repository={NEVER_REPOSITORY} columns={SYNC_COLUMNS} />,
      },
      {
        // The error path, and specifically the DEFAULT one: `renderError` is undefined, so what
        // renders is the wrapper DataView supplies around `ErrorState` rather than a caller's own
        // node. Also the first picture of `error-state` inside a DataView rather than on a page.
        id: "dataview-error",
        title: "DataView — the query failed",
        node: <DataView repository={FAILING_REPOSITORY} columns={SYNC_COLUMNS} />,
      },
      {
        // A table wider than the box, which nothing else produces — the three sync columns size
        // to their content and fit with room to spare. This is the only specimen in which the
        // horizontal scroll container does anything: without it the table widens the whole
        // DataView, and no other baseline in the suite notices.
        //
        // What it does NOT picture, and this was measured rather than assumed: the reset's themed
        // scrollbar, whose own comment names the horizontal overflow of a DataView table as the
        // place it is most obvious. Headless Chromium gives this container an OVERLAY scrollbar —
        // offsetHeight minus clientHeight is 0, so the bar occupies no layout space and paints
        // nothing at rest. The `::-webkit-scrollbar` rules are still gated by no lane at all. What
        // this baseline does hold is the clip: scrollWidth 1447 inside clientWidth 1196, with the
        // ninth column out of frame and the eighth cut mid-word.
        id: "dataview-wide",
        title: "DataView — a table wider than the box",
        node: <DataView repository={SYNC_REPOSITORY} columns={WIDE_SYNC_COLUMNS} />,
      },
      {
        id: "dataview-column-steps",
        title: "DataView — declared column tracks (xs / sm / md, and one undeclared)",
        node: <DataView repository={STEP_REPOSITORY} columns={STEP_COLUMNS} variant="embedded" />,
      },
      {
        id: "resource-list",
        ready: '[data-terp="resource-list-row"]',
        title: "ResourceList — loaded, with create and row actions",
        node: (
          <SignedIn>
            <ResourceList
              title="Links"
              resource={LINK_RESOURCE}
              renderItem={(item) => <span>{item.name}</span>}
              createPlaceholder="New link name"
              renderActions={() => <Button variant="ghost">Remove</Button>}
            />
          </SignedIn>
        ),
      },
      {
        id: "resource-list-empty",
        ready: '[data-terp="resource-list-empty"]',
        title: "ResourceList — empty",
        node: (
          <SignedIn>
            <ResourceList title="Links" resource={EMPTY_RESOURCE} renderItem={(item) => <span>{item.name}</span>} />
          </SignedIn>
        ),
      },
      {
        // The error line, which nothing painted — so the danger ink on the framework's
        // failed-create message sat in no baseline and axe never measured it in any of the
        // five themes. Everything else is `resource-list` unchanged, so the two baselines
        // differ in exactly one thing.
        id: "resource-list-error",
        ready: '[data-terp="resource-list-error"]',
        title: "ResourceList — the create failed",
        node: (
          <SignedIn>
            <ResourceList
              title="Links"
              resource={FAILED_RESOURCE}
              renderItem={(item) => <span>{item.name}</span>}
              createPlaceholder="New link name"
              renderActions={() => <Button variant="ghost">Remove</Button>}
            />
          </SignedIn>
        ),
      },
    ],
  },
  {
    id: "states",
    title: "Empty, error and loading",
    specimens: [
      {
        // The only surface in the package with an imperative API rather than props, so the
        // specimen mounts a helper that pushes one of each tone. See `ToastRow` for the
        // duration, which is not an arbitrary large number.
        id: "toast-tones",
        title: "Toast — one of each tone, fixed to the viewport corner",
        overlay: true,
        node: (
          <ToastProvider>
            <ToastRow />
          </ToastProvider>
        ),
      },
      {
        id: "empty-state",
        title: "EmptyState — with an action",
        node: (
          <EmptyState
            title="No revisions yet"
            description="Publishing a draft records the first revision."
            action={<Button variant="primary">New draft</Button>}
          />
        ),
      },
      {
        id: "empty-state-bare",
        title: "EmptyState — title only",
        node: <EmptyState title="Nothing to show" />,
      },
      {
        id: "empty-state-compact",
        // Two of them, because one compact block proves nothing: the reason this size
        // exists is a screen with several empty sections, where the default's poster
        // geometry repeated a sentence over 480px.
        title: "EmptyState — compact, stacked",
        node: (
          <Stack gap={3}>
            <EmptyState
              size="compact"
              title="No connections"
              description="Add one to begin."
            />
            <EmptyState size="compact" title="No recent activity" />
          </Stack>
        ),
      },
      {
        id: "error-state",
        title: "ErrorState — a failed read",
        node: <ErrorState error="The source system refused the connection." />,
      },
      {
        id: "loading-state",
        title: "LoadingState and InlineSpinner",
        node: (
          <Stack gap={4}>
            <LoadingState />
            <Stack direction="row" gap={2} align="center">
              <InlineSpinner />
              <span>Inline, beside text</span>
            </Stack>
          </Stack>
        ),
      },
    ],
  },
  {
    id: "primitives",
    title: "Primitives",
    specimens: [
      {
        id: "tooltip",
        title: "Tooltip — resting trigger",
        node: (
          <Tooltip content="Explains the control">
            <Button variant="ghost">Hover me</Button>
          </Tooltip>
        ),
      },
      {
        // The bubble itself, which nothing painted. Its whole style block — surface, ink,
        // shadow, radius, measure and the `min(18rem, ...)` clamp — was reachable only by
        // hovering or focusing, and neither lane does either: the screenshot lane shoots a
        // resting page and the axe lane reads a static tree. So every declaration in it could
        // have been changed, or deleted, with no gate saying anything. `defaultOpen` is the
        // door, the same one `defaultCollapsed` and `defaultDrawerOpen` opened for the shell.
        //
        // `overlay` because the bubble is position: absolute above its anchor and would be
        // clipped out of an element-scoped shot — the plainest case of the four the flag
        // exists for, and the one most likely to be missed.
        id: "tooltip-open",
        title: "Tooltip — the bubble, shown",
        overlay: true,
        node: (
          // Padded down so the bubble, which sits ABOVE its anchor, clears the specimen's own
          // title rather than covering it. Worth knowing while reading the picture: the panel is
          // position: absolute with only inset-inline-start set, so it shrink-to-fits against
          // the anchor's box — which is why a long string wraps narrow instead of running to the
          // declared max-inline-size. That clamp may well be unreachable in this geometry; it is
          // noted rather than asserted, because nothing here has measured it.
          <div style={{ paddingBlockStart: "7rem" }}>
            <Tooltip content="Explains the control" defaultOpen>
              <Button variant="ghost">Hover me</Button>
            </Tooltip>
          </div>
        ),
      },
      {
        id: "stack-directions",
        title: "Stack — row and column at gap 4",
        node: (
          <Stack gap={4}>
            <Stack direction="row" gap={4}>
              <Badge tone="neutral" label="one" />
              <Badge tone="neutral" label="two" />
              <Badge tone="neutral" label="three" />
            </Stack>
            <Stack gap={4}>
              <Badge tone="info" label="stacked one" />
              <Badge tone="info" label="stacked two" />
            </Stack>
          </Stack>
        ),
      },
      {
        // The narrow half of a responsive Stack, and half of the only gate a media query can
        // have. jsdom evaluates no media query and a structural test can only say the rule
        // exists, so the pair below is what proves the cutover applies at the width it claims:
        // same node, two viewports, and the baselines must differ in BOTH the axis and the gap.
        //
        // 420 is well below the 768px cutover the shell and the DataView already use — one
        // breakpoint in the framework, so a toolbar changes over exactly when the chrome does.
        id: "stack-responsive-narrow",
        title: "Stack — responsive direction and gap, below the cutover",
        viewport: { width: 420, height: 900 },
        node: (
          <Stack direction={{ narrow: "column", wide: "row" }} gap={{ narrow: 2, wide: 6 }}>
            <Button size="sm">Filter</Button>
            <Button size="sm" variant="secondary">
              Export
            </Button>
            <Button size="sm" variant="ghost">
              Reset
            </Button>
          </Stack>
        ),
      },
      {
        // The wide half. 900 rather than the pinned 1280 for no reason except that it is
        // unambiguously above the cutover and narrow enough that the row is legible as a row.
        id: "stack-responsive-wide",
        title: "Stack — the same node, above the cutover",
        viewport: { width: 900, height: 900 },
        node: (
          <Stack direction={{ narrow: "column", wide: "row" }} gap={{ narrow: 2, wide: 6 }}>
            <Button size="sm">Filter</Button>
            <Button size="sm" variant="secondary">
              Export
            </Button>
            <Button size="sm" variant="ghost">
              Reset
            </Button>
          </Stack>
        ),
      },
      {
        // The fixed counts. Visible at the specimen's own width, so no contrived box needed —
        // and the four rules are what a caller reaches for when the count is the design rather
        // than a consequence of the container.
        id: "grid-columns",
        title: "Grid — the four fixed column counts",
        node: (
          <Stack gap={4}>
            {([1, 2, 3, 4] as const).map((count) => (
              <Grid key={count} columns={count} gap={2}>
                {Array.from({ length: count }, (_, index) => (
                  <GridCell key={index} label={`${count}× · ${index + 1}`} />
                ))}
              </Grid>
            ))}
          </Stack>
        ),
      },
      {
        // The responsive claim, and it needs the boxes to say anything at all: `auto` reflows
        // to what its CONTAINER can hold, so at the specimen's full width every case would be
        // one wide row and the picture would prove nothing. Three widths, one grid, no media
        // query anywhere — which is the whole argument for `auto` over a breakpoint prop.
        //
        // The widths are picked so the counts actually differ, which took arithmetic rather
        // than taste: a track floor of 16rem with a 0.5rem gap fits three columns only above
        // 49rem, so the obvious 48rem produced two and read as though `auto` barely worked.
        // 52 / 36 / 18 gives 3 -> 2 -> 1.
        id: "grid-auto-fit",
        title: "Grid — auto, reflowing to three container widths",
        node: (
          <Stack gap={4}>
            {(["52rem", "36rem", "18rem"] as const).map((width) => (
              <div key={width} style={{ width, border: "1px dashed var(--color-neutral-300)" }}>
                <Grid gap={2}>
                  <GridCell label="one" />
                  <GridCell label="two" />
                  <GridCell label="three" />
                </Grid>
              </div>
            ))}
          </Stack>
        ),
      },
      {
        // The four track floors. Pinned to 66rem with SIX cells, because that is the
        // combination at which all four differ — 6, 4, 3 and 2 columns. Both halves needed
        // arithmetic: at 48rem sm and md both yielded two, and with four cells xs and sm both
        // filled a single row, so either shortcut left two of the three non-default rules
        // unpainted. At the specimen's own width they would all fit everything. Same trap
        // `dataview-compact` exists to avoid for the density tokens.
        id: "grid-min-column",
        title: "Grid — the four track floors, at one container width",
        node: (
          <Stack gap={4}>
            {(["xs", "sm", "md", "lg"] as const).map((minColumn) => (
              <div
                key={minColumn}
                style={{ width: "66rem", border: "1px dashed var(--color-neutral-300)" }}
              >
                <Grid minColumn={minColumn} gap={2}>
                  {Array.from({ length: 6 }, (_, index) => (
                    <GridCell key={index} label={`${minColumn} · ${index + 1}`} />
                  ))}
                </Grid>
              </div>
            ))}
          </Stack>
        ),
      },
      {
        // The alignment rules, and this one CANNOT be observed without the contrived context:
        // with cells of equal height, stretch, start, center and end paint identically, so the
        // three non-default rules would be in the sheet with nothing depending on them. Each
        // row therefore holds one tall cell and one short one.
        id: "grid-align",
        title: "Grid — block alignment, with cells of unequal height",
        node: (
          <Stack gap={4}>
            {(["stretch", "start", "center", "end"] as const).map((align) => (
              <Grid key={align} columns={3} gap={2} align={align}>
                <GridCell label={align} />
                <GridCell label="tall" lines={3} />
                <GridCell label="short" />
              </Grid>
            ))}
          </Stack>
        ),
      },
      {
        // The use the primitive exists for, rather than a demonstration of it. The diagnosis's
        // sharpest piece of evidence was a fifteen-field form shipped as one long vertical run
        // because two columns could not be expressed at all — app modules may not write `style`
        // or `className`, so this was unbuildable rather than awkward. This is that form.
        id: "grid-two-column-form",
        title: "Grid — a two-column form, which was previously unbuildable",
        node: (
          <Grid columns={2} gap={4} align="start">
            <Field label="Integration name">
              <Input defaultValue="Customer master" aria-label="Integration name" />
            </Field>
            <Field label="Source system">
              <Input defaultValue="sap://prd/s1" aria-label="Source system" />
            </Field>
            <Field label="Target system" hint="Where records land after mapping.">
              <Input defaultValue="terp://ledger/s1" aria-label="Target system" />
            </Field>
            <Field label="Retention (days)">
              <Input defaultValue="90" aria-label="Retention in days" />
            </Field>
          </Grid>
        ),
      },
      {
        // Level and size are separate choices, and the last row is why: an h2 rendered at the
        // smallest step. Forcing the two together is what makes an author pick the wrong
        // element to get the right size, which is how a document's outline gets broken by a
        // styling decision. There is no level 1 — Page renders the single h1 of every routed
        // view, so a second one in a body would give the document two top-level headings.
        id: "typography-headings",
        title: "Heading — the three levels, and a level decoupled from its size",
        node: (
          <Stack gap={3}>
            <Heading level={2}>Level 2, default size</Heading>
            <Heading level={3}>Level 3, default size</Heading>
            <Heading level={4}>Level 4, default size</Heading>
            <Heading level={2} size="xl">
              Level 2 at xl
            </Heading>
            <Heading level={2} size="sm">
              Level 2 at sm
            </Heading>
          </Stack>
        ),
      },
      {
        // Every tone against every step, because tone is a colour and step is a metric and a
        // regression in either is invisible in a specimen that varies only the other.
        id: "typography-text",
        title: "Text — three tones across the type steps",
        node: (
          <Stack gap={3}>
            {(["default", "muted", "subtle"] as const).map((tone) => (
              <Stack key={tone} gap={1}>
                {(["xs", "sm", "base", "lg"] as const).map((size) => (
                  <Text key={size} tone={tone} size={size}>
                    {tone} · {size} — the quick brown fox jumps over the lazy dog.
                  </Text>
                ))}
              </Stack>
            ))}
          </Stack>
        ),
      },
      {
        // The measure, which needs prose long enough to reach it — at two words the cap is in
        // the sheet with nothing depending on it.
        id: "typography-measure",
        title: "Text — the two measures, against uncapped prose",
        node: (
          <Stack gap={3}>
            <Text>{LOREM}</Text>
            <Text measure="base">{LOREM}</Text>
            <Text measure="narrow">{LOREM}</Text>
          </Stack>
        ),
      },
      {
        // Inline inside a sentence, then a block in a box narrower than its longest line. The
        // box is the point: at the specimen's own width the sample fits, so `overflow-x` was in
        // the sheet with nothing depending on it — measured, the first recording of this
        // specimen showed no clip at all. It also shows as a CLIP rather than a scrollbar,
        // because headless Chromium gives an inner container an overlay bar that paints
        // nothing at rest, which `dataview-wide` already found the hard way. The clip is why
        // the <pre> is focusable: a scroll container a keyboard cannot reach cannot be
        // scrolled (SC 2.1.1).
        id: "typography-code",
        title: "Code — inline in a sentence, and a block clipped by its container",
        node: (
          <Stack gap={3}>
            <Text>
              Set <Code>OIDC_CLIENT_ID</Code> in <Code>.env</Code> before running{" "}
              <Code>terp dev</Code>.
            </Text>
            <div style={{ width: "26rem" }}>
              <Code block>{CODE_SAMPLE}</Code>
            </div>
          </Stack>
        ),
      },
      {
        id: "typography-link",
        title: "Link — routed and external, inside prose",
        node: routedLinkSpecimen(),
      },
      {
        // `as="ul"` on both primitives, which is the only thing that paints their list reset.
        // A <ul> arrives with a 40px inline padding and a marker per child from the UA sheet,
        // and both components document this use — so without the reset the documented use
        // rendered bulleted and indented, and no specimen rendered a list to notice.
        id: "layout-as-list",
        title: "Stack and Grid — rendered as lists, which needs the UA reset",
        node: (
          <Stack gap={4}>
            <Stack as="ul" gap={2}>
              <li>
                <GridCell label="Stack as ul · one" />
              </li>
              <li>
                <GridCell label="Stack as ul · two" />
              </li>
            </Stack>
            <Grid as="ul" columns={3} gap={2}>
              <li>
                <GridCell label="Grid as ul · one" />
              </li>
              <li>
                <GridCell label="two" />
              </li>
              <li>
                <GridCell label="three" />
              </li>
            </Grid>
          </Stack>
        ),
      },
      {
        id: "nav-icons",
        title: "NavIcon — resolved glyph beside the initial fallback",
        // The fallback tile is painted by no other specimen: every SHELL_NAV item supplies a
        // resolvable name, so the branch that renders a label's initial was invisible to both
        // lanes — which is how it kept an accent-on-accent-soft pairing that measures 1.60:1
        // in twilight until a review measured it.
        node: (
          <Stack direction="row" gap={3} align="center">
            <NavIcon name="users" label="Users" />
            <NavIcon name="no-such-glyph" label="Warehouse" />
            <NavIcon label="Records" />
          </Stack>
        ),
      },
      {
        id: "icons",
        title: "Icon — a representative sample",
        node: (
          <Stack direction="row" gap={3} wrap align="center">
            {/* The last entry used to be "close", which is not a glyph — the glyph is "x" — so
                this gallery rendered nine icons and one empty cell with a caption under it, and
                its baseline recorded the blank and passed for releases. A missing glyph and a
                glyph that is not there look identical, which is why no lane found it. Icon's
                `name` is a checked name now, so the typo is a build failure rather than a
                picture of nothing. */}
            {([
              "plus",
              "download",
              "search",
              "shield",
              "database",
              "list",
              "layers",
              "settings",
              "check",
              "x",
            ] satisfies IconName[]).map((name) => (
              <Stack key={name} gap={1} align="center">
                <Icon name={name} />
                <span style={{ fontSize: "var(--font-size-xs)" }}>{name}</span>
              </Stack>
            ))}
          </Stack>
        ),
      },
    ],
  },
  {
    id: "chrome",
    title: "Chrome",
    specimens: [
      {
        id: "theme-toggle",
        title: "ThemeToggle — both variants, closed",
        node: (
          <Stack direction="row" gap={4} align="center">
            <ThemeToggle variant="stacked" />
            <ThemeToggle variant="inline" />
          </Stack>
        ),
      },
      {
        id: "language-switcher",
        title: "LanguageSwitcher — both variants, closed",
        node: (
          <Stack direction="row" gap={4} align="center">
            <LanguageSwitcher variant="stacked" />
            <LanguageSwitcher variant="inline" />
          </Stack>
        ),
      },
      {
        // This specimen exists because a mutation went uncaught. The popover wrapper's
        // `display: inline-flex` is shared by Popover, Menu, both date pickers and all three
        // chrome menus, and no baseline could see it: every specimen rendering an inline
        // chrome toggle put it inside a Stack, and in a flex parent a blockified inline-flex
        // box and a plain block box shrink-wrap a single child to the same pixels. Dropping
        // the declaration was wrong and invisible at once. In text flow it is the whole line.
        id: "chrome-toggles-in-flow",
        title: "ThemeToggle and LanguageSwitcher — inline variants in text flow",
        node: (
          // A div rather than a p: the wrapper is a div, and phrasing content is all a
          // paragraph may hold — the browser would close the p and the specimen would be
          // measuring its own invalid markup.
          <div style={{ maxWidth: "30rem" }}>
            Theme <ThemeToggle variant="inline" /> and language{" "}
            <LanguageSwitcher variant="inline" /> sit in the line rather than breaking it.
          </div>
        ),
      },
      {
        id: "breadcrumbs",
        title: "Breadcrumbs — three levels",
        node: (
          <Breadcrumbs
            items={[
              { label: "Records", to: "/records" },
              { label: "Sync definitions", to: "/records/syncs" },
              { label: "Customer master" },
            ]}
          />
        ),
      },
      {
        id: "page-actions",
        title: "PageActions — primary, secondary and overflow",
        node: (
          <PageActions
            primary={<Button variant="primary">Publish</Button>}
            secondary={<Button variant="secondary">Save draft</Button>}
            overflow={[
              { label: "Duplicate", onSelect: () => {} },
              { label: "Delete", onSelect: () => {} },
            ]}
          />
        ),
      },
      {
        id: "menu-closed",
        title: "Menu — closed trigger",
        node: (
          <Menu trigger={<Icon name="settings" size="1.15rem" />} triggerLabel="Settings">
            {({ close }) => <MenuItem label="Duplicate" onSelect={() => close()} />}
          </Menu>
        ),
      },
      {
        // Every MenuItem state in one panel, which is one concern rather than four: this is
        // what a menu's items look like, and none of the four can mask another because they
        // sit side by side. The panel also opens with its first enabled item focused
        // (Menu.tsx roves on mount), so the shot carries the focus ring too — the one state
        // the resting baselines otherwise never capture.
        id: "menu-open",
        title: "Menu — open, with selected, destructive and disabled items",
        overlay: true,
        node: (
          <Menu
            defaultOpen
            trigger={<Icon name="settings" size="1.15rem" />}
            triggerLabel="Settings"
          >
            {({ close }) => (
              <>
                <MenuItem
                  label="Duplicate"
                  icon={<Icon name="clipboard" />}
                  onSelect={() => close()}
                />
                <MenuItem label="Comfortable" selected onSelect={() => close()} />
                <MenuItem label="Compact" selected={false} onSelect={() => close()} />
                <MenuItem label="Archive" disabled onSelect={() => close()} />
                <MenuItem
                  label="Delete"
                  destructive
                  icon={<Icon name="trash" />}
                  onSelect={() => close()}
                />
              </>
            )}
          </Menu>
        ),
      },
      {
        id: "module-nav",
        title: "ModuleNav — first tab active",
        node: moduleNavSpecimen(),
      },
      {
        id: "page-header",
        title: "Page — the band: trail, badges, lead line and actions",
        node: (
          <Page
            title="Customer master"
            breadcrumbs={[{ label: "Records", to: "/records" }]}
            badges={[
              <Badge key="state" tone="success">
                Published
              </Badge>,
              <Badge key="scope" tone="neutral">
                All regions
              </Badge>,
            ]}
            description="Every account the ERP will accept an order against."
            actions={<Button variant="primary">Publish</Button>}
          >
            <p style={{ margin: 0 }}>Body content below the header.</p>
          </Page>
        ),
      },
      {
        // The band with nothing but a title, which is the shape most pages have and the one the
        // slots must not cost anything: no badge row, no lead line, no reserved gap. Read
        // beside page-header, this pair is the only picture of "absent is absent".
        //
        // Absent here is `undefined`. The falsy cases a caller actually writes —
        // `badges={isPublished && <Badge/>}` handing this `false` — are held by Page.test.tsx
        // instead, because `false` and `undefined` render identically and a screenshot cannot
        // tell one empty band from another.
        id: "page-header-bare",
        title: "Page — the band with a title and nothing else",
        node: (
          <Page title="Customer master" breadcrumbs={[{ label: "Records", to: "/records" }]}>
            <p style={{ margin: 0 }}>Body content below the header.</p>
          </Page>
        ),
      },
      {
        // A root page, which is a trail of ONE rather than a bare heading: an overview's title
        // has to sit in the same boxes as a detail's or the name moves the moment you open a
        // record, so the Breadcrumb landmark is present here with nothing to link to yet.
        // What this picture is for is that the band's chrome — the border and the header's
        // height — is identical whether or not there are ancestors in front of the leaf.
        id: "page-header-root",
        title: "Page — a root page, heading with no trail",
        node: (
          <Page
            title="Customer master"
            badges={<Badge tone="neutral">Read only</Badge>}
            actions={<Button variant="primary">Publish</Button>}
          >
            <p style={{ margin: 0 }}>Body content below the header.</p>
          </Page>
        ),
      },
      {
        // A long title meeting a wide action cluster: the band wraps rather than overflowing,
        // and grows past its floor when it does. The lead line truncates instead of wrapping,
        // which is the declaration a screenshot can actually hold.
        id: "page-header-crowded",
        title: "Page — a long title, a lead line and a wide action cluster",
        node: (
          <Page
            title="Customer master data, consolidated across every operating company"
            breadcrumbs={[
              { label: "Records", to: "/records" },
              { label: "Master data", to: "/records/master" },
            ]}
            badges={<Badge tone="warning">Review</Badge>}
            description="A lead line long enough that it has to be cut off rather than allowed to wrap onto a second line and set the band's height."
            actions={
              <PageActions
                primary={<Button variant="primary">Publish</Button>}
                secondary={<Button>Discard</Button>}
                overflow={[{ label: "Delete", variant: "destructive", onSelect: () => {} }]}
              />
            }
          >
            <p style={{ margin: 0 }}>Body content below the header.</p>
          </Page>
        ),
      },
      {
        // `Page`'s two async frames, which nothing pictured. The header staying put while the
        // body is replaced is the frame's whole promise — the user keeps their place in the
        // layers — and `loading-state` / `error-state` photograph those blocks standing alone,
        // never inside the frame that swaps them in.
        //
        // The fixed-height GRID wrapper is not decoration, and a plain fixed-height div would
        // not do. `Page`'s own grid declares `align-content: start`, and that declaration is
        // unobservable unless the article is taller than its content: as a block child of a
        // tall box the article is content-height, so start and stretch paint identically and
        // the declaration would move into the sheet with no baseline able to see it. A grid
        // wrapper stretches the article to the full 24rem, and then packing the two rows at
        // the top rather than spreading them is exactly what the picture shows.
        id: "page-loading",
        title: "Page — the body is loading, the header stays",
        node: (
          <div style={{ height: "24rem", display: "grid", border: "1px solid var(--color-neutral-200)" }}>
            <Page
              title="Customer master"
              breadcrumbs={[{ label: "Records", to: "/records" }]}
              actions={<Button variant="primary">Publish</Button>}
              isLoading
            >
              <p style={{ margin: 0 }}>Never rendered while isLoading is set.</p>
            </Page>
          </div>
        ),
      },
      {
        // Both props are set, and the picture has to be the error. `error` winning over
        // `isLoading` is a documented `Page` behaviour with no other gate — without it a query
        // that failed could sit on a spinner for ever — and it is only assertable in a picture
        // if the picture is taken with both set. Same box and same header as `page-loading`, so
        // the two differ in one thing.
        id: "page-error",
        title: "Page — the body failed, and error beats isLoading",
        node: (
          <div style={{ height: "24rem", display: "grid", border: "1px solid var(--color-neutral-200)" }}>
            <Page
              title="Customer master"
              breadcrumbs={[{ label: "Records", to: "/records" }]}
              actions={<Button variant="primary">Publish</Button>}
              isLoading
              error="The record could not be loaded."
            >
              <p style={{ margin: 0 }}>Never rendered while error is set.</p>
            </Page>
          </div>
        ),
      },
      {
        // The first picture of a governed OVERVIEW body anywhere, and the reason it needs
        // three children rather than one is a rule, not composition taste.
        //
        // `Page` is already pictured — `page-header`, `page-loading` and `page-error` all
        // render it directly. What had no picture is either archetype that WRAPS it, and with
        // it the shape the layout contract actually admits: 4b widened the overview slot to
        // take `Text` as a lead paragraph and `Divider` as a rule between sections, and no
        // specimen has ever rendered either inside a governed body. Three children also put
        // TWO of the page grid's `gap: var(--space-4)` rows between body siblings in frame;
        // `page-header` has one body child, so it only ever exercised the header-to-body gap.
        //
        // No `parents`, which is the overview's own trail contract: a module's top-level
        // listing omits the redundant current-page-only crumb, so this is the one archetype
        // specimen with a title row and no breadcrumb above it.
        id: "overview-page",
        title: "OverviewPage — lead paragraph, rule, collection",
        node: (
          <OverviewPage title="Sync definitions" actions={<Button variant="primary">New sync</Button>}>
            <Text tone="muted">
              Every definition that moves records between a source system and the ledger.
            </Text>
            <Divider />
            <DataView repository={SYNC_REPOSITORY} columns={SYNC_COLUMNS} />
          </OverviewPage>
        ),
      },
      {
        // The detail archetype, and the two things only it can show.
        //
        // The breadcrumb trail is REQUIRED here — `parents` is non-optional on `DetailPage`
        // precisely so a record is never orphaned from its overview — so this is the trail at
        // its real depth (hub, overview, record) rather than the single ancestor `page-header`
        // renders.
        //
        // And the body is the record-sections shape the contract admits: `DetailList` for the
        // record's own fields, a rule, then a `Card` whose body is a `DataView`. That last
        // pairing is the case `variant="plain"` was shipped for in 4b, and this is the first
        // specimen to render it in that case rather than alone: the section's heading sits
        // flush above a table that keeps its own full width and its own single border, which
        // is what boxing it would take away. `card-plain` shows the variant; this shows why.
        id: "detail-page",
        title: "DetailPage — record fields, rule, a boxed collection",
        node: (
          <DetailPage
            title="Customer master"
            parents={[
              { label: "Records", to: "/records" },
              { label: "Sync definitions", to: "/records/syncs" },
            ]}
            actions={<Button variant="secondary">Run now</Button>}
          >
            <DetailList
              layout="aligned"
              items={[
                { label: "Source", value: "sap://prd/customers" },
                { label: "Target", value: "terp://ledger/customers" },
                { label: "Window", value: "02:00–04:00 UTC" },
                { label: "Retention", value: "90 days" },
              ]}
            />
            <Divider />
            <Card title="Recent runs" variant="plain">
              <DataView repository={SYNC_REPOSITORY} columns={SYNC_COLUMNS} />
            </Card>
          </DetailPage>
        ),
      },
      {
        // The form archetype, and the two things only it shows.
        //
        // `measure="narrow"` is its default, so the whole frame — header included — caps at
        // 32rem against a ~1232px specimen card. That asymmetry with the shell's content
        // measure is the design rather than an inconsistency: a wide page with a narrow column
        // wants its title spanning the track, a form does not, and a Save button a screen-width
        // from its last field is worse than one sitting over it. This is the only picture of a
        // capped HEADER anywhere.
        //
        // And the body is a `Stack as="form"` rather than a run of `Field`s, which is the
        // contract's one real refusal here: bare fields cannot be submitted, because Enter does
        // nothing without a form element. The specimen renders the legal shape so the picture
        // and the slot table agree.
        id: "form-page",
        title: "FormPage — a capped frame around one form",
        node: (
          <FormPage
            title="New sync definition"
            parents={[{ label: "Sync definitions", to: "/records/syncs" }]}
            actions={
              <PageActions
                secondary={<Button variant="secondary">Cancel</Button>}
                primary={<Button variant="primary">Create</Button>}
              />
            }
          >
            <Stack as="form" gap={4}>
              <Field label="Name">
                <Input defaultValue="Customer master" />
              </Field>
              <Field label="Source system" hint="Where records are read from.">
                <Select
                  options={[
                    { value: "sap", label: "SAP production" },
                    { value: "ledger", label: "Ledger" },
                  ]}
                  defaultValue="sap"
                />
              </Field>
              <Field label="Retention" error="Must be between 1 and 3650 days.">
                <Input type="number" defaultValue="90" />
              </Field>
            </Stack>
          </FormPage>
        ),
      },
      {
        // The settings archetype: `Card` sections and nothing that holds a collection.
        //
        // Two sections rather than one, because the gap between them is the only thing the
        // page grid contributes here and one card cannot show it. And no `parents`, which is
        // the difference from `FormPage` in the trail: a preferences screen is a destination,
        // not something reached from the thing it writes into, so this is the narrow frame
        // WITHOUT a breadcrumb above it — the other half of the pair.
        id: "settings-page",
        ready: '[data-terp="card"]',
        title: "SettingsPage — capped frame, Card sections, no trail",
        node: (
          <SettingsPage title="Preferences">
            <Card title="Appearance" description="How the app looks on this device.">
              <Stack gap={3}>
                <Field label="Theme">
                  <Select
                    options={[
                      { value: "system", label: "Follow the system" },
                      { value: "dark", label: "Dark" },
                    ]}
                    defaultValue="system"
                  />
                </Field>
                <Switch label="Compact rows" defaultChecked />
              </Stack>
            </Card>
            <Card title="Notifications" description="What gets sent, and where.">
              <Stack gap={3}>
                <Switch label="Email on failure" defaultChecked />
                <Switch label="Daily digest" />
              </Stack>
            </Card>
          </SettingsPage>
        ),
      },
      {
        // The split archetype at its wide layout. The panes are only two columns above the
        // 768px cutover — below it they stack, list first — so this is the picture of the
        // two-column half and `split-page-narrow` below is the other.
        //
        // The list pane holds something with a real minimum width, for the reason
        // `app-shell-narrow` needed a DataView rather than a paragraph: the `minmax(0, 24rem)`
        // track and the pane's own `min-width: 0` only do anything under content pressure. A
        // paragraph would shrink quietly and prove neither.
        //
        // Both panes also carry something FOCUSABLE — a button per row, an action on the record
        // in the detail — and that is not decoration. `visual/keyboard.spec.ts`
        // asserts the tab order runs list-then-detail at both layouts, and the first version of
        // this specimen had plain spans in the list and a bare Card beside it: nothing focusable
        // in either pane, so the sequence under test was empty and the assertion vacuous. The
        // lane's own guard caught it. A master-detail list whose rows cannot be activated is
        // also not one.
        //
        // Hence `SignedIn` around both: `ResourceList`'s row actions are write-gated, so they
        // need the auth context, which the dev server's own `workbench-mock-auth` plugin
        // answers with a fixed rank-30 user. The `resource-list` specimen already relies on
        // exactly that.
        id: "split-page",
        ready: '[data-terp="splitpane"]',
        title: "SplitPage — list beside the record it selects",
        node: (
          <SplitPage
            title="Sync definitions"
            parents={[{ label: "Records", to: "/records" }]}
            actions={<Button variant="primary">New sync</Button>}
          >
            {/* Buttons in a Stack rather than a `ResourceList`, and that is a determinism
                fix rather than a simplification. `ResourceList` wraps its row actions in
                `<Authorized action="write">`, which resolves only after the auth boot's two
                round-trips — so the rows appeared or did not depending on when the shot was
                taken, and the FIRST recording of these two baselines caught the state without
                them: 385px tall against 430 once the session landed. `toHaveScreenshot` keeps
                shooting until two consecutive frames match, which stabilises on whichever
                state it finds and cannot tell one from the other.
                So the rule is narrower than the registry's "no live data": a specimen may sit
                behind the auth seam, because the dev server answers it with a fixed user — but
                nothing it RENDERS may depend on the session having resolved. `SignedIn` alone
                is fine; `Authorized` content inside it is not.
                (`ResourceList` also renders a bare, unmarked `<h1>` for its optional `title`,
                which its own docs warn about under a Page. That is a separate finding and it
                is recorded in the changelog rather than worked around here.) */}
            <SplitPane role="list" label="Definitions">
              <Stack as="ul" gap={1}>
                {SPLIT_ROWS.map((row) => (
                  <li key={row}>
                    <Button variant="ghost" fullWidth>
                      {row}
                    </Button>
                  </li>
                ))}
              </Stack>
            </SplitPane>
            <SplitPane role="detail" label="Selected definition">
              <Card
                title="Customer master"
                description="sap://prd/customers"
                actions={<Button variant="secondary">Run now</Button>}
              >
                <DetailList
                  layout="aligned"
                  items={[
                    { label: "Window", value: "02:00–04:00 UTC" },
                    { label: "Retention", value: "90 days" },
                    { label: "Last run", value: "1284 rows" },
                  ]}
                />
              </Card>
            </SplitPane>
          </SplitPage>
        ),
      },
      {
        // The split's own cutover, and it needs a viewport of its own for the reason the
        // shell's mobile specimen does: the two-column rule lives in the sheet's single
        // wide-viewport block, so at the pinned 1280 it always applies and the stacked layout
        // is unreachable. 700x900 is below the 768px breakpoint the chrome around it uses.
        //
        // What the picture is FOR is the order: list first, detail under it, which is also the
        // tab sequence. A `row-reverse` or an `order` in the two-column rule would look right
        // wide and read backwards narrow, and `visual/keyboard.spec.ts` holds the same property
        // at both widths.
        id: "split-page-narrow",
        title: "SplitPage — stacked below the breakpoint, list first",
        viewport: { width: 700, height: 900 },
        node: (
          <SplitPage title="Sync definitions" listWidth="md">
            <SplitPane role="list" label="Definitions">
              <Stack as="ul" gap={1}>
                {SPLIT_ROWS.map((row) => (
                  <li key={row}>
                    <Button variant="ghost" fullWidth>
                      {row}
                    </Button>
                  </li>
                ))}
              </Stack>
            </SplitPane>
            <SplitPane role="detail" label="Selected definition">
              <Card
                title="Customer master"
                description="sap://prd/customers"
                actions={<Button variant="secondary">Run now</Button>}
              >
                <DetailList items={[{ label: "Retention", value: "90 days" }]} />
              </Card>
            </SplitPane>
          </SplitPage>
        ),
      },
      {
        id: "hub-page",
        title: "HubPage — card grid with stats",
        node: (
          <HubPage title="Records">
            <HubCard
              to="/records/syncs"
              title="Sync definitions"
              description="What moves, and when."
              icon={<Icon name="layers" />}
              stat="14 active"
            />
            <HubCard
              to="/records/links"
              title="Links"
              description="Connections to source systems."
              icon={<Icon name="database" />}
              stat="3 connected"
            />
            <HubCard
              to="/records/history"
              title="History"
              description="Every run, kept."
              icon={<Icon name="list" />}
            />
          </HubPage>
        ),
      },
      {
        // The minimum card beside a full one, which nothing else renders: hub-page gives every
        // card an icon and a description. Three things are only observable here.
        //
        // The icon tile's ABSENCE — the title row has to close up rather than reserve the
        // 2.25rem box, and no other specimen has a card without one.
        //
        // And both placeholder rows. HubCard renders a non-breaking space at visibility: hidden
        // when description or stat is missing, so the card's three grid rows keep their heights
        // and a bare card stays flush with a full one in the same row. That only means anything
        // with a full card beside it, which is why this specimen has two: if the placeholders
        // stop working, the two card bodies stop lining up.
        id: "hub-card-bare",
        title: "HubCard — the minimum card beside a full one",
        node: (
          <HubPage title="Records">
            <HubCard to="/records/audit" title="Audit trail" />
            <HubCard
              to="/records/syncs"
              title="Sync definitions"
              // Deliberately long enough to push this card past the body's 10rem floor. That
              // is what makes the height CHAIN observable: the grid stretches both <li>s to
              // the taller row, and the bare card's anchor has to carry that height down to
              // its body or it hugs its own content and leaves a gap below it. With both
              // cards at the floor, forcing the anchor inline changed nothing — measured, at
              // 160px either way — so the mutation passed and the rule was ungated.
              description="What moves, when it moves, and which source system each record came from. Long enough on purpose: the description track is minmax(3rem, 1fr), so it absorbs slack until the card's own content passes the ten-rem floor, and only past that floor does the grid have to stretch the bare card beside it."
              icon={<Icon name="layers" />}
              stat="14 active"
            />
          </HubPage>
        ),
      },
      {
        id: "user-menu",
        ready: '[data-terp="avatar"]',
        title: "UserMenu — closed trigger",
        node: (
          <SignedIn>
            <UserMenu onSettings={() => {}} />
          </SignedIn>
        ),
      },
      {
        id: "user-menu-collapsed",
        ready: '[data-terp="avatar"]',
        title: "UserMenu — collapsed (icon rail)",
        node: (
          <SignedIn>
            <UserMenu collapsed onSettings={() => {}} />
          </SignedIn>
        ),
      },
      {
        // The account menu's own geometry lives in its PANEL — a wider minimum, its own
        // padding, and the identity block above the items — and the panel is portalled to
        // document.body, so those rules are keyed on the owner attribute rather than on
        // anything reachable from the trigger. Closed, none of it is painted; this is the only
        // baseline that sees it.
        id: "user-menu-open",
        ready: '[data-terp="avatar"]',
        title: "UserMenu — open panel with the identity block",
        overlay: true,
        node: (
          <SignedIn>
            <UserMenu defaultOpen onSettings={() => {}} />
          </SignedIn>
        ),
      },
      {
        id: "login-view",
        ready: '[data-terp="login-form"]',
        title: "LoginView — credentials and SSO",
        node: (
          // Height-clipped: the view is a 100vh page; the clip keeps the centered form in
          // the picture while the specimen stays a bounded box.
          <div style={{ height: "42rem", overflow: "hidden", border: "1px solid var(--color-neutral-200)" }}>
            <SignedIn>
              <LoginView ssoProviders={[{ name: "microsoft", label: "Microsoft" }]} />
            </SignedIn>
          </div>
        ),
      },
      {
        id: "profile-view",
        ready: '[data-terp="profile-card"]',
        title: "ProfileView — identity and preferences",
        node: (
          <SignedIn>
            <ProfileView />
          </SignedIn>
        ),
      },
      {
        // The renderLink here marks the first item current, which no version of this specimen
        // did before. It is not decoration: the active route's whole treatment — the brand-soft
        // wash, the accent ink, the heavier weight — used to be NAV_LINK_ACTIVE_STYLE, a style
        // object the shell handed the router to spread onto its own link. It is a rule keyed on
        // aria-current="page" now, and this is the only thing that paints it.
        id: "app-shell",
        title: "AppShell — sidebar, header and content",
        node: (
          // 60rem rather than the 24rem this used to be, and it is a fix rather than a
          // preference: the shell declares min-height: 100vh, so in a 24rem box its footer sat
          // at y=932 while the element clip ended at 473 — measured — and the footer's four
          // declarations were in no baseline at all. A specimen of the shell that cuts off one
          // of the shell's own landmarks is not a specimen of the shell. Still a fixed box
          // rather than the bare viewport, so the composition stays deterministic.
          <div style={{ height: "60rem", border: "1px solid var(--color-neutral-200)" }}>
            <AppShell
              title="Terp workbench"
              nav={SHELL_NAV}
              renderLink={(item, children) => (
                <a href={item.to} aria-current={item.to === "/" ? "page" : undefined}>
                  {children}
                </a>
              )}
            >
              <p style={{ margin: 0 }}>Page content renders in the main region.</p>
            </AppShell>
          </div>
        ),
      },
      {
        // The icon rail, which nothing has ever rendered. It is localStorage-backed internal
        // state, so before defaultCollapsed existed there was no way into it from a specimen or
        // a test — and four rules apply to this state and no other: the sidebar's 4rem width,
        // the brand's centring, and the visually-hidden treatment of the brand title and of
        // every nav label. All four shipped unpainted.
        //
        // Deliberately the same nav and the same active item as app-shell above, so the two
        // baselines differ in exactly one thing.
        id: "app-shell-collapsed",
        title: "AppShell — collapsed to the icon rail",
        node: (
          // Same box as app-shell above, so the two baselines differ in one thing.
          <div style={{ height: "60rem", border: "1px solid var(--color-neutral-200)" }}>
            <AppShell
              title="Terp workbench"
              nav={SHELL_NAV}
              defaultCollapsed
              renderLink={(item, children) => (
                <a href={item.to} aria-current={item.to === "/" ? "page" : undefined}>
                  {children}
                </a>
              )}
            >
              <p style={{ margin: 0 }}>Page content renders in the main region.</p>
            </AppShell>
          </div>
        ),
      },
      {
        // The shell below its own breakpoint, which no lane has ever rendered. The viewport is
        // pinned at 1280 and the mobile variant needs 768 or less, so `styles.test.ts` asserts
        // the mobile geometry as TEXT and says why in as many words: "no baseline can hold it".
        // A per-specimen viewport is what holds it.
        //
        // Drawer CLOSED, which is the whole composition at this width: on mobile the sidebar
        // renders only while the drawer is open, so this is the header, the main region at its
        // tightened padding, and the footer. The open drawer — its geometry, the backdrop, the
        // focus sentinels — needs a way into internal state that does not exist yet, exactly as
        // the icon rail needed `defaultCollapsed`; it belongs with the shell work rather than
        // here.
        id: "app-shell-mobile",
        title: "AppShell — below the mobile breakpoint, drawer closed",
        viewport: { width: 420, height: 900 },
        node: (
          // The same 60rem box as its two desktop siblings, for the same measured reason: the
          // shell declares min-height: 100vh, so a shorter box clips its own footer out of the
          // element shot.
          <div style={{ height: "60rem", border: "1px solid var(--color-neutral-200)" }}>
            <AppShell
              title="Terp workbench"
              nav={SHELL_NAV}
              renderLink={(item, children) => (
                <a href={item.to} aria-current={item.to === "/" ? "page" : undefined}>
                  {children}
                </a>
              )}
            >
              <p style={{ margin: 0 }}>Page content renders in the main region.</p>
            </AppShell>
          </div>
        ),
      },
      {
        // The content measure and the band it creates, which are one mechanism and need one
        // picture (ADR 0097 §2). Three things are only visible here, and the viewport is the
        // one that was measured rather than predicted.
        //
        // `--shell-content-max-width` is 80rem = 1280px, and the rule caps nothing until the
        // article's own track is wider than that. Measured, at three widths, with this
        // specimen's wrapper, `appshell-main`'s padding and the scrollbar gutter all in play:
        //
        //     1280 -> article 898, body 898     (rule matches, caps nothing)
        //     1600 -> article 1218, body 1218   (still nothing)
        //     1920 -> article 1538, body 1280   (258px of cap, and a band)
        //
        // So the pinned 1280 is not merely a weak picture of this rule, it is a green baseline
        // over a declaration that never fires — and so is 1600, which was the first guess. A
        // predicted figure said 1632/352px at 1920 by subtracting only the sidebar and the main
        // padding; the real track is 1538 because the specimen's own box and the gutter come
        // off too. Threshold-shaped rules need the number from the browser.
        //
        // The body has to be something that WANTS the full width, for the reason
        // `app-shell-narrow` needed a DataView rather than a paragraph: a short block is
        // narrower than the measure either way, so the rule would apply to nothing observable.
        //
        // And the page needs a header with a trail, because the band IS that header — no new
        // element, no portal. Without breadcrumbs the header row is one short title and the
        // full-track behaviour has nothing to show; with them the trail runs the full 1538
        // while the table below it stops at 1280, which is the whole shape.
        id: "app-shell-measured",
        title: "AppShell — content capped at the measure, header on the full track",
        viewport: { width: 1920, height: 900 },
        node: (
          // 60rem, matching its three sibling shell specimens rather than the 50rem this
          // started with. The shell declares min-height: 100vh, so in an 800px box at a 900px
          // viewport it lays out taller than its container and paints past the card's edge —
          // and the element screenshot clips to the card, so the footer was cropped out of both
          // recorded baselines.
          <div style={{ height: "60rem", border: "1px solid var(--color-neutral-200)" }}>
            <AppShell
              title="Terp workbench"
              nav={SHELL_NAV}
              contentWidth="measured"
              renderLink={(item, children) => (
                <a href={item.to} aria-current={item.to === "/" ? "page" : undefined}>
                  {children}
                </a>
              )}
            >
              <Page
                title="Sync definitions"
                breadcrumbs={[{ label: "Records", to: "/records" }]}
                actions={<Button variant="primary">New sync</Button>}
              >
                <DataView repository={SYNC_REPOSITORY} columns={WIDE_SYNC_COLUMNS} />
              </Page>
            </AppShell>
          </div>
        ),
      },
      {
        // The mobile drawer, open — the first picture of four rules that shipped four releases
        // ago and have never been painted.
        //
        // `styles.test.ts` asserts them as TEXT, with "no baseline can hold it" written beside
        // them, and that was true: below the breakpoint the sidebar renders only while
        // `drawerOpen` is set, which is internal state with no way in. A per-specimen viewport
        // was not enough — `app-shell-mobile` already renders at 420x900 and shows the drawer
        // CLOSED. `defaultDrawerOpen` is the door, the same one `defaultCollapsed` opened for
        // the icon rail, where four rules were likewise unpainted behind it.
        //
        // What comes into frame: the drawer's `position: fixed` / `100dvh` / drawer z-index /
        // shadow, the backdrop's `inset: 0` and its 40% black, and the brand row with its close
        // button — which exists only on mobile and had no picture either.
        //
        // `overlay: true`, and not as a precaution: the drawer is `position: fixed` and the
        // backdrop is `inset: 0`, so both paint outside the specimen element's box. An element
        // shot would clip to the card and record the page behind them.
        id: "app-shell-drawer-open",
        title: "AppShell — the mobile drawer, open over its backdrop",
        viewport: { width: 420, height: 900 },
        overlay: true,
        node: (
          <div style={{ height: "50rem", border: "1px solid var(--color-neutral-200)" }}>
            <AppShell
              title="Terp workbench"
              nav={SHELL_NAV}
              defaultDrawerOpen
              renderLink={(item, children) => (
                <a href={item.to} aria-current={item.to === "/" ? "page" : undefined}>
                  {children}
                </a>
              )}
            >
              <p style={{ margin: 0 }}>The page behind the drawer, inert while it is open.</p>
            </AppShell>
          </div>
        ),
      },
      {
        // The comfortable island: a compact shell with one deliberately comfortable table
        // inside it. This is the picture the density vocabulary was missing, and the thing it
        // shows is a NEGATIVE — that the inner DataView did not inherit the shell's density.
        //
        // Before this, `density="comfortable"` stamped nothing, on the reasoning that
        // comfortable was the sheet's own :root value. That held only while nothing could make
        // an ancestor compact. A shell density makes the combination legal and silently
        // inert — the defect shape this phase has refused three times — so comfortable gained
        // named tokens and a rule of its own, and the two now compose through inheritance
        // rather than through absence. (An earlier version of this note counted how many
        // times the phase had refused that shape, and disagreed with the four other places
        // that counted it. A citation keeps; a tally rots.)
        //
        // Two DataViews, because one cannot show an island. The first inherits the shell's
        // compact cells; the second sits beside it at the comfortable padding. If the island
        // rule were deleted, the two would become identical and this baseline would say so.
        id: "app-shell-density-island",
        title: "AppShell — a compact shell with one comfortable table in it",
        node: (
          <div style={{ height: "44rem", border: "1px solid var(--color-neutral-200)" }}>
            <AppShell
              title="Terp workbench"
              nav={SHELL_NAV}
              density="compact"
              renderLink={(item, children) => (
                <a href={item.to} aria-current={item.to === "/" ? "page" : undefined}>
                  {children}
                </a>
              )}
            >
              <Stack gap={4}>
                <Text tone="muted">Inheriting the shell: compact cells.</Text>
                <DataView repository={SYNC_REPOSITORY} columns={SYNC_COLUMNS} />
                <Text tone="muted">An island: comfortable, inside the same compact shell.</Text>
                <DataView
                  repository={SYNC_REPOSITORY}
                  columns={SYNC_COLUMNS}
                  density="comfortable"
                />
              </Stack>
            </AppShell>
          </div>
        ),
      },
      {
        // The brand seam: a fixed-colour mark that cannot survive both appearances, so the app
        // supplies a pair and the SHEET picks. The two baselines are the gate and they only work
        // as a pair — the light one must show the dark-ink mark and the dark one the light-ink
        // mark, so deleting either switch rule, or getting the two the wrong way round, moves
        // exactly one of them.
        //
        // Collapsed as well, which is the other half of the seam: the rail is 4rem, and before
        // the mark had a box of its own an oversized asset was clipped by the aside's
        // overflow-x: hidden with nothing to say so. There is no separate collapsed-mark slot
        // and this is why — `logo` is the mark, `title` is the wordmark, and the rail already
        // hides the second.
        id: "app-shell-brand-pair",
        title: "AppShell — a brand mark per appearance, in the collapsed rail",
        node: (
          <div style={{ height: "30rem", border: "1px solid var(--color-neutral-200)" }}>
            <AppShell
              title="Terp workbench"
              nav={SHELL_NAV}
              logo={BRAND_MARK_LIGHT}
              logoDark={BRAND_MARK_DARK}
              defaultCollapsed
              renderLink={(item, children) => (
                <a href={item.to} aria-current={item.to === "/" ? "page" : undefined}>
                  {children}
                </a>
              )}
            >
              <Text tone="muted">One asset per appearance; the theme decides.</Text>
            </AppShell>
          </div>
        ),
      },
      {
        // The header placement: no sidebar at all, the nav in a horizontal row, the brand and
        // the user menu in the header with it. Deleting the list rule collapses the four links
        // back into a vertical grid inside the header, which is unmissable here; deleting the
        // surface rule moves the light header from #f8fafc back to #ffffff, which is small and
        // still a diff. The third rule of the three — overflow: visible on the nav — no
        // baseline can hold, because it only matters around a focus ring; the computed lane
        // asserts it against the sidebar shell, where the same nav is a scroll container.
        //
        // navFooter is a plain button rather than the real UserMenu on purpose. UserMenu needs
        // TerpProvider, and an async boot is exactly the nondeterminism that recorded two split
        // panes at their pre-auth width earlier in this phase — toHaveScreenshot stabilises on
        // whichever state it finds and reports nothing.
        id: "app-shell-header-nav",
        title: "AppShell — the navigation in the header, with no sidebar",
        node: (
          <div style={{ height: "44rem", border: "1px solid var(--color-neutral-200)" }}>
            <AppShell
              title="Terp workbench"
              nav={SHELL_NAV}
              navPlacement="header"
              navFooter={
                <Button variant="secondary" size="sm">
                  Account
                </Button>
              }
              renderLink={(item, children) => (
                <a href={item.to} aria-current={item.to === "/" ? "page" : undefined}>
                  {children}
                </a>
              )}
            >
              <Stack gap={4}>
                <Text tone="muted">
                  Few destinations, no permanent chrome: the shape the template&rsquo;s portal
                  preset asks for.
                </Text>
                <DataView repository={SYNC_REPOSITORY} columns={SYNC_COLUMNS} />
              </Stack>
            </AppShell>
          </div>
        ),
      },
      {
        // Navigation groups in the sidebar. Same four destinations as `app-shell` above, so the
        // two baselines differ in exactly one thing: the grouping.
        //
        // Three rules land here and no earlier baseline holds any of them — the label's own
        // block (size, weight, the uppercase treatment and 0.08em from the published scale), the
        // adjacent-sibling margin that separates one group from the next, and the label's
        // horizontal padding lining it up with the icons under it. Delete the label rule and the
        // section headers become body-sized sentence-case text, which is unmissable here.
        //
        // "Archief" is declared and never referenced, so it renders nowhere. That negative is
        // half the point of the picture: a label over a void is the failure the empty-group rule
        // exists to prevent, and it would be plainly visible if the rule were removed.
        id: "app-shell-nav-groups",
        title: "AppShell — the navigation in declared groups",
        node: (
          <div style={{ height: "60rem", border: "1px solid var(--color-neutral-200)" }}>
            <AppShell
              title="Terp workbench"
              nav={SHELL_NAV_GROUPED}
              navGroups={SHELL_NAV_GROUPS}
              renderLink={(item, children) => (
                <a href={item.to} aria-current={item.to === "/" ? "page" : undefined}>
                  {children}
                </a>
              )}
            >
              <p style={{ margin: 0 }}>Page content renders in the main region.</p>
            </AppShell>
          </div>
        ),
      },
      {
        // The same grouped nav collapsed to the icon rail, which is where the group labels stop
        // being readable and the structure has to survive without them. Two rules apply here and
        // nowhere else: the label joins the visually-hidden block, and a divider takes over the
        // job the label was doing. Delete the divider rule and the rail becomes one
        // undifferentiated column of icons — the grouping simply vanishes at 4rem, which is the
        // failure worth having a picture of.
        //
        // Same box and same nav as `app-shell-nav-groups` above, so the pair differs in the rail
        // state alone.
        id: "app-shell-nav-groups-collapsed",
        title: "AppShell — grouped navigation collapsed to the icon rail",
        node: (
          <div style={{ height: "60rem", border: "1px solid var(--color-neutral-200)" }}>
            <AppShell
              title="Terp workbench"
              nav={SHELL_NAV_GROUPED}
              navGroups={SHELL_NAV_GROUPS}
              defaultCollapsed
              renderLink={(item, children) => (
                <a href={item.to} aria-current={item.to === "/" ? "page" : undefined}>
                  {children}
                </a>
              )}
            >
              <p style={{ margin: 0 }}>Page content renders in the main region.</p>
            </AppShell>
          </div>
        ),
      },
      {
        // Groups in the header placement, which is the case that decided the CSS. Without the
        // row rules each group wrapper is a block, so a two-group header renders one stacked
        // list per group and grows the header — a navigation put in the header precisely to
        // avoid permanent chrome, taking three lines of it. Delete the nav's `display: flex` and
        // that is what this baseline shows.
        //
        // It is also the picture of a rule that exists only to be undone: the label's block
        // padding is right in a column and wrong in a row, where it adds to the group gap and
        // pushes the label off the links' centre line. The single-group case is already held by
        // `app-shell-header-nav`, and that baseline must NOT move — the row rules are written so
        // that one wrapper behaves exactly as the bare list did.
        //
        // navFooter is a plain button rather than the real UserMenu, for the reason
        // `app-shell-header-nav` records: UserMenu needs TerpProvider, and an async boot is
        // exactly the nondeterminism a screenshot stabilises on silently.
        id: "app-shell-header-nav-groups",
        title: "AppShell — grouped navigation in the header, as a row",
        node: (
          <div style={{ height: "44rem", border: "1px solid var(--color-neutral-200)" }}>
            <AppShell
              title="Terp workbench"
              nav={SHELL_NAV_GROUPED}
              navGroups={SHELL_NAV_GROUPS}
              navPlacement="header"
              navFooter={
                <Button variant="secondary" size="sm">
                  Account
                </Button>
              }
              renderLink={(item, children) => (
                <a href={item.to} aria-current={item.to === "/" ? "page" : undefined}>
                  {children}
                </a>
              )}
            >
              <Stack gap={4}>
                <Text tone="muted">
                  Groups run along the row; the sidebar&rsquo;s stacking margin is scoped away
                  from this placement, where it would be a cross-axis margin.
                </Text>
                <DataView repository={SYNC_REPOSITORY} columns={SYNC_COLUMNS} />
              </Stack>
            </AppShell>
          </div>
        ),
      },
      {
        // The grouped mobile drawer, and it exists for an INTERACTION rather than for a rule of
        // its own. `headerNav` is `!isMobile && navPlacement === "header"`, so below the
        // breakpoint the shell stamps no `data-nav-placement` at all and a header-placement app
        // gets the grouped drawer under the SIDEBAR rules — the only navigation it has on a
        // phone. Nothing else in the suite renders that combination, and the scoping decision
        // that keeps the stacking margin off the header row is exactly what has to keep it ON
        // here. `navPlacement="header"` is passed deliberately: it is the case that would break.
        //
        // A new specimen rather than groups added to `app-shell-drawer-open`, and that is a
        // constraint rather than a preference: that specimen has a win32 baseline recorded on a
        // developer machine, and Windows Chrome is blocked by group policy here, so changing it
        // would leave a baseline that is knowingly wrong and unrecordable. New specimens are
        // linux-only either way.
        //
        // `overlay: true` for the reason `app-shell-drawer-open` records: the drawer is
        // `position: fixed` and its backdrop is `inset: 0`, so both paint outside the element box.
        id: "app-shell-nav-groups-drawer",
        title: "AppShell — grouped navigation in the mobile drawer",
        viewport: { width: 420, height: 900 },
        overlay: true,
        node: (
          <div style={{ height: "50rem", border: "1px solid var(--color-neutral-200)" }}>
            <AppShell
              title="Terp workbench"
              nav={SHELL_NAV_GROUPED}
              navGroups={SHELL_NAV_GROUPS}
              navPlacement="header"
              defaultDrawerOpen
              renderLink={(item, children) => (
                <a href={item.to} aria-current={item.to === "/" ? "page" : undefined}>
                  {children}
                </a>
              )}
            >
              <p style={{ margin: 0 }}>The page behind the drawer, inert while it is open.</p>
            </AppShell>
          </div>
        ),
      },
      {
        // The desktop shell just above the breakpoint — the band between 769px and wide, which
        // the pinned viewport also cannot reach. The sidebar's `flex-shrink: 0` is documented as
        // biting here and nowhere else, and the content is deliberately something with a real
        // min-content width rather than a short paragraph, because a row under no pressure
        // never asks a flex item whether it may shrink.
        id: "app-shell-narrow",
        ready: '[data-terp="dataview-table"]',
        title: "AppShell — just above the mobile breakpoint, under content pressure",
        viewport: { width: 820, height: 900 },
        node: (
          <div style={{ height: "60rem", border: "1px solid var(--color-neutral-200)" }}>
            <AppShell
              title="Terp workbench"
              nav={SHELL_NAV}
              renderLink={(item, children) => (
                <a href={item.to} aria-current={item.to === "/" ? "page" : undefined}>
                  {children}
                </a>
              )}
            >
              <DataView repository={SYNC_REPOSITORY} columns={WIDE_SYNC_COLUMNS} />
            </AppShell>
          </div>
        ),
      },
    ],
  },
  {
    // The packaged admin screens. Three markers — `admin-form`, `admin-section-title` and a
    // third, `admin-payload`, since retired — shipped with NO baseline on either platform and
    // were never rendered by the axe lane, which is how five base styles survived the entire
    // 0094 migration inside views both ratchets read as clean. The sheet's own comment on that
    // block says so.
    //
    // `admin-payload` is gone because the picture it gained is what showed it was a `Code block`
    // written out a second time: a <pre> with a background, a radius and overflow-x, differing
    // from the real one by a neutral, a border and a line-height. The specimen keeps its id — it
    // names the surface it pictures, the audit panel's payload, not a marker.
    //
    // The three specimens below are deliberately not the same KIND of specimen, and the
    // difference is the honest part rather than an inconsistency. `admin-user-create` mounts
    // the real packaged screen, because that screen fetches nothing on mount. The other two
    // owners — `GroupDetail` and `AuditLogAdmin` — build an HTTP repository and load on mount.
    //
    // Mounting them is possible, and an earlier version of this note gave a bad reason for
    // not doing it — that a mock server would break the registry's no-live-data rule. This app
    // ALREADY has one: `workbench-mock-auth` in vite.config.ts answers the auth boot with a
    // fixed user, and its own comment calls that the determinism rule applied to the session.
    // So the precedent runs the other way, and extending it with audit and group fixtures is
    // the better long-term answer rather than a forbidden one.
    //
    // What is actually in the way is the axe lane. It reads the tree ONCE, with no stability
    // retry and no wait for data, so a run that scoped the loading frame would pass on an empty
    // DataView and report nothing — worse than no coverage, because it looks like coverage.
    // (The screenshot lane would likely survive: `toHaveScreenshot` keeps shooting until two
    // consecutive frames match.) Closing that means teaching the axe lane to wait for a row,
    // which is a change to the harness rather than to a specimen.
    //
    // So for now those two reproduce the SURFACE the sheet styles, in the real components that
    // carry it, the screens' own composition stays covered by `admin/admin.test.tsx` — and the
    // one claim about a real component that a reproduced surface CANNOT make, the audit
    // payload's `tabIndex`, is asserted there instead.
    id: "admin",
    title: "Packaged admin screens",
    specimens: [
      {
        // The real `UserCreate`, mounted the way the app mounts it (see adminScreenSpecimen).
        //
        // `admin-form` is `max-width: 32rem` and nothing else, so the picture only means
        // something at a width GREATER than the cap with content that would otherwise stretch:
        // the specimen card is ~1232px here and every `Input` inside is full-width, so the cap
        // is the only thing between the fields and the right edge. At a narrower viewport the
        // declaration would be a no-op and the baseline would gate nothing.
        id: "admin-user-create",
        ready: '[data-terp="admin-form"]',
        title: "UserCreate — the packaged provisioning form",
        node: adminScreenSpecimen(<UserCreate />, "/admin/users/new"),
      },
      {
        // `admin-section-title` reproduced in place: two `h2`s heading two sections of a
        // record screen, which is exactly where `GroupDetail` renders them (its members list
        // and its permission grants).
        //
        // Both of the rule's declarations need a neighbour to be observable at all.
        // `font-size: var(--font-size-base)` is only interesting against the page's own `h1`,
        // which is `font-size-lg` — the UA default for an `h2` is LARGER than that, so without
        // the rule a section outranks the view it sits in, and the two have to be in one frame
        // to see it. And `margin: 0` only shows against a sibling to collapse into, which is
        // why there are two sections rather than one.
        id: "admin-section-title",
        title: "Admin section headings — h2 under the page h1",
        node: (
          <Page title="Warehouse operators">
            <h2 data-terp="admin-section-title">Members</h2>
            <DetailList
              items={[
                { label: "Direct members", value: "14" },
                { label: "Inherited", value: "3" },
              ]}
            />
            <h2 data-terp="admin-section-title">Permission grants</h2>
            <DetailList
              items={[
                { label: "records.read", value: "Granted" },
                { label: "records.publish", value: "Granted" },
              ]}
            />
          </Page>
        ),
      },
      {
        // The audit event's redacted payload, in a box narrower than its longest line.
        //
        // The fixed-width wrapper IS the specimen, and the first version of this did not have
        // one — it rendered the payload inside a real expanded `DataViewTable` row, the way
        // `AuditLogAdmin` does on DESKTOP, and measuring that is what showed it gated nothing.
        // In a table cell the `<pre>` came out 1594px with `scrollWidth === clientWidth`: it
        // never scrolled, it GREW, and it pushed the table to 1626px. `overflow-x: auto` cannot
        // fire on a box that is never narrower than its content, and a `<td>` under
        // `table-layout: auto` is shrink-to-fit, so nothing constrains it there.
        //
        // "Inert in production" would be too strong, though, and an earlier version of this
        // said it: `DataView` renders CARDS below the 768px breakpoint, and the expanded panel
        // then lands in a plain block `dataview-card-expanded` div. There the `<pre>` fills its
        // container and scrolls exactly as it does here — so on a phone the declaration is live,
        // which is also what makes the `tabIndex` on the real component a live fix rather than a
        // precaution. The desktop table cell is the case where it does nothing, and the fix for
        // that is the DataView's expanded-cell width model, which belongs with the
        // column-sizing work.
        //
        // A block-level `<pre>` in an ordinary container does the opposite: it fills the
        // container and scrolls its own overflow. This constrains the container and pictures
        // the rule doing its job, which is the thing a baseline can hold; the numbers behind
        // both halves are asserted in visual/computed.spec.ts.
        id: "admin-payload",
        title: "Audit payload — JSON wider than a constrained box",
        node: (
          <div style={{ width: "34rem", display: "grid", gap: "var(--space-3)" }}>
            <DetailList
              items={[
                { label: "Target", value: "sync_definition 4d2c1b7e" },
                { label: "Actor", value: "9f2c1b7e" },
                { label: "Request", value: "req_01HQ8ZK4" },
              ]}
            />
            <Code block>{AUDIT_PAYLOAD}</Code>
          </div>
        ),
      },
    ],
  },
];

/**
 * Pushes one toast of each tone on mount, so the toast viewport has a deterministic render.
 *
 * The duration is one day, and the specific value matters: a "never expire" sentinel like
 * `Number.MAX_SAFE_INTEGER` overflows `setTimeout`'s 32-bit delay and fires *immediately*, so
 * the toasts would dismiss themselves mid-run and the specimen would flake in the direction
 * that looks like a real diff. Anything below 2^31-1 ms (about 24.8 days) is safe.
 *
 * A mount effect rather than a click: the registry's rule is that a specimen renders at a
 * fixed state without interaction, and this is the only way to reach that state for a
 * component whose API is imperative.
 */
function ToastRow() {
  const toast = useToast();
  useEffect(() => {
    const durationMs = 24 * 60 * 60 * 1000;
    toast.success("Sync definition published.", { durationMs });
    toast.warning("Some rows were skipped.", { durationMs });
    toast.error("The connection was refused.", { durationMs });
  }, [toast]);
  return <p style={{ margin: 0 }}>Three toasts, one per tone, in the corner.</p>;
}

/** Every specimen, flattened — the visual suite iterates this. */
export const ALL_SPECIMENS: (Specimen & { groupId: string })[] = SPECIMEN_GROUPS.flatMap(
  (group) => group.specimens.map((specimen) => ({ ...specimen, groupId: group.id })),
);
