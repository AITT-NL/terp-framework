import { useNavigate } from "@tanstack/react-router";
import { useMemo } from "react";
import type { components } from "@terpjs/contract";

import { Icon } from "../icons";
import { OverviewPage } from "../OverviewPage";
import { PageActions } from "../PageActions";
import { useTerpClient } from "../TerpProvider";
import { DataView, HttpDataViewRepository, useServerDataView } from "../dataview";
import type { DataViewColumn } from "../dataview";
import { Button } from "../ui/Button";
import { useStrings } from "../uiText";
import type { TerpStrings } from "../uiText";
import { unwrap } from "../unwrap";

import { adminCrumb, renderAdminCrumb } from "./crumbs";

type GroupRead = components["schemas"]["GroupRead"];

function buildColumns(strings: TerpStrings): DataViewColumn<GroupRead>[] {
  return [
    { id: "name", header: strings.groupName, accessor: (g) => g.name, meta: { mobileSlot: "title" } },
    {
      id: "description",
      header: strings.description,
      accessor: (g) => g.description,
      meta: { mobileSlot: "subtitle" },
    },
    {
      id: "member_count",
      header: strings.members,
      accessor: (g) => g.member_count,
      meta: { mobileSlot: "status", width: 110 },
    },
    {
      id: "created_at",
      header: strings.createdColumn,
      accessor: (g) => g.created_at,
      cell: (g) => new Date(g.created_at).toLocaleDateString(),
      meta: { mobileSlot: "date", width: 120 },
    },
  ];
}

/**
 * The packaged groups overview (`/admin/groups`): a server-paged table with live
 * member counts. Rows open dedicated details; creation and destructive operations
 * live on routed pages instead of competing with list navigation.
 */
export function GroupsAdmin() {
  const client = useTerpClient();
  const strings = useStrings();
  const navigate = useNavigate();
  const serverQuery = useServerDataView({ initialPageSize: 10 });

  const columns = useMemo(() => buildColumns(strings), [strings]);
  const repository = useMemo(
    () =>
      new HttpDataViewRepository<GroupRead>({
        getRowId: (g) => g.id,
        search: false,
        request: async ({ skip, limit }, signal) => {
          const page = unwrap(
            await client.GET("/api/v1/groups/", {
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
      title={strings.adminGroups}
      parents={[{ ...adminCrumb(strings), to: "/admin" }]}
      renderLink={renderAdminCrumb}
      actions={
        <PageActions
          primary={
            <Button
              icon={<Icon name="plus" />}
              onClick={() => void navigate({ to: "/admin/groups/new" })}
            >
              {strings.createGroup}
            </Button>
          }
        />
      }
    >
      <DataView<GroupRead>
        viewId="terp.admin.groups"
        repository={repository}
        columns={columns}
        serverQuery={serverQuery}
        pageSizeOptions={[10, 25, 50]}
        getRowLabel={(group) => group.name}
        onRowClick={(group) =>
          void navigate({
            to: "/admin/groups/$groupId",
            params: { groupId: group.id },
          })
        }
      />
    </OverviewPage>
  );
}
