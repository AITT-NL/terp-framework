import { expect, test } from "@playwright/test";
import { EDITOR, VIEWER, login } from "@terpjs/conformance";

import { NOTES } from "./seed";

// RBAC gating on the notes module: the create form is wrapped in `<Authorized action="write">`,
// so the UI honours the backend role ladder. A read-only viewer (below the write threshold) sees
// the notes but no create form, while an editor (at the write threshold) gets it — proving the
// frontend gate is driven by the same roles the deny-by-default backend enforces, not a
// client-side guess.

test("a read-only viewer sees notes but not the write-gated create form", async ({ page }) => {
  await login(page, VIEWER);
  // Reading is allowed — the seeded notes still render for a viewer.
  await expect(page.getByText(NOTES.seedText[0])).toBeVisible();
  // Writing is gated — the create form and its Add button are absent for a viewer.
  await expect(page.getByPlaceholder(NOTES.createPlaceholder)).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Add" })).toHaveCount(0);
});

test("an editor at the write threshold sees the create form", async ({ page }) => {
  await login(page, EDITOR);
  await expect(page.getByPlaceholder(NOTES.createPlaceholder)).toBeVisible();
  await expect(page.getByRole("button", { name: "Add" })).toBeVisible();
});
