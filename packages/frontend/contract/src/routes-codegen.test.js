import { spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { afterEach, describe, expect, it } from "vitest";

import {
  canonicalPath,
  extractRoutePaths,
  generateRouteTable,
  moduleFiles,
  paramNamesOf,
  renderRouteTable,
  run,
} from "./routes-codegen.js";

// The route-types generator (ADR 0092): it turns manifest route literals into the
// declaration file that makes a wrong path or param name a typecheck error. Its two
// contracts are determinism (a committed artifact that drift-checks) and failing closed
// (never emit a partial table, because a missing route reads as a *wrong* route).

const temporaries = [];

afterEach(() => {
  for (const directory of temporaries.splice(0)) {
    fs.rmSync(directory, { recursive: true, force: true });
  }
});

/** An app tree with one module per entry: `{ notes: "<module.tsx source>" }`. */
function appWithModules(modules) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "terp-routes-"));
  temporaries.push(root);
  for (const [name, source] of Object.entries(modules)) {
    const directory = path.join(root, "src", "modules", name);
    fs.mkdirSync(directory, { recursive: true });
    fs.writeFileSync(path.join(directory, "module.tsx"), source, "utf8");
  }
  return root;
}

function manifest(routes) {
  return [
    'import { defineModuleManifest } from "@terpjs/contract";',
    "export const manifest = defineModuleManifest({",
    '  name: "x",',
    `  routes: [${routes}],`,
    "});",
  ].join("\n");
}

describe("param extraction from a path", () => {
  it("reads both dialects and canonicalises to the manifest spelling", () => {
    expect(paramNamesOf("/records/:recordId")).toEqual(["recordId"]);
    expect(paramNamesOf("/records/$recordId")).toEqual(["recordId"]);
    expect(paramNamesOf("/spaces/:spaceId/items/:itemId")).toEqual(["spaceId", "itemId"]);
    expect(paramNamesOf("/records")).toEqual([]);
    // The packaged admin manifest uses the TanStack spelling; the table is keyed the
    // stack-agnostic way, so both spellings land on one key.
    expect(canonicalPath("/admin/users/$userId")).toBe("/admin/users/:userId");
    expect(canonicalPath("/records/:recordId")).toBe("/records/:recordId");
  });
});

describe("extraction from a module manifest", () => {
  it("reads every route path a manifest declares", () => {
    const { paths, problems } = extractRoutePaths(
      manifest('{ path: "/records", view: "List" }, { path: "/records/:recordId", view: "Detail" }'),
      "module.tsx",
    );
    expect(problems).toEqual([]);
    expect(paths).toEqual(["/records", "/records/:recordId"]);
  });

  it("reads a manifest declared as a property value, not only `export const manifest`", () => {
    // The packaged admin area's shape: defineModuleManifest(...) inside an object literal.
    const { paths, problems } = extractRoutePaths(
      [
        'import { defineModuleManifest } from "@terpjs/contract";',
        "export const adminModule = {",
        '  manifest: defineModuleManifest({ name: "a", routes: [{ path: "/admin", view: "Hub" }] }),',
        "};",
      ].join("\n"),
      "module.tsx",
    );
    expect(problems).toEqual([]);
    expect(paths).toEqual(["/admin"]);
  });

  it("refuses a path that is not a plain string literal, naming file and line", () => {
    const { paths, problems } = extractRoutePaths(
      manifest("{ path: `/records/${base}`, view: \"List\" }"),
      "src/modules/records/module.tsx",
    );
    expect(paths).toEqual([]);
    expect(problems).toHaveLength(1);
    expect(problems[0]).toContain("src/modules/records/module.tsx:4");
    expect(problems[0]).toContain("not a plain string literal");
  });

  it("refuses a spread route and a non-literal routes array", () => {
    const spread = extractRoutePaths(manifest("...shared"), "module.tsx");
    expect(spread.problems[0]).toContain("not an object literal");

    const dynamic = extractRoutePaths(
      [
        'import { defineModuleManifest } from "@terpjs/contract";',
        "export const manifest = defineModuleManifest({ name: \"x\", routes: buildRoutes() });",
      ].join("\n"),
      "module.tsx",
    );
    expect(dynamic.problems[0]).toContain("not an array literal");
  });

  it("refuses a module slot with no manifest call at all", () => {
    const { problems } = extractRoutePaths("export const views = {};", "module.tsx");
    expect(problems[0]).toContain("no defineModuleManifest");
  });

  it("refuses a route with no path", () => {
    const { problems } = extractRoutePaths(manifest('{ view: "List" }'), "module.tsx");
    expect(problems[0]).toContain("declares no `path`");
  });
});

describe("rendering the declaration file", () => {
  it("is deterministic: deduped, sorted, LF-only, one trailing newline", () => {
    const first = renderRouteTable(["/b", "/a", "/b"]);
    const second = renderRouteTable(["/b", "/b", "/a"]);
    expect(first).toBe(second);
    expect(first).not.toContain("\r");
    expect(first.endsWith("}\n")).toBe(true);
    expect(first.indexOf('"/a"')).toBeLessThan(first.indexOf('"/b"'));
  });

  it("types a parameterised route's params and leaves a paramless route empty", () => {
    const rendered = renderRouteTable(["/records/:recordId", "/records", "/s/:a/i/:b"]);
    expect(rendered).toContain('"/records": Record<never, never>;');
    expect(rendered).toContain('"/records/:recordId": { recordId: string };');
    expect(rendered).toContain('"/s/:a/i/:b": { a: string; b: string };');
  });

  it("augments the react-core table so the app's own types pick it up", () => {
    const rendered = renderRouteTable(["/"]);
    expect(rendered).toContain('declare module "@terpjs/react-core"');
    expect(rendered).toContain("interface TerpRouteTable");
    // A module augmentation only applies from a file that IS a module.
    expect(rendered).toContain('import "@terpjs/react-core";');
  });
});

describe("generating across an app's module slots", () => {
  it("merges every slot and dedupes a path two modules claim", () => {
    const root = appWithModules({
      home: manifest('{ path: "/", view: "Home" }'),
      notes: manifest('{ path: "/", view: "NotesList" }, { path: "/notes/:noteId", view: "Note" }'),
    });
    const rendered = generateRouteTable(path.join(root, "src", "modules"));
    expect(rendered.match(/"\/":/g)).toHaveLength(1);
    expect(rendered).toContain('"/notes/:noteId": { noteId: string };');
  });

  it("refuses the whole run when any one slot resists static reading", () => {
    const root = appWithModules({
      good: manifest('{ path: "/good", view: "G" }'),
      bad: manifest("{ path: ROUTES.bad, view: \"B\" }"),
    });
    expect(() => generateRouteTable(path.join(root, "src", "modules"))).toThrow(
      /refused to emit a partial route table/,
    );
  });

  it("refuses an app with no module slots rather than emitting an empty table", () => {
    const root = appWithModules({});
    expect(() => generateRouteTable(path.join(root, "src", "modules"))).toThrow(/No module slots/);
  });

  it("finds module.ts as well as module.tsx, in a stable order", () => {
    const root = appWithModules({ b: manifest('{ path: "/b", view: "B" }') });
    const plain = path.join(root, "src", "modules", "a");
    fs.mkdirSync(plain, { recursive: true });
    fs.writeFileSync(path.join(plain, "module.ts"), manifest('{ path: "/a", view: "A" }'), "utf8");
    expect(moduleFiles(path.join(root, "src", "modules")).map((file) => path.basename(path.dirname(file)))).toEqual(["a", "b"]);
  });
});

describe("the CLI's write and --check modes", () => {
  it("writes the table, then reports it unchanged on a second run", () => {
    const root = appWithModules({ home: manifest('{ path: "/", view: "Home" }') });
    const messages = [];
    const log = (message) => messages.push(message);

    expect(run([], { cwd: root, log })).toBe(0);
    const written = fs.readFileSync(path.join(root, "src", "routes.gen.d.ts"), "utf8");
    expect(written).toContain('"/": Record<never, never>;');
    expect(messages[0]).toContain("wrote");

    expect(run([], { cwd: root, log })).toBe(0);
    expect(messages[1]).toContain("unchanged");
  });

  it("--check passes on a current file and refuses a stale or missing one, with the fix", () => {
    const root = appWithModules({ home: manifest('{ path: "/", view: "Home" }') });
    const messages = [];
    const log = (message) => messages.push(message);

    // Missing: the app never generated.
    expect(run(["--check"], { cwd: root, log })).toBe(1);
    expect(messages.at(-1)).toContain("missing");
    expect(messages.at(-1)).toContain("run routes");

    run([], { cwd: root, log: () => {} });
    expect(run(["--check"], { cwd: root, log })).toBe(0);
    expect(messages.at(-1)).toContain("is current");

    // Stale: a manifest gained a route after the last generate.
    fs.writeFileSync(
      path.join(root, "src", "modules", "home", "module.tsx"),
      manifest('{ path: "/", view: "Home" }, { path: "/late/:lateId", view: "Late" }'),
      "utf8",
    );
    expect(run(["--check"], { cwd: root, log })).toBe(1);
    expect(messages.at(-1)).toContain("stale");
  });

  it("the shipped bin actually runs the generator (a bin that no-ops would fake every check)", () => {
    // Regression guard for a real bug: the module used to self-execute behind an
    // `import.meta.url === process.argv[1]` guard, which does NOT hold when npm invokes
    // the bin through its shim — so `terp-routes --check` did nothing and exited 0. A
    // drift check that passes because it never ran is worse than no check, and only
    // spawning the actual executable can catch it.
    const bin = path.resolve(fileURLToPath(new URL(".", import.meta.url)), "..", "bin", "terp-routes.js");
    const root = appWithModules({ home: manifest('{ path: "/", view: "Home" }') });

    const written = spawnSync(process.execPath, [bin], { cwd: root, encoding: "utf8" });
    expect(written.status).toBe(0);
    expect(written.stdout).toContain("wrote");
    expect(fs.existsSync(path.join(root, "src", "routes.gen.d.ts"))).toBe(true);

    const current = spawnSync(process.execPath, [bin, "--check"], { cwd: root, encoding: "utf8" });
    expect(current.status).toBe(0);
    expect(current.stdout).toContain("is current");

    // And it reports a real drift with a non-zero exit, not a silent pass.
    fs.writeFileSync(
      path.join(root, "src", "modules", "home", "module.tsx"),
      manifest('{ path: "/", view: "Home" }, { path: "/added/:addedId", view: "Added" }'),
      "utf8",
    );
    const stale = spawnSync(process.execPath, [bin, "--check"], { cwd: root, encoding: "utf8" });
    expect(stale.status).toBe(1);
    expect(stale.stdout).toContain("stale");

    // A manifest it cannot read statically exits 2 and names the file.
    fs.writeFileSync(
      path.join(root, "src", "modules", "home", "module.tsx"),
      manifest("{ path: ROUTES.home, view: \"Home\" }"),
      "utf8",
    );
    const refused = spawnSync(process.execPath, [bin], { cwd: root, encoding: "utf8" });
    expect(refused.status).toBe(2);
    expect(refused.stderr).toContain("refused to emit a partial route table");
  });

  it("honours --out and --modules-dir, and refuses an unknown argument", () => {
    const root = appWithModules({ home: manifest('{ path: "/", view: "Home" }') });
    expect(run(["--out", "types/routes.d.ts", "--modules-dir", "src/modules"], { cwd: root, log: () => {} })).toBe(0);
    expect(fs.existsSync(path.join(root, "types", "routes.d.ts"))).toBe(true);
    expect(() => run(["--nope"], { cwd: root, log: () => {} })).toThrow(/unknown argument/);
  });
});
