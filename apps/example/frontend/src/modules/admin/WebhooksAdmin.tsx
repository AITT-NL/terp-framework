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
  Trans,
  unwrap,
  useServerDataView,
  useTerpClient,
  useToast,
  useUiText,
  useFormatDate,
} from "@terpjs/react-core";
import type { DataViewColumn } from "@terpjs/react-core";
import { useMemo, useState } from "react";
import type { FormEvent } from "react";

import type { components, paths } from "../../api/schema";
import { ADMIN_PARENTS, renderAdminCrumb } from "./crumbs";

type SubscriptionRead = components["schemas"]["WebhookSubscriptionRead"];

export const WEBHOOKS_TABS = [
  {
    label: { id: "admin.webhooks.tab.subscriptions", message: "Subscriptions" },
    to: "/admin/webhooks",
  },
  {
    label: { id: "admin.webhooks.tab.deliveries", message: "Deliveries" },
    to: "/admin/webhooks/deliveries",
  },
] as const;

function buildColumns(
  formatDate: (value: string) => string,
): DataViewColumn<SubscriptionRead>[] {
  return [
    {
      id: "target_url",
      header: { id: "admin.webhooks.column.targetUrl", message: "Target URL" },
      accessor: (s) => s.target_url,
      meta: { mobileSlot: "title" },
    },
    {
      id: "event",
      header: { id: "admin.webhooks.column.event", message: "Event" },
      accessor: (s) => s.event,
      meta: { mobileSlot: "subtitle" },
    },
    {
      id: "active",
      header: { id: "admin.webhooks.column.status", message: "Status" },
      accessor: (s) => (s.active ? "active" : "paused"),
      cell: (s) =>
        s.active ? (
          <Trans id="admin.webhooks.status.active" message="Active" />
        ) : (
          <Trans id="admin.webhooks.status.paused" message="Paused" />
        ),
      meta: { mobileSlot: "status", width: "xs" },
    },
    {
      id: "created_at",
      header: { id: "admin.webhooks.column.created", message: "Created" },
      accessor: (s) => s.created_at,
      cell: (s) => formatDate(s.created_at),
      meta: { mobileSlot: "date", width: "sm" },
    },
  ];
}

/**
 * Webhook subscription administration over the shipped webhooks capability: subscribe a
 * target URL to an event (with the signing secret), pause/resume, and delete — with the
 * delivery log one tab away.
 */
export function WebhooksAdmin() {
  const formatDate = useFormatDate();
  const columns = useMemo(() => buildColumns(formatDate), [formatDate]);
  const client = useTerpClient<paths>();
  const toast = useToast();
  const text = useUiText();
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
      toast.success(
        text({ id: "admin.webhooks.toast.subscribed", message: "Subscription added" }),
      );
      setTargetUrl("");
      setEvent("");
      setSecret("");
      refetch();
    } catch (error) {
      toast.warning(
        error instanceof Error
          ? error.message
          : text({
              id: "admin.webhooks.toast.createFailed",
              message: "Could not create the subscription",
            }),
      );
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
      toast.success(
        active
          ? text({
              id: "admin.webhooks.toast.resumed",
              message: "Subscription resumed",
            })
          : text({
              id: "admin.webhooks.toast.paused",
              message: "Subscription paused",
            }),
      );
      refetch();
    } catch (error) {
      toast.warning(
        error instanceof Error
          ? error.message
          : text({ id: "admin.webhooks.toast.updateFailed", message: "Update failed" }),
      );
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
      toast.success(
        text({ id: "admin.webhooks.toast.deleted", message: "Subscription deleted" }),
      );
      refetch();
    } catch (error) {
      toast.warning(
        error instanceof Error
          ? error.message
          : text({
              id: "admin.webhooks.toast.deleteFailed",
              message: "Could not delete the subscription",
            }),
      );
    } finally {
      setDeleting(false);
      setPendingDelete(null);
    }
  }

  return (
    <OverviewPage
      title={{ id: "admin.webhooks.title", message: "Webhooks" }}
      parents={ADMIN_PARENTS}
      renderLink={renderAdminCrumb}
    >
      <ModuleNav items={WEBHOOKS_TABS} />
      <Stack as="form" direction="row" gap={2} align="end" wrap onSubmit={onCreate}>
        <Field label={{ id: "admin.webhooks.field.targetUrl", message: "Target URL" }}>
          <Input
            type="url"
            value={targetUrl}
            onChange={(changeEvent) => setTargetUrl(changeEvent.target.value)}
            required
          />
        </Field>
        <Field
          label={{ id: "admin.webhooks.field.event", message: "Event" }}
          hint={{ id: "admin.webhooks.field.eventHint", message: 'e.g. "note.created"' }}
        >
          <Input value={event} onChange={(changeEvent) => setEvent(changeEvent.target.value)} required />
        </Field>
        <Field
          label={{ id: "admin.webhooks.field.secret", message: "Signing secret" }}
          hint={{
            id: "admin.webhooks.field.secretHint",
            message: "At least 16 characters",
          }}
        >
          <Input
            type="password"
            // The hint said "at least 16 characters" and nothing enforced it — ADR 0099 cites
            // exactly this field as the framework's whole client-validation gap: four unwritten
            // HTML attributes, not a missing library. Here is one of them written.
            minLength={16}
            // A signing secret is generated, never a credential the browser has saved.
            autoComplete="new-password"
            value={secret}
            onChange={(changeEvent) => setSecret(changeEvent.target.value)}
            required
          />
        </Field>
        <Button type="submit" disabled={creating}>
          {creating ? (
            <Trans id="admin.webhooks.subscribing" message="Subscribing…" />
          ) : (
            <Trans id="admin.webhooks.add" message="Add subscription" />
          )}
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
            ? {
                label: { id: "admin.webhooks.pause", message: "Pause" },
                onClick: () => void setActive(subscription, false),
              }
            : {
                label: { id: "admin.webhooks.resume", message: "Resume" },
                onClick: () => void setActive(subscription, true),
              },
          {
            label: { id: "admin.webhooks.delete", message: "Delete" },
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
        title={{
          id: "admin.webhooks.confirm.title",
          message: "Delete this subscription?",
        }}
        description={{
          id: "admin.webhooks.confirm.description",
          message: "No further deliveries will be attempted for it.",
        }}
        destructive
        isPending={deleting}
      />
    </OverviewPage>
  );
}
