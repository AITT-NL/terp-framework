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
  unwrap,
  useServerDataView,
  useTerpClient,
  useToast,
} from "@terp/react-core";
import type { DataViewColumn } from "@terp/react-core";
import { useMemo, useState } from "react";
import type { FormEvent } from "react";

import type { components, paths } from "../../api/schema";
import { ADMIN_PARENTS, renderAdminCrumb } from "./crumbs";

type GrantRead = components["schemas"]["GrantRead"];

const columns: DataViewColumn<GrantRead>[] = [
  {
    id: "permission",
    header: "Permission",
    accessor: (g) => g.permission,
    meta: { mobileSlot: "title" },
  },
  {
    id: "created_at",
    header: "Granted",
    accessor: (g) => g.created_at,
    cell: (g) => new Date(g.created_at).toLocaleDateString(),
    meta: { mobileSlot: "date", width: 120 },
  },
];

/**
 * Access-grant administration over the shipped access capability. Grants are stored and
 * listed per subject, so the view is subject-scoped: load a user's standing grants, add
 * one (a permission string), and revoke one with confirmation.
 */
export function AccessGrantsAdmin() {
  const client = useTerpClient<paths>();
  const toast = useToast();
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
      toast.success(`Granted ${permission}`);
      setPermission("");
      setVersion((v) => v + 1);
    } catch (error) {
      toast.warning(error instanceof Error ? error.message : "Could not create the grant");
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
      toast.success(`Revoked ${pendingRevoke.permission}`);
      setVersion((v) => v + 1);
    } catch (error) {
      toast.warning(error instanceof Error ? error.message : "Could not revoke the grant");
    } finally {
      setRevoking(false);
      setPendingRevoke(null);
    }
  }

  return (
    <OverviewPage
      title="Access grants"
      parents={ADMIN_PARENTS}
      renderLink={renderAdminCrumb}
    >
      <Stack as="form" direction="row" gap={2} align="end" wrap onSubmit={onLoad}>
        <Field label="Subject id" hint="The user whose grants to manage">
          <Input
            value={subjectInput}
            onChange={(event) => setSubjectInput(event.target.value)}
            required
          />
        </Field>
        <Button type="submit" variant="secondary">
          Load grants
        </Button>
      </Stack>
      {repository === null ? (
        <EmptyState
          title="No subject selected"
          description="Enter a subject id to list and manage that user's grants."
        />
      ) : (
        <>
          <Stack as="form" direction="row" gap={2} align="end" wrap onSubmit={onCreate}>
            <Field label="Permission" hint='e.g. "notes:write"'>
              <Input
                value={permission}
                onChange={(event) => setPermission(event.target.value)}
                required
              />
            </Field>
            <Button type="submit" disabled={creating}>
              {creating ? "Granting…" : "Add grant"}
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
                label: "Revoke",
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
        title={`Revoke ${pendingRevoke?.permission ?? "grant"}?`}
        description="The subject loses this permission immediately."
        destructive
        isPending={revoking}
      />
    </OverviewPage>
  );
}
