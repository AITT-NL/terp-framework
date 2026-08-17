import {
  Alert,
  Badge,
  Button,
  Card,
  Checkbox,
  Combobox,
  DatePicker,
  DetailList,
  EmptyState,
  ErrorState,
  Field,
  Icon,
  InlineSpinner,
  Input,
  LoadingState,
  Popover,
  Radio,
  RadioGroup,
  Select,
  Stack,
  Switch,
  Tabs,
  Textarea,
  Tooltip,
} from "@terpjs/react-core";
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
        node: (
          <Stack gap={3}>
            <Input defaultValue="A single line of text" />
            <Select defaultValue="published">
              {SELECT_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </Select>
            <Textarea rows={3} defaultValue={"Several lines\nof text."} />
          </Stack>
        ),
      },
      {
        id: "text-inputs-disabled",
        title: "Input, Select, Textarea — disabled",
        node: (
          <Stack gap={3}>
            <Input defaultValue="Not editable" disabled />
            <Select defaultValue="draft" disabled>
              {SELECT_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </Select>
            <Textarea rows={2} defaultValue="Not editable" disabled />
          </Stack>
        ),
      },
      {
        id: "text-inputs-invalid",
        title: "Input — flagged invalid",
        node: <Input defaultValue="not-an-email" aria-invalid />,
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
];

/** Every specimen, flattened — the visual suite iterates this. */
export const ALL_SPECIMENS: (Specimen & { groupId: string })[] = SPECIMEN_GROUPS.flatMap(
  (group) => group.specimens.map((specimen) => ({ ...specimen, groupId: group.id })),
);
