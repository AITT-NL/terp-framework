import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

import { LAYOUT_CONTRACTS } from "./layoutContract";
import {
  NAV_GROUP_FIELDS,
  NAV_GROUP_REQUIRED,
  SHELL_STRUCTURED_KEYS,
  SHELL_VALUES,
  TOP_LEVEL_KEYS,
} from "./layoutDeclaration";
import { THEMES } from "./themes";

// The published layout vocabulary against the module that enforces it.
//
// `layout.manifest.json` exists so that a tool editing an app's files can offer exactly the keys
// and values THAT APP'S OWN pinned framework will honour. That inversion is the point: an unknown
// key is refused when the router is composed, so a tool working from its own idea of the
// vocabulary can hand an app a file its framework will not start on. Reading the vocabulary out
// of the app's own node_modules removes the guess.
//
// Which makes every drift here a live defect rather than a tidiness problem, and both directions
// fail differently:
//
//   * A key or value the resolver reads and the manifest omits is a choice no tool will ever
//     offer — declarable, documented, and invisible to the audience the file was published for.
//   * A key or value the manifest offers and the resolver does not read is worse: a tool writes
//     it in good faith and the app refuses to start, naming a key the tool was told to use.
//
// The manifest is hand-written rather than generated, for the reason `theme.themes.test.ts` gives
// about the theme union: generating it would need a TypeScript loader in a build step this package
// does not have, and half its content — the titles and descriptions an operator reads — is not
// derivable from the source at all. So the copy stays a copy, and the copy is checked.
//
// What "checked" covers, precisely, because an earlier version of this comment claimed more than
// the assertions delivered: every key at all three levels, every enum, every declared type, every
// emptiness floor, the required pair, the unknown-key refusals, and the export subpath. What it
// does NOT cover is prose — a title or description is asserted present, never compared to
// anything, because there is nothing to compare it to.

interface ManifestProperty {
  type?: string;
  title?: string;
  description?: string;
  enum?: string[];
  properties?: Record<string, ManifestProperty>;
  items?: ManifestProperty;
  required?: string[];
  additionalProperties?: boolean;
  minLength?: number;
}

const manifest: ManifestProperty = JSON.parse(
  readFileSync(new URL("./layout.manifest.json", import.meta.url), "utf-8"),
);

const properties = manifest.properties ?? {};
const shell = properties.shell?.properties ?? {};
const group = shell.navGroups?.items?.properties ?? {};

/** Every property in the document, by the path a refusal would name it with. */
function everyProperty(): [string, ManifestProperty][] {
  return [
    ...Object.entries(properties).map(([key, value]): [string, ManifestProperty] => [key, value]),
    ...Object.entries(shell).map(([key, value]): [string, ManifestProperty] => [
      `shell.${key}`,
      value,
    ]),
    ...Object.entries(group).map(([key, value]): [string, ManifestProperty] => [
      `shell.navGroups.items.${key}`,
      value,
    ]),
  ];
}

describe("the published layout vocabulary", () => {
  it("reads the manifest it is asserting about", () => {
    // Every assertion below compares against something parsed out of the file. A file that
    // failed to parse into the expected shape would compare empty objects and report green,
    // which is the one failure mode a parity test cannot afford.
    expect(Object.keys(properties).length).toBeGreaterThan(2);
    expect(Object.keys(shell).length).toBeGreaterThan(2);
    expect(Object.keys(group).length).toBeGreaterThan(2);
  });

  it("offers exactly the keys the document admits", () => {
    expect(Object.keys(properties).sort()).toEqual([...TOP_LEVEL_KEYS].sort());
  });

  it("offers exactly the keys the shell admits", () => {
    const declared = [...Object.keys(SHELL_VALUES), ...SHELL_STRUCTURED_KEYS];
    expect(Object.keys(shell).sort()).toEqual(declared.sort());
  });

  it("offers exactly the values each shell key accepts", () => {
    for (const [key, values] of Object.entries(SHELL_VALUES)) {
      expect(shell[key]?.enum, `shell.${key}`).toEqual([...values]);
    }
  });

  it("offers every palette this release ships, and no other", () => {
    // Including "system", which is a real thing to declare rather than the absence of one — an
    // absent key leaves whatever was in force alone, this one pins the platform preference.
    expect(properties.defaultTheme?.enum).toEqual([...THEMES]);
  });

  it("offers every layout contract this release knows, and no other", () => {
    // A contract offered here that `buildAppRouter` cannot find is an app that refuses to
    // start with "Unknown layout contract", pointing at a value a tool was told was legal.
    expect(properties.contract?.enum?.slice().sort()).toEqual(Object.keys(LAYOUT_CONTRACTS).sort());
  });

  it("offers exactly the fields a navigation group carries", () => {
    expect(Object.keys(group).sort()).toEqual([...NAV_GROUP_FIELDS].sort());
    // Against the resolver's own list, not against a copy of it written here. Comparing a
    // mirror to a second copy of the thing it mirrors proves nothing about either.
    expect(shell.navGroups?.items?.required?.slice().sort()).toEqual(
      [...NAV_GROUP_REQUIRED].sort(),
    );
  });

  it("refuses an unknown key at every level it has one", () => {
    // The manifest describes a document whose consumer refuses unknown keys at both levels and
    // on a group entry. A manifest that said otherwise would tell a tool it may write anything.
    expect(manifest.additionalProperties).toBe(false);
    expect(properties.shell?.additionalProperties).toBe(false);
    expect(shell.navGroups?.items?.additionalProperties).toBe(false);
  });

  it("gives every property a title and a description", () => {
    // The half of the file no generator could produce, and the reason it is hand-written. A
    // property with neither renders in a form as its own key and nothing else, which for
    // `navPlacement` is a shrug and for `contract` is a choice that can turn a build red.
    for (const [path, property] of everyProperty()) {
      expect(property.title?.trim(), `${path}: title`).toBeTruthy();
      expect(property.description?.trim(), `${path}: description`).toBeTruthy();
    }
  });

  it("declares a type for every property, so a renderer never has to guess", () => {
    for (const [path, property] of everyProperty()) {
      expect(property.type, `${path}: type`).toBeTruthy();
    }
  });

  it("declares the type the resolver actually refuses anything else for", () => {
    // Truthiness was the whole of this check, and truthiness is not a type: with `navGroups`
    // retyped to "object" and `order` to "string" every assertion in this file stayed green,
    // while `resolveNavGroups` refuses a non-array and a non-integer by name. That is exactly
    // the failure the header calls worse — a tool writes `"navGroups": {}` in good faith,
    // reading a type the manifest offered, and the app will not compose.
    expect(shell.navGroups?.type).toBe("array");
    expect(shell.navGroups?.items?.type).toBe("object");
    expect(group.order?.type).toBe("integer");
    expect(group.id?.type).toBe("string");
    expect(group.label?.type).toBe("string");
    for (const key of Object.keys(SHELL_VALUES)) {
      expect(shell[key]?.type, `shell.${key}`).toBe("string");
    }
  });

  it("declares the emptiness floors the resolver refuses, and no others", () => {
    // Each of these is a value the resolver rejects, so a manifest offering it without the
    // floor tells a tool the empty string is legal. And `label` must NOT carry one: the empty
    // label is how the document declares a group that renders no heading, and a floor there
    // would tell a tool to refuse the one way of stating that.
    expect(properties.contract?.minLength).toBe(1);
    expect(properties.defaultTheme?.minLength).toBe(1);
    expect(group.id?.minLength).toBe(1);
    expect(group.label?.minLength).toBeUndefined();
    expect(group.order?.minLength).toBeUndefined();
  });

  it("is reachable by the subpath a consumer imports it from", () => {
    // The file only does its job from inside an app's node_modules, and the only thing that
    // puts it there under a stable name is the package's own export map. A rename that moved
    // the file would leave every gate above green while the published path 404s in the one
    // place the file is read — and this package's own suite reads it by relative URL, so
    // nothing else here would notice.
    const pkg: { exports: Record<string, string> } = JSON.parse(
      readFileSync(new URL("../package.json", import.meta.url), "utf-8"),
    );
    const subpath = pkg.exports["./layout.manifest.json"];
    expect(subpath).toBe("./src/layout.manifest.json");
    expect(
      readFileSync(new URL(`../${subpath!.slice(2)}`, import.meta.url), "utf-8").length,
    ).toBeGreaterThan(0);
  });
});
