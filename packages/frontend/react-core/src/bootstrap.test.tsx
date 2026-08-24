// @vitest-environment jsdom
import { cleanup, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { defineModuleManifest } from "@terpjs/contract";

import { collectModules, renderTerpApp } from "./bootstrap";

afterEach(() => {
  cleanup();
});

const notesModule = {
  manifest: defineModuleManifest({
    name: "notes",
    routes: [{ path: "/", view: "NotesList" }],
    nav: [{ label: "Notes", to: "/" }],
  }),
  views: { NotesList: () => <h1>Notes</h1> },
};

describe("collectModules", () => {
  it("merges manifests and views from module files", () => {
    const { manifests, views } = collectModules({
      "./modules/notes/module.tsx": notesModule,
    });
    expect(manifests.map((manifest) => manifest.name)).toEqual(["notes"]);
    expect(Object.keys(views)).toEqual(["NotesList"]);
  });

  it("rejects a module that does not export manifest/views", () => {
    expect(() => collectModules({ "./modules/bad/module.tsx": {} })).toThrow(/must export/);
  });

  it("rejects duplicate view ids instead of silently overwriting a module", () => {
    expect(() =>
      collectModules({
        "./modules/notes/module.tsx": notesModule,
        "./modules/tasks/module.tsx": {
          manifest: defineModuleManifest({
            name: "tasks",
            routes: [{ path: "/tasks", view: "NotesList" }],
            nav: [{ label: "Tasks", to: "/tasks" }],
          }),
          views: { NotesList: () => <h1>Tasks</h1> },
        },
      }),
    ).toThrow(/exported by more than one module/);
  });
});

describe("renderTerpApp", () => {
  it("mounts the app and shows the login view while signed out", async () => {
    const root = document.createElement("div");
    document.body.appendChild(root);

    renderTerpApp({
      title: "Test",
      modules: { "./modules/notes/module.tsx": notesModule },
      rootElement: root,
    });

    await waitFor(() =>
      expect(screen.getByRole("button", { name: /sign in/i })).toBeInTheDocument(),
    );
    root.remove();
  });

  it("forwards the layout declaration to buildAppRouter", () => {
    // Same shape as the navGroups test below, for the same reason: the forwarding is one line in
    // a hand-written enumeration, and a missing line leaves every gate on the declaration green
    // while the one-call entry point — the one apps actually use — ignores the file entirely.
    //
    // Gated through a refusal only `buildAppRouter` can raise, and that took a second attempt.
    // The first version asserted the resolver's enum refusal — which `renderTerpApp` now raises
    // ITSELF, from its own resolve call, before `buildAppRouter` is reached. So it threw with
    // the forwarding line deleted and reported green: a test that passes with the bug. An
    // UNKNOWN CONTRACT is refused only inside `buildAppRouter`, against its own table, so the
    // throw here observes the one line under test and nothing else.
    //
    // Mutation: delete `layout: options.layout` from the buildAppRouter call, and this stops
    // throwing.
    const root = document.createElement("div");
    document.body.appendChild(root);
    try {
      expect(() =>
        renderTerpApp({
          title: "Test",
          modules: { "./modules/notes/module.tsx": notesModule },
          layout: { contract: "bespoke" },
          rootElement: root,
        }),
      ).toThrow(/Unknown layout contract "bespoke"/);
    } finally {
      root.remove();
    }
  });

  it("opens on the palette the declaration names, and on the option when it does not", async () => {
    // The forwarding tests above gate their line through a THROW, because a signed-out mount
    // renders no shell to read. The palette is the exception and gets the stronger assertion:
    // `ThemeProvider` wraps `RequireAuth`, so it mounts signed out, and the attribute it writes
    // on <html> is the actual observable effect an app ships. A throw here would only prove the
    // file was validated, not that the value reached anything.
    //
    // Mutations, both red, and both by reading NULL rather than "midnight": `"system"` is the
    // provider's default and it REMOVES the attribute, so neither mutation can produce the
    // string. (An earlier version of this comment said the first one reads "system", which is
    // not a value `data-theme` ever holds.) Pass `options.defaultTheme` to `ThemeProvider`
    // instead of `layout.defaultTheme`, or drop `defaultTheme` from the explicit set handed to
    // the resolver, and the corresponding assertion reads null.
    for (const [label, options] of [
      ["from the file", { layout: { defaultTheme: "midnight" } }],
      ["from the option", { defaultTheme: "midnight" as const }],
    ] as const) {
      // A stored choice outranks the default — that is the whole point of a *default* — so the
      // assertion would be about localStorage rather than about the declaration without this.
      window.localStorage.clear();
      document.documentElement.removeAttribute("data-theme");
      const root = document.createElement("div");
      document.body.appendChild(root);
      try {
        renderTerpApp({
          title: "Test",
          modules: { "./modules/notes/module.tsx": notesModule },
          rootElement: root,
          ...options,
        });
        await waitFor(() =>
          expect(
            document.documentElement.getAttribute("data-theme"),
            `${label}: the declared palette must reach <html>`,
          ).toBe("midnight"),
        );
      } finally {
        root.remove();
        document.documentElement.removeAttribute("data-theme");
      }
    }
  });

  it("refuses the palette named in the file and passed as an option", () => {
    // Non-exclusive per ADR 0009 — either source alone is complete, as the test above shows —
    // but not both, and not even when they agree. Reachable only through `renderTerpApp`,
    // because `buildAppRouter` has no palette option to conflict with.
    const root = document.createElement("div");
    document.body.appendChild(root);
    try {
      expect(() =>
        renderTerpApp({
          title: "Test",
          modules: { "./modules/notes/module.tsx": notesModule },
          layout: { defaultTheme: "midnight" },
          defaultTheme: "midnight",
          rootElement: root,
        }),
      ).toThrow(/both declare "defaultTheme" \(file: "midnight", code: "midnight"\)/);
    } finally {
      root.remove();
    }
  });

  it("names every doubly-declared key at once, groups included", async () => {
    // The property the resolver's `conflicts.join("; ")` exists for, asserted through the entry
    // point apps use — and it was broken here. `renderTerpApp` resolves the declaration itself
    // (the palette mounts outside the router) and its explicit set omitted `navGroups`, so a
    // groups conflict was invisible from this side: the author fixed the density conflict,
    // re-ran, and hit a second, different refusal. Mutation: drop `navGroups: options.navGroups`
    // from the resolve call at the top of `renderTerpApp` and this names only the density.
    const root = document.createElement("div");
    document.body.appendChild(root);
    let message = "";
    try {
      renderTerpApp({
        title: "Test",
        modules: { "./modules/notes/module.tsx": notesModule },
        layout: {
          shell: {
            density: "comfortable",
            navGroups: [{ id: "work", label: "Workspace" }],
          },
        },
        density: "compact",
        navGroups: [{ id: "admin", label: "Admin" }],
        rootElement: root,
      });
    } catch (error) {
      message = (error as Error).message;
    } finally {
      root.remove();
    }
    expect(message).toContain('"shell.density"');
    expect(message).toContain('"shell.navGroups"');
  });

  it("refuses the navigation groups named in the file and passed as an option", () => {
    // The array key travelling the same seam as the scalars, end to end: the resolver sees the
    // file, `buildAppRouter` hands the resolved list to the shell, and declaring the groups in
    // both places is one fact declared twice. Named by id, because a list of objects stringified
    // into an error message tells the reader nothing they can match up.
    const root = document.createElement("div");
    document.body.appendChild(root);
    try {
      expect(() =>
        renderTerpApp({
          title: "Test",
          modules: { "./modules/notes/module.tsx": notesModule },
          layout: { shell: { navGroups: [{ id: "work", label: "Workspace" }] } },
          navGroups: [{ id: "admin", label: "Admin" }],
          rootElement: root,
        }),
      ).toThrow(/both declare "shell\.navGroups" \(file: "work", code: "admin"\)/);
    } finally {
      root.remove();
    }
  });

  it("refuses duplicate ids declared in the file, through the router's own check", () => {
    // The check lives in `buildAppRouter` and now reads the RESOLVED list, so this is the proof
    // that a duplicate reaches it from the file and not only from the option. Mutation: point
    // the check back at `options.navGroups` and this stops throwing while the option-side test
    // above stays green.
    const root = document.createElement("div");
    document.body.appendChild(root);
    try {
      expect(() =>
        renderTerpApp({
          title: "Test",
          modules: { "./modules/notes/module.tsx": notesModule },
          layout: {
            shell: {
              navGroups: [
                { id: "work", label: "Workspace" },
                { id: "work", label: "Again" },
              ],
            },
          },
          rootElement: root,
        }),
      ).toThrow(/duplicate id\(s\): work/);
    } finally {
      root.remove();
    }
  });

  it("forwards navGroups to buildAppRouter", () => {
    // `renderTerpApp` hands its options to `buildAppRouter` through a hand-written enumeration of
    // names, and nothing covered it — `navPlacement`, `contentWidth` and `density` all travel that
    // same list with no assertion that any of them arrives. A missing line there leaves every
    // other gate on groups green while the feature does nothing for every app using the one-call
    // entry point, which is the entry point apps actually use.
    //
    // Gated through the duplicate-id refusal rather than through a rendered label, and that is
    // the point of doing it this way: this test mounts the SIGNED-OUT app, so the shell never
    // renders and there is no nav to read. The throw only happens if the option was forwarded, so
    // it observes the one line under test and nothing else. Mutation: delete
    // `navGroups: options.navGroups` from the buildAppRouter call, and this stops throwing.
    const root = document.createElement("div");
    document.body.appendChild(root);
    try {
      expect(() =>
        renderTerpApp({
          title: "Test",
          modules: { "./modules/notes/module.tsx": notesModule },
          navGroups: [
            { id: "work", label: "Werkruimte" },
            { id: "work", label: "Weer werkruimte" },
          ],
          rootElement: root,
        }),
      ).toThrow(/duplicate id\(s\): work/);
    } finally {
      root.remove();
    }
  });
});
