import {
  Button,
  ConfirmDialog,
  DataView,
  Field,
  HttpDataViewRepository,
  Input,
  ModuleNav,
  OverviewPage,
  Stack,
  unwrap,
  useServerDataView,
  useTerpClient,
  useToast,
} from "@terp/react-core";
import type { DataViewColumn } from "@terp/react-core";
import { useMemo, useState } from "react";
import type { FormEvent } from "react";

import type { components, paths } from "../../api/schema";

type SubscriptionRead = components["schemas"]["WebhookSubscriptionRead"];

export const WEBHOOKS_TABS = [
  { label: "Subscriptions", to: "/admin/webhooks" },
  { label: "Deliveries", to: "/admin/webhooks/deliveries" },
] as const;

const columns: DataViewColumn<SubscriptionRead>[] = [
  {
    id: "target_url",
    header: "Target URL",
    accessor: (s) => s.target_url,
    meta: { mobileSlot: "title" },
  },
  { id: "event", header: "Event", accessor: (s) => s.event, meta: { mobileSlot: "subtitle" } },
  {
    id: "active",
    header: "Status",
    accessor: (s) => (s.active ? "active" : "paused"),
    meta: { mobileSlot: "status", width: 100 },
  },
  {
    id: "created_at",
    header: "Created",
    accessor: (s) => s.created_at,
    cell: (s) => new Date(s.created_at).toLocaleDateString(),
    meta: { mobileSlot: "date", width: 120 },
  },
];

/**
 * Webhook subscription administration over the shipped webhooks capability: subscribe a
 * target URL to an event (with the signing secret), pause/resume, and delete — with the
 * delivery log one tab away.
 */
export function WebhooksAdmin() {
  const client = useTerpClient<paths>();
  const toast = useToast();
  const serverQuery = useServerDataView({ initialPageSize: 10 });
  const [version, setVersion] = useState(0);

  const [targetUrl, setTargetUrl] = useState("");
  const [event, setEvent] = useState("");
  const [secret, setSecret] = useState("");
  const [creating, setCreating] = useState(false);
  const [pendingDelete, setPendingDelete] = useState<SubscriptionRead | null>(null);
  const [deleting, setDeleting] = useState(false);

  const repository = useMemo(
    () =>
      new HttpDataViewRepository<SubscriptionRead>({
        getRowId: (s) => s.id,
        search: false,
        request: async ({ skip, limit }, signal) => {
          const page = unwrap(
            await client.GET("/api/v1/webhooks/subscriptions", {
              params: { query: { skip, limit } },
              signal,
            }),
          );
          return { items: page.items, total: page.total };
        },
      }),
    // `version` re-creates the repository after a mutation so the list refetches.
    [client, version],
  );

  const refetch = () => setVersion((v) => v + 1);

  async function onCreate(formEvent: FormEvent) {
    formEvent.preventDefault();
    setCreating(true);
    try {
      unwrap(
        await client.POST("/api/v1/webhooks/subscriptions", {
          body: { target_url: targetUrl, event, secret, active: true },
        }),
      );
      toast.success(`Subscribed to ${event}`);
      setTargetUrl("");
      setEvent("");
      setSecret("");
      refetch();
    } catch (error) {
      toast.warning(error instanceof Error ? error.message : "Could not create the subscription");
    } finally {
      setCreating(false);
    }
  }

  async function setActive(subscription: SubscriptionRead, active: boolean) {
    try {
      unwrap(
        await client.PATCH("/api/v1/webhooks/subscriptions/{subscription_id}", {
          params: { path: { subscription_id: subscription.id } },
          body: { active, version: subscription.version },
        }),
      );
      toast.success(active ? "Subscription resumed" : "Subscription paused");
      refetch();
    } catch (error) {
      toast.warning(error instanceof Error ? error.message : "Update failed");
    }
  }

  async function onConfirmDelete() {
    if (!pendingDelete) return;
    setDeleting(true);
    try {
      unwrap(
        await client.DELETE("/api/v1/webhooks/subscriptions/{subscription_id}", {
          params: { path: { subscription_id: pendingDelete.id } },
        }),
      );
      toast.success("Subscription deleted");
      refetch();
    } catch (error) {
      toast.warning(error instanceof Error ? error.message : "Could not delete the subscription");
    } finally {
      setDeleting(false);
      setPendingDelete(null);
    }
  }

  return (
    <OverviewPage title="Webhooks">
      <ModuleNav items={WEBHOOKS_TABS} />
      <Stack as="form" direction="row" gap={2} align="end" wrap onSubmit={onCreate}>
        <Field label="Target URL">
          <Input
            type="url"
            value={targetUrl}
            onChange={(changeEvent) => setTargetUrl(changeEvent.target.value)}
            required
          />
        </Field>
        <Field label="Event" hint='e.g. "note.created"'>
          <Input value={event} onChange={(changeEvent) => setEvent(changeEvent.target.value)} required />
        </Field>
        <Field label="Signing secret" hint="At least 16 characters">
          <Input
            type="password"
            value={secret}
            onChange={(changeEvent) => setSecret(changeEvent.target.value)}
            required
          />
        </Field>
        <Button type="submit" disabled={creating}>
          {creating ? "Subscribing…" : "Add subscription"}
        </Button>
      </Stack>
      <DataView<SubscriptionRead>
        viewId="admin.webhooks"
        repository={repository}
        columns={columns}
        serverQuery={serverQuery}
        pageSizeOptions={[10, 25, 50]}
        rowActions={(subscription) => [
          subscription.active
            ? { label: "Pause", onClick: () => void setActive(subscription, false) }
            : { label: "Resume", onClick: () => void setActive(subscription, true) },
          {
            label: "Delete",
            variant: "destructive",
            onClick: () => setPendingDelete(subscription),
          },
        ]}
      />
      <ConfirmDialog
        open={pendingDelete !== null}
        onOpenChange={(open) => {
          if (!open) setPendingDelete(null);
        }}
        onConfirm={() => void onConfirmDelete()}
        title="Delete this subscription?"
        description="No further deliveries will be attempted for it."
        destructive
        isPending={deleting}
      />
    </OverviewPage>
  );
}
