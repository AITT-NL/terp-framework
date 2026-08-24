import type { NavGroup } from "@terpjs/contract";

import { THEMES } from "./themes";
import type { Theme } from "./themes";

/**
 * The app's checked-in layout declaration — `frontend/layout-contract.json` — as the ONE
 * source for what it declares.
 *
 * That file already existed and already governed something: the `terp/layout-contract` lint
 * rule walks up from each linted file, reads `contract`, and enforces the slot table for it.
 * The runtime half read nothing — it took a `layoutContract` string passed in TypeScript. So
 * an app declared the same fact twice, and the template said so out loud: "keep the two in
 * sync", with `layoutContract: "standard"` in `main.tsx` beside `{"contract": "standard"}` in
 * the file. Delete one and the app keeps a build-time rule with no runtime check, or a runtime
 * check no lint agrees with, and nothing says which.
 *
 * So the file is imported and passed in, and it carries the shell's declarations too. Three
 * shell choices shipped in 0.10.0 as TypeScript options only — density, navigation placement
 * and the content measure — which made them unreachable to anything that edits files rather
 * than code. Moving them into the declaration is what lets a project's own checked-in document
 * say how its shell is shaped, and therefore what lets a tool read and rewrite it.
 *
 * **Opt-in and non-exclusive** (the authoring-model rule the platform holds itself to): an app
 * that passes no declaration behaves exactly as it did, and hand-writing every option in
 * TypeScript stays legal and complete. What is refused is declaring one fact in both places —
 * see {@link resolveLayoutDeclaration}, and the reason is not tidiness.
 */

/**
 * The shell's own declarations. Every key optional; an absent key changes nothing.
 *
 * **The value types are `string`, not the unions, and that is forced rather than sloppy.**
 * `resolveJsonModule` types an imported JSON string as `string` — never as its literal — so
 * `{ "shell": { "density": "compact" } }` imports as `{ shell: { density: string } }`. Declaring
 * the unions here would make the template stop typechecking the moment an app filled the shell
 * section in, which is the one thing this declaration is for. Measured before choosing: tsc
 * reports "Type 'string' is not assignable to type '\"compact\" | \"comfortable\"'".
 *
 * So the legal values live in {@link resolveLayoutDeclaration}'s runtime check, and that check
 * is not belt-and-braces — it is the ONLY check this key ever gets. The unions survive on
 * {@link ResolvedLayout}, which is what the shell is handed.
 */
export interface LayoutShellDeclaration {
  /** App-wide density (`AppShell.density`): `"comfortable"` or `"compact"`. */
  readonly density?: string;
  /** Navigation placement on desktop (`AppShell.navPlacement`): `"sidebar"` or `"header"`. */
  readonly navPlacement?: string;
  /** Content measure (`AppShell.contentWidth`): `"full"` or `"measured"`. */
  readonly contentWidth?: string;
  /**
   * The app's navigation groups, which a module's `NavItem.group` names by id.
   *
   * Declarable here and nowhere else in a file, for the reason groups exist at all: a group
   * spans modules, so no module can own one — which left the app's own code as the only place
   * one could be declared, and therefore left the order of an app's navigation out of reach of
   * anything that edits files.
   *
   * Unlike the three keys above, `id` and `label` are typed as REQUIRED here, and that is not
   * a lapse in the measured `string` rule beside it. That rule is about a value's TYPE — a JSON
   * string never narrows to its literal, so a union would stop an app's own file typechecking.
   * Presence is a different question, and one `resolveJsonModule` answers accurately: an
   * imported file missing a label is a compile error naming the field, which is strictly better
   * than the runtime refusal below. Both exist, because a declaration handed in at runtime gets
   * only the second.
   */
  readonly navGroups?: readonly LayoutNavGroupDeclaration[];
  /**
   * The app's own mark, as paths its static-asset directory serves.
   *
   * Paths rather than elements, because a file is what a tool can put somewhere and a
   * `ReactNode` is not. The bootstrap option stays a `ReactNode` and stays legal — an app
   * that wants an inline SVG or a component keeps writing one — and declaring the same slot
   * both ways is refused where both halves are visible, in `buildAppRouter`.
   */
  readonly brand?: LayoutBrandDeclaration;
}

/**
 * The mark, and its dark counterpart.
 *
 * The counterpart is declared rather than derived: a mark with fixed colours cannot survive a
 * dark background, and nothing here can tell whether this one can. An app with one mark
 * declares one and keeps it everywhere, which is the right answer for a mark that does survive.
 */
export interface LayoutBrandDeclaration {
  /** The mark inside the app's own frame; the shell sizes it, so an oversized file is scaled. */
  readonly logo?: string;
  /** The mark for a dark palette. The stylesheet picks, by the appearance of the palette in
   *  force rather than by the viewer's platform — an app may pin a dark palette on a light
   *  platform, and a mark chosen by the platform would then be the wrong one. */
  readonly logoDark?: string;
}

/**
 * One navigation group as the file spells it.
 *
 * `label` is a plain `string`, not `string | null`, and the empty string is how the document
 * says "render no label element at all". Two reasons, and the second is the real one. The
 * standard's schema is validated by a deliberately minimal validator with no way to express
 * "string or null". And required-with-an-empty-value keeps the property the runtime
 * {@link NavGroup} chose `string | null` for in the first place: having no label is a decision
 * the declaration STATES, rather than a key someone forgot. Optional-with-absent-meaning-none
 * would have handed it straight back to omission.
 */
export interface LayoutNavGroupDeclaration {
  /** Referenced by `NavItem.group`. Non-empty — a group with no id is one nothing can name. */
  readonly id: string;
  /** Rendered above the group's list; `""` declares a positioning-only group with no label. */
  readonly label: string;
  /** Ascending sort key against sibling groups; absent is 0 and the sort is stable. */
  readonly order?: number;
}

/**
 * The contents of `frontend/layout-contract.json`.
 *
 * The file keeps its name. It is the file the lint rule already looks for, every scaffolded app
 * already has one, and renaming it would break the one consumer that worked — for a nicer noun.
 */
export interface LayoutDeclaration {
  /** The slot-typed layout contract the app opts into, e.g. `"standard"`. */
  readonly contract?: string;
  /**
   * The palette the app opens on, until a person chooses another (`ThemeProvider.defaultTheme`):
   * one of the shipped theme names, or `"system"` to follow the viewer's own platform preference.
   *
   * Top level rather than under `shell`, because a palette paints the frame and the page alike
   * while `shell` is where the frame's geometry is declared — and because the standard splits
   * the two the other way round: shell vocabulary is fixed normatively, palette names are a
   * stack's own to publish, so this follows `contract`'s half of that split.
   *
   * `string` for the same measured reason every shell value is (see
   * {@link LayoutShellDeclaration}), so the runtime check below is the only one it gets.
   */
  readonly defaultTheme?: string;
  /** The shell's shape. Grouped, because `contract` governs page bodies and this governs chrome. */
  readonly shell?: LayoutShellDeclaration;
}

/** What the resolver hands the router: one value per key, from whichever source declared it. */
export interface ResolvedLayout {
  readonly contract?: string;
  readonly defaultTheme?: Theme;
  readonly density?: "comfortable" | "compact";
  readonly navPlacement?: "sidebar" | "header";
  readonly contentWidth?: "full" | "measured";
  readonly navGroups?: readonly NavGroup[];
  /** The declared brand PATHS. Not merged with the `logo` option, which is a rendered
   *  element rather than a path; `buildAppRouter` refuses the two together. */
  readonly brand?: LayoutBrandDeclaration;
}

/**
 * The legal values per shell key, as data.
 *
 * One table, so the refusal message can name the alternatives and a new key cannot be added
 * without its enum. This is the ONLY place the legal values are enforced for a declaration —
 * the interface above cannot carry them (see LayoutShellDeclaration) — and it is also what
 * narrows a `string` from the file to the union {@link ResolvedLayout} promises.
 */
export const SHELL_VALUES = {
  density: ["comfortable", "compact"],
  navPlacement: ["sidebar", "header"],
  contentWidth: ["full", "measured"],
} as const;

type ShellEnumKey = keyof typeof SHELL_VALUES;

const SHELL_ENUM_KEYS = Object.keys(SHELL_VALUES) as readonly ShellEnumKey[];

/**
 * Shell keys that are a shape rather than a choice between fixed values.
 *
 * Written out beside {@link SHELL_VALUES} rather than folded into it, because the two are read
 * differently and by different readers: the enum table is what narrows a `string` from the file
 * to the union {@link ResolvedLayout} promises, and this one only says the key exists. The
 * architecture suite parses both literals to hold the whole shell vocabulary against the
 * standard's schema, so a key added to neither is a key the standard would not know about.
 */
export const SHELL_STRUCTURED_KEYS = ["brand", "navGroups"] as const;

/** Every key `shell` admits, in the order a refusal offers them. */
const SHELL_KEYS: readonly string[] = [...SHELL_ENUM_KEYS, ...SHELL_STRUCTURED_KEYS];

/** Every field a declared navigation group may carry. */
export const NAV_GROUP_FIELDS = ["id", "label", "order"] as const;

/**
 * The fields a group must carry.
 *
 * Named rather than written inline in the loop that reads it, for the reason the other four
 * vocabulary literals are named: the published manifest mirrors this one too, and a mirror
 * compared against a copy of itself in a test proves nothing.
 */
export const NAV_GROUP_REQUIRED = ["id", "label"] as const;

/** Every slot the brand declares. */
export const BRAND_FIELDS = ["logo", "logoDark"] as const;

/** Where a refusal points the reader. The file, not the option, because the file is the source. */
const FILE = "frontend/layout-contract.json";

/**
 * Every key the document itself admits.
 *
 * Hoisted out of the refusal that reads it so that all four vocabulary literals in this module
 * are named constants: the published `layout.manifest.json` mirrors them for tools, and both
 * parity tests — this stack's against the standard, and the manifest's against this module —
 * find them by name.
 */
export const TOP_LEVEL_KEYS = ["contract", "defaultTheme", "shell"] as const;

/** A JSON object — not null, not an array, not a scalar. */
function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** What the reader actually wrote, for a message that saves them opening the file.
 *
 * `an object` is spelled out rather than left to `a ${typeof value}`, which reported
 * `"navGroups": {}` as "got a object" — a typo in the message rather than a fact about the
 * file. The array case predates this and is reached by `resolveLayoutDeclaration([])` and by
 * `"shell": []`, neither of which involves a group; it is listed here because both are article
 * exceptions, not because either is new. */
function describe(value: unknown): string {
  if (value === null) return "null";
  if (value === undefined) return "nothing";
  if (Array.isArray(value)) return "an array";
  if (typeof value === "object") return "an object";
  return `a ${typeof value}`;
}

/**
 * The declared brand, checked.
 *
 * Every refusal is the same kind as the enum refusal on a shell value: a path the shell would
 * hand to an `<img>` that cannot load it, which renders as a broken mark rather than as the
 * placeholder an app with no mark gets — worse than declaring nothing, and silent until someone
 * looks at the header.
 */
function resolveBrand(declared: unknown): LayoutBrandDeclaration {
  if (!isPlainObject(declared)) {
    throw new Error(`${FILE}: shell.brand must be a JSON object, got ${describe(declared)}.`);
  }
  const unknown = Object.keys(declared).filter(
    (key) => !(BRAND_FIELDS as readonly string[]).includes(key),
  );
  if (unknown.length > 0) {
    throw new Error(
      `${FILE}: shell.brand has unknown ${unknown.length === 1 ? "mark" : "marks"} ` +
        `${unknown.map((key) => `"${key}"`).join(", ")}; a brand is ` +
        `${BRAND_FIELDS.map((key) => `"${key}"`).join(" and ")}.`,
    );
  }
  const brand: { logo?: string; logoDark?: string } = {};
  for (const slot of BRAND_FIELDS) {
    const value = declared[slot];
    if (value === undefined) continue;
    if (typeof value !== "string") {
      throw new Error(
        `${FILE}: shell.brand.${slot} must be a path, got ${describe(value)}.`,
      );
    }
    if (value.trim() === "") {
      throw new Error(
        `${FILE}: shell.brand.${slot} is empty; omit it to keep one mark for every palette.`,
      );
    }
    brand[slot] = value;
  }
  return brand;
}

/** A group list as a refusal names it: the ids, in order, or the fact that there are none.
 *
 * Each id quoted separately, like every other list this module emits. Wrapping the joined
 * string in one pair of quotes rendered two groups as `"work, admin"`, which reads as a single
 * group whose id contains a comma — the opposite of the reason the ids are in the message at
 * all, which is that they are the part a reader can match up against either source by eye. */
function describeGroups(groups: readonly NavGroup[]): string {
  if (groups.length === 0) return "no groups";
  return groups.map((group) => `"${group.id}"`).join(", ");
}

/**
 * The file's navigation groups as the runtime {@link NavGroup}s the shell is handed.
 *
 * Every refusal here is the same kind as the enum refusal on a shell value: a group the shell
 * would accept and then render as nothing, or not render at all. A group with a numeric id is
 * one no `NavItem.group` string can ever match, so its items fall into the trailing unlabelled
 * bucket and the group never appears — a declaration that silently does nothing, which is the
 * failure this whole document exists to remove.
 *
 * Duplicate ids are deliberately NOT refused here. `buildAppRouter` already refuses them, with
 * a message this one could only restate, and routing the resolved list through that check means
 * one refusal covers a group declared in the file and a group passed as an option alike.
 */
function resolveNavGroups(declared: unknown): readonly NavGroup[] {
  if (!Array.isArray(declared)) {
    throw new Error(
      `${FILE}: shell.navGroups must be an array, got ${describe(declared)}.`,
    );
  }
  return declared.map((entry: unknown, index: number): NavGroup => {
    const at = `shell.navGroups[${index}]`;
    if (!isPlainObject(entry)) {
      throw new Error(`${FILE}: ${at} must be a JSON object, got ${describe(entry)}.`);
    }
    const unknown = Object.keys(entry).filter(
      (key) => !(NAV_GROUP_FIELDS as readonly string[]).includes(key),
    );
    if (unknown.length > 0) {
      throw new Error(
        `${FILE}: ${at} has unknown ${unknown.length === 1 ? "field" : "fields"} ` +
          `${unknown.map((key) => `"${key}"`).join(", ")}; a group is ` +
          `${NAV_GROUP_FIELDS.map((key) => `"${key}"`).join(", ")}.`,
      );
    }
    // A missing required field is reported as missing, not as a type. "must be a string, got
    // nothing" sends the reader looking for a value they never wrote; the schema requires both
    // fields, so the message should say which one is absent.
    for (const field of NAV_GROUP_REQUIRED) {
      if (entry[field] === undefined) {
        throw new Error(
          `${FILE}: ${at} is missing "${field}"; every group declares ` +
            `${NAV_GROUP_REQUIRED.map((name) => `"${name}"`).join(" and ")}` +
            (field === "label" ? ', and "" is a group that renders no label at all.' : "."),
        );
      }
    }
    if (typeof entry.id !== "string") {
      throw new Error(`${FILE}: ${at}.id must be a string, got ${describe(entry.id)}.`);
    }
    if (entry.id === "") {
      throw new Error(
        `${FILE}: ${at}.id is the empty string; a group with no id is one no navigation ` +
          "item can name.",
      );
    }
    if (typeof entry.label !== "string") {
      throw new Error(
        `${FILE}: ${at}.label must be a string, got ${describe(entry.label)}; use "" for a ` +
          "group that renders no label at all.",
      );
    }
    // The one line where the document's spelling and the runtime's meet: `""` is how a file
    // says "render no label element", and `null` is how NavGroup says the same thing.
    const group: NavGroup = { id: entry.id, label: entry.label === "" ? null : entry.label };
    if (entry.order === undefined) {
      return group;
    }
    // Split from the guard above rather than folded into one condition, because a compound
    // negation over `unknown` does not narrow: `order` stayed `{} | null` and the assignment
    // below did not compile. Two guards narrow it to `number` with no cast.
    if (typeof entry.order !== "number" || !Number.isInteger(entry.order)) {
      throw new Error(
        `${FILE}: ${at}.order must be a whole number, got ` +
          `${typeof entry.order === "number" ? entry.order : describe(entry.order)}; it is a ` +
          "sort key against sibling groups, and absent means 0.",
      );
    }
    return { ...group, order: entry.order };
  });
}

/**
 * Resolve the declaration against the options an app passed in TypeScript.
 *
 * Returns *explicit* untouched when there is no declaration, so an app that passes none is on
 * the exact path it was on before this existed.
 *
 * Three things are refused, each fail-closed at compose time rather than absorbed:
 *
 * 1. **A value outside its enum, or a malformed navigation group.** A JSON file is not
 *    typechecked, so `"density": "compakt"` would otherwise reach the shell as an attribute
 *    value nothing styles, and a group with a numeric id would reach it as a group no item can
 *    name — declarations that silently do nothing, which is the failure this whole declaration
 *    exists to remove.
 * 2. **A key the framework does not know.** Same reasoning one level up: a hand-written or
 *    newer-framework key would sit in the file looking effective. Refusing names it instead.
 *    This is the cost of the choice and it is the right way round — an app pinned to a release
 *    is told the release cannot honour a key, rather than being told nothing.
 * 3. **One fact declared twice.** If the file says `"density": "compact"` and the app also
 *    passes `density: "comfortable"`, one of them loses silently. Whichever way that
 *    precedence went, a person editing the losing source would watch their change do nothing —
 *    and once a file is what tools edit, the tool becomes the one making a change that does
 *    nothing. So it is an authoring error, named with both sources.
 */
export function resolveLayoutDeclaration(
  declaration: LayoutDeclaration | undefined,
  explicit: ResolvedLayout,
): ResolvedLayout {
  if (declaration === undefined) {
    return explicit;
  }
  // The shape first, because this comes from a FILE and a file can hold anything JSON can.
  // Every branch below was reached by probing rather than imagined: `null` threw a bare
  // "Cannot convert undefined or null to object" with no mention of which file; a string or an
  // array had its character/element indices reported as unknown KEYS; and an array was
  // accepted outright — `Object.keys([])` is empty, so `[]` declared nothing and returned
  // silently, which is the exact failure this module exists to prevent, in this module.
  if (!isPlainObject(declaration)) {
    throw new Error(`${FILE}: expected a JSON object, got ${describe(declaration)}.`);
  }
  const known = new Set<string>(TOP_LEVEL_KEYS);
  const unknownTop = Object.keys(declaration).filter((key) => !known.has(key));
  if (unknownTop.length > 0) {
    throw new Error(
      `${FILE}: unknown ${unknownTop.length === 1 ? "key" : "keys"} ` +
        `${unknownTop.map((key) => `"${key}"`).join(", ")}; this release reads ` +
        // Comma-joined like the shell message beside it. It read "a and b" while there were
        // exactly two keys, which does not survive a third: "a and b and c".
        `${[...known].map((key) => `"${key}"`).join(", ")}.`,
    );
  }

  if (declaration.contract !== undefined && typeof declaration.contract !== "string") {
    throw new Error(
      `${FILE}: "contract" must be a string, got ${describe(declaration.contract)}.`,
    );
  }
  if (declaration.defaultTheme !== undefined && typeof declaration.defaultTheme !== "string") {
    throw new Error(
      `${FILE}: "defaultTheme" must be a string, got ${describe(declaration.defaultTheme)}.`,
    );
  }
  // Checked BEFORE defaulting, not after: `?? {}` swallows `null`, so `"shell": null` would
  // have been read as "declared nothing" while `"shell": []` was refused — and the standard's
  // own schema types this as an object, so it rejects null. Two consumers disagreeing about one
  // document is the thing the declaration exists to stop.
  if (declaration.shell !== undefined && !isPlainObject(declaration.shell)) {
    throw new Error(
      `${FILE}: "shell" must be a JSON object, got ${describe(declaration.shell)}.`,
    );
  }
  const shell = declaration.shell ?? {};
  const unknownShell = Object.keys(shell).filter((key) => !SHELL_KEYS.includes(key));
  if (unknownShell.length > 0) {
    throw new Error(
      `${FILE}: unknown shell ${unknownShell.length === 1 ? "key" : "keys"} ` +
        `${unknownShell.map((key) => `"${key}"`).join(", ")}; this release reads ` +
        `${SHELL_KEYS.map((key) => `"${key}"`).join(", ")}.`,
    );
  }

  const resolved: Record<string, unknown> = { ...explicit };
  const conflicts: string[] = [];

  if (declaration.contract !== undefined) {
    if (explicit.contract !== undefined) {
      conflicts.push(`"contract" (file: "${declaration.contract}", code: "${explicit.contract}")`);
    }
    resolved.contract = declaration.contract;
  }

  if (declaration.defaultTheme !== undefined) {
    // The enum this key gets, and the list is imported rather than restated: `THEMES` is the
    // same array the theme control offers and the provider validates a stored choice against,
    // held to the compiled stylesheet by `theme.themes.test.ts`. A copy here would be a third
    // place a shipped palette could go missing from.
    //
    // Refused rather than fallen back to a palette that does exist, which the standard states
    // outright: a fallback is how a declaration ends up doing nothing while looking like it
    // works — `data-theme="midnite"` matches no block, so the app renders the base palette and
    // nothing anywhere says the file was ignored.
    if (!(THEMES as readonly string[]).includes(declaration.defaultTheme)) {
      throw new Error(
        `${FILE}: "defaultTheme" is "${declaration.defaultTheme}"; expected one of ` +
          `${THEMES.map((theme) => `"${theme}"`).join(", ")}.`,
      );
    }
    if (explicit.defaultTheme !== undefined) {
      conflicts.push(
        `"defaultTheme" (file: "${declaration.defaultTheme}", code: "${explicit.defaultTheme}")`,
      );
    }
    resolved.defaultTheme = declaration.defaultTheme;
  }

  const declaredBrand = shell.brand;
  if (declaredBrand !== undefined) {
    resolved.brand = resolveBrand(declaredBrand);
  }

  const declaredGroups = shell.navGroups;
  if (declaredGroups !== undefined) {
    const groups = resolveNavGroups(declaredGroups);
    if (explicit.navGroups !== undefined) {
      // Not the value, which is a list of objects nobody wants stringified into an error, but
      // the ids — the one part of a group a reader can match up against either source by eye.
      conflicts.push(
        `"shell.navGroups" (file: ${describeGroups(groups)}, ` +
          `code: ${describeGroups(explicit.navGroups)})`,
      );
    }
    resolved.navGroups = groups;
  }

  for (const key of SHELL_ENUM_KEYS) {
    const declared = shell[key];
    if (declared === undefined) continue;
    // A file can put a number or an object here. Refused with the type named rather than
    // stringified into the enum message, where `shell.density is "7"` would read as a typo in
    // a string the author never wrote.
    if (typeof declared !== "string") {
      throw new Error(`${FILE}: shell.${key} must be a string, got ${describe(declared)}.`);
    }
    const legal = SHELL_VALUES[key] as readonly string[];
    if (!legal.includes(declared)) {
      throw new Error(
        `${FILE}: shell.${key} is "${declared}"; expected one of ` +
          `${legal.map((value) => `"${value}"`).join(", ")}.`,
      );
    }
    const fromCode = explicit[key];
    if (fromCode !== undefined) {
      conflicts.push(`"shell.${key}" (file: "${declared}", code: "${fromCode}")`);
    }
    resolved[key] = declared;
  }

  if (conflicts.length > 0) {
    throw new Error(
      `${FILE} and the bootstrap options both declare ${conflicts.join("; ")}. ` +
        "Declare each in one place: the file is what a tool can read and rewrite, so " +
        "prefer it and drop the option.",
    );
  }
  return resolved as ResolvedLayout;
}
