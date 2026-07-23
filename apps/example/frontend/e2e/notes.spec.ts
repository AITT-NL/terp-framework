import { expect, test } from "@playwright/test";
import { login } from "@terpjs/conformance";

import { NOTES } from "./seed";

// Notes module CRUD over the running stack: the seeded notes render, and creating a note
// round-trips through the audited backend into the list — proving the generated typed client,
// the deny-by-default write path, and the SPA wiring against the real stack.

test.beforeEach(async ({ page }) => {
  await login(page);
});

test("the seeded notes are listed", async ({ page }) => {
  for (const text of NOTES.seedText) {
    await expect(page.getByText(text)).toBeVisible();
  }
});

test("a newly created note appears in the list", async ({ page }) => {
  const title = `conformance note ${Date.now()}`;
  await page.getByPlaceholder(NOTES.createPlaceholder).fill(title);
  await page.getByRole("button", { name: "Add" }).click();
  await expect(page.getByText(title)).toBeVisible();
});
