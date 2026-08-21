import {
  Alert,
  AppShell,
  Badge,
  Breadcrumbs,
  Button,
  Card,
  Checkbox,
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
  EmptyState,
  ErrorState,
  Field,
  HubCard,
  HubPage,
  Icon,
  InlineSpinner,
  InMemoryDataViewRepository,
  Input,
  LanguageSwitcher,
  LoadingState,
  LoginView,
  Markdown,
  Menu,
  MenuItem,
  ModuleNav,
  NavIcon,
  Page,
  PageActions,
  Popover,
  ProfileView,
  Radio,
  RadioGroup,
  ResourceList,
  Select,
  Stack,
  Switch,
  Tabs,
  TerpProvider,
  Textarea,
  ThemeToggle,
  ToastProvider,
  Tooltip,
  useToast,
  UserMenu,
} from "@terpjs/react-core";
import type { BadgeTone, DataViewColumn, DataViewRepository, Resource } from "@terpjs/react-core";
import type { NavItem } from "@terpjs/contract";
import {
  createMemoryHistory,
  createRootRoute,
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
}

export interface SpecimenGroup {
  id: string;
  title: string;
  specimens: Specimen[];
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
const SHELL_NAV: readonly NavItem[] = [
  { label: "Overview", to: "/", icon: "home" },
  { label: "Records", to: "/records", icon: "list" },
  { label: "Reports", to: "/reports", icon: "layers" },
  { label: "Admin", to: "/admin", icon: "shield" },
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

// A table too wide for its box, and the width comes from the HEADERS rather than from the
// `meta.width` hint that looks like the obvious lever. Measured at every step, because the obvious
// lever does nothing: the table rule is `width: 100%` with `table-layout: auto`, so a specified
// column width is a *preference* the auto algorithm shrinks to fit — three columns hinted at 700px
// each recorded a baseline that fits the box exactly. What auto layout cannot shrink is a MINIMUM,
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
        id: "resource-list",
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
            {[
              "plus",
              "download",
              "search",
              "shield",
              "database",
              "list",
              "layers",
              "settings",
              "check",
              "close",
            ].map((name) => (
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
        title: "Page — breadcrumbs, title and actions",
        node: (
          <Page
            title="Customer master"
            breadcrumbs={[{ label: "Records", to: "/records" }]}
            actions={<Button variant="primary">Publish</Button>}
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
        title: "UserMenu — closed trigger",
        node: (
          <SignedIn>
            <UserMenu onSettings={() => {}} />
          </SignedIn>
        ),
      },
      {
        id: "user-menu-collapsed",
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
        // The desktop shell just above the breakpoint — the band between 769px and wide, which
        // the pinned viewport also cannot reach. The sidebar's `flex-shrink: 0` is documented as
        // biting here and nowhere else, and the content is deliberately something with a real
        // min-content width rather than a short paragraph, because a row under no pressure
        // never asks a flex item whether it may shrink.
        id: "app-shell-narrow",
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
