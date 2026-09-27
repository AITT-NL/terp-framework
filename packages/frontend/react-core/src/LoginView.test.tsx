// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { LoginView } from "./LoginView";
import { TerpProvider } from "./TerpProvider";

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function stubFetch() {
  // The provider probes /auth/refresh on mount; a 401 keeps the session signed out.
  vi.stubGlobal(
    "fetch",
    vi.fn<typeof fetch>(async () => json({}, 401)),
  );
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("LoginView dev credentials", () => {
  it("offers no fill button unless devCredentials is passed", async () => {
    stubFetch();
    render(
      <TerpProvider baseUrl="https://api.test">
        <LoginView />
      </TerpProvider>,
    );
    await screen.findByRole("heading", { name: "Sign in" });
    expect(screen.queryByRole("button", { name: "Fill dev credentials" })).toBeNull();
  });

  it("fills the form with the dev credentials on click", async () => {
    stubFetch();
    render(
      <TerpProvider baseUrl="https://api.test">
        <LoginView
          devCredentials={{
            email: "admin@example.test",
            password: "correct horse battery staple",
          }}
        />
      </TerpProvider>,
    );
    fireEvent.click(await screen.findByRole("button", { name: "Fill dev credentials" }));
    // By label, not by placeholder. Reaching for a placeholder here was itself a symptom:
    // it was the only handle these inputs had.
    expect(screen.getByLabelText("Email")).toHaveValue("admin@example.test");
    expect(screen.getByLabelText("Password")).toHaveValue("correct horse battery staple");
  });
});

describe("LoginView accessible names", () => {
  it("labels both credentials so they survive typing and can be addressed by name", async () => {
    // The first screen of every Terp app, and it was labelled by placeholder alone. A
    // placeholder is not an accessible name and it disappears the moment someone types, so
    // the field a user is halfway through filling had nothing identifying it (WCAG 3.3.2)
    // — and `getByLabel` could not find either input, which made the one screen every app
    // ships the one screen its own tests could not address by name.
    stubFetch();
    render(
      <TerpProvider baseUrl="https://api.test">
        <LoginView />
      </TerpProvider>,
    );
    await screen.findByRole("heading", { name: "Sign in" });

    const email = screen.getByLabelText("Email");
    const password = screen.getByLabelText("Password");
    expect(email).toHaveAttribute("type", "email");
    expect(password).toHaveAttribute("type", "password");

    // The name has to survive typing, which is the whole difference from a placeholder.
    fireEvent.change(email, { target: { value: "someone@example.test" } });
    expect(screen.getByLabelText("Email")).toHaveValue("someone@example.test");

    // And the autocomplete tokens stay, so a password manager still offers to fill.
    expect(email).toHaveAttribute("autocomplete", "username");
    expect(password).toHaveAttribute("autocomplete", "current-password");
  });
});

describe("LoginView named parts", () => {
  it("names each credential and the submit button for a caller that cannot read the labels", async () => {
    // `@terpjs/conformance` signs in to every Terp app through this screen, and it used to find
    // the controls by their English names — so an app that boots in any other locale failed its
    // own conformance suite before it had written a line. It finds them by marker path now,
    // which makes each path a cross-package contract: it has to land on exactly the control the
    // helper means to fill. The dev fill button is rendered so a submit part wrapped around the
    // wrong button, or around both, fails rather than passing by being the only candidate.
    stubFetch();
    const { container } = render(
      <TerpProvider baseUrl="https://api.test">
        <LoginView devCredentials={{ email: "admin@example.test", password: "pw" }} />
      </TerpProvider>,
    );
    await screen.findByRole("heading", { name: "Sign in" });

    const only = (selector: string) => {
      const found = container.querySelectorAll(selector);
      expect(found, selector).toHaveLength(1);
      return found[0];
    };
    expect(only('[data-terp="login-email"] [data-terp="input"]')).toBe(
      screen.getByLabelText("Email"),
    );
    expect(only('[data-terp="login-password"] [data-terp="input"]')).toBe(
      screen.getByLabelText("Password"),
    );
    expect(only('[data-terp="login-submit"] [data-terp="button"]')).toBe(
      screen.getByRole("button", { name: "Sign in" }),
    );
  });
});
