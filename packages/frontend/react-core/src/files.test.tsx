// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { FileUpload, useFileDownload, type FileMeta } from "./files";
import { TerpProvider } from "./TerpProvider";

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

const STORED: FileMeta = {
  id: "f-1",
  filename: "report.txt",
  content_type: "text/plain",
  size: 5,
  sha256: "abc",
  owner_id: null,
  version: 1,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function stubFetch(handler: (request: Request) => Promise<Response | null>) {
  vi.stubGlobal(
    "fetch",
    vi.fn<typeof fetch>(async (input) => {
      const request = input as Request;
      if (request.url.endsWith("/api/v1/auth/refresh")) return json({}, 401);
      return (await handler(request)) ?? json({}, 404);
    }),
  );
}

describe("FileUpload", () => {
  it("uploads the picked file as multipart/form-data and reports the metadata", async () => {
    stubFetch(async (request) => {
      if (request.url.endsWith("/api/v1/files/") && request.method === "POST") {
        // The client must send multipart/form-data with the browser-set boundary,
        // carrying the picked file under the backend's `file` field.
        expect(request.headers.get("content-type")).toMatch(/^multipart\/form-data/);
        const form = await request.clone().formData();
        expect(form.get("file")).not.toBeNull();
        return json(STORED, 201);
      }
      return null;
    });
    const onUploaded = vi.fn();

    const { container } = render(
      <TerpProvider baseUrl="https://api.test">
        <FileUpload onUploaded={onUploaded} />
      </TerpProvider>,
    );

    expect(screen.getByRole("button", { name: "Upload file" })).toBeInTheDocument();
    const input = container.querySelector('input[type="file"]');
    expect(input).not.toBeNull();
    fireEvent.change(input as HTMLInputElement, {
      target: { files: [new File(["hello"], "report.txt", { type: "text/plain" })] },
    });

    await waitFor(() => expect(onUploaded).toHaveBeenCalledWith(STORED));
  });

  it("reports a failed upload through onError", async () => {
    stubFetch(async (request) => {
      if (request.url.endsWith("/api/v1/files/") && request.method === "POST") {
        return json({ detail: "File too large", code: "file_too_large" }, 413);
      }
      return null;
    });
    const onUploaded = vi.fn();
    const onError = vi.fn();

    const { container } = render(
      <TerpProvider baseUrl="https://api.test">
        <FileUpload onUploaded={onUploaded} onError={onError} />
      </TerpProvider>,
    );

    fireEvent.change(container.querySelector('input[type="file"]') as HTMLInputElement, {
      target: { files: [new File(["x"], "big.bin")] },
    });

    await waitFor(() => expect(onError).toHaveBeenCalled());
    expect(onUploaded).not.toHaveBeenCalled();
  });
});

describe("useFileDownload", () => {
  it("fetches the content through the client and saves it as a named download", async () => {
    stubFetch(async (request) => {
      if (request.url.endsWith("/api/v1/files/f-1/content")) {
        return new Response("hello", {
          status: 200,
          headers: { "content-type": "application/octet-stream" },
        });
      }
      return null;
    });
    const objectUrls: Blob[] = [];
    const urlWithObjectUrls = URL as typeof URL & {
      createObjectURL?: (blob: Blob) => string;
      revokeObjectURL?: (url: string) => void;
    };
    urlWithObjectUrls.createObjectURL = (blob: Blob) => {
      objectUrls.push(blob);
      return "blob:mock";
    };
    urlWithObjectUrls.revokeObjectURL = () => {};
    const clicked = vi.fn();
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(clicked);

    function Download() {
      const download = useFileDownload();
      return (
        <button type="button" onClick={() => void download({ id: "f-1", filename: "report.txt" })}>
          Download
        </button>
      );
    }

    render(
      <TerpProvider baseUrl="https://api.test">
        <Download />
      </TerpProvider>,
    );

    fireEvent.click(screen.getByRole("button", { name: "Download" }));
    await waitFor(() => expect(clicked).toHaveBeenCalled());
    expect(await objectUrls[0]?.text()).toBe("hello");
  });
});
