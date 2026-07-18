import { useNavigate } from "@tanstack/react-router";
import { useState } from "react";
import type { FormEvent } from "react";

import { Field } from "../Field";
import { Icon } from "../icons";
import { Stack } from "../layout";
import { Page } from "../Page";
import { PageActions } from "../PageActions";
import { useTerpClient } from "../TerpProvider";
import { useToast } from "../toast";
import { Button } from "../ui/Button";
import { Input } from "../ui/Input";
import { useStrings } from "../uiText";
import { unwrap } from "../unwrap";

import { adminCrumb, renderAdminCrumb } from "./crumbs";

const FORM_ID = "terp-admin-group-create";

/** Dedicated group-creation page (`/admin/groups/new`). */
export function GroupCreate() {
  const client = useTerpClient();
  const navigate = useNavigate();
  const strings = useStrings();
  const toast = useToast();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [creating, setCreating] = useState(false);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setCreating(true);
    try {
      const group = unwrap(
        await client.POST("/api/v1/groups/", { body: { name, description } }),
      );
      toast.success(strings.saved);
      await navigate({
        to: "/admin/groups/$groupId",
        params: { groupId: group.id },
      });
    } catch (error) {
      toast.warning(error instanceof Error ? error.message : strings.requestFailed);
    } finally {
      setCreating(false);
    }
  }

  return (
    <Page
      title={strings.createGroup}
      breadcrumbs={[
        { ...adminCrumb(strings), to: "/admin" },
        { label: strings.adminGroups, to: "/admin/groups" },
      ]}
      renderLink={renderAdminCrumb}
      actions={
        <PageActions
          secondary={
            <Button variant="secondary" onClick={() => void navigate({ to: "/admin/groups" })}>
              {strings.cancel}
            </Button>
          }
          primary={
            <Button
              type="submit"
              form={FORM_ID}
              icon={<Icon name="plus" />}
              disabled={creating}
            >
              {creating ? strings.working : strings.createGroup}
            </Button>
          }
        />
      }
    >
      <div style={{ maxWidth: "32rem" }}>
        <Stack id={FORM_ID} as="form" gap={4} onSubmit={onSubmit}>
          <Field label={strings.groupName}>
            <Input value={name} onChange={(event) => setName(event.target.value)} required />
          </Field>
          <Field label={strings.description}>
            <Input value={description} onChange={(event) => setDescription(event.target.value)} />
          </Field>
        </Stack>
      </div>
    </Page>
  );
}