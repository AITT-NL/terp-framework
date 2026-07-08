// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useEffect } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ProfileView } from "./ProfileView";
import { TerpProvider, useAuth } from "./TerpProvider";
import { LOCALE_EN, LOCALE_NL, LocaleProvider } from "./locale";
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

describe("ProfileView", () => {
  it("shows the identity, the preference controls and sign-out, framed by a Page", async () => {
    const fetchMock = stubAuthFetch();
    render(
      <ThemeProvider>
        <LocaleProvider locales={{ en: LOCALE_EN, nl: LOCALE_NL }}>
          <TerpProvider baseUrl="https://api.test">
            <LogInOnMount />
            <ProfileView />
          </TerpProvider>
        </LocaleProvider>
      </ThemeProvider>,
    );

    await waitFor(() =>
      expect(screen.getByRole("heading", { level: 1, name: "Profile" })).toBeInTheDocument(),
    );
    expect(screen.getAllByText("jane.doe@example.com").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("editor (20)")).toBeInTheDocument();
    // The stacked preference controls live here (settings surface).
    expect(screen.getByLabelText("Theme")).toBeInTheDocument();
    expect(screen.getByLabelText("Language")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Sign out" }));
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(([input]) =>
          (input as Request).url.endsWith("/api/v1/auth/logout"),
        ),
      ).toBe(true),
    );
  });

  it("renders nothing while signed out", () => {
    stubAuthFetch();
    render(
      <TerpProvider baseUrl="https://api.test">
        <ProfileView />
      </TerpProvider>,
    );
    expect(screen.queryByRole("heading", { name: "Profile" })).not.toBeInTheDocument();
  });

  it("follows the active locale (Dutch out of the box)", async () => {
    stubAuthFetch();
    window.localStorage.setItem("terp.locale", "nl");
    render(
      <LocaleProvider locales={{ en: LOCALE_EN, nl: LOCALE_NL }}>
        <TerpProvider baseUrl="https://api.test">
          <LogInOnMount />
          <ProfileView />
        </TerpProvider>
      </LocaleProvider>,
    );
    await waitFor(() =>
      expect(screen.getByRole("heading", { level: 1, name: "Profiel" })).toBeInTheDocument(),
    );
    expect(screen.getByRole("button", { name: "Uitloggen" })).toBeInTheDocument();
  });
});
