import { expect, test } from "@playwright/test";
import { EDITOR, login, logout } from "@terpjs/conformance";

import { NOTES } from "./seed";

const REVOCATION_EDITOR = {
  email: "revocation-editor@acme.test",
  password: "correct horse battery staple",
};

// The frontend must SURFACE a backend failure, not swallow it — over the real deny-by-default
// backend, not a mock. `openapi-fetch` returns `{ data, error }` and does NOT throw on a non-2xx,
// so a data hook that reads `.data` alone hides every HTTP error: a failed write silently no-ops,
// and a server-revoked session lingers as a signed-in shell over empty lists. These two flows are
// the end-to-end proof for the client `unwrap()` + 401-interceptor fixes (ADR 0031 on the client),
// exercised through this app's notes module.

test("a rejected write surfaces the backend error instead of silently no-oping", async ({
  page,
}) => {
  await login(page, EDITOR);

  // The note title caps at 200 chars server-side and the create input imposes no maxlength, so an
  // over-long title is a deterministic rejection from the real API (not a client-side guard).
  await page.getByPlaceholder(NOTES.createPlaceholder).fill("x".repeat(201));
  await page.getByRole("button", { name: "Add" }).click();

  // The failure is shown, not swallowed: `unwrap()` throws on the non-2xx and the data hook lifts
  // it into the list's error state. FastAPI's 422 body carries a list `detail`, which `unwrap()`
  // flattens into an actionable field message. The seeded notes still render — the read is
  // unaffected.
  await expect(page.getByText(/title: String should have at most 200 characters/)).toBeVisible();
  await expect(page.getByText(NOTES.seedText[0])).toBeVisible();
});

test("a server-revoked session is returned to the sign-in screen", async ({ browser }) => {
  // Two sessions for the SAME account. Signing out of one bumps that subject's token epoch
  // server-side (ADR 0031), revoking EVERY outstanding token for the subject — including the other
  // session's. The still-"signed-in" session only learns this on its next authenticated request:
  // that 401 must clear the session and fall back to login, not leave an empty signed-in shell.
  const working = await browser.newContext();
  const revoker = await browser.newContext();
  try {
    const workingPage = await working.newPage();
    const revokerPage = await revoker.newPage();

    await login(workingPage, REVOCATION_EDITOR);
    await expect(workingPage.getByRole("navigation", { name: "Primary" })).toBeVisible();

    // A second session for the same account, then sign it out — revoking the shared subject's
    // tokens (the working session's token included).
    await login(revokerPage, REVOCATION_EDITOR);
    await logout(revokerPage);

    // The working session performs its next authenticated action (a create → POST). Its now-stale
    // token is refused, and the app bounces back to the sign-in screen rather than no-oping.
    await workingPage.getByPlaceholder(NOTES.createPlaceholder).fill("written after revocation");
    await workingPage.getByRole("button", { name: "Add" }).click();

    await expect(workingPage.getByRole("heading", { name: "Sign in" })).toBeVisible();
    await expect(workingPage.getByRole("navigation", { name: "Primary" })).toHaveCount(0);
  } finally {
    await working.close();
    await revoker.close();
  }
});
