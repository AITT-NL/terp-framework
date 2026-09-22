// @vitest-environment jsdom
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { RequireAuth } from "./RequireAuth";
import { BOOT_REQUEST_TIMEOUT_MS, TerpProvider } from "./TerpProvider";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

/**
 * A dead backend used to be indistinguishable from a signed-out visitor, and worse
 * than that: a fetch to a dead proxy target does not fail, it hangs, so the boot
 * refresh never settled, `loading` stayed true and `RequireAuth` rendered its `pending`
 * slot — nothing — for as long as the page stayed open. An empty `#root`, three console
 * messages, zero errors, zero warnings.
 */
describe("a backend that does not answer the boot check", () => {
  it("gives the boot request a deadline, so a hang becomes a failure", async () => {
    // The mechanism, pinned at the wiring: without a signal there is nothing to make a
    // hanging fetch settle, and every assertion below depends on it settling.
    const timeout = vi.spyOn(AbortSignal, "timeout");
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>(async () => new Response("{}", { status: 401 })),
    );

    render(
      <TerpProvider baseUrl="https://api.test">
        <RequireAuth fallback={<span>please-sign-in</span>}>
          <span>app</span>
        </RequireAuth>
      </TerpProvider>,
    );

    await waitFor(() => expect(screen.getByText("please-sign-in")).toBeInTheDocument());
    expect(timeout).toHaveBeenCalledWith(BOOT_REQUEST_TIMEOUT_MS);
    expect(BOOT_REQUEST_TIMEOUT_MS).toBeGreaterThan(0);
  });

  it("says so on the screen instead of offering a sign-in that cannot work", async () => {
    // A rejected fetch is what an aborted one produces, and what a refused connection
    // produces: no answer came back at all.
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>(async () => {
        throw new TypeError("Failed to fetch");
      }),
    );
    vi.spyOn(console, "warn").mockImplementation(() => {});

    render(
      <TerpProvider baseUrl="https://api.test">
        <RequireAuth fallback={<span>please-sign-in</span>}>
          <span>app</span>
        </RequireAuth>
      </TerpProvider>,
    );

    await waitFor(() =>
      expect(screen.getByText(/cannot reach its server/i)).toBeInTheDocument(),
    );
    // Not the login view: a sign-in form that cannot possibly succeed sends the reader
    // to check their own password for a problem that is not theirs.
    expect(screen.queryByText("please-sign-in")).not.toBeInTheDocument();
    expect(screen.queryByText("app")).not.toBeInTheDocument();
  });

  it("is loud in the console too, naming the API it could not reach", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>(async () => {
        throw new TypeError("Failed to fetch");
      }),
    );
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});

    render(
      <TerpProvider baseUrl="https://api.test">
        <RequireAuth fallback={<span>please-sign-in</span>}>
          <span>app</span>
        </RequireAuth>
      </TerpProvider>,
    );

    await waitFor(() => expect(warn).toHaveBeenCalled());
    const message = warn.mock.calls.map((call) => String(call[0])).join("\n");
    expect(message).toContain("https://api.test");
    expect(message).toContain("did not answer");
  });

  it("renders a caller's own unreachable view when it has one", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>(async () => {
        throw new TypeError("Failed to fetch");
      }),
    );
    vi.spyOn(console, "warn").mockImplementation(() => {});

    render(
      <TerpProvider baseUrl="https://api.test">
        <RequireAuth
          fallback={<span>please-sign-in</span>}
          unreachable={<span>our-own-message</span>}
        >
          <span>app</span>
        </RequireAuth>
      </TerpProvider>,
    );

    await waitFor(() => expect(screen.getByText("our-own-message")).toBeInTheDocument());
  });

  it("keeps 'nobody is signed in' a separate answer from 'nobody answered'", async () => {
    // The distinction the old code could not make. A 401 IS an answer, so this must
    // render the login view and never the failure — an assertion that only checked for
    // the failure's absence would pass on a provider that showed nothing at all.
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>(async () => new Response("{}", { status: 401 })),
    );

    render(
      <TerpProvider baseUrl="https://api.test">
        <RequireAuth fallback={<span>please-sign-in</span>}>
          <span>app</span>
        </RequireAuth>
      </TerpProvider>,
    );

    await waitFor(() => expect(screen.getByText("please-sign-in")).toBeInTheDocument());
    expect(screen.queryByText(/cannot reach its server/i)).not.toBeInTheDocument();
  });
});
