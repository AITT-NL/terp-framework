import { expect, test, type Page } from "@playwright/test";

import { ADMIN, login, logout } from "../src/index";

// An app may replace the framework's sign-in screen (`renderTerpApp({ login: … })`). That screen
// is then the app's own, and so are its sign-in steps: its specs sign in by the screen's own
// accessible names. The helpers drive the framework's screen only, so on such an app they fail,
// and the failure is what an agent reads next. It has to say what was not found and name the
// two ways forward, or the shortest-looking fix is to copy the framework's data-terp markers
// onto the app's screen, which forges react-core's identity for its components.
//
// No stack is involved: every request is answered with a page standing in for the app.

/** A sign-in screen of the app's own: labelled, in its own words, carrying no data-terp. */
const APPS_OWN_SIGN_IN = `
  <main>
    <h1>Welcome back</h1>
    <form>
      <label>Work email <input type="email" name="email"></label>
      <label>Passphrase <input type="password" name="password"></label>
      <button type="submit">Continue</button>
    </form>
  </main>`;

/**
 * The framework's shell as `logout()` finds it, by its markers: the account menu's trigger and
 * its sign-out item. Signing out shows the app's own sign-in screen, as it does in an app that
 * replaced the framework's.
 */
const SHELL_THAT_SIGNS_OUT_TO_THE_APPS_SCREEN = `
  <nav data-terp="appshell-nav" aria-label="Main"></nav>
  <div data-terp="user-menu">
    <button data-terp="menu-trigger" aria-haspopup="menu"
      onclick="document.getElementById('menu').hidden = false">admin@example.test</button>
    <div id="menu" role="menu" hidden>
      <span data-terp="user-menu-sign-out" style="display: contents">
        <button data-terp="menu-item" role="menuitem"
          onclick="document.body.innerHTML = document.getElementById('signed-out').innerHTML"
        >Sign out</button>
      </span>
    </div>
  </div>
  <template id="signed-out">${APPS_OWN_SIGN_IN}</template>`;

async function serve(page: Page, body: string): Promise<void> {
  const html = `<!doctype html><html lang="en"><body>${body}</body></html>`;
  await page.route("**/*", (route) => route.fulfill({ contentType: "text/html", body: html }));
}

/** The message *action* fails with; a helper that passes here has found a screen it must not. */
async function failureOf(action: Promise<unknown>): Promise<string> {
  const outcome = await action.then(
    () => undefined,
    (error: unknown) => error,
  );
  expect(outcome, "the helper passed on a screen that is not the framework's").toBeInstanceOf(
    Error,
  );
  return (outcome as Error).message;
}

/** What every such failure owes its reader, whichever helper raised it. */
function expectTheWaysForward(message: string): void {
  expect(message).toContain('no [data-terp="login-title"] became visible');
  expect(message).toContain("If this app replaces it (renderTerpApp({ login: … }))");
  expect(message).toContain("sign in and out from the spec by the screen's own accessible names");
  expect(message).toContain("drop the `login` option, so the framework's screen renders again");
  expect(message).toContain("Do not add data-terp markers to the app's screen");
  // The assertion's own account still follows, so nothing it said is lost.
  expect(message).toContain("toBeVisible");
}

test("login() on an app's own sign-in screen says so, and names the ways forward", async ({
  page,
}) => {
  await serve(page, APPS_OWN_SIGN_IN);
  const message = await failureOf(login(page, ADMIN));
  expect(message).toContain("The framework's sign-in screen is not on the page at ");
  expect(message).toContain("check the address the suite drives");
  expectTheWaysForward(message);
});

test("logout() onto an app's own sign-in screen says so, and names the ways forward", async ({
  page,
}) => {
  await serve(page, SHELL_THAT_SIGNS_OUT_TO_THE_APPS_SCREEN);
  await page.goto("/");
  const message = await failureOf(logout(page));
  expect(message).toContain("After signing out, the framework's sign-in screen did not appear");
  expect(message).toContain("signing out did not return to the sign-in screen");
  expectTheWaysForward(message);
});
