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
import { Select } from "../ui/Select";
import { useStrings } from "../uiText";
import { unwrap } from "../unwrap";

import { adminCrumb, renderAdminCrumb } from "./crumbs";
import { adminRoleOptions } from "./roles";

const FORM_ID = "terp-admin-user-create";

/** Dedicated account-provisioning page (`/admin/users/new`). */
export function UserCreate() {
  const client = useTerpClient();
  const navigate = useNavigate();
  const strings = useStrings();
  const toast = useToast();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState("10");
  const [creating, setCreating] = useState(false);
  const roles = adminRoleOptions(strings);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setCreating(true);
    try {
      const user = unwrap(
        await client.POST("/api/v1/users/", {
          body: { email, password, role: Number(role) },
        }),
      );
      toast.success(strings.saved);
      await navigate({
        to: "/admin/users/$userId",
        params: { userId: user.id },
      });
    } catch (error) {
      toast.warning(error instanceof Error ? error.message : strings.requestFailed);
    } finally {
      setCreating(false);
    }
  }

  return (
    <Page
      title={strings.provisionUser}
      breadcrumbs={[
        { ...adminCrumb(strings), to: "/admin" },
        { label: strings.adminUsers, to: "/admin/users" },
      ]}
      renderLink={renderAdminCrumb}
      actions={
        <PageActions
          secondary={
            <Button variant="secondary" onClick={() => void navigate({ to: "/admin/users" })}>
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
              {creating ? strings.working : strings.provisionUser}
            </Button>
          }
        />
      }
    >
      <div style={{ maxWidth: "32rem" }}>
        <Stack id={FORM_ID} as="form" gap={4} onSubmit={onSubmit}>
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
              {roles.map((option) => (
                <option key={option.rank} value={option.rank}>
                  {option.label}
                </option>
              ))}
            </Select>
          </Field>
        </Stack>
      </div>
    </Page>
  );
}