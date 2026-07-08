// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useEffect } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { TerpProvider, useAuth } from "./TerpProvider";
import { UserMenu, userInitials } from "./UserMenu";
import { LOCALE_EN, LocaleProvider } from "./locale";
import { ThemeProvider } from "./theme";

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "content-type": "application/json" },
  });
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  window.localStorage.clear();
  document.documentElement.removeAttribute("data-theme");
});

function LogInOnMount() {
  const auth = useAuth();
  useEffect(() => {
    void auth.login({ email: "jane.doe@example.com", password: "pw" });
  }, []);
  return null;
}

function stubAuthFetch() {
  const fetchMock = vi.fn<typeof fetch>(async (input) => {
    const url = (input as Request).url;
    if (url.endsWith("/api/v1/auth/login")) {
      return jsonResponse({ access_token: "token", token_type: "bearer" });
    }
    if (url.endsWith("/api/v1/auth/logout")) {
      return new Response(null, { status: 204 });
    }
    return jsonResponse({
      id: "u1",
      email: "jane.doe@example.com",
      role_rank: 20,
      role_name: "editor",
    });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("userInitials", () => {
  it("derives initials from the email's local part", () => {
    expect(userInitials("jane.doe@example.com")).toBe("JD");
    expect(userInitials("admin@example.test")).toBe("A");
    expect(userInitials("@example.test")).toBe("?");
  });
});

describe("UserMenu", () => {
  it("renders nothing while signed out", () => {
    stubAuthFetch();
    render(
      <TerpProvider baseUrl="https://api.test">
        <UserMenu />
      </TerpProvider>,
    );
    expect(screen.queryByRole("button", { name: "Account menu" })).not.toBeInTheDocument();
  });

  it("shows the avatar initials, email and role, and opens the panel", async () => {
    stubAuthFetch();
    render(
      <ThemeProvider>
        <LocaleProvider locales={{ en: LOCALE_EN, nl: { label: "Nederlands" } }}>
          <TerpProvider baseUrl="https://api.test">
            <LogInOnMount />
            <UserMenu />
          </TerpProvider>
        </LocaleProvider>
      </ThemeProvider>,
    );
    const trigger = await screen.findByRole("button", { name: "Account menu" });
    expect(screen.getByText("JD")).toBeInTheDocument();
    expect(screen.getByText("jane.doe@example.com")).toBeInTheDocument();
    expect(screen.getByText("editor")).toBeInTheDocument();
    expect(trigger).toHaveAttribute("aria-expanded", "false");

    fireEvent.click(trigger);
    expect(trigger).toHaveAttribute("aria-expanded", "true");
    // The panel shows the identity block and offers sign-out (Settings needs onSettings).
    expect(screen.getAllByText("jane.doe@example.com")).toHaveLength(2);
    expect(screen.queryByRole("menuitem", { name: "Settings" })).not.toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: "Sign out" })).toBeInTheDocument();
  });

  it("opens the settings page and closes the panel", async () => {
    stubAuthFetch();
    const onSettings = vi.fn();
    render(
      <TerpProvider baseUrl="https://api.test">
        <LogInOnMount />
        <UserMenu onSettings={onSettings} />
      </TerpProvider>,
    );
    fireEvent.click(await screen.findByRole("button", { name: "Account menu" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Settings" }));
    expect(onSettings).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("menuitem", { name: "Sign out" })).not.toBeInTheDocument();
  });

  it("shows only the avatar on the trigger when collapsed", async () => {
    stubAuthFetch();
    render(
      <TerpProvider baseUrl="https://api.test">
        <LogInOnMount />
        <UserMenu collapsed />
      </TerpProvider>,
    );
    const trigger = await screen.findByRole("button", { name: "Account menu" });
    expect(screen.getByText("JD")).toBeInTheDocument();
    expect(screen.queryByText("jane.doe@example.com")).not.toBeInTheDocument();
    // The identity still surfaces inside the opened panel.
    fireEvent.click(trigger);
    expect(screen.getByText("jane.doe@example.com")).toBeInTheDocument();
  });

  it("signs out via the menu (revokes the token server-side)", async () => {
    const fetchMock = stubAuthFetch();
    render(
      <TerpProvider baseUrl="https://api.test">
        <LogInOnMount />
        <UserMenu />
      </TerpProvider>,
    );
    fireEvent.click(await screen.findByRole("button", { name: "Account menu" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Sign out" }));
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(([input]) =>
          (input as Request).url.endsWith("/api/v1/auth/logout"),
        ),
      ).toBe(true),
    );
  });

  it("closes on Escape", async () => {
    stubAuthFetch();
    render(
      <TerpProvider baseUrl="https://api.test">
        <LogInOnMount />
        <UserMenu />
      </TerpProvider>,
    );
    const trigger = await screen.findByRole("button", { name: "Account menu" });
    fireEvent.click(trigger);
    expect(screen.getByRole("menuitem", { name: "Sign out" })).toBeInTheDocument();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("menuitem", { name: "Sign out" })).not.toBeInTheDocument();
  });
});
