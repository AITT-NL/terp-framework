import { useNavigate } from "@tanstack/react-router";
import { useMemo, useState } from "react";
import type { FormEvent } from "react";
import type { components } from "@terp/contract";

import { Page } from "../Page";
import { useTerpClient } from "../TerpProvider";
import { Field } from "../Field";
import { DataView, HttpDataViewRepository, useServerDataView } from "../dataview";
import type { DataViewColumn } from "../dataview";
import { Stack } from "../layout";
import { useToast } from "../toast";
import { Button } from "../ui/Button";
import { ConfirmDialog } from "../ConfirmDialog";
import { Input } from "../ui/Input";
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
 * The packaged groups overview (`/admin/groups`): create a group, see live member
 * counts, delete with confirmation (the backend cascades memberships + grants
 * atomically, ADR 0074), and click through to a group's detail page for members
 * and permissions.
 */
export function GroupsAdmin() {
  const client = useTerpClient();
  const toast = useToast();
  const strings = useStrings();
  const navigate = useNavigate();
  const serverQuery = useServerDataView({ initialPageSize: 10 });
  const [version, setVersion] = useState(0);

  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [creating, setCreating] = useState(false);
  const [pendingDelete, setPendingDelete] = useState<GroupRead | null>(null);
  const [deleting, setDeleting] = useState(false);

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
    [client, version],
  );

  function failed(error: unknown): void {
    toast.warning(error instanceof Error ? error.message : strings.requestFailed);
  }

  async function onCreate(event: FormEvent) {
    event.preventDefault();
    setCreating(true);
    try {
      unwrap(await client.POST("/api/v1/groups/", { body: { name, description } }));
      toast.success(strings.saved);
      setName("");
      setDescription("");
      setVersion((v) => v + 1);
    } catch (error) {
      failed(error);
    } finally {
      setCreating(false);
    }
  }

  async function onConfirmDelete() {
    if (!pendingDelete) return;
    setDeleting(true);
    try {
      unwrap(
        await client.DELETE("/api/v1/groups/{group_id}", {
          params: { path: { group_id: pendingDelete.id } },
        }),
      );
      toast.success(strings.saved);
      setVersion((v) => v + 1);
    } catch (error) {
      failed(error);
    } finally {
      setDeleting(false);
      setPendingDelete(null);
    }
  }

  return (
    <Page
      title={strings.adminGroups}
      breadcrumbs={[adminCrumb(strings)]}
      renderLink={renderAdminCrumb}
    >
      <Stack as="form" direction="row" gap={2} align="end" wrap onSubmit={onCreate}>
        <Field label={strings.groupName}>
          <Input value={name} onChange={(event) => setName(event.target.value)} required />
        </Field>
        <Field label={strings.description}>
          <Input
            value={description}
            onChange={(event) => setDescription(event.target.value)}
          />
        </Field>
        <Button type="submit" disabled={creating}>
          {creating ? strings.working : strings.createGroup}
        </Button>
      </Stack>
      <DataView<GroupRead>
        viewId="terp.admin.groups"
        repository={repository}
        columns={columns}
        serverQuery={serverQuery}
        pageSizeOptions={[10, 25, 50]}
        onRowClick={(group) =>
          void navigate({
            to: "/admin/groups/$groupId",
            params: { groupId: group.id },
          })
        }
        rowActions={(group) => [
          {
            label: strings.deleteGroup,
            variant: "destructive",
            onClick: () => setPendingDelete(group),
          },
        ]}
      />
      <ConfirmDialog
        open={pendingDelete !== null}
        onOpenChange={(open) => {
          if (!open) {
            setPendingDelete(null);
          }
        }}
        onConfirm={() => void onConfirmDelete()}
        title={`${strings.deleteGroup}: ${pendingDelete?.name ?? ""}`}
        description={strings.deleteGroupConfirm}
        confirmLabel={strings.deleteGroup}
        isPending={deleting}
      />
    </Page>
  );
}
