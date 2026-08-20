// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { downloadUrl, saveBlob, useEndpointDownload } from "./download";
import { TerpProvider } from "./TerpProvider";

// Downloading a *generated* artifact (ADR 0096). The two things a hand-rolled version
// gets wrong are what these tests pin: a raw `<a href>` carries no bearer token (so it
// saves an error page under the intended filename), and a raw fetch leaks the object URL.

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  restoreObjectUrl();
});

// jsdom ships no object-URL implementation, so it is installed per test rather than
// stubbed over the global `URL` — replacing that breaks the client's own URL building,
// which is exactly the machinery these tests are here to exercise.
type ObjectUrlHost = { createObjectURL?: (blob: Blob) => string; revokeObjectURL?: (url: string) => void };
const objectUrlHost = URL as unknown as ObjectUrlHost;
const originalCreate = objectUrlHost.createObjectURL;
const originalRevoke = objectUrlHost.revokeObjectURL;

function installObjectUrl(): { revoked: string[] } {
  const revoked: string[] = [];
  objectUrlHost.createObjectURL = () => "blob:x";
  objectUrlHost.revokeObjectURL = (url: string) => void revoked.push(url);
  return { revoked };
}

function restoreObjectUrl(): void {
  objectUrlHost.createObjectURL = originalCreate;
  objectUrlHost.revokeObjectURL = originalRevoke;
}

describe("downloadUrl", () => {
  it("fills path placeholders and appends only the set query keys", () => {
    expect(
      downloadUrl({
        path: "/api/v1/revisions/{revisionId}/evidence",
        filename: "x.json",
        params: { revisionId: "r-1" },
        query: { format: "json", locale: undefined },
      }),
    ).toBe("/api/v1/revisions/r-1/evidence?format=json");
  });

  it("encodes a param rather than splicing it into the path raw", () => {
    expect(downloadUrl({ path: "/api/v1/x/{id}", filename: "f", params: { id: "a/b" } })).toBe(
      "/api/v1/x/a%2Fb",
    );
  });

  it("refuses an unfilled placeholder instead of requesting a literal {id}", () => {
    // Requesting `/revisions/{revisionId}/evidence` would 404 — or, on a permissive
    // route, hand back somebody else's bytes.
    expect(() =>
      downloadUrl({ path: "/api/v1/revisions/{revisionId}/evidence", filename: "x" }),
    ).toThrow(/still contains the placeholder "\{revisionId\}"/);
  });
});

describe("saveBlob", () => {
  it("offers the bytes under the given filename and revokes the object URL", () => {
    const { revoked } = installObjectUrl();
    const clicked: string[] = [];
    const click = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(function (this: HTMLAnchorElement) {
        clicked.push(this.download);
      });

    saveBlob(new Blob(["body"]), "evidence.json");

    expect(clicked).toEqual(["evidence.json"]);
    // Revoked in a `finally`, which is the leak every hand-rolled copy forgets.
    expect(revoked).toEqual(["blob:x"]);
    // ...and nothing is left in the document.
    expect(document.querySelector("a")).toBeNull();
    click.mockRestore();
  });
});

describe("useEndpointDownload", () => {
  function DownloadButton() {
    const download = useEndpointDownload();
    return (
      <button
        type="button"
        onClick={() =>
          void download({
            path: "/api/v1/revisions/{revisionId}/evidence",
            params: { revisionId: "r-1" },
            filename: "evidence.json",
          }).catch((error: unknown) => {
            document.title = (error as Error).message;
          })
        }
      >
        download
      </button>
    );
  }

  it("fetches through the session client, so the request carries the session", async () => {
    const fetchMock = vi.fn<typeof fetch>(
      async () => new Response("bytes", { status: 200, headers: { "content-type": "application/octet-stream" } }),
    );
    vi.stubGlobal("fetch", fetchMock);
    installObjectUrl();
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});

    render(
      <TerpProvider baseUrl="https://api.test">
        <DownloadButton />
      </TerpProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: "download" }));

    // The provider's own boot session-probe is also on this mock, so match the download
    // rather than assuming it is the first request.
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.map((call) => (call[0] as Request).url),
        // Resolved against the client's base URL — the thing a raw <a href> could not do.
      ).toContain("https://api.test/api/v1/revisions/r-1/evidence"),
    );
    click.mockRestore();
  });

  it("rejects on a non-2xx instead of saving the error body under the filename", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>(async () => new Response("nope", { status: 403 })),
    );
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});

    render(
      <TerpProvider baseUrl="https://api.test">
        <DownloadButton />
      </TerpProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: "download" }));

    await waitFor(() => expect(document.title).toMatch(/failed with HTTP 403/));
    // Nothing was handed to the browser: the failure surfaces instead of downloading.
    expect(click).not.toHaveBeenCalled();
    click.mockRestore();
  });
});
