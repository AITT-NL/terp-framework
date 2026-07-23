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
import { adminRoleLabel } from "./roles";

type UserRead = components["schemas"]["UserRead"];

function buildColumns(strings: TerpStrings): DataViewColumn<UserRead>[] {
  return [
    { id: "email", header: strings.email, accessor: (u) => u.email, meta: { mobileSlot: "title" } },
    {
      id: "role",
      header: strings.role,
      accessor: (u) => u.role,
      cell: (u) => adminRoleLabel(strings, u.role),
      meta: { mobileSlot: "subtitle", width: 100 },
    },
    {
      id: "is_active",
      header: strings.statusColumn,
      accessor: (u) => (u.is_active ? strings.statusActive : strings.statusDeactivated),
      meta: { mobileSlot: "status", width: 110 },
    },
    {
      id: "created_at",
      header: strings.createdColumn,
      accessor: (u) => u.created_at,
      cell: (u) => new Date(u.created_at).toLocaleDateString(),
      meta: { mobileSlot: "date", width: 120 },
    },
  ];
}

/**
 * The packaged users overview (`/admin/users`): a server-paged directory whose rows
 * open dedicated detail pages. Creation and lifecycle mutations live on routed pages,
 * keeping this screen focused on finding and comparing accounts.
 */
export function UsersAdmin() {
  const client = useTerpClient();
  const strings = useStrings();
  const navigate = useNavigate();
  const serverQuery = useServerDataView({ initialPageSize: 10 });

  const columns = useMemo(() => buildColumns(strings), [strings]);
  const repository = useMemo(
    () =>
      new HttpDataViewRepository<UserRead>({
        getRowId: (u) => u.id,
        search: false,
        request: async ({ skip, limit }, signal) => {
          const page = unwrap(
            await client.GET("/api/v1/users/", {
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
      title={strings.adminUsers}
      parents={[{ ...adminCrumb(strings), to: "/admin" }]}
      renderLink={renderAdminCrumb}
      actions={
        <PageActions
          primary={
            <Button
              icon={<Icon name="plus" />}
              onClick={() => void navigate({ to: "/admin/users/new" })}
            >
              {strings.provisionUser}
            </Button>
          }
        />
      }
    >
      <DataView<UserRead>
        viewId="terp.admin.users"
        repository={repository}
        columns={columns}
        serverQuery={serverQuery}
        pageSizeOptions={[10, 25, 50]}
        getRowLabel={(user) => user.email}
        onRowClick={(user) =>
          void navigate({
            to: "/admin/users/$userId",
            params: { userId: user.id },
          })
        }
      />
    </OverviewPage>
  );
}
