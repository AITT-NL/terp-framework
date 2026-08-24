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
import { useNavLink } from "./navLink";

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
    fireEvent.click(screen.getByRole("button", { name: /editor@example\.com/ }));
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
    fireEvent.click(screen.getByRole("button", { name: /editor@example\.com/ }));
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

describe("buildAppRouter — which nav item is current (ADR 0097 §6, amended in 4e)", () => {
  // A nav where one destination is an ancestor of another. This is not a contrived shape: the
  // packaged admin module ships `/admin` and the example app adds `/admin/grants` and
  // `/admin/webhooks` beside it, so every generated app has it.
  const nested: ModuleManifest[] = [
    { name: "home", routes: [{ path: "/", view: "Home" }], nav: [{ label: "Home", to: "/" }] },
    {
      name: "settings",
      routes: [
        { path: "/settings", view: "Settings" },
        { path: "/settings/users", view: "SettingsUsers" },
        { path: "/settings/appearance", view: "SettingsAppearance" },
      ],
      nav: [
        { label: "Settings", to: "/settings" },
        { label: "Members", to: "/settings/users" },
      ],
    },
  ];
  const nestedViews = {
    Home: () => <Page title="Home view">home</Page>,
    Settings: () => <Page title="Settings view">settings</Page>,
    SettingsUsers: () => <Page title="Members view">members</Page>,
    SettingsAppearance: () => <Page title="Appearance view">appearance</Page>,
  };

  async function renderAt(path: string) {
    vi.stubGlobal("fetch", sessionFetch());
    const router = buildAppRouter(nested, {
      views: nestedViews,
      title: "Terp",
      history: createMemoryHistory({ initialEntries: [path] }),
    });
    const result = render(
      <TerpProvider baseUrl="https://api.test">
        <LogInOnMount />
        <RouterProvider router={router} />
      </TerpProvider>,
    );
    await waitFor(() =>
      expect(document.querySelector('[data-terp="appshell-nav"] a')).not.toBeNull(),
    );
    return result;
  }

  /** Every nav link the shell rendered that claims to be the current page. */
  function currentLinks(): string[] {
    return [...document.querySelectorAll('[data-terp="appshell-nav"] a[aria-current="page"]')].map(
      (a) => a.getAttribute("href") ?? "",
    );
  }

  it("names exactly one current item where a per-link predicate names two", async () => {
    // The defect. The router decides `isActive` per link with no knowledge of siblings, and
    // before 4e the adapter left every item prefix-matching — so at /settings/users BOTH
    // /settings and /settings/users carried aria-current="page", both painted, and a screen
    // reader announced two current pages.
    await renderAt("/settings/users");
    await waitFor(() => expect(currentLinks()).toEqual(["/settings/users"]));
  });

  it("keeps the ancestor current on a page that is not itself a nav item", async () => {
    // The other half, and why per-item `exact` is not the fix: /settings/appearance is a real
    // route with no nav entry, so making /settings exact would leave the sidebar with nothing
    // current at all.
    await renderAt("/settings/appearance");
    await waitFor(() => expect(currentLinks()).toEqual(["/settings"]));
  });

  it("does not let the root item claim a page it does not own", async () => {
    // `/` prefixes every path as a string. The adapter used to work around that with a
    // hand-written `exact: item.to === "/"`; the predicate matches on segments instead, so the
    // workaround is gone and the behaviour is unchanged.
    await renderAt("/settings");
    await waitFor(() => expect(currentLinks()).toEqual(["/settings"]));
  });

  it("keeps the router from volunteering a second current item", async () => {
    // The mechanism, asserted directly rather than through its effect. `data-status` is the one
    // attribute only the router writes, so it shows what the router thought independently of
    // what the shell told it. With activeOptions.exact it can only agree.
    await renderAt("/settings/users");
    await waitFor(() =>
      expect(
        document.querySelectorAll('[data-terp="appshell-nav"] a[data-status="active"]'),
      ).toHaveLength(1),
    );
  });
});

describe("AppShell without activePath", () => {
  it("claims nothing when nobody tells it where it is", async () => {
    // The absent-prop half of the density idiom. A bare shell must not invent a current item —
    // and the nine workbench specimens depend on this, because they supply aria-current from
    // their own renderLink and would otherwise fight the shell.
    const { AppShell } = await import("./AppShell");
    render(
      <AppShell
        title="Terp"
        nav={[{ label: "Notes", to: "/notes" }]}
        renderLink={(item, children, { active }) => (
          <a href={item.to} aria-current={active ? "page" : undefined}>
            {children}
          </a>
        )}
      >
        <p>body</p>
      </AppShell>,
    );
    expect(document.querySelectorAll('[aria-current="page"]')).toHaveLength(0);
  });
});

describe("buildAppRouter — the shell's navigation subscription", () => {
  it("keeps the published link renderer stable across a navigation", async () => {
    // A gate for a fix, not for a feature. Reading the pathname makes `Shell` re-render on every
    // navigation, where before it re-rendered only when the session changed. `Outlet` is
    // memoised with no props, so a plain re-render stops at that boundary — but a CONTEXT VALUE
    // punches through a memo bailout, and this value is used AS A COMPONENT (Breadcrumbs and
    // HubCard render it through useNavLink). An unstable identity therefore remounts every
    // in-app link in the tree on each navigation, which is worse than the re-render it looks
    // like. The assertion is reference equality, because that is the actual contract.
    vi.stubGlobal("fetch", sessionFetch());
    const seen: unknown[] = [];
    function Probe() {
      seen.push(useNavLink());
      return null;
    }
    const probeManifests: ModuleManifest[] = [
      {
        name: "home",
        routes: [
          { path: "/", view: "Home" },
          { path: "/notes", view: "NotesList" },
        ],
        nav: [
          { label: "Home", to: "/" },
          { label: "Notes", to: "/notes" },
        ],
      },
    ];
    const router = buildAppRouter(probeManifests, {
      views: {
        Home: () => (
          <Page title="Home view">
            <Probe />
          </Page>
        ),
        NotesList: () => (
          <Page title="Notes view">
            <Probe />
          </Page>
        ),
      },
      title: "Terp",
      history: createMemoryHistory({ initialEntries: ["/"] }),
    });

    render(
      <TerpProvider baseUrl="https://api.test">
        <LogInOnMount />
        <RouterProvider router={router} />
      </TerpProvider>,
    );
    await waitFor(() => expect(seen.length).toBeGreaterThan(0));
    const before = seen.at(-1);

    await router.navigate({ to: "/notes" });
    await waitFor(() =>
      expect(screen.getByRole("heading", { name: "Notes view" })).toBeInTheDocument(),
    );

    expect(seen.at(-1)).toBe(before);
    expect(new Set(seen).size).toBe(1);
  });
});

describe("buildAppRouter — a declared permission gates the ROUTE, not just the link", () => {
  // The asymmetry this exists to prevent: hiding a nav link while leaving its route reachable by
  // URL is not a weaker form of authorization, it is the appearance of one. `role` has never had
  // that gap — it is declared on both NavItem and ModuleRoute — and `permission` does not get to
  // introduce it. The mutation that motivated this test (gate the route on `role` alone) left the
  // whole suite green.
  const gated: ModuleManifest[] = [
    {
      name: "billing",
      routes: [{ path: "/export", view: "Export", permission: "billing.export" }],
      nav: [{ label: "Export", to: "/export", permission: "billing.export" }],
    },
  ];
  const gatedViews = { Export: () => <Page title="Export view">export body</Page> };

  function sessionWithPermissions(permissions: string[]) {
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
        permissions,
      });
    });
  }

  async function renderWith(permissions: string[]) {
    vi.stubGlobal("fetch", sessionWithPermissions(permissions));
    const router = buildAppRouter(gated, {
      views: gatedViews,
      title: "Terp",
      history: createMemoryHistory({ initialEntries: ["/export"] }),
    });
    render(
      <TerpProvider baseUrl="https://api.test">
        <LogInOnMount />
        <RouterProvider router={router} />
      </TerpProvider>,
    );
  }

  it("renders the view when the grant is held", async () => {
    await renderWith(["billing.export"]);
    await waitFor(() =>
      expect(screen.getByRole("heading", { name: "Export view" })).toBeInTheDocument(),
    );
    expect(screen.getByRole("link", { name: "Export" })).toBeInTheDocument();
  });

  it("refuses the route when the grant is missing, even though the rank clears", async () => {
    // rank 20 clears every role floor this manifest declares — the ONLY thing withheld is the
    // named grant, so a route gated on `role` alone would render the page in full.
    await renderWith([]);
    await waitFor(() =>
      expect(screen.getByText("You do not have access to this page.")).toBeInTheDocument(),
    );
    expect(screen.queryByRole("heading", { name: "Export view" })).not.toBeInTheDocument();
    // ...and the link is gone too, which is the half that was already working.
    expect(screen.queryByRole("link", { name: "Export" })).not.toBeInTheDocument();
  });
});

describe("buildAppRouter navGroups", () => {
  it("passes the app's declared groups through to the shell", async () => {
    // The pass-through is a hand-written enumeration of option names, and nothing covered it:
    // `navPlacement`, `contentWidth` and `density` all reach the shell through the same list and
    // no test asserts any of them arrives. So every other gate on groups can be green while the
    // one line that carries them to the shell is missing, and every app using the sanctioned
    // entry point gets nothing. Mutation: delete `navGroups={options.navGroups}` from the
    // AppShell element, and the labelled list loses its name.
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

    const router = buildAppRouter(
      [
        {
          name: "notes",
          routes: [{ path: "/notes", view: "NotesList" }],
          nav: [{ label: "Notes", to: "/notes", group: "work" }],
        },
      ],
      {
        views: { NotesList: views.NotesList },
        title: "Terp",
        navGroups: [{ id: "work", label: "Werkruimte" }],
        history: createMemoryHistory({ initialEntries: ["/notes"] }),
      },
    );

    render(
      <TerpProvider baseUrl="https://api.test">
        <LogInOnMount />
        <RouterProvider router={router} />
      </TerpProvider>,
    );

    await waitFor(() =>
      expect(screen.getByRole("heading", { name: "Notes view" })).toBeInTheDocument(),
    );
    // Asserted by accessible NAME, which is the only form that survives both a dropped
    // attribute and a dangling IDREF — see AppShell.test.tsx for why no lane catches either.
    expect(screen.getByRole("list", { name: "Werkruimte" })).toBeInTheDocument();
  });

  it("carries a DECLARED density all the way to the shell root", async () => {
    // The gap the two comments above name, closed for the key that arrives by a different
    // route. `density` reaches the shell through the same hand-written enumeration, and now it
    // can also come from the app's checked-in layout-contract.json — so there are two ways for
    // it to go missing and this covers the new one end to end: file -> resolver -> AppShell
    // prop -> rendered attribute.
    //
    // Mutations, both red: change `density={layout.density}` back to `options.density` in the
    // AppShell element (the resolver runs and its answer is thrown away), or drop
    // `density: options.density` from the resolver call (the option path dies instead).
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

    const router = buildAppRouter(
      [{ name: "notes", routes: [{ path: "/notes", view: "NotesList" }] }],
      {
        views: { NotesList: views.NotesList },
        title: "Terp",
        layout: { shell: { density: "compact" } },
        history: createMemoryHistory({ initialEntries: ["/notes"] }),
      },
    );

    render(
      <TerpProvider baseUrl="https://api.test">
        <LogInOnMount />
        <RouterProvider router={router} />
      </TerpProvider>,
    );

    await waitFor(() =>
      expect(screen.getByRole("heading", { name: "Notes view" })).toBeInTheDocument(),
    );
    expect(document.querySelector('[data-terp="appshell"]')).toHaveAttribute(
      "data-density",
      "compact",
    );
  });

  it("carries DECLARED groups all the way to the rendered navigation", async () => {
    // The array key end to end: file -> resolver -> AppShell prop -> the list's accessible name.
    // The sibling test above proves the option path and this proves the file path, because they
    // are two different lines and either can go missing on its own.
    //
    // The empty label is the interesting half. The document spells "render no label at all" as
    // `""` and NavGroup spells it `null`, so the resolver maps between them — and a resolver
    // that passed `""` straight through would give the shell a labelled list whose name is the
    // empty string, which is a list with no accessible name at all and no error anywhere.
    //
    // Mutations, all red: `navGroups={options.navGroups}` in the AppShell element, dropping
    // `navGroups: options.navGroups` from the resolver call, or removing the `"" -> null` map.
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

    const router = buildAppRouter(
      [
        {
          name: "notes",
          routes: [
            { path: "/notes", view: "NotesList" },
            { path: "/pinned", view: "NotesList" },
          ],
          nav: [
            { label: "Notes", to: "/notes", group: "work" },
            { label: "Pinned", to: "/pinned", group: "quiet" },
          ],
        },
      ],
      {
        views: { NotesList: views.NotesList },
        title: "Terp",
        layout: {
          shell: {
            // Declared in the OPPOSITE order to the one they must render in. Written the
            // obvious way round first, and the ordering assertion below was then vacuous:
            // with the sort key dropped every group ties at 0 and the stable sort keeps
            // declaration order, which was already the answer being asserted. Only a
            // declaration order the sort has to undo can observe the sort.
            navGroups: [
              { id: "work", label: "Werkruimte", order: 2 },
              { id: "quiet", label: "", order: 1 },
            ],
          },
        },
        history: createMemoryHistory({ initialEntries: ["/notes"] }),
      },
    );

    render(
      <TerpProvider baseUrl="https://api.test">
        <LogInOnMount />
        <RouterProvider router={router} />
      </TerpProvider>,
    );

    await waitFor(() =>
      expect(screen.getByRole("heading", { name: "Notes view" })).toBeInTheDocument(),
    );
    expect(screen.getByRole("list", { name: "Werkruimte" })).toBeInTheDocument();
    // Exactly ONE group label element, which is what proves the `"" -> null` map ran. This
    // assertion was written the wrong way first — comparing the lists' `aria-label` and
    // `aria-labelledby` ATTRIBUTES against `""` — and the mutation walked straight past it,
    // because an unmapped `""` does not produce an empty attribute. It produces a label element
    // containing nothing and an `aria-labelledby` pointing at it, so the list claims a name and
    // has none: a defect no attribute check and no role-name query can see, since a list with
    // an empty name and a list with no name are indistinguishable to both. Counting the label
    // elements is the form that sees it.
    expect(document.querySelectorAll('[data-terp="appshell-nav-group-label"]')).toHaveLength(1);
    // And the declared sort key put the unlabelled group first: `order: 1` against `order: 2`,
    // rather than whichever order they happened to render in. `getAllByRole` is document order.
    const first = screen.getAllByRole("list")[0]!;
    expect(first.getAttribute("aria-labelledby")).toBeNull();
  });

  it("refuses the app's declaration and its options declaring one fact twice", () => {
    // Compose time, beside the duplicate-group refusal below and for the same reason: an
    // authoring error with no legitimate transient form. The message names both sources
    // because the reader otherwise cannot tell which value they are looking at.
    expect(() =>
      buildAppRouter([], {
        views: {},
        title: "Terp",
        layoutContract: "standard",
        layout: { contract: "standard" },
      }),
    ).toThrow(/both declare "contract" \(file: "standard", code: "standard"\)/);
    expect(() =>
      buildAppRouter([], {
        views: {},
        title: "Terp",
        layout: { shell: { density: "compakt" as "compact" } },
      }),
    ).toThrow(/shell\.density is "compakt"/);
  });

  it("refuses a duplicate group id when the router is composed", () => {
    // An authoring error with no legitimate transient form, so it is refused once here rather
    // than absorbed on every render. Deliberately NOT symmetrical with an item naming an
    // undeclared group, which is the normal state of an app mid-adoption and falls open.
    expect(() =>
      buildAppRouter([], {
        views: {},
        title: "Terp",
        navGroups: [
          { id: "work", label: "Werkruimte" },
          { id: "work", label: "Weer werkruimte" },
        ],
      }),
    ).toThrow(/duplicate id\(s\): work/);
  });

  it("does not refuse an item naming a group nobody declared", () => {
    // The counterpart to the row above, and the reason the throw is narrow: a module ships on
    // its own schedule, so an undeclared id is ordinary rather than wrong. The link must still
    // be reachable. Mutation: widen the composition check to unreferenced/undeclared ids and
    // this throws.
    expect(() =>
      buildAppRouter(
        [
          {
            name: "notes",
            routes: [{ path: "/notes", view: "NotesList" }],
            nav: [{ label: "Notes", to: "/notes", group: "not-declared-yet" }],
          },
        ],
        { views: { NotesList: views.NotesList }, title: "Terp", navGroups: [] },
      ),
    ).not.toThrow();
  });
});
