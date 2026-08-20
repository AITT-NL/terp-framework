// @vitest-environment jsdom
import { RouterProvider, createMemoryHistory } from "@tanstack/react-router";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useEffect, useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ModuleManifest } from "@terpjs/contract";

import {
  buildAppRouter,
  useRouteParam,
  useRouteParams,
  useRouteSearch,
  useTerpNavigate,
} from "./router";
import { Page } from "./Page";
import { TerpProvider, useAuth } from "./TerpProvider";

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "content-type": "application/json" },
  });
}

/** The login + session-probe fetch a routed test needs to reach a guarded view. */
function sessionFetch() {
  return vi.fn<typeof fetch>(async (input) => {
    const url = (input as Request).url;
    if (url.endsWith("/api/v1/auth/login")) {
      return jsonResponse({ access_token: "t", token_type: "bearer" });
    }
    return jsonResponse({
      id: "1",
      email: "editor@example.com",
      role_rank: 20,
      role_name: "editor",
    });
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

const manifests: ModuleManifest[] = [
  {
    name: "home",
    routes: [{ path: "/", view: "Home" }],
    nav: [],
  },
  {
    name: "notes",
    routes: [{ path: "/notes", view: "NotesList" }],
    nav: [{ label: "Notes", to: "/notes" }],
  },
  {
    name: "users",
    routes: [{ path: "/users", view: "UsersList", role: "admin" }],
    nav: [{ label: "Users", to: "/users", role: "admin" }],
  },
];

const views = {
  Home: () => <Page title="Home view">home body</Page>,
  NotesList: () => <Page title="Notes view">notes body</Page>,
  UsersList: () => <Page title="Users view">users body</Page>,
};

describe("buildAppRouter", () => {
  it("renders the matched view in the shell with a role-filtered nav", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const url = (input as Request).url;
      if (url.endsWith("/api/v1/auth/login")) {
        return jsonResponse({ access_token: "t", token_type: "bearer" });
      }
      return jsonResponse({ id: "1", email: "editor@example.com", role_rank: 20, role_name: "editor" });
    });
    vi.stubGlobal("fetch", fetchMock);

    const router = buildAppRouter(manifests, {
      views,
      title: "Terp",
      history: createMemoryHistory({ initialEntries: ["/notes"] }),
    });

    render(
      <TerpProvider baseUrl="https://api.test">
        <LogInOnMount />
        <RouterProvider router={router} />
      </TerpProvider>,
    );

    await waitFor(() =>
      expect(screen.getByRole("heading", { name: "Notes view" })).toBeInTheDocument(),
    );
    // Editor (rank 20) sees the Notes nav but not the admin-only Users nav.
    expect(screen.getByRole("link", { name: "Notes" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Users" })).not.toBeInTheDocument();
  });

  it("mounts a parameterised route in BOTH spellings the contract documents", async () => {
    // The manifest is stack-agnostic and documents `:id`; TanStack wants `$id`. Passing
    // the documented spelling through untranslated built a route that never matched —
    // and nothing caught it: not the lint, not typecheck, not the build. Pin both.
    for (const [path, entry] of [
      ["/things/:thingId", "/things/abc"],
      ["/legacy/$thingId", "/legacy/abc"],
    ] as const) {
      vi.stubGlobal(
        "fetch",
        vi.fn<typeof fetch>(async (input) => {
          const url = (input as Request).url;
          if (url.endsWith("/api/v1/auth/login")) {
            return jsonResponse({ access_token: "t", token_type: "bearer" });
          }
          return jsonResponse({
            id: "1",
            email: "editor@example.com",
            role_rank: 20,
            role_name: "editor",
          });
        }),
      );
      const router = buildAppRouter([{ name: "things", routes: [{ path, view: "Thing" }] }], {
        views: { Thing: () => <Page title="Thing view">thing body</Page> },
        title: "Terp",
        history: createMemoryHistory({ initialEntries: [entry] }),
      });
      render(
        <TerpProvider baseUrl="https://api.test">
          <LogInOnMount />
          <RouterProvider router={router} />
        </TerpProvider>,
      );
      await waitFor(() =>
        expect(screen.getByRole("heading", { name: "Thing view" })).toBeInTheDocument(),
      );
      cleanup();
    }
  });

  it("useRouteParam reads a declared param and refuses an undeclared name, fail closed", async () => {
    // buildAppRouter realises routes at runtime, so TanStack's type registry cannot
    // check a param name for any app — useRouteParam is the sanctioned read: the
    // declared param comes back, an undeclared name throws a directive error instead
    // of silently yielding undefined (the failure mode of the raw `as {...}` cast).
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const url = (input as Request).url;
      if (url.endsWith("/api/v1/auth/login")) {
        return jsonResponse({ access_token: "t", token_type: "bearer" });
      }
      return jsonResponse({ id: "1", email: "editor@example.com", role_rank: 20, role_name: "editor" });
    });
    vi.stubGlobal("fetch", fetchMock);

    function ThingView() {
      const thingId = useRouteParam("thingId");
      return <Page title={`Thing ${thingId}`}>thing body</Page>;
    }
    const router = buildAppRouter(
      [{ name: "things", routes: [{ path: "/things/:thingId", view: "Thing" }], nav: [] }],
      {
        views: { Thing: ThingView },
        title: "Terp",
        history: createMemoryHistory({ initialEntries: ["/things/abc"] }),
      },
    );
    render(
      <TerpProvider baseUrl="https://api.test">
        <LogInOnMount />
        <RouterProvider router={router} />
      </TerpProvider>,
    );
    await waitFor(() =>
      expect(screen.getByRole("heading", { name: "Thing abc" })).toBeInTheDocument(),
    );
    cleanup();

    function WrongParamView() {
      const nope = useRouteParam("thisParamDoesNotExist");
      return <Page title={`Wrong ${nope}`}>wrong body</Page>;
    }
    const wrongRouter = buildAppRouter(
      [{ name: "things", routes: [{ path: "/things/:thingId", view: "Thing" }], nav: [] }],
      {
        views: { Thing: WrongParamView },
        title: "Terp",
        history: createMemoryHistory({ initialEntries: ["/things/abc"] }),
      },
    );
    render(
      <TerpProvider baseUrl="https://api.test">
        <LogInOnMount />
        <RouterProvider router={wrongRouter} />
      </TerpProvider>,
    );
    // The view throws before it can render; the screen never shows the wrong body.
    await waitFor(() => expect(console.error).toHaveBeenCalled());
    expect(screen.queryByRole("heading", { name: /Wrong/ })).not.toBeInTheDocument();
  });

  it("useRouteParams reads a whole declared route's params, and refuses a stale one", async () => {
    // The exact read (ADR 0092): keyed by the manifest path, every param that path
    // declares must be present. A generated table that no longer matches the manifest
    // therefore fails closed naming the param, instead of leaking undefined into a request.
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    vi.stubGlobal("fetch", sessionFetch());

    function PairView() {
      const { spaceId, itemId } = useRouteParams("/spaces/:spaceId/items/:itemId");
      return <Page title={`${spaceId}/${itemId}`}>pair body</Page>;
    }
    render(
      <TerpProvider baseUrl="https://api.test">
        <LogInOnMount />
        <RouterProvider
          router={buildAppRouter(
            [{ name: "spaces", routes: [{ path: "/spaces/:spaceId/items/:itemId", view: "Pair" }] }],
            {
              views: { Pair: PairView },
              title: "Terp",
              history: createMemoryHistory({ initialEntries: ["/spaces/s1/items/i9"] }),
            },
          )}
        />
      </TerpProvider>,
    );
    await waitFor(() =>
      expect(screen.getByRole("heading", { name: "s1/i9" })).toBeInTheDocument(),
    );
    cleanup();

    // The same view under a route that declares only one of the two params.
    render(
      <TerpProvider baseUrl="https://api.test">
        <LogInOnMount />
        <RouterProvider
          router={buildAppRouter(
            [{ name: "spaces", routes: [{ path: "/spaces/:spaceId", view: "Pair" }] }],
            {
              views: { Pair: PairView },
              title: "Terp",
              history: createMemoryHistory({ initialEntries: ["/spaces/s1"] }),
            },
          )}
        />
      </TerpProvider>,
    );
    await waitFor(() => expect(console.error).toHaveBeenCalled());
    expect(screen.queryByRole("heading", { name: /s1/ })).not.toBeInTheDocument();
  });

  it("useTerpNavigate navigates by the manifest's path spelling, carrying params", async () => {
    // The manifest spells a param `:id`; TanStack wants `$id`. useTerpNavigate takes the
    // manifest spelling (what the generated table is keyed by) and translates, so a caller
    // never holds two spellings — and the params ride along.
    vi.stubGlobal("fetch", sessionFetch());

    function ListView() {
      const navigate = useTerpNavigate();
      return (
        <Page title="Things view">
          <button type="button" onClick={() => void navigate({ to: "/things/:thingId", params: { thingId: "abc" } })}>
            open abc
          </button>
        </Page>
      );
    }
    function DetailView() {
      return <Page title={`Thing ${useRouteParam("thingId")}`}>thing body</Page>;
    }
    render(
      <TerpProvider baseUrl="https://api.test">
        <LogInOnMount />
        <RouterProvider
          router={buildAppRouter(
            [
              {
                name: "things",
                routes: [
                  { path: "/things", view: "ThingsList" },
                  { path: "/things/:thingId", view: "ThingDetail" },
                ],
              },
            ],
            {
              views: { ThingsList: ListView, ThingDetail: DetailView },
              title: "Terp",
              history: createMemoryHistory({ initialEntries: ["/things"] }),
            },
          )}
        />
      </TerpProvider>,
    );

    fireEvent.click(await screen.findByRole("button", { name: "open abc" }));
    await waitFor(() =>
      expect(screen.getByRole("heading", { name: "Thing abc" })).toBeInTheDocument(),
    );
  });

  it("useRouteSearch reads the route's declared query-string keys, absent ones as undefined", async () => {
    // The hole this closes: a list screen's filters live in the query string, so before
    // search was declarable EVERY filtered screen left the typed seam for the router's own
    // useSearch — losing path and param checking too, on the majority of screens.
    vi.stubGlobal("fetch", sessionFetch());

    function ListView() {
      const { status, page } = useRouteSearch("/records");
      return (
        <Page title="Records">
          <p>{`status=${status ?? "-"} page=${page ?? "-"}`}</p>
        </Page>
      );
    }
    render(
      <TerpProvider baseUrl="https://api.test">
        <LogInOnMount />
        <RouterProvider
          router={buildAppRouter(
            [
              {
                name: "records",
                routes: [{ path: "/records", view: "List", search: ["status", "page"] }],
              },
            ],
            {
              views: { List: ListView },
              title: "Terp",
              history: createMemoryHistory({ initialEntries: ["/records?status=open"] }),
            },
          )}
        />
      </TerpProvider>,
    );

    // `status` came from the URL; `page` is declared but unset, which is `undefined` rather
    // than a missing key a screen has to guard.
    expect(await screen.findByText("status=open page=-")).toBeInTheDocument();
  });

  it("useRouteSearch returns only declared keys, so a stray URL key cannot reach a screen", async () => {
    vi.stubGlobal("fetch", sessionFetch());

    function ListView() {
      const search = useRouteSearch("/records") as Record<string, string | undefined>;
      return <Page title="Records">{`keys=${Object.keys(search).join(",") || "none"}`}</Page>;
    }
    render(
      <TerpProvider baseUrl="https://api.test">
        <LogInOnMount />
        <RouterProvider
          router={buildAppRouter(
            [{ name: "records", routes: [{ path: "/records", view: "List", search: ["status"] }] }],
            {
              views: { List: ListView },
              title: "Terp",
              history: createMemoryHistory({
                initialEntries: ["/records?status=open&smuggled=yes"],
              }),
            },
          )}
        />
      </TerpProvider>,
    );

    expect(await screen.findByText("keys=status")).toBeInTheDocument();
  });

  it("useRouteSearch refuses a path the router never mounted, naming what is mounted", async () => {
    vi.stubGlobal("fetch", sessionFetch());

    function ListView() {
      // A silently empty bag would hand the screen `undefined` for every key it asked
      // for, which reads as "no filters applied" — the failure this refusal replaces.
      let message = "no refusal";
      try {
        (useRouteSearch as (path: string) => unknown)("/typo");
      } catch (error) {
        message = (error as Error).message;
      }
      return <Page title="Records">{message}</Page>;
    }
    render(
      <TerpProvider baseUrl="https://api.test">
        <LogInOnMount />
        <RouterProvider
          router={buildAppRouter([{ name: "records", routes: [{ path: "/records", view: "List" }] }], {
            views: { List: ListView },
            title: "Terp",
            history: createMemoryHistory({ initialEntries: ["/records"] }),
          })}
        />
      </TerpProvider>,
    );

    expect(await screen.findByText(/is not a mounted route/)).toBeInTheDocument();
    expect(screen.getByText(/mounted: \/records/)).toBeInTheDocument();
  });

  it("useTerpNavigate carries search onto the URL, and clearing a key removes it", async () => {
    // Replace, not merge (ADR 0096): clearing a filter means sending the key as
    // undefined, and a merge would keep the old value — so "clear" would not clear.
    vi.stubGlobal("fetch", sessionFetch());

    function ListView() {
      const navigate = useTerpNavigate();
      const { status } = useRouteSearch("/records");
      return (
        <Page title="Records">
          <p>{`status=${status ?? "-"}`}</p>
          <button
            type="button"
            onClick={() => void navigate({ to: "/records", search: { status: "open" } })}
          >
            filter open
          </button>
          <button
            type="button"
            onClick={() => void navigate({ to: "/records", search: { status: undefined } })}
          >
            clear
          </button>
        </Page>
      );
    }
    render(
      <TerpProvider baseUrl="https://api.test">
        <LogInOnMount />
        <RouterProvider
          router={buildAppRouter(
            [{ name: "records", routes: [{ path: "/records", view: "List", search: ["status"] }] }],
            {
              views: { List: ListView },
              title: "Terp",
              history: createMemoryHistory({ initialEntries: ["/records"] }),
            },
          )}
        />
      </TerpProvider>,
    );

    fireEvent.click(await screen.findByRole("button", { name: "filter open" }));
    await waitFor(() => expect(screen.getByText("status=open")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "clear" }));
    await waitFor(() => expect(screen.getByText("status=-")).toBeInTheDocument());
  });

  it("a second composed router does not inherit the first one's declared searches", async () => {
    // The declarations are published per router through a context, not a module-level
    // table: a shared table would let one app embedding another (or one test process
    // composing two) read routes it never mounted.
    vi.stubGlobal("fetch", sessionFetch());
    buildAppRouter([{ name: "a", routes: [{ path: "/a", view: "V", search: ["x"] }] }], {
      views: { V: () => <Page title="A">a</Page> },
      title: "Terp",
      history: createMemoryHistory({ initialEntries: ["/a"] }),
    });

    function BView() {
      let message = "no refusal";
      try {
        (useRouteSearch as (path: string) => unknown)("/a");
      } catch (error) {
        message = (error as Error).message;
      }
      return <Page title="B">{message}</Page>;
    }
    render(
      <TerpProvider baseUrl="https://api.test">
        <LogInOnMount />
        <RouterProvider
          router={buildAppRouter([{ name: "b", routes: [{ path: "/b", view: "V" }] }], {
            views: { V: BView },
            title: "Terp",
            history: createMemoryHistory({ initialEntries: ["/b"] }),
          })}
        />
      </TerpProvider>,
    );

    expect(await screen.findByText(/"\/a" is not a mounted route/)).toBeInTheDocument();
  });

  it("gives breadcrumbs and hub cards the router's link without being asked", async () => {
    // A crumb rendered without `renderLink` used to fall back to a raw <a href>: a full
    // page reload, silently, with nothing to catch it. Inside a Terp router the default
    // is the router's own Link, so the trail navigates client-side.
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>(async (input) => {
        const url = (input as Request).url;
        if (url.endsWith("/api/v1/auth/login")) {
          return jsonResponse({ access_token: "t", token_type: "bearer" });
        }
        return jsonResponse({ id: "1", email: "editor@example.com", role_rank: 20, role_name: "editor" });
      }),
    );
    const router = buildAppRouter(
      [
        {
          name: "notes",
          routes: [
            { path: "/notes", view: "NotesList" },
            { path: "/notes/:noteId", view: "NoteDetail" },
          ],
          nav: [],
        },
      ],
      {
        views: {
          NotesList: () => <Page title="Notes view">notes body</Page>,
          NoteDetail: () => (
            <Page title="Note view" breadcrumbs={[{ label: "Notes", to: "/notes" }]}>
              note body
            </Page>
          ),
        },
        title: "Terp",
        history: createMemoryHistory({ initialEntries: ["/notes/1"] }),
      },
    );

    render(
      <TerpProvider baseUrl="https://api.test">
        <LogInOnMount />
        <RouterProvider router={router} />
      </TerpProvider>,
    );

    const crumb = await screen.findByRole("link", { name: "Notes" });
    fireEvent.click(crumb);
    await waitFor(() =>
      expect(screen.getByRole("heading", { name: "Notes view" })).toBeInTheDocument(),
    );
  });

  it("navigates home through the product brand", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const url = (input as Request).url;
      if (url.endsWith("/api/v1/auth/login")) {
        return jsonResponse({ access_token: "t", token_type: "bearer" });
      }
      return jsonResponse({ id: "1", email: "editor@example.com", role_rank: 20, role_name: "editor" });
    });
    vi.stubGlobal("fetch", fetchMock);
    const router = buildAppRouter(manifests, {
      views,
      title: "Terp",
      history: createMemoryHistory({ initialEntries: ["/notes"] }),
    });

    render(
      <TerpProvider baseUrl="https://api.test">
        <LogInOnMount />
        <RouterProvider router={router} />
      </TerpProvider>,
    );
    await screen.findByRole("heading", { name: "Notes view" });
    const brand = screen.getByRole("link", { name: "Terp" });
    expect(brand).toHaveAttribute("data-terp", "appshell-brand");
    fireEvent.click(brand);
    await screen.findByRole("heading", { name: "Home view" });
  });

  it("shows a sign-out control for the signed-in user and revokes the token on click", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const url = (input as Request).url;
      if (url.endsWith("/api/v1/auth/login")) {
        return jsonResponse({ access_token: "t", token_type: "bearer" });
      }
      if (url.endsWith("/api/v1/auth/logout")) {
        return new Response(null, { status: 204 });
      }
      return jsonResponse({ id: "1", email: "editor@example.com", role_rank: 20, role_name: "editor" });
    });
    vi.stubGlobal("fetch", fetchMock);

    const router = buildAppRouter(manifests, {
      views,
      title: "Terp",
      history: createMemoryHistory({ initialEntries: ["/notes"] }),
    });

    render(
      <TerpProvider baseUrl="https://api.test">
        <LogInOnMount />
        <RouterProvider router={router} />
      </TerpProvider>,
    );

    // The sidebar's user menu shows the signed-in user's email; sign-out lives inside it.
    await waitFor(() => expect(screen.getByText("editor@example.com")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Account menu" }));
    // Clicking sign-out revokes the token server-side (ADR 0031).
    fireEvent.click(screen.getByRole("menuitem", { name: "Sign out" }));
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(([input]) =>
          (input as Request).url.endsWith("/api/v1/auth/logout"),
        ),
      ).toBe(true),
    );
  });

  it("rejects a route whose view id was not collected", () => {
    expect(() =>
      buildAppRouter(
        [{ name: "missing", routes: [{ path: "/missing", view: "MissingView" }] }],
        {
          views: {},
          title: "Terp",
          history: createMemoryHistory({ initialEntries: ["/missing"] }),
        },
      ),
    ).toThrow(/missing view/);
  });

  it("refuses a routed view that skips the page archetypes (fail closed)", async () => {
    // The runtime half of the page-archetype control: a view rendering bare markup (no Page /
    // OverviewPage / DetailPage / HubPage in its tree) is refused after mount, not shown.
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const url = (input as Request).url;
      if (url.endsWith("/api/v1/auth/login")) {
        return jsonResponse({ access_token: "t", token_type: "bearer" });
      }
      return jsonResponse({ id: "1", email: "editor@example.com", role_rank: 20, role_name: "editor" });
    });
    vi.stubGlobal("fetch", fetchMock);

    const router = buildAppRouter(
      [{ name: "bare", routes: [{ path: "/bare", view: "BareView" }], nav: [] }],
      {
        views: { BareView: () => <h1>Bare view</h1> },
        title: "Terp",
        history: createMemoryHistory({ initialEntries: ["/bare"] }),
      },
    );

    render(
      <TerpProvider baseUrl="https://api.test">
        <LogInOnMount />
        <RouterProvider router={router} />
      </TerpProvider>,
    );

    // The bare view mounts, the post-mount check bites, and the screen is torn down.
    await waitFor(() =>
      expect(screen.queryByRole("heading", { name: "Bare view" })).not.toBeInTheDocument(),
    );
  });

  it("accepts a view whose page archetype lands on a follow-up commit", async () => {
    // A view may frame one commit late (e.g. a lazy inner component resolving); the grace
    // window tolerates it while a view that never frames is still refused.
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const url = (input as Request).url;
      if (url.endsWith("/api/v1/auth/login")) {
        return jsonResponse({ access_token: "t", token_type: "bearer" });
      }
      return jsonResponse({ id: "1", email: "editor@example.com", role_rank: 20, role_name: "editor" });
    });
    vi.stubGlobal("fetch", fetchMock);

    function LateFramedView() {
      const [ready, setReady] = useState(false);
      useEffect(() => setReady(true), []);
      return ready ? <Page title="Late view">late body</Page> : null;
    }

    const router = buildAppRouter(
      [{ name: "late", routes: [{ path: "/late", view: "LateView" }], nav: [] }],
      {
        views: { LateView: LateFramedView },
        title: "Terp",
        history: createMemoryHistory({ initialEntries: ["/late"] }),
      },
    );

    render(
      <TerpProvider baseUrl="https://api.test">
        <LogInOnMount />
        <RouterProvider router={router} />
      </TerpProvider>,
    );

    await waitFor(() =>
      expect(screen.getByRole("heading", { name: "Late view" })).toBeInTheDocument(),
    );
  });

  it("mounts the built-in profile page; the user menu's Settings opens it", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const url = (input as Request).url;
      if (url.endsWith("/api/v1/auth/login")) {
        return jsonResponse({ access_token: "t", token_type: "bearer" });
      }
      return jsonResponse({ id: "1", email: "editor@example.com", role_rank: 20, role_name: "editor" });
    });
    vi.stubGlobal("fetch", fetchMock);

    const router = buildAppRouter(manifests, {
      views,
      title: "Terp",
      history: createMemoryHistory({ initialEntries: ["/notes"] }),
    });

    render(
      <TerpProvider baseUrl="https://api.test">
        <LogInOnMount />
        <RouterProvider router={router} />
      </TerpProvider>,
    );

    await waitFor(() => expect(screen.getByText("editor@example.com")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Account menu" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Settings" }));

    await waitFor(() =>
      expect(screen.getByRole("heading", { level: 1, name: "Profile" })).toBeInTheDocument(),
    );
    // The identity comes from the server-validated session (email + role), framed by a Page.
    expect(screen.getByText("editor (20)")).toBeInTheDocument();
  });

  it("lets an app manifest claim /profile over the built-in page", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const url = (input as Request).url;
      if (url.endsWith("/api/v1/auth/login")) {
        return jsonResponse({ access_token: "t", token_type: "bearer" });
      }
      return jsonResponse({ id: "1", email: "editor@example.com", role_rank: 20, role_name: "editor" });
    });
    vi.stubGlobal("fetch", fetchMock);

    const router = buildAppRouter(
      [{ name: "custom", routes: [{ path: "/profile", view: "CustomProfile" }], nav: [] }],
      {
        views: { CustomProfile: () => <Page title="Custom profile">custom body</Page> },
        title: "Terp",
        history: createMemoryHistory({ initialEntries: ["/profile"] }),
      },
    );

    render(
      <TerpProvider baseUrl="https://api.test">
        <LogInOnMount />
        <RouterProvider router={router} />
      </TerpProvider>,
    );

    await waitFor(() =>
      expect(screen.getByRole("heading", { name: "Custom profile" })).toBeInTheDocument(),
    );
  });
});
