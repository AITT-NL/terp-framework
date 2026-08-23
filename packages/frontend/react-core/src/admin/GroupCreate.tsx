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
import { ApiError, unwrap } from "../unwrap";

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
  const [fieldErrors, setFieldErrors] = useState<Readonly<Record<string, string>>>({});

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setCreating(true);
    // Cleared on every attempt: the server re-validates the whole body, so its answer is the
    // complete set of what is wrong, and a stale key would sit under a field already fixed.
    setFieldErrors({});
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
      // A reason that names a field belongs on that field; anything unattributed stays a toast.
      if (error instanceof ApiError && Object.keys(error.fields).length > 0) {
        setFieldErrors(error.fields);
        return;
      }
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
      <div data-terp="admin-form">
        <Stack id={FORM_ID} as="form" gap={4} onSubmit={onSubmit}>
          <Field label={strings.groupName} error={fieldErrors.name}>
            <Input value={name} onChange={(event) => setName(event.target.value)} required />
          </Field>
          <Field label={strings.description} error={fieldErrors.description}>
            <Input value={description} onChange={(event) => setDescription(event.target.value)} />
          </Field>
        </Stack>
      </div>
    </Page>
  );
}