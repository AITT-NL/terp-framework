import { useParams } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import type { components } from "@terpjs/contract";

import { ConfirmDialog } from "../ConfirmDialog";
import { DetailPage } from "../DetailPage";
import { Field } from "../Field";
import { Icon } from "../icons";
import { DetailList } from "../layout";
import { PageActions } from "../PageActions";
import { useTerpClient } from "../TerpProvider";
import { useResource } from "../useResource";
import { useToast } from "../toast";
import { Button } from "../ui/Button";
import { Input } from "../ui/Input";
import { useStrings } from "../uiText";
import { unwrap } from "../unwrap";

import { adminCrumb, renderAdminCrumb } from "./crumbs";
import { adminRoleLabel, adminRoleOptions } from "./roles";

type UserRead = components["schemas"]["UserRead"];

type PendingLifecycle =
  | { kind: "role"; rank: number }
  | { kind: "active"; active: boolean };

/** Dedicated account detail and lifecycle page (`/admin/users/$userId`). */
export function UserDetail() {
  const params = useParams({ strict: false }) as { userId?: string };
  const userId = params.userId ?? "";
  const client = useTerpClient();
  const strings = useStrings();
  const toast = useToast();
  const [pendingLifecycle, setPendingLifecycle] = useState<PendingLifecycle | null>(null);
  const [mutating, setMutating] = useState(false);
  const [resetOpen, setResetOpen] = useState(false);
  const [resetPassword, setResetPassword] = useState("");
  const [resetting, setResetting] = useState(false);
  const roles = adminRoleOptions(strings);

  useEffect(() => {
    setPendingLifecycle(null);
    setResetOpen(false);
    setResetPassword("");
    setMutating(false);
    setResetting(false);
  }, [userId]);

  const user = useResource<UserRead>(
    {
      list: async () => [
        unwrap(
          await client.GET("/api/v1/users/{user_id}", {
            params: { path: { user_id: userId } },
          }),
        ),
      ],
    },
    [userId],
  );
  const record = user.items[0];

  function failed(error: unknown): void {
    toast.warning(error instanceof Error ? error.message : strings.requestFailed);
  }

  async function onConfirmLifecycle() {
    if (record === undefined || pendingLifecycle === null) return;
    setMutating(true);
    try {
      if (pendingLifecycle.kind === "role") {
        unwrap(
          await client.PATCH("/api/v1/users/{user_id}", {
            params: { path: { user_id: record.id } },
            body: { role: pendingLifecycle.rank, version: record.version },
          }),
        );
      } else {
        const path = pendingLifecycle.active
          ? "/api/v1/users/{user_id}/reactivate"
          : "/api/v1/users/{user_id}/deactivate";
        unwrap(await client.POST(path, { params: { path: { user_id: record.id } } }));
      }
      toast.success(strings.saved);
      setPendingLifecycle(null);
      await user.reload();
    } catch (error) {
      failed(error);
    } finally {
      setMutating(false);
    }
  }

  async function onConfirmReset() {
    if (record === undefined || resetPassword.trim() === "") return;
    setResetting(true);
    try {
      unwrap(
        await client.POST("/api/v1/users/{user_id}/reset-password", {
          params: { path: { user_id: record.id } },
          body: { password: resetPassword },
        }),
      );
      toast.success(strings.saved);
      setResetOpen(false);
      setResetPassword("");
      await user.reload();
    } catch (error) {
      failed(error);
    } finally {
      setResetting(false);
    }
  }

  const pendingRole = pendingLifecycle?.kind === "role"
    ? adminRoleLabel(strings, pendingLifecycle.rank)
    : "";
  const lifecycleDescription = pendingLifecycle?.kind === "role"
    ? strings.changeRoleConfirm.replace("{role}", pendingRole)
    : pendingLifecycle?.active
      ? strings.reactivateUserConfirm
      : strings.deactivateUserConfirm;

  return (
    <DetailPage
      title={record?.email ?? strings.adminUsers}
      parents={[
        { ...adminCrumb(strings), to: "/admin" },
        { label: strings.adminUsers, to: "/admin/users" },
      ]}
      renderLink={renderAdminCrumb}
      isLoading={user.loading}
      error={user.cause ?? user.error ?? undefined}
      actions={record !== undefined ? (
        <PageActions
          secondary={
            <Button
              variant="secondary"
              icon={<Icon name="key" />}
              onClick={() => setResetOpen(true)}
            >
              {strings.resetPassword}
            </Button>
          }
          overflow={[
            ...roles
              .filter((option) => option.rank !== record.role)
              .map((option) => ({
                label: strings.makeRole.replace("{role}", option.label.toLowerCase()),
                onSelect: () => setPendingLifecycle({ kind: "role", rank: option.rank }),
              })),
            record.is_active
              ? {
                  label: strings.deactivate,
                  icon: <Icon name="lock" />,
                  variant: "destructive" as const,
                  onSelect: () => setPendingLifecycle({ kind: "active", active: false }),
                }
              : {
                  label: strings.reactivate,
                  icon: <Icon name="refresh" />,
                  onSelect: () => setPendingLifecycle({ kind: "active", active: true }),
                },
          ]}
        />
      ) : undefined}
    >
      {record !== undefined && (
        <DetailList
          items={[
            { label: strings.email, value: record.email },
            { label: strings.role, value: adminRoleLabel(strings, record.role) },
            {
              label: strings.statusColumn,
              value: record.is_active ? strings.statusActive : strings.statusDeactivated,
            },
            { label: strings.createdColumn, value: new Date(record.created_at).toLocaleString() },
          ]}
        />
      )}
      <ConfirmDialog
        open={pendingLifecycle !== null}
        onOpenChange={(open) => {
          if (!open) setPendingLifecycle(null);
        }}
        onConfirm={() => void onConfirmLifecycle()}
        title={pendingLifecycle?.kind === "role"
          ? strings.makeRole.replace("{role}", pendingRole.toLowerCase())
          : pendingLifecycle?.active
            ? strings.reactivate
            : strings.deactivate}
        description={lifecycleDescription}
        confirmLabel={pendingLifecycle?.kind === "role"
          ? strings.confirm
          : pendingLifecycle?.active
            ? strings.reactivate
            : strings.deactivate}
        destructive={pendingLifecycle?.kind === "active" && !pendingLifecycle.active}
        isPending={mutating}
      />
      <ConfirmDialog
        open={resetOpen}
        onOpenChange={(open) => {
          if (!open) {
            setResetOpen(false);
            setResetPassword("");
          }
        }}
        onConfirm={() => void onConfirmReset()}
        title={`${strings.resetPassword}: ${record?.email ?? ""}`}
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
        confirmDisabled={resetPassword.trim() === ""}
        isPending={resetting}
      />
    </DetailPage>
  );
}