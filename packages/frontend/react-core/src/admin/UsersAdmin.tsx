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
import { Select } from "../ui/Select";
import { useStrings } from "../uiText";
import type { TerpStrings } from "../uiText";
import { unwrap } from "../unwrap";

import { adminCrumb, renderAdminCrumb } from "./crumbs";

type UserRead = components["schemas"]["UserRead"];

/** The bundled ladder's display names; an unmodeled rank shows as `rank N`. */
const ROLE_NAMES: Record<number, string> = { 10: "viewer", 20: "editor", 30: "admin" };
const ROLE_OPTIONS = [
  { rank: 10, label: "Viewer" },
  { rank: 20, label: "Editor" },
  { rank: 30, label: "Admin" },
];

function buildColumns(strings: TerpStrings): DataViewColumn<UserRead>[] {
  return [
    { id: "email", header: strings.email, accessor: (u) => u.email, meta: { mobileSlot: "title" } },
    {
      id: "role",
      header: strings.role,
      accessor: (u) => u.role,
      cell: (u) => ROLE_NAMES[u.role] ?? `rank ${u.role}`,
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
 * The packaged users administration screen (`/admin/users`): provision, change role,
 * deactivate / reactivate (session-revoking) and reset a password. Every lifecycle
 * endpoint the base-profile users capability mounts, typed from `@terp/contract`,
 * assembled from DataView + the form primitives, and localized like all chrome.
 */
export function UsersAdmin() {
  const client = useTerpClient();
  const toast = useToast();
  const strings = useStrings();
  const serverQuery = useServerDataView({ initialPageSize: 10 });
  const [version, setVersion] = useState(0);

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState("10");
  const [creating, setCreating] = useState(false);

  const [resetTarget, setResetTarget] = useState<UserRead | null>(null);
  const [resetPassword, setResetPassword] = useState("");
  const [resetting, setResetting] = useState(false);

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
    // `version` re-creates the repository after a mutation so the list refetches.
    [client, version],
  );

  const refetch = () => setVersion((v) => v + 1);

  function failed(error: unknown): void {
    toast.warning(error instanceof Error ? error.message : strings.requestFailed);
  }

  async function onProvision(event: FormEvent) {
    event.preventDefault();
    setCreating(true);
    try {
      unwrap(
        await client.POST("/api/v1/users/", {
          body: { email, password, role: Number(role) },
        }),
      );
      toast.success(strings.saved);
      setEmail("");
      setPassword("");
      setRole("10");
      refetch();
    } catch (error) {
      failed(error);
    } finally {
      setCreating(false);
    }
  }

  async function setActive(user: UserRead, active: boolean) {
    const path = active
      ? "/api/v1/users/{user_id}/reactivate"
      : "/api/v1/users/{user_id}/deactivate";
    try {
      unwrap(await client.POST(path, { params: { path: { user_id: user.id } } }));
      toast.success(strings.saved);
      refetch();
    } catch (error) {
      failed(error);
    }
  }

  async function changeRole(user: UserRead, rank: number) {
    try {
      unwrap(
        await client.PATCH("/api/v1/users/{user_id}", {
          params: { path: { user_id: user.id } },
          body: { role: rank, version: user.version },
        }),
      );
      toast.success(strings.saved);
      refetch();
    } catch (error) {
      failed(error);
    }
  }

  async function onConfirmReset() {
    if (!resetTarget) return;
    setResetting(true);
    try {
      unwrap(
        await client.POST("/api/v1/users/{user_id}/reset-password", {
          params: { path: { user_id: resetTarget.id } },
          body: { password: resetPassword },
        }),
      );
      toast.success(strings.saved);
      setResetTarget(null);
      setResetPassword("");
      refetch();
    } catch (error) {
      failed(error);
    } finally {
      setResetting(false);
    }
  }

  return (
    <Page
      title={strings.adminUsers}
      breadcrumbs={[adminCrumb(strings)]}
      renderLink={renderAdminCrumb}
    >
      <Stack as="form" direction="row" gap={2} align="end" wrap onSubmit={onProvision}>
        <Field label={strings.email}>
          <Input
            type="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            required
          />
        </Field>
        <Field label={strings.password}>
          <Input
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            required
          />
        </Field>
        <Field label={strings.role}>
          <Select value={role} onChange={(event) => setRole(event.target.value)}>
            {ROLE_OPTIONS.map((option) => (
              <option key={option.rank} value={option.rank}>
                {option.label}
              </option>
            ))}
          </Select>
        </Field>
        <Button type="submit" disabled={creating}>
          {creating ? strings.working : strings.provisionUser}
        </Button>
      </Stack>
      <DataView<UserRead>
        viewId="terp.admin.users"
        repository={repository}
        columns={columns}
        serverQuery={serverQuery}
        pageSizeOptions={[10, 25, 50]}
        rowActions={(user) => [
          ...ROLE_OPTIONS.filter((option) => option.rank !== user.role).map((option) => ({
            label: strings.makeRole.replace("{role}", option.label.toLowerCase()),
            onClick: () => void changeRole(user, option.rank),
          })),
          {
            label: strings.resetPassword,
            onClick: () => setResetTarget(user),
          },
          user.is_active
            ? {
                label: strings.deactivate,
                variant: "destructive" as const,
                onClick: () => void setActive(user, false),
              }
            : {
                label: strings.reactivate,
                onClick: () => void setActive(user, true),
              },
        ]}
      />
      <ConfirmDialog
        open={resetTarget !== null}
        onOpenChange={(open) => {
          if (!open) {
            setResetTarget(null);
            setResetPassword("");
          }
        }}
        onConfirm={() => void onConfirmReset()}
        title={`${strings.resetPassword}: ${resetTarget?.email ?? ""}`}
        description={
          <Field label={strings.newPassword}>
            <Input
              type="password"
              value={resetPassword}
              onChange={(event) => setResetPassword(event.target.value)}
              required
            />
          </Field>
        }
        confirmLabel={strings.resetPassword}
        isPending={resetting}
      />
    </Page>
  );
}
