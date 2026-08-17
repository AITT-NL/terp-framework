/**
 * Minimal ambient declarations for the source-scanning tests only — the package keeps
 * `"types": []` so component source never sees ambient Node globals.
 *
 * Both live here rather than inline in the tests that use them: a global augmentation
 * repeated in two files is a TS2717 the moment the copies disagree, and they disagree
 * silently until someone widens one of them.
 */
declare module "node:fs" {
  export function readFileSync(path: URL | string, encoding: "utf-8"): string;
}

// Declared at top level, not inside `declare global`: this file is a global script (it has
// no imports or exports), so the interface merges with the ambient `ImportMeta` directly —
// `declare global` is only meaningful from inside a module.
interface ImportMeta {
  glob: (
    pattern: string,
    options: { query: "?raw"; import: "default"; eager: true },
  ) => Record<string, string>;
}
