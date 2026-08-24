/**
 * Minimal ambient declarations for the two things this package reads off `import.meta` — the
 * package keeps `"types": []` so component source never sees ambient Node globals.
 *
 * Safe to declare here even though every consuming app already has `vite/client`: nothing
 * imports this file, so it is part of THIS package's program and not of a consumer's, and the
 * two `ImportMeta` augmentations never meet.
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
  /**
   * The build-mode flag, `false` in a production build.
   *
   * Written out verbatim at its one call site rather than read through a helper or a cast: a
   * bundler folds the expression `import.meta.env.DEV` TEXTUALLY, so anything else leaves the
   * branch — and the module behind it — in a production bundle.
   */
  readonly env: { readonly DEV: boolean };
}
