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
import { routeFieldErrors } from "./fieldErrors";
import { adminRoleOptions } from "./roles";

const FORM_ID = "terp-admin-user-create";

/** The inputs this form renders, and so the only reasons it can put anywhere the user will see. */
const RENDERED_FIELDS = ["email", "password", "role"] as const;

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
  const [fieldErrors, setFieldErrors] = useState<Readonly<Record<string, string>>>({});
  const roles = adminRoleOptions(strings);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setCreating(true);
    // Cleared on every attempt, not merged: the server re-validates the whole body, so its
    // answer is the complete set of what is wrong. Keeping a stale key would leave an error
    // under a field the user just fixed.
    setFieldErrors({});
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
      // A reason that names a field belongs on that field, not floating above the form in a
      // toast the user has to hold in their head while looking for the input it means. Anything
      // the server did not attribute — or attributed to something this form has no input for —
      // stays a toast, which is where the delete and revoke handlers correctly leave it.
      const { shown, leftover } = routeFieldErrors(error, RENDERED_FIELDS);
      setFieldErrors(shown);
      if (Object.keys(shown).length === 0 || leftover) {
        toast.warning(error instanceof Error ? error.message : strings.requestFailed);
      }
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
      <div data-terp="admin-form">
        <Stack id={FORM_ID} as="form" gap={4} onSubmit={onSubmit}>
          <Field label={strings.email} error={fieldErrors.email}>
            <Input
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              required
            />
          </Field>
          <Field label={strings.password} error={fieldErrors.password}>
            <Input
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              required
            />
          </Field>
          <Field label={strings.role} error={fieldErrors.role}>
            {/* `options` + `onValueChange` rather than an `<option>` per rank and a raw
                change event: the same three rows, as data. No cast is removed here — this file
                never had one, because `role` was already a plain string — and `T` degrades to
                `string` for the same reason, since the option values are `String(rank)` rather
                than members of a declared union. What this conversion buys is the list, not the
                type: the rank is a number in the ladder and a string in the DOM, which is why
                `String(rank)` is the option value and `role` stays a string until the POST body
                coerces it. The typed half has its exhibit in an app that owns an enum. */}
            <Select
              options={roles.map((option) => ({
                value: String(option.rank),
                label: option.label,
              }))}
              value={role}
              onValueChange={setRole}
            />
          </Field>
        </Stack>
      </div>
    </Page>
  );
}