// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useEffect } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ResourceList } from "./ResourceList";
import { ApiError } from "./unwrap";
import { TerpProvider, useAuth } from "./TerpProvider";
import type { Resource } from "./useResource";

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "content-type": "application/json" },
  });
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function LogInOnMount() {
  const auth = useAuth();
  useEffect(() => {
    void auth.login({ email: "editor@example.com", password: "pw" });
  }, []);
  return null;
}

function editorFetch() {
  return vi.fn<typeof fetch>(async (input) => {
    const url = (input as Request).url;
    if (url.endsWith("/api/v1/auth/login")) {
      return jsonResponse({ access_token: "t", token_type: "bearer" });
    }
    return jsonResponse({ id: "1", email: "editor@example.com", role_rank: 20, role_name: "editor" });
  });
}

type Row = { id: string; label: string };

function fakeResource(overrides: Partial<Resource<Row, string>> = {}): Resource<Row, string> {
  return {
    items: [],
    loading: false,
    error: null,
    cause: null,
    reload: async () => {},
    create: async () => {},
    mutate: async (operation) => {
      await operation();
    },
    ...overrides,
  };
}

describe("ResourceList", () => {
  it("renders rows and a write-gated create form for a writer, and creates on submit", async () => {
    vi.stubGlobal("fetch", editorFetch());
    const create = vi.fn(async () => {});
    const resource = fakeResource({ items: [{ id: "a", label: "Alpha" }], create });

    render(
      <TerpProvider baseUrl="https://api.test">
        <LogInOnMount />
        <ResourceList
          title="Things"
          resource={resource}
          createPlaceholder="New thing"
          renderItem={(row) => <strong>{row.label}</strong>}
        />
      </TerpProvider>,
    );

    expect(screen.getByRole("heading", { name: "Things" })).toBeInTheDocument();
    expect(screen.getByText("Alpha")).toBeInTheDocument();
    // The create form appears once the editor session loads (it is write-gated by ResourceList).
    await waitFor(() => expect(screen.getByPlaceholderText("New thing")).toBeInTheDocument());

    fireEvent.change(screen.getByPlaceholderText("New thing"), { target: { value: "Beta" } });
    fireEvent.click(screen.getByRole("button", { name: "Add" }));
    await waitFor(() => expect(create).toHaveBeenCalledWith("Beta"));
  });

  it("hides the create form when the resource is read-only (no createPlaceholder)", () => {
    const resource = fakeResource({ items: [], loading: false });
    render(
      <TerpProvider baseUrl="https://api.test">
        <ResourceList title="Empty" resource={resource} renderItem={(row) => <span>{row.label}</span>} />
      </TerpProvider>,
    );
    expect(screen.getByText("Nothing here yet.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Add" })).not.toBeInTheDocument();
  });

  it("surfaces the resource error as an alert", () => {
    const resource = fakeResource({ error: "boom" });
    render(
      <TerpProvider baseUrl="https://api.test">
        <ResourceList title="Errored" resource={resource} renderItem={(row) => <span>{row.label}</span>} />
      </TerpProvider>,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("boom");
  });

  it("prefers the mapped copy for the failure's stable code over the raw message", () => {
    const resource = fakeResource({
      error: "permission denied for tenant",
      cause: new ApiError("permission denied for tenant", {
        code: "permission_denied",
        status: 403,
      }),
    });
    render(
      <TerpProvider baseUrl="https://api.test">
        <ResourceList title="Errored" resource={resource} renderItem={(row) => <span>{row.label}</span>} />
      </TerpProvider>,
    );
    expect(screen.getByRole("alert")).toHaveTextContent(
      "You do not have permission to do this.",
    );
    expect(screen.queryByText("permission denied for tenant")).not.toBeInTheDocument();
  });

  it("keeps the typed draft when a create fails, so the user can retry", async () => {
    vi.stubGlobal("fetch", editorFetch());
    const create = vi.fn(async () => {
      throw new Error("Nope.");
    });
    const resource = fakeResource({ error: "Nope.", create });

    render(
      <TerpProvider baseUrl="https://api.test">
        <LogInOnMount />
        <ResourceList
          title="Things"
          resource={resource}
          createPlaceholder="New thing"
          renderItem={(row) => <strong>{row.label}</strong>}
        />
      </TerpProvider>,
    );

    await waitFor(() => expect(screen.getByPlaceholderText("New thing")).toBeInTheDocument());
    fireEvent.change(screen.getByPlaceholderText("New thing"), { target: { value: "Beta" } });
    fireEvent.click(screen.getByRole("button", { name: "Add" }));
    await waitFor(() => expect(create).toHaveBeenCalledWith("Beta"));

    // A failed create is not swallowed: the error shows and the draft is kept for a retry.
    expect(screen.getByText("Nope.")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("New thing")).toHaveValue("Beta");
  });

  it("renders a custom create form via renderCreate (write-gated), not the default single-field form", async () => {
    vi.stubGlobal("fetch", editorFetch());
    const resource = fakeResource({ items: [] });

    render(
      <TerpProvider baseUrl="https://api.test">
        <LogInOnMount />
        <ResourceList
          title="Things"
          resource={resource}
          renderCreate={() => <span>custom-create-form</span>}
          renderItem={(row) => <span>{row.label}</span>}
        />
      </TerpProvider>,
    );

    // The custom form appears once the writer session loads (ResourceList still applies the gate).
    await waitFor(() => expect(screen.getByText("custom-create-form")).toBeInTheDocument());
    // The default single-field "Add" form is not rendered when renderCreate is supplied.
    expect(screen.queryByRole("button", { name: "Add" })).not.toBeInTheDocument();
  });
});
