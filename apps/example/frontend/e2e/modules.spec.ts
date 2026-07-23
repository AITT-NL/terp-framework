import { expect, test } from "@playwright/test";
import { login } from "@terpjs/conformance";

import { JOURNALS, PROJECTS, TASKS } from "./seed";

// The app's other modules over the running stack — each dogfoods a framework trait through the
// same typed data hook (useResource): tasks (soft-delete), projects (tenancy), journals (ownership).
// Proves the seeded rows render and that a task can be created and then soft-deleted, dropping out of
// the list because the base query hides deleted rows — all against the real deny-by-default backend.

test.beforeEach(async ({ page }) => {
  await login(page);
});

test("the tasks module lists the seeded tasks", async ({ page }) => {
  await page.getByRole("link", { name: TASKS.link }).click();
  for (const text of TASKS.seedText) {
    await expect(page.getByText(text)).toBeVisible();
  }
});

test("the projects module lists the tenant's seeded projects", async ({ page }) => {
  await page.getByRole("link", { name: PROJECTS.link }).click();
  for (const text of PROJECTS.seedText) {
    await expect(page.getByText(text)).toBeVisible();
  }
});

test("the journals module lists the seeded journal", async ({ page }) => {
  await page.getByRole("link", { name: JOURNALS.link }).click();
  for (const text of JOURNALS.seedText) {
    await expect(page.getByText(text)).toBeVisible();
  }
});

test("a task can be created and then soft-deleted out of the list", async ({ page }) => {
  await page.getByRole("link", { name: TASKS.link }).click();
  const title = `conformance task ${Date.now()}`;
  await page.getByLabel("Title").fill(title);
  await page.getByRole("button", { name: "Add" }).click();

  const row = page.getByRole("listitem").filter({ hasText: title });
  await expect(row).toBeVisible();

  // Soft-delete: the row drops out of the list (the backend hides deleted rows via the base query).
  await row.getByRole("button", { name: "Delete" }).click();
  await expect(page.getByText(title)).toHaveCount(0);
});

test("a task is created with a chosen status through the multi-field form", async ({ page }) => {
  await page.getByRole("link", { name: TASKS.link }).click();
  const title = `status task ${Date.now()}`;
  await page.getByLabel("Title").fill(title);
  await page.getByLabel("Status").selectOption("doing");
  await page.getByRole("button", { name: "Add" }).click();

  // The chosen status round-trips through the typed create and renders on the row.
  await expect(page.getByRole("listitem").filter({ hasText: title })).toContainText("doing");
});

test("a journal is created with a multi-line entry through the multi-field form", async ({ page }) => {
  await page.getByRole("link", { name: JOURNALS.link }).click();
  const title = `entry journal ${Date.now()}`;
  await page.getByLabel("Title").fill(title);
  await page.getByLabel("Entry").fill("line one\nline two");
  await page.getByRole("button", { name: "Add" }).click();

  await expect(page.getByText(title)).toBeVisible();
});
