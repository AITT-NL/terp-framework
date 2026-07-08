import { useMemo } from "react";
import type { components } from "@terp/contract";

import { Page } from "../Page";
import { useTerpClient } from "../TerpProvider";
import { DataView, HttpDataViewRepository, useServerDataView } from "../dataview";
import type { DataViewColumn } from "../dataview";
import { DetailList } from "../layout";
import { useStrings } from "../uiText";
import type { TerpStrings } from "../uiText";
import { unwrap } from "../unwrap";

import { adminCrumb, renderAdminCrumb } from "./crumbs";

type AuditEventRead = components["schemas"]["AuditEventRead"];

function buildColumns(strings: TerpStrings): DataViewColumn<AuditEventRead>[] {
  return [
    {
      id: "created_at",
      header: strings.whenColumn,
      accessor: (e) => e.created_at,
      cell: (e) => new Date(e.created_at).toLocaleString(),
      meta: { mobileSlot: "date", width: 170 },
    },
    {
      id: "action",
      header: strings.actionColumn,
      accessor: (e) => e.action,
      meta: { mobileSlot: "status", width: 100 },
    },
    {
      id: "target",
      header: strings.targetColumn,
      accessor: (e) => `${e.target_type} ${e.target_id}`,
      cell: (e) => `${e.target_type} · ${e.target_id.slice(0, 8)}`,
      meta: { mobileSlot: "title" },
    },
    {
      id: "actor",
      header: strings.actorColumn,
      accessor: (e) => e.actor_id ?? "",
      cell: (e) => (e.actor_id === null ? "—" : e.actor_id.slice(0, 8)),
      meta: { mobileSlot: "subtitle", width: 110 },
    },
  ];
}

const payloadStyle = {
  margin: 0,
  padding: "var(--space-3)",
  background: "var(--color-neutral-100)",
  borderRadius: "var(--radius-md)",
  fontSize: "var(--font-size-sm, 0.875rem)",
  overflowX: "auto" as const,
};

/**
 * The packaged audit-log screen (`/admin/audit`): the append-only trail every
 * mutation lands in (ADR 0007), newest first as served, read-only by design.
 * A row expands to the full identifiers and the redacted payload snapshot.
 */
export function AuditLogAdmin() {
  const client = useTerpClient();
  const strings = useStrings();
  const serverQuery = useServerDataView({ initialPageSize: 25 });

  const columns = useMemo(() => buildColumns(strings), [strings]);
  const repository = useMemo(
    () =>
      new HttpDataViewRepository<AuditEventRead>({
        getRowId: (e) => e.id,
        search: false,
        request: async ({ skip, limit }, signal) => {
          const page = unwrap(
            await client.GET("/api/v1/audit/", {
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
    <Page
      title={strings.adminAudit}
      breadcrumbs={[adminCrumb(strings)]}
      renderLink={renderAdminCrumb}
    >
      <DataView<AuditEventRead>
        viewId="terp.admin.audit"
        repository={repository}
        columns={columns}
        serverQuery={serverQuery}
        pageSizeOptions={[25, 50, 100]}
        renderExpanded={(event) => (
          <div>
            <DetailList
              items={[
                { label: strings.targetColumn, value: `${event.target_type} ${event.target_id}` },
                { label: strings.actorColumn, value: event.actor_id ?? "—" },
                { label: "Request", value: event.request_id ?? "—" },
              ]}
            />
            {event.payload !== null && (
              <pre style={payloadStyle}>{JSON.stringify(event.payload, null, 2)}</pre>
            )}
          </div>
        )}
      />
    </Page>
  );
}
