// @vitest-environment jsdom
import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { TerpProvider } from "./TerpProvider";

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  window.history.replaceState({}, "", "/");
});

interface HeldRequest {
  url: string;
  answer: (response: Response) => void;
  fail: (reason: unknown) => void;
}

/** A fetch that holds every request until the test answers it. */
function heldFetch() {
  const held: HeldRequest[] = [];
  const fetchMock = vi.fn<typeof fetch>(
    (input) =>
      new Promise<Response>((answer, fail) => {
        held.push({ url: (input as Request).url, answer, fail });
      }),
  );
  vi.stubGlobal("fetch", fetchMock);
  return { fetchMock, held };
}

/**
 * Mounts a provider, waits for its first boot request, and unmounts it with that request
 * still out. The returned spy counts reads of `window.event` from then on: React reads it to
 * schedule every state update made outside an event, and it is the read that throws when the
 * answer arrives after a test environment has removed `window`.
 */
async function unmountDuringBoot(held: HeldRequest[]) {
  const { unmount } = render(
    <TerpProvider baseUrl="https://api.test">
      <span>app</span>
    </TerpProvider>,
  );
  await vi.waitFor(() => expect(held).toHaveLength(1));
  unmount();
  return vi.spyOn(window, "event", "get");
}

/** Lets everything an answer sets off run to its end. */
function settle(): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, 0));
}

describe("a provider unmounted while its boot check is out", () => {
  it("does nothing with a check that was never answered", async () => {
    const { held } = heldFetch();
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const event = await unmountDuringBoot(held);

    held[0].fail(new TypeError("Failed to fetch"));
    await settle();

    expect(event).not.toHaveBeenCalled();
    // The "did not answer" warning is about an app that is still on the screen.
    expect(warn).not.toHaveBeenCalled();
  });

  it("asks for no user when the check restores a session", async () => {
    const { fetchMock, held } = heldFetch();
    const event = await unmountDuringBoot(held);

    held[0].answer(json({ access_token: "restored", token_type: "bearer" }));
    await settle();

    expect(event).not.toHaveBeenCalled();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(held[0].url).toMatch(/\/api\/v1\/auth\/refresh$/);
  });

  it("finishes no SSO landing", async () => {
    window.history.replaceState({}, "", "/auth/callback/dex?code=c1&state=s1");
    const { fetchMock, held } = heldFetch();
    const event = await unmountDuringBoot(held);

    held[0].answer(json({ access_token: "sso-token", token_type: "bearer" }));
    await settle();

    expect(event).not.toHaveBeenCalled();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(held[0].url).toMatch(/\/api\/v1\/oidc\/dex\/callback$/);
  });
});
