import { afterEach, describe, expect, it, vi } from "vitest";

import { createAuthClient } from "./createAuthClient";

function jsonResponse(): Response {
  return new Response("{}", {
    status: 200,
    headers: { "content-type": "application/json" },
  });
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("createAuthClient", () => {
  it("omits the Authorization header when there is no token", async () => {
    const fetchMock = vi.fn<typeof fetch>(async () => jsonResponse());
    vi.stubGlobal("fetch", fetchMock);

    const client = createAuthClient("https://api.test", () => null);
    await client.GET("/api/v1/me/", {});

    const request = fetchMock.mock.calls[0][0] as Request;
    expect(request.headers.get("Authorization")).toBeNull();
    expect(request.credentials).toBe("include");
  });

  it("attaches the live bearer token, reflecting a post-login change", async () => {
    const fetchMock = vi.fn<typeof fetch>(async () => jsonResponse());
    vi.stubGlobal("fetch", fetchMock);

    let token: string | null = null;
    const client = createAuthClient("https://api.test", () => token);

    await client.GET("/api/v1/me/", {});
    expect((fetchMock.mock.calls[0][0] as Request).headers.get("Authorization")).toBeNull();

    token = "abc123";
    await client.GET("/api/v1/me/", {});
    expect((fetchMock.mock.calls[1][0] as Request).headers.get("Authorization")).toBe(
      "Bearer abc123",
    );
  });

  it("refreshes and retries once on a 401 to an authenticated request", async () => {
    const fetchMock = vi.fn<typeof fetch>(async () => {
      if (fetchMock.mock.calls.length === 1) {
        return new Response("{}", { status: 401 });
      }
      return jsonResponse();
    });
    vi.stubGlobal("fetch", fetchMock);
    const onUnauthorized = vi.fn();
    const refreshAccessToken = vi.fn(async () => "new-token");
    const client = createAuthClient("https://api.test", () => "old-token", {
      refreshAccessToken,
      onUnauthorized,
    });

    await client.GET("/api/v1/me/", {});

    expect(refreshAccessToken).toHaveBeenCalledOnce();
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect((fetchMock.mock.calls[0][0] as Request).headers.get("Authorization")).toBe(
      "Bearer old-token",
    );
    expect((fetchMock.mock.calls[1][0] as Request).headers.get("Authorization")).toBe(
      "Bearer new-token",
    );
    expect(onUnauthorized).not.toHaveBeenCalled();
  });

  it("coalesces concurrent 401s into one refresh call", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const auth = (input as Request).headers.get("Authorization");
      if (auth === "Bearer old-token") {
        return new Response("{}", { status: 401 });
      }
      return jsonResponse();
    });
    vi.stubGlobal("fetch", fetchMock);
    let resolveRefresh!: (token: string) => void;
    const refreshAccessToken = vi.fn(
      () => new Promise<string>((resolve) => {
        resolveRefresh = resolve;
      }),
    );
    const client = createAuthClient("https://api.test", () => "old-token", {
      refreshAccessToken,
      onUnauthorized: vi.fn(),
    });

    const first = client.GET("/api/v1/me/", {});
    const second = client.GET("/api/v1/me/", {});
    await vi.waitFor(() => expect(refreshAccessToken).toHaveBeenCalledOnce());
    resolveRefresh("fresh-token");
    await Promise.all([first, second]);

    expect(refreshAccessToken).toHaveBeenCalledOnce();
    const freshRetries = fetchMock.mock.calls.filter(
      ([input]) => (input as Request).headers.get("Authorization") === "Bearer fresh-token",
    );
    expect(freshRetries).toHaveLength(2);
  });

  it("clears the session when a 401 cannot be refreshed", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>(async () => new Response("{}", { status: 401 })),
    );
    const onUnauthorized = vi.fn();
    const client = createAuthClient("https://api.test", () => "tok", {
      refreshAccessToken: vi.fn(async () => null),
      onUnauthorized,
    });

    await client.GET("/api/v1/me/", {});
    expect(onUnauthorized).toHaveBeenCalledOnce();
  });

  it("clears the session when the replayed request is also rejected with 401", async () => {
    // Refresh succeeds but the subject was revoked between refresh and replay: the replay
    // 401 must still clear the session instead of leaving a signed-in shell over empty data.
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>(async () => new Response("{}", { status: 401 })),
    );
    const onUnauthorized = vi.fn();
    const client = createAuthClient("https://api.test", () => "tok", {
      refreshAccessToken: vi.fn(async () => "fresh-token"),
      onUnauthorized,
    });

    await client.GET("/api/v1/me/", {});
    expect(onUnauthorized).toHaveBeenCalledOnce();
  });

  it("does not refresh auth endpoints themselves", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>(async () => new Response("{}", { status: 401 })),
    );
    const refreshAccessToken = vi.fn(async () => "new-token");
    const onUnauthorized = vi.fn();
    const client = createAuthClient("https://api.test", () => "tok", {
      refreshAccessToken,
      onUnauthorized,
    });

    await client.POST("/api/v1/auth/logout", {});
    expect(refreshAccessToken).not.toHaveBeenCalled();
    expect(onUnauthorized).not.toHaveBeenCalled();
  });

  it("does not clear the session on a 401 without a token (a bad-credentials login)", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>(async () => new Response("{}", { status: 401 })),
    );
    const onUnauthorized = vi.fn();
    const client = createAuthClient("https://api.test", () => null, { onUnauthorized });

    await client.POST("/api/v1/auth/login", { body: { email: "x", password: "y" } });
    expect(onUnauthorized).not.toHaveBeenCalled();
  });

  it("does not clear the session on a successful authenticated request", async () => {
    vi.stubGlobal("fetch", vi.fn<typeof fetch>(async () => jsonResponse()));
    const onUnauthorized = vi.fn();
    const client = createAuthClient("https://api.test", () => "tok", { onUnauthorized });

    await client.GET("/api/v1/me/", {});
    expect(onUnauthorized).not.toHaveBeenCalled();
  });
});
