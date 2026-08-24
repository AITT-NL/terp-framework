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
  /** The shell's shape. Grouped, because `contract` governs page bodies and this governs chrome. */
  readonly shell?: LayoutShellDeclaration;
}

/** What the resolver hands the router: one value per key, from whichever source declared it. */
export interface ResolvedLayout {
  readonly contract?: string;
  readonly density?: "comfortable" | "compact";
  readonly navPlacement?: "sidebar" | "header";
  readonly contentWidth?: "full" | "measured";
}

/**
 * The legal values per shell key, as data.
 *
 * One table, so the refusal message can name the alternatives and a new key cannot be added
 * without its enum. This is the ONLY place the legal values are enforced for a declaration —
 * the interface above cannot carry them (see LayoutShellDeclaration) — and it is also what
 * narrows a `string` from the file to the union {@link ResolvedLayout} promises.
 */
const SHELL_VALUES = {
  density: ["comfortable", "compact"],
  navPlacement: ["sidebar", "header"],
  contentWidth: ["full", "measured"],
} as const;

type ShellKey = keyof typeof SHELL_VALUES;

const SHELL_KEYS = Object.keys(SHELL_VALUES) as readonly ShellKey[];

/** Where a refusal points the reader. The file, not the option, because the file is the source. */
const FILE = "frontend/layout-contract.json";

/**
 * Resolve the declaration against the options an app passed in TypeScript.
 *
 * Returns *explicit* untouched when there is no declaration, so an app that passes none is on
 * the exact path it was on before this existed.
 *
 * Three things are refused, each fail-closed at compose time rather than absorbed:
 *
 * 1. **A value outside its enum.** A JSON file is not typechecked, so `"density": "compakt"`
 *    would otherwise reach the shell as an attribute value nothing styles — a declaration that
 *    silently does nothing, which is the failure this whole declaration exists to remove.
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
  const known = new Set<string>(["contract", "shell"]);
  const unknownTop = Object.keys(declaration).filter((key) => !known.has(key));
  if (unknownTop.length > 0) {
    throw new Error(
      `${FILE}: unknown ${unknownTop.length === 1 ? "key" : "keys"} ` +
        `${unknownTop.map((key) => `"${key}"`).join(", ")}; this release reads ` +
        `${[...known].map((key) => `"${key}"`).join(" and ")}.`,
    );
  }

  const shell = declaration.shell ?? {};
  const unknownShell = Object.keys(shell).filter(
    (key) => !(SHELL_KEYS as readonly string[]).includes(key),
  );
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

  for (const key of SHELL_KEYS) {
    const declared = shell[key];
    if (declared === undefined) continue;
    // `declared` is `string` here by construction (see LayoutShellDeclaration); the enum check
    // below is what narrows it, so the cast after it is earned rather than asserted.
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
