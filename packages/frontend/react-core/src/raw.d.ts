/**
 * Minimal Node file access for the token guard test only — the package keeps
 * `"types": []` so component source never sees ambient Node globals.
 */
declare module "node:fs" {
  export function readFileSync(path: URL | string, encoding: "utf-8"): string;
}
