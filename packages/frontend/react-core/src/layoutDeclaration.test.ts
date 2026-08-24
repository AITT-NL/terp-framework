import { describe, expect, it } from "vitest";

import { resolveLayoutDeclaration } from "./layoutDeclaration";
import { THEMES } from "./themes";

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
    ).toThrow(
      /unknown shell key "sidebarWidth"; this release reads "density", "navPlacement", "contentWidth", "navGroups"/,
    );
    // "theme", not "defaultTheme": a near-miss of a real key is the shape a hand-edit
    // produces, and it is what the unknown-key refusal is for.
    expect(() => resolveLayoutDeclaration({ theme: "dark" } as never, {})).toThrow(
      /unknown key "theme"; this release reads "contract", "defaultTheme", "shell"/,
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
    // about the next one. Every conflicting key is named at once — how many keys there are is
    // TOP_LEVEL_KEYS plus SHELL_KEYS, not a number written down here, which was already stale
    // one commit after it was written.
    let message = "";
    try {
      resolveLayoutDeclaration(
        {
          contract: "standard",
          defaultTheme: "midnight",
          shell: { density: "compact", navPlacement: "header" },
        },
        {
          contract: "standard",
          defaultTheme: "dark",
          density: "compact",
          navPlacement: "header",
        },
      );
    } catch (error) {
      message = (error as Error).message;
    }
    expect(message).toContain('"contract"');
    expect(message).toContain('"defaultTheme"');
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

  // ---- the palette the app opens on ---------------------------------------- #

  it("supplies the palette from the file, narrowed to the published list", () => {
    // The point of the key: which palette an app opens on used to be reachable only by editing
    // that app's own code, which put it out of reach of anything that edits files.
    expect(resolveLayoutDeclaration({ defaultTheme: "midnight" }, {})).toEqual({
      defaultTheme: "midnight",
    });
  });

  it("accepts every palette the framework publishes, and nothing else", () => {
    // Asserted over the published array rather than over a hand-picked few, because the failure
    // this prevents is a SHIPPED palette an app cannot name — which a spot-check of three would
    // not catch. `THEMES` is the same list the theme control offers, held to the compiled
    // stylesheet by theme.themes.test.ts, so this closes the loop from stylesheet to file.
    expect(THEMES.length).toBeGreaterThan(3);
    for (const theme of THEMES) {
      expect(resolveLayoutDeclaration({ defaultTheme: theme }, {})).toEqual({
        defaultTheme: theme,
      });
    }
  });

  it("accepts the OS-preference sentinel like any other palette", () => {
    // `"system"` is a real thing to declare — "open on whatever the viewer's platform prefers"
    // — and it goes through the same enum check, the same conflict check and the same output as
    // a named palette. Nothing about it is exempt, which is the point: an earlier version of
    // this test and of ADR 0100 said the file's `"system"` OVERRIDES a passed option, and it
    // does not. Declaring it in both places is refused like every other key, and the second
    // assertion here is what says so.
    expect(resolveLayoutDeclaration({ defaultTheme: "system" }, {})).toEqual({
      defaultTheme: "system",
    });
    expect(() =>
      resolveLayoutDeclaration({ defaultTheme: "system" }, { defaultTheme: "dark" }),
    ).toThrow(/both declare "defaultTheme" \(file: "system", code: "dark"\)/);
    // And an absent key does leave the option in force, which is the half that was true.
    expect(resolveLayoutDeclaration({}, { defaultTheme: "dark" })).toEqual({
      defaultTheme: "dark",
    });
  });

  it("refuses a palette this release does not ship, naming the ones it does", () => {
    // The alternative is falling back to a palette that does exist, and that is how a
    // declaration ends up doing nothing while looking like it works: `data-theme="midnite"`
    // matches no block in the stylesheet, so the app renders the base palette and nothing
    // anywhere reports that the file was ignored.
    expect(() => resolveLayoutDeclaration({ defaultTheme: "midnite" }, {})).toThrow(
      /"defaultTheme" is "midnite"; expected one of "light", "dark", "midnight", "twilight", "contrast", "system"/,
    );
  });

  it("refuses the palette declared twice, like every other key", () => {
    expect(() =>
      resolveLayoutDeclaration({ defaultTheme: "midnight" }, { defaultTheme: "dark" }),
    ).toThrow(/"defaultTheme" \(file: "midnight", code: "dark"\)/);
    expect(() =>
      resolveLayoutDeclaration({ defaultTheme: "dark" }, { defaultTheme: "dark" }),
    ).toThrow(/both declare/);
  });

  // ---- the navigation groups ------------------------------------------------ #

  it("supplies the groups from the file, with the empty label meaning no label", () => {
    // A group spans modules, so no module can own one — which left the app's own code as the
    // only place one could be declared. `""` is how a file says what `NavGroup` says with
    // `null`: render no label element at all.
    expect(
      resolveLayoutDeclaration(
        {
          shell: {
            navGroups: [
              { id: "work", label: "Workspace", order: 1 },
              { id: "pinned", label: "" },
            ],
          },
        },
        {},
      ),
    ).toEqual({
      navGroups: [
        { id: "work", label: "Workspace", order: 1 },
        { id: "pinned", label: null },
      ],
    });
  });

  it("omits the sort key when the file omits it, rather than writing a zero", () => {
    // `groupNav` reads `order ?? 0` over a stable sort, so absent and 0 sort identically — but
    // they are not the same statement, and a resolver that materialised one into the other
    // would make "I said nothing about order" indistinguishable from "I said first".
    const [group] = resolveLayoutDeclaration(
      { shell: { navGroups: [{ id: "work", label: "Workspace" }] } },
      {},
    ).navGroups!;
    // `null === null ? "Workspace" : ""` stood here, which is a constant expression dressed
    // up as a choice between the two spellings of a label. It selected nothing.
    expect(group).toEqual({ id: "work", label: "Workspace" });
    expect(Object.hasOwn(group!, "order")).toBe(false);
  });

  it("treats an empty group list as a declaration of no groups", () => {
    // Not the same as omitting the key: an empty list still conflicts with a passed option,
    // because the app has said something about groups and the option says something else.
    expect(resolveLayoutDeclaration({ shell: { navGroups: [] } }, {})).toEqual({
      navGroups: [],
    });
    expect(() =>
      resolveLayoutDeclaration(
        { shell: { navGroups: [] } },
        { navGroups: [{ id: "work", label: "Workspace" }] },
      ),
    ).toThrow(/"shell\.navGroups" \(file: no groups, code: "work"\)/);
    // Two ids on one side, which no test rendered before: the message used to wrap the whole
    // joined list in one pair of quotes, so this read as a single group named `work, admin` —
    // the opposite of what putting the ids in the message is for.
    expect(() =>
      resolveLayoutDeclaration(
        { shell: { navGroups: [] } },
        {
          navGroups: [
            { id: "work", label: "Workspace" },
            { id: "admin", label: "Admin" },
          ],
        },
      ),
    ).toThrow(/code: "work", "admin"\)/);
  });

  it("refuses a group the shell would render as nothing", () => {
    // Each of these reaches the shell as a group no `NavItem.group` string can name, so its
    // items fall into the trailing unlabelled bucket and the group never appears: a declaration
    // that silently does nothing, which is what the document exists to remove.
    expect(() =>
      resolveLayoutDeclaration({ shell: { navGroups: [{ id: 7, label: "x" }] } } as never, {}),
    ).toThrow(/shell\.navGroups\[0\]\.id must be a string, got a number/);
    expect(() =>
      resolveLayoutDeclaration({ shell: { navGroups: [{ id: "", label: "x" }] } }, {}),
    ).toThrow(/shell\.navGroups\[0\]\.id is the empty string/);
    expect(() =>
      resolveLayoutDeclaration({ shell: { navGroups: [{ id: "work" }] } } as never, {}),
    ).toThrow(
      /shell\.navGroups\[0\] is missing "label"; every group declares "id" and "label", and "" is a group that renders no label at all/,
    );
    expect(() =>
      resolveLayoutDeclaration({ shell: { navGroups: [{ label: "x" }] } } as never, {}),
    ).toThrow(/shell\.navGroups\[0\] is missing "id"; every group declares "id" and "label"\./);
    expect(() =>
      resolveLayoutDeclaration(
        { shell: { navGroups: [{ id: "work", label: null }] } } as never,
        {},
      ),
    ).toThrow(/shell\.navGroups\[0\]\.label must be a string, got null; use "" for a group/);
  });

  it("refuses a sort key that is not a whole number, naming what it got", () => {
    expect(() =>
      resolveLayoutDeclaration(
        { shell: { navGroups: [{ id: "work", label: "x", order: 1.5 }] } },
        {},
      ),
    ).toThrow(/shell\.navGroups\[0\]\.order must be a whole number, got 1\.5/);
    expect(() =>
      resolveLayoutDeclaration(
        { shell: { navGroups: [{ id: "work", label: "x", order: "1" }] } } as never,
        {},
      ),
    ).toThrow(/shell\.navGroups\[0\]\.order must be a whole number, got a string/);
  });

  it("refuses a field on a group this release does not read", () => {
    // Same reasoning one level down from the unknown-key refusal: an "icon" nobody renders sits
    // in the file looking effective.
    expect(() =>
      resolveLayoutDeclaration(
        { shell: { navGroups: [{ id: "work", label: "x", icon: "folder" }] } } as never,
        {},
      ),
    ).toThrow(/shell\.navGroups\[0\] has unknown field "icon"; a group is "id", "label", "order"/);
  });

  it("refuses a group list that is not a list, and an entry that is not an object", () => {
    expect(() =>
      resolveLayoutDeclaration({ shell: { navGroups: {} } } as never, {}),
    ).toThrow(/shell\.navGroups must be an array, got an object/);
    expect(() =>
      resolveLayoutDeclaration({ shell: { navGroups: ["work"] } } as never, {}),
    ).toThrow(/shell\.navGroups\[0\] must be a JSON object, got a string/);
  });

  it("does not refuse duplicate ids — the router does, over the resolved list", () => {
    // Deliberate, and the reason is that one refusal must cover both sources. `buildAppRouter`
    // already refuses duplicates and now reads the RESOLVED list, so a duplicate declared in the
    // file is refused by the same check and the same message as one passed as an option.
    // Restating it here would be a second message for one error.
    expect(
      resolveLayoutDeclaration(
        { shell: { navGroups: [{ id: "work", label: "A" }, { id: "work", label: "B" }] } },
        {},
      ).navGroups,
    ).toHaveLength(2);
  });

  // ---- the file can hold anything JSON can ---------------------------------

  it("refuses a declaration that is not a JSON object, naming what it got", () => {
    // Every case here was found by PROBING the function rather than by imagining inputs, and
    // each was broken differently. `null` threw a bare "Cannot convert undefined or null to
    // object" with no mention of the file. A string and an array had their character and
    // element indices reported as unknown KEYS. And an array was accepted outright — it has no
    // keys, so it declared nothing and returned silently, which is the exact failure this
    // module exists to prevent, occurring inside it.
    expect(() => resolveLayoutDeclaration(null as never, {})).toThrow(
      /expected a JSON object, got null/,
    );
    expect(() => resolveLayoutDeclaration([] as never, {})).toThrow(
      /expected a JSON object, got an array/,
    );
    expect(() => resolveLayoutDeclaration("standard" as never, {})).toThrow(
      /expected a JSON object, got a string/,
    );
  });

  it("refuses a shell that is not a JSON object", () => {
    for (const shell of [null, "compact", 7, []]) {
      expect(() => resolveLayoutDeclaration({ shell } as never, {})).toThrow(
        /"shell" must be a JSON object, got /,
      );
    }
  });

  it("refuses a value that is not a string, by type rather than by enum", () => {
    // `shell.density is "7"` would read as a typo in a string the author never wrote, so the
    // type is named instead of the value being stringified into the enum message.
    expect(() => resolveLayoutDeclaration({ shell: { density: 7 } } as never, {})).toThrow(
      /shell\.density must be a string, got a number/,
    );
    expect(() => resolveLayoutDeclaration({ contract: 7 } as never, {})).toThrow(
      /"contract" must be a string, got a number/,
    );
    expect(() => resolveLayoutDeclaration({ defaultTheme: [] } as never, {})).toThrow(
      /"defaultTheme" must be a string, got an array/,
    );
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
