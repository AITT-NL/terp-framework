"""Frontend files emitted by ``terp new module`` for a project with a web app."""

_MODULE_TSX = """\
import { defineModuleManifest } from "@terpjs/contract";

import { __PASCAL__List } from "./__PASCAL__List";
import { moduleTitle } from "./title";

// Dropped in and auto-discovered by renderTerpApp's import.meta.glob — no registration.
export const manifest = defineModuleManifest({
  name: "__NAME__",
  routes: [{ path: "/__NAME__", view: "__PASCAL__List" }],
  nav: [{ label: moduleTitle, to: "/__NAME__" }],
});

export const views = { __PASCAL__List };
"""

_VIEW_TSX = """\
// The `__NAME__` module view — a starting point you own (real React, no hidden DSL). It composes
// the shared <ResourceList> so every module lists + creates the same way, with the write-gate
// applied for you. Wire it to YOUR endpoint once you've generated the typed client:
//
//   uv run terp openapi && npm --prefix frontend run generate   // -> src/api/schema.d.ts
//
//   import { unwrap, useResource, useTerpClient } from "@terpjs/react-core";
//   import type { paths, components } from "../../api/schema";
//   type __MODEL__Read = components["schemas"]["__MODEL__Read"];
//   const client = useTerpClient<paths>();
//   const resource = useResource<__MODEL__Read, string>({
//     list: async () => unwrap(await client.GET("/api/v1/__NAME__/", {})).items,
//     create: async (name) => { unwrap(await client.POST("/api/v1/__NAME__/", { body: { name } })); },
//   });
//   // Give <ResourceList> a localized createPlaceholder when enabling creation.
//
import { OverviewPage, ResourceList, useResource } from "@terpjs/react-core";

import { moduleTitle } from "./title";

export function __PASCAL__List() {
  // Placeholder until you wire the typed client above: an empty, read-only list (compiles pre-codegen).
  const resource = useResource<{ id: string; name: string }, string>({ list: async () => [] });
  return (
    <OverviewPage title={moduleTitle}>
      <ResourceList
        resource={resource}
        renderItem={(item) => <strong>{item.name}</strong>}
      />
    </OverviewPage>
  );
}
"""


_VIEW_TEST_TSX = """// The `__NAME__` module's first frontend test, written in the same breath as the view for
// the same reason the backend test package is (ADR 0119): a module whose default shape has
// no test owes a debt nobody mentioned, and until the vitest seam existed the frontend had
// nowhere to pay it. Run it with `npm --prefix frontend test`; `terp verify` runs it too.
//
// What belongs here is the logic between a type check and a browser -- branches, empty and
// error states, formatters, plural rules, a column definition. The Playwright suite in
// conformance/ still owns "does the whole app work against a real backend".
import { render, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { __PASCAL__List } from "./__PASCAL__List";
import { moduleTitle } from "./title";

describe("__PASCAL__List", () => {
  it("renders its page title", () => {
    const { container } = render(<__PASCAL__List />);
    expect(within(container).getByRole("heading", { name: moduleTitle.message })).toBeInTheDocument();
  });

  it("shows the empty state, and no rows, until the typed client is wired", async () => {
    const { container } = render(<__PASCAL__List />);
    const marker = (name: string) => container.querySelector(`[data-terp="${name}"]`);
    // The starter view lists nothing, so the empty marker is what renders. Once you wire
    // a real endpoint this is the assertion to change -- expect a row, and expect the
    // empty marker to be gone. Asserting BOTH sides is the point: a test that only checks
    // the wanted element is present still passes when the unwanted one is there too.
    await waitFor(() => expect(marker("resource-list-empty")).not.toBeNull());
    expect(marker("resource-list-items")).toBeNull();
  });
});
"""


def frontend_files(name: str, pascal: str, model: str) -> dict[str, str]:
    """Render the manifest, shared title, list view and its test for a new module."""
    title = " ".join(word for word in name.split("_") if word).capitalize() or name
    return {
        "title.ts": f'export const moduleTitle = {{ id: "{name}.title", message: "{title}" }};\n',
        "module.tsx": _MODULE_TSX.replace("__PASCAL__", pascal).replace("__NAME__", name),
        f"{pascal}List.tsx": _VIEW_TSX.replace("__PASCAL__", pascal)
        .replace("__MODEL__", model)
        .replace("__NAME__", name),
        f"{pascal}List.test.tsx": _VIEW_TEST_TSX.replace("__PASCAL__", pascal).replace(
            "__NAME__", name
        ),
    }
