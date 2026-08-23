import { useMemo } from "react";
import type { components } from "@terpjs/contract";

import { Page } from "../Page";
import { useTerpClient } from "../TerpProvider";
import { DataView, HttpDataViewRepository, useServerDataView } from "../dataview";
import type { DataViewColumn } from "../dataview";
import { DetailList } from "../layout";
import { useFormatDateTime } from "../format";
import { useStrings } from "../uiText";
import type { TerpStrings } from "../uiText";
import { unwrap } from "../unwrap";

import { adminCrumb, renderAdminCrumb } from "./crumbs";

type AuditEventRead = components["schemas"]["AuditEventRead"];

function buildColumns(
  strings: TerpStrings,
  formatDateTime: (value: string) => string,
): DataViewColumn<AuditEventRead>[] {
  return [
    {
      id: "created_at",
      header: strings.whenColumn,
      accessor: (e) => e.created_at,
      cell: (e) => formatDateTime(e.created_at),
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

/**
 * The packaged audit-log screen (`/admin/audit`): the append-only trail every
 * mutation lands in (ADR 0007), newest first as served, read-only by design.
 * A row expands to the full identifiers and the redacted payload snapshot.
 */
export function AuditLogAdmin() {
  const client = useTerpClient();
  const strings = useStrings();
  const serverQuery = useServerDataView({ initialPageSize: 25 });

  const formatDateTime = useFormatDateTime();
  const columns = useMemo(
    () => buildColumns(strings, formatDateTime),
    [strings, formatDateTime],
  );
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
              // tabIndex, for the reason `Code` block carries one: `admin-payload` declares
              // `overflow-x: auto`, so a wide payload is a scroll container, and a scroll
              // container no keyboard can reach is the SC 2.1.1 failure axe reports as
              // `scrollable-region-focusable`. Found by the workbench specimen the moment one
              // existed — the marker had no baseline and axe had never rendered it.
              <pre data-terp="admin-payload" tabIndex={0}>
                {JSON.stringify(event.payload, null, 2)}
              </pre>
            )}
          </div>
        )}
      />
    </Page>
  );
}
