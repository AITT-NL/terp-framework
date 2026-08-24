import { describe, expect, it } from "vitest";

import { resolveLayoutDeclaration } from "./layoutDeclaration";

describe("resolveLayoutDeclaration", () => {
  it("returns the options untouched when there is no declaration", () => {
    // The property that makes this opt-in: an app that passes no file is on the exact path it
    // was on before this module existed, so adopting the declaration is a choice rather than a
    // migration. Asserted as identity of VALUES rather than of the object, because the router
    // spreads it either way.
    const explicit = {
      contract: "standard",
      density: "compact",
      navPlacement: "header",
      contentWidth: "measured",
    } as const;
    expect(resolveLayoutDeclaration(undefined, explicit)).toEqual(explicit);
    expect(resolveLayoutDeclaration(undefined, {})).toEqual({});
  });

  it("supplies the contract and every shell key from the file", () => {
    expect(
      resolveLayoutDeclaration(
        {
          contract: "standard",
          shell: { density: "compact", navPlacement: "header", contentWidth: "measured" },
        },
        {},
      ),
    ).toEqual({
      contract: "standard",
      density: "compact",
      navPlacement: "header",
      contentWidth: "measured",
    });
  });

  it("leaves a key the file does not mention to the options", () => {
    // Partial declarations are the normal state, not an edge case: a file that names only the
    // contract is what every scaffolded app has today, and its shell options must keep working.
    expect(
      resolveLayoutDeclaration({ contract: "standard" }, { density: "compact" }),
    ).toEqual({ contract: "standard", density: "compact" });
  });

  it("treats an empty shell object as saying nothing", () => {
    expect(resolveLayoutDeclaration({ shell: {} }, { density: "compact" })).toEqual({
      density: "compact",
    });
  });

  // ---- the three refusals ---------------------------------------------------

  it("refuses a value outside its enum, naming the alternatives", () => {
    // A JSON file is not typechecked. Without this, `"compakt"` reaches the shell as an
    // attribute value nothing styles — a declaration that silently does nothing, which is the
    // failure the declaration exists to remove.
    expect(() =>
      resolveLayoutDeclaration({ shell: { density: "compakt" } }, {}),
    ).toThrow(/shell\.density is "compakt"; expected one of "comfortable", "compact"/);
  });

  it("refuses a key this release does not read, at either level", () => {
    // The cost of the choice, and it is the right way round: an app pinned to a release is told
    // the release cannot honour a key, rather than being told nothing while the key sits in the
    // file looking effective.
    expect(() =>
      resolveLayoutDeclaration({ shell: { sidebarWidth: "20rem" } as never }, {}),
    ).toThrow(/unknown shell key "sidebarWidth"; this release reads/);
    expect(() => resolveLayoutDeclaration({ theme: "dark" } as never, {})).toThrow(
      /unknown key "theme"; this release reads "contract" and "shell"/,
    );
  });

  it("refuses one fact declared twice, and names both sources with their values", () => {
    // Whichever way precedence went, someone editing the losing source would watch their change
    // do nothing — and once the file is what tools edit, the tool becomes the one making a
    // change that does nothing. The message has to carry both values or the reader cannot tell
    // which one they are looking at.
    expect(() =>
      resolveLayoutDeclaration(
        { shell: { density: "compact" } },
        { density: "comfortable" },
      ),
    ).toThrow(/"shell\.density" \(file: "compact", code: "comfortable"\)/);
    expect(() =>
      resolveLayoutDeclaration({ contract: "standard" }, { contract: "bespoke" }),
    ).toThrow(/"contract" \(file: "standard", code: "bespoke"\)/);
  });

  it("reports every conflicting key at once rather than the first", () => {
    // A one-at-a-time refusal turns adopting the file into a guessing loop: fix, re-run, learn
    // about the next one. There are only four keys; name them all.
    let message = "";
    try {
      resolveLayoutDeclaration(
        { contract: "standard", shell: { density: "compact", navPlacement: "header" } },
        { contract: "standard", density: "compact", navPlacement: "header" },
      );
    } catch (error) {
      message = (error as Error).message;
    }
    expect(message).toContain('"contract"');
    expect(message).toContain('"shell.density"');
    expect(message).toContain('"shell.navPlacement"');
  });

  it("refuses a duplicate even when both sources agree", () => {
    // The tempting exemption, declined. Two sources holding the same value today is exactly the
    // state that rots: one of them gets edited, the other does not, and the app silently keeps
    // the stale one. The template shipped precisely this — `layoutContract: "standard"` beside
    // `{"contract": "standard"}` — with "keep the two in sync" written above it.
    expect(() =>
      resolveLayoutDeclaration({ contract: "standard" }, { contract: "standard" }),
    ).toThrow(/both declare/);
  });

  it("names the file rather than the option in every message", () => {
    // The file is the source a person or a tool should edit, so it is the thing a refusal points
    // at. A message naming only the TypeScript option would send the reader to the half this
    // change exists to retire.
    for (const declaration of [
      { theme: "dark" } as never,
      { shell: { density: "nope" } },
      { contract: "standard" },
    ]) {
      expect(() =>
        resolveLayoutDeclaration(declaration, { contract: "standard" }),
      ).toThrow(/frontend\/layout-contract\.json/);
    }
  });
});
