import {
  Button,
  ConfirmDialog,
  DataView,
  EmptyState,
  Field,
  HttpDataViewRepository,
  Input,
  OverviewPage,
  Stack,
  Trans,
  unwrap,
  useUiText,
  useServerDataView,
  useTerpClient,
  useToast,
  useFormatDate,
} from "@terpjs/react-core";
import type { DataViewColumn } from "@terpjs/react-core";
import { useMemo, useState } from "react";
import type { FormEvent } from "react";

import type { components, paths } from "../../api/schema";
import { ADMIN_PARENTS, renderAdminCrumb } from "./crumbs";

type GrantRead = components["schemas"]["GrantRead"];

function buildColumns(
  formatDate: (value: string) => string,
): DataViewColumn<GrantRead>[] {
  return [
    {
      id: "permission",
      header: { id: "admin.grants.column.permission", message: "Permission" },
      accessor: (g) => g.permission,
      meta: { mobileSlot: "title" },
    },
    {
      id: "created_at",
      header: { id: "admin.grants.column.granted", message: "Granted" },
      accessor: (g) => g.created_at,
      cell: (g) => formatDate(g.created_at),
      meta: { mobileSlot: "date", width: "sm" },
    },
  ];
}

/**
 * Access-grant administration over the shipped access capability. Grants are stored and
 * listed per subject, so the view is subject-scoped: load a user's standing grants, add
 * one (a permission string), and revoke one with confirmation.
 */
export function AccessGrantsAdmin() {
  const formatDate = useFormatDate();
  const columns = useMemo(() => buildColumns(formatDate), [formatDate]);
  const client = useTerpClient<paths>();
  const toast = useToast();
  const text = useUiText();
  const serverQuery = useServerDataView({ initialPageSize: 10 });
  const [version, setVersion] = useState(0);

  const [subjectInput, setSubjectInput] = useState("");
  const [subjectId, setSubjectId] = useState("");
  const [permission, setPermission] = useState("");
  const [creating, setCreating] = useState(false);
  const [pendingRevoke, setPendingRevoke] = useState<GrantRead | null>(null);
  const [revoking, setRevoking] = useState(false);

  const repository = useMemo(
    () =>
      subjectId === ""
        ? null
        : new HttpDataViewRepository<GrantRead>({
            getRowId: (g) => g.id,
            search: false,
            request: async ({ skip, limit }, signal) => {
              const page = unwrap(
                await client.GET("/api/v1/access/grants", {
                  params: { query: { subject_id: subjectId, skip, limit } },
                  signal,
                }),
              );
              return { items: page.items, total: page.total };
            },
          }),
    // `version` re-creates the repository after a mutation so the list refetches.
    [client, subjectId, version],
  );

  function onLoad(event: FormEvent) {
    event.preventDefault();
    setSubjectId(subjectInput.trim());
  }

  async function onCreate(event: FormEvent) {
    event.preventDefault();
    setCreating(true);
    try {
      unwrap(
        await client.POST("/api/v1/access/grants", {
          body: { subject_id: subjectId, permission },
        }),
      );
      toast.success(
        text({ id: "admin.grants.toast.granted", message: "Grant added" }),
      );
      setPermission("");
      setVersion((v) => v + 1);
    } catch (error) {
      toast.warning(
        error instanceof Error
          ? error.message
          : text({
              id: "admin.grants.toast.createFailed",
              message: "Could not create the grant",
            }),
      );
    } finally {
      setCreating(false);
    }
  }

  async function onConfirmRevoke() {
    if (!pendingRevoke) return;
    setRevoking(true);
    try {
      unwrap(
        await client.DELETE("/api/v1/access/grants/{grant_id}", {
          params: { path: { grant_id: pendingRevoke.id } },
        }),
      );
      toast.success(
        text({ id: "admin.grants.toast.revoked", message: "Grant revoked" }),
      );
      setVersion((v) => v + 1);
    } catch (error) {
      toast.warning(
        error instanceof Error
          ? error.message
          : text({
              id: "admin.grants.toast.revokeFailed",
              message: "Could not revoke the grant",
            }),
      );
    } finally {
      setRevoking(false);
      setPendingRevoke(null);
    }
  }

  return (
    <OverviewPage
      title={{ id: "admin.grants.title", message: "Access grants" }}
      parents={ADMIN_PARENTS}
      renderLink={renderAdminCrumb}
    >
      <Stack as="form" direction="row" gap={2} align="end" wrap onSubmit={onLoad}>
        <Field
          label={{ id: "admin.grants.field.subject", message: "Subject id" }}
          hint={{
            id: "admin.grants.field.subjectHint",
            message: "The user whose grants to manage",
          }}
        >
          <Input
            value={subjectInput}
            onChange={(event) => setSubjectInput(event.target.value)}
            required
          />
        </Field>
        <Button type="submit" variant="secondary">
          <Trans id="admin.grants.load" message="Load grants" />
        </Button>
      </Stack>
      {repository === null ? (
        <EmptyState
          title={{ id: "admin.grants.empty.title", message: "No subject selected" }}
          description={{
            id: "admin.grants.empty.description",
            message: "Enter a subject id to list and manage that user's grants.",
          }}
        />
      ) : (
        <>
          <Stack as="form" direction="row" gap={2} align="end" wrap onSubmit={onCreate}>
            <Field
              label={{ id: "admin.grants.field.permission", message: "Permission" }}
              hint={{ id: "admin.grants.field.permissionHint", message: 'e.g. "notes:write"' }}
            >
              <Input
                value={permission}
                onChange={(event) => setPermission(event.target.value)}
                required
              />
            </Field>
            <Button type="submit" disabled={creating}>
              {creating ? (
                <Trans id="admin.grants.granting" message="Granting…" />
              ) : (
                <Trans id="admin.grants.add" message="Add grant" />
              )}
            </Button>
          </Stack>
          <DataView<GrantRead>
            viewId="admin.grants"
            repository={repository}
            columns={columns}
            serverQuery={serverQuery}
            pageSizeOptions={[10, 25, 50]}
            rowActions={(grant) => [
              {
                label: { id: "admin.grants.revoke", message: "Revoke" },
                variant: "destructive",
                onClick: () => setPendingRevoke(grant),
              },
            ]}
          />
        </>
      )}
      <ConfirmDialog
        open={pendingRevoke !== null}
        onOpenChange={(open) => {
          if (!open) setPendingRevoke(null);
        }}
        onConfirm={() => void onConfirmRevoke()}
        title={{ id: "admin.grants.confirm.title", message: "Revoke this grant?" }}
        description={{
          id: "admin.grants.confirm.description",
          message: "The subject loses this permission immediately.",
        }}
        destructive
        isPending={revoking}
      />
    </OverviewPage>
  );
}
