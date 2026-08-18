import {
  Alert,
  AppShell,
  Badge,
  Breadcrumbs,
  Button,
  Card,
  Checkbox,
  Combobox,
  DataView,
  DatePicker,
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
  Tooltip,
  UserMenu,
} from "@terpjs/react-core";
import type { BadgeTone, DataViewColumn, Resource } from "@terpjs/react-core";
import type { NavItem } from "@terpjs/contract";
import {
  createMemoryHistory,
  createRootRoute,
  createRouter,
  RouterProvider,
} from "@tanstack/react-router";
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
  { id: "name", header: "Name", accessor: (row) => row.name },
  {
    id: "status",
    header: "Status",
    accessor: (row) => row.status,
    cell: (row) => <Badge tone={SYNC_TONES[row.status]} label={row.status} />,
  },
  { id: "rows", header: "Rows", accessor: (row) => row.rows },
];

const syncRepositoryOptions = {
  getRowId: (row: SyncRow) => row.id,
  getValue: (row: SyncRow, columnId: string) => row[columnId as keyof SyncRow],
  searchFields: ["name"],
};

const SYNC_REPOSITORY = new InMemoryDataViewRepository(SYNC_ROWS, syncRepositoryOptions);
const EMPTY_REPOSITORY = new InMemoryDataViewRepository<SyncRow>([], syncRepositoryOptions);

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
            <Field label="Contact email" error="Enter an address with an @ in it.">
              <Input defaultValue="not-an-email" aria-invalid />
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
        id: "date-picker",
        title: "DatePicker — fixed value",
        node: <DatePicker value={FIXED_DATE} />,
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
    ],
  },
  {
    id: "states",
    title: "Empty, error and loading",
    specimens: [
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
        id: "app-shell",
        title: "AppShell — sidebar, header and content",
        node: (
          // Height-constrained rather than full-viewport: the shell is flex-based, so a fixed
          // box renders the same composition deterministically inside a specimen card.
          <div style={{ height: "24rem", border: "1px solid var(--color-neutral-200)" }}>
            <AppShell
              title="Terp workbench"
              nav={SHELL_NAV}
              renderLink={(item, children) => <a href={item.to}>{children}</a>}
            >
              <p style={{ margin: 0 }}>Page content renders in the main region.</p>
            </AppShell>
          </div>
        ),
      },
    ],
  },
];

/** Every specimen, flattened — the visual suite iterates this. */
export const ALL_SPECIMENS: (Specimen & { groupId: string })[] = SPECIMEN_GROUPS.flatMap(
  (group) => group.specimens.map((specimen) => ({ ...specimen, groupId: group.id })),
);
