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
    expect(screen.getByPlaceholderText("Email")).toHaveValue("admin@example.test");
    expect(screen.getByPlaceholderText("Password")).toHaveValue("correct horse battery staple");
  });
});
