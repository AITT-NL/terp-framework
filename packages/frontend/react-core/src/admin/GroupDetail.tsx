import { useNavigate, useParams } from "@tanstack/react-router";
import { useEffect, useId, useMemo, useState } from "react";
import type { FormEvent } from "react";
import type { components } from "@terpjs/contract";

import { ConfirmDialog } from "../ConfirmDialog";
import { DetailPage } from "../DetailPage";
import { useTerpClient } from "../TerpProvider";
import { Field } from "../Field";
import { Icon } from "../icons";
import { DataView, HttpDataViewRepository } from "../dataview";
import type { DataViewColumn } from "../dataview";
import { DetailList, Stack } from "../layout";
import { PageActions } from "../PageActions";
import { useResource } from "../useResource";
import { useToast } from "../toast";
import { Button } from "../ui/Button";
import { Input } from "../ui/Input";
import { useStrings } from "../uiText";
import { unwrap } from "../unwrap";

import { adminCrumb, renderAdminCrumb } from "./crumbs";

type GroupRead = components["schemas"]["GroupRead"];
type GroupMemberRead = components["schemas"]["GroupMemberRead"];
type GrantRead = components["schemas"]["GrantRead"];
type UserRead = components["schemas"]["UserRead"];

/** How long the member picker waits after a keystroke before searching accounts. */
const SEARCH_DEBOUNCE_MS = 250;

/**
 * The packaged group detail page (`/admin/groups/$groupId`): the group's members
 * (add / remove — idempotent on the backend) and the permissions granted to the
 * group (ordinary access grants whose subject is the group's id, effective for
 * every member through the subject-expansion seam, ADR 0074). Members are picked
 * by email through the directory's server-side `?email=` search — no client-side
 * user cache, so any directory size works — and member rows carry the email the
 * backend resolved for them.
 */
export function GroupDetail() {
  const params = useParams({ strict: false }) as { groupId?: string };
  const groupId = params.groupId ?? "";
  const client = useTerpClient();
  const navigate = useNavigate();
  const toast = useToast();
  const strings = useStrings();
  const suggestionsId = useId();

  const [membersVersion, setMembersVersion] = useState(0);
  const [grantsVersion, setGrantsVersion] = useState(0);
  const [memberQuery, setMemberQuery] = useState("");
  const [suggestions, setSuggestions] = useState<UserRead[]>([]);
  const [adding, setAdding] = useState(false);
  const [permission, setPermission] = useState("");
  const [granting, setGranting] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [pendingMember, setPendingMember] = useState<GroupMemberRead | null>(null);
  const [removingMember, setRemovingMember] = useState(false);
  const [pendingGrant, setPendingGrant] = useState<GrantRead | null>(null);
  const [revoking, setRevoking] = useState(false);

  useEffect(() => {
    setMemberQuery("");
    setSuggestions([]);
    setPermission("");
    setDeleteOpen(false);
    setPendingMember(null);
    setPendingGrant(null);
    setAdding(false);
    setGranting(false);
    setDeleting(false);
    setRemovingMember(false);
    setRevoking(false);
  }, [groupId]);

  const group = useResource<GroupRead>(
    {
      list: async () => {
        const row = unwrap(
          await client.GET("/api/v1/groups/{group_id}", {
            params: { path: { group_id: groupId } },
          }),
        );
        return [row];
      },
    },
    // Reload when navigating between group detail pages in place.
    [groupId],
  );

  // Debounced directory lookup feeding the picker's suggestions (best-effort).
  useEffect(() => {
    const needle = memberQuery.trim();
    if (needle === "") {
      setSuggestions([]);
      return;
    }
    const timer = setTimeout(() => {
      void (async () => {
        try {
          const page = unwrap(
            await client.GET("/api/v1/users/", {
              params: { query: { email: needle, limit: 20 } },
            }),
          );
          setSuggestions(page.items);
        } catch {
          // Suggestions are a convenience; submitting still resolves the email.
        }
      })();
    }, SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [client, memberQuery]);

  const memberColumns: DataViewColumn<GroupMemberRead>[] = useMemo(
    () => [
      {
        id: "user",
        header: strings.userField,
        accessor: (m) => m.email ?? m.user_id,
        meta: { mobileSlot: "title" },
      },
      {
        id: "created_at",
        header: strings.createdColumn,
        accessor: (m) => m.created_at,
        cell: (m) => new Date(m.created_at).toLocaleDateString(),
        meta: { mobileSlot: "date", width: 120 },
      },
    ],
    [strings],
  );

  const grantColumns: DataViewColumn<GrantRead>[] = useMemo(
    () => [
      {
        id: "permission",
        header: strings.permission,
        accessor: (g) => g.permission,
        meta: { mobileSlot: "title" },
      },
      {
        id: "created_at",
        header: strings.createdColumn,
        accessor: (g) => g.created_at,
        cell: (g) => new Date(g.created_at).toLocaleDateString(),
        meta: { mobileSlot: "date", width: 120 },
      },
    ],
    [strings],
  );

  const membersRepository = useMemo(
    () =>
      new HttpDataViewRepository<GroupMemberRead>({
        getRowId: (m) => m.id,
        search: false,
        request: async ({ skip, limit }, signal) => {
          const page = unwrap(
            await client.GET("/api/v1/groups/{group_id}/members", {
              params: { path: { group_id: groupId }, query: { skip, limit } },
              signal,
            }),
          );
          return { items: page.items, total: page.total };
        },
      }),
    [client, groupId, membersVersion],
  );

  const grantsRepository = useMemo(
    () =>
      new HttpDataViewRepository<GrantRead>({
        getRowId: (g) => g.id,
        search: false,
        request: async ({ skip, limit }, signal) => {
          const page = unwrap(
            await client.GET("/api/v1/access/grants", {
              params: { query: { subject_id: groupId, skip, limit } },
              signal,
            }),
          );
          return { items: page.items, total: page.total };
        },
      }),
    [client, groupId, grantsVersion],
  );

  function failed(error: unknown): void {
    toast.warning(error instanceof Error ? error.message : strings.requestFailed);
  }

  async function onAddMember(event: FormEvent) {
    event.preventDefault();
    const needle = memberQuery.trim();
    if (needle === "") return;
    setAdding(true);
    try {
      // Resolve the typed email to an account: exact match among the current
      // suggestions first, else one direct directory query.
      let match = suggestions.find((user) => user.email === needle);
      if (match === undefined) {
        const page = unwrap(
          await client.GET("/api/v1/users/", {
            params: { query: { email: needle, limit: 20 } },
          }),
        );
        match = page.items.find((user) => user.email === needle);
      }
      if (match === undefined) {
        toast.warning(strings.userNotFound);
        return;
      }
      unwrap(
        await client.POST("/api/v1/groups/{group_id}/members", {
          params: { path: { group_id: groupId } },
          body: { user_id: match.id },
        }),
      );
      toast.success(strings.saved);
      setMemberQuery("");
      setSuggestions([]);
      setMembersVersion((v) => v + 1);
      void group.reload();
    } catch (error) {
      failed(error);
    } finally {
      setAdding(false);
    }
  }

  async function onConfirmRemoveMember() {
    if (pendingMember === null) return;
    setRemovingMember(true);
    try {
      unwrap(
        await client.DELETE("/api/v1/groups/{group_id}/members/{user_id}", {
          params: { path: { group_id: groupId, user_id: pendingMember.user_id } },
        }),
      );
      toast.success(strings.saved);
      setPendingMember(null);
      setMembersVersion((v) => v + 1);
      void group.reload();
    } catch (error) {
      failed(error);
    } finally {
      setRemovingMember(false);
    }
  }

  async function onGrant(event: FormEvent) {
    event.preventDefault();
    setGranting(true);
    try {
      unwrap(
        await client.POST("/api/v1/access/grants", {
          body: { subject_id: groupId, permission },
        }),
      );
      toast.success(strings.saved);
      setPermission("");
      setGrantsVersion((v) => v + 1);
    } catch (error) {
      failed(error);
    } finally {
      setGranting(false);
    }
  }

  async function onConfirmRevoke() {
    if (pendingGrant === null) return;
    setRevoking(true);
    try {
      unwrap(
        await client.DELETE("/api/v1/access/grants/{grant_id}", {
          params: { path: { grant_id: pendingGrant.id } },
        }),
      );
      toast.success(strings.saved);
      setPendingGrant(null);
      setGrantsVersion((v) => v + 1);
    } catch (error) {
      failed(error);
    } finally {
      setRevoking(false);
    }
  }

  async function onConfirmDelete() {
    setDeleting(true);
    try {
      unwrap(
        await client.DELETE("/api/v1/groups/{group_id}", {
          params: { path: { group_id: groupId } },
        }),
      );
      toast.success(strings.saved);
      await navigate({ to: "/admin/groups" });
    } catch (error) {
      failed(error);
    } finally {
      setDeleting(false);
    }
  }

  const record = group.items[0];
  return (
    <DetailPage
      title={record?.name ?? strings.adminGroups}
      parents={[
        { ...adminCrumb(strings), to: "/admin" },
        { label: strings.adminGroups, to: "/admin/groups" },
      ]}
      renderLink={renderAdminCrumb}
      isLoading={group.loading}
      error={group.cause ?? group.error ?? undefined}
      actions={record !== undefined ? (
        <PageActions
          overflow={[
            {
              label: strings.deleteGroup,
              icon: <Icon name="trash" />,
              variant: "destructive",
              onSelect: () => setDeleteOpen(true),
            },
          ]}
        />
      ) : undefined}
    >
      <Stack gap={6}>
        {record !== undefined && (
          <DetailList
            items={[
              { label: strings.description, value: record.description || "-" },
              { label: strings.members, value: record.member_count },
              { label: strings.createdColumn, value: new Date(record.created_at).toLocaleString() },
            ]}
          />
        )}
        <Stack gap={3}>
          <h2 style={{ margin: 0, fontSize: "var(--font-size-base)" }}>
            {strings.members}
          </h2>
          <Stack as="form" direction="row" gap={2} align="end" wrap onSubmit={onAddMember}>
            <Field label={strings.userField}>
              <Input
                type="email"
                value={memberQuery}
                list={suggestionsId}
                placeholder={strings.email}
                onChange={(event) => setMemberQuery(event.target.value)}
                required
              />
            </Field>
            <datalist id={suggestionsId}>
              {suggestions.map((user) => (
                <option key={user.id} value={user.email} />
              ))}
            </datalist>
            <Button type="submit" disabled={adding || memberQuery.trim() === ""}>
              {adding ? strings.working : strings.addMember}
            </Button>
          </Stack>
          <DataView<GroupMemberRead>
            variant="embedded"
            repository={membersRepository}
            columns={memberColumns}
            rowActions={(member) => [
              {
                label: strings.removeMember,
                variant: "destructive",
                onClick: () => setPendingMember(member),
              },
            ]}
          />
        </Stack>
        <Stack gap={3}>
          <h2 style={{ margin: 0, fontSize: "var(--font-size-base)" }}>
            {strings.permissions}
          </h2>
          <Stack as="form" direction="row" gap={2} align="end" wrap onSubmit={onGrant}>
            <Field label={strings.permission}>
              <Input
                value={permission}
                onChange={(event) => setPermission(event.target.value)}
                required
              />
            </Field>
            <Button type="submit" disabled={granting}>
              {granting ? strings.working : strings.grantPermission}
            </Button>
          </Stack>
          <DataView<GrantRead>
            variant="embedded"
            repository={grantsRepository}
            columns={grantColumns}
            rowActions={(grant) => [
              {
                label: strings.revoke,
                variant: "destructive",
                onClick: () => setPendingGrant(grant),
              },
            ]}
          />
        </Stack>
      </Stack>
      <ConfirmDialog
        open={deleteOpen}
        onOpenChange={setDeleteOpen}
        onConfirm={() => void onConfirmDelete()}
        title={`${strings.deleteGroup}: ${record?.name ?? ""}`}
        description={strings.deleteGroupConfirm}
        confirmLabel={strings.deleteGroup}
        destructive
        isPending={deleting}
      />
      <ConfirmDialog
        open={pendingMember !== null}
        onOpenChange={(open) => {
          if (!open) setPendingMember(null);
        }}
        onConfirm={() => void onConfirmRemoveMember()}
        title={strings.removeMember}
        description={strings.removeMemberConfirm}
        confirmLabel={strings.removeMember}
        destructive
        isPending={removingMember}
      />
      <ConfirmDialog
        open={pendingGrant !== null}
        onOpenChange={(open) => {
          if (!open) setPendingGrant(null);
        }}
        onConfirm={() => void onConfirmRevoke()}
        title={strings.revoke}
        description={strings.revokeConfirm}
        confirmLabel={strings.revoke}
        destructive
        isPending={revoking}
      />
    </DetailPage>
  );
}
