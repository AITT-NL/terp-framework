import {
  DataView,
  HttpDataViewRepository,
  ModuleNav,
  OverviewPage,
  unwrap,
  useServerDataView,
  useTerpClient,
} from "@terpjs/react-core";
import type { DataViewColumn } from "@terpjs/react-core";
import { useMemo } from "react";

import type { components, paths } from "../../api/schema";
import { ADMIN_PARENTS, renderAdminCrumb } from "./crumbs";
import { WEBHOOKS_TABS } from "./WebhooksAdmin";

type DeliveryRead = components["schemas"]["WebhookDeliveryRead"];

const columns: DataViewColumn<DeliveryRead>[] = [
  { id: "event", header: "Event", accessor: (d) => d.event, meta: { mobileSlot: "title" } },
  { id: "outcome", header: "Outcome", accessor: (d) => d.outcome, meta: { mobileSlot: "status", width: 110 } },
  {
    id: "response_code",
    header: "Response",
    accessor: (d) => d.response_code ?? "",
    meta: { width: 100 },
  },
  { id: "attempt", header: "Attempt", accessor: (d) => d.attempt, meta: { width: 90 } },
  {
    id: "last_error",
    header: "Last error",
    accessor: (d) => d.last_error ?? "",
    meta: { mobileSlot: "subtitle" },
  },
  {
    id: "created_at",
    header: "When",
    accessor: (d) => d.created_at,
    cell: (d) => new Date(d.created_at).toLocaleString(),
    meta: { mobileSlot: "date", width: 160 },
  },
];

/**
 * The webhook delivery log: a read-only, server-paged DataView over the deliveries the
 * dispatcher recorded (outcome, response code, attempt and last error per row).
 */
export function WebhookDeliveriesAdmin() {
  const client = useTerpClient<paths>();
  const serverQuery = useServerDataView({ initialPageSize: 10 });

  const repository = useMemo(
    () =>
      new HttpDataViewRepository<DeliveryRead>({
        getRowId: (d) => d.id,
        search: false,
        request: async ({ skip, limit }, signal) => {
          const page = unwrap(
            await client.GET("/api/v1/webhooks/deliveries", {
              params: { query: { skip, limit } },
              signal,
            }),
          );
          return { items: page.items, total: page.total };
        },
      }),
    [client],
  );

  return (
    <OverviewPage
      title="Webhook deliveries"
      parents={ADMIN_PARENTS}
      renderLink={renderAdminCrumb}
    >
      <ModuleNav items={WEBHOOKS_TABS} />
      <DataView<DeliveryRead>
        viewId="admin.webhooks.deliveries"
        repository={repository}
        columns={columns}
        serverQuery={serverQuery}
        pageSizeOptions={[10, 25, 50]}
      />
    </OverviewPage>
  );
}
