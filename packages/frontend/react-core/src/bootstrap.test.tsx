// @vitest-environment jsdom
import { cleanup, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { defineModuleManifest } from "@terp/contract";

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
});
