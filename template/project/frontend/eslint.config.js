import terpBoundaries from "@terpjs/eslint-boundaries";

// Terp's frontend boundary enforcement (the analog of the backend `terp check` gate). Every rule
// holds every source file under src/, a helper beside the modules exactly like a module (ADR 0175):
// localization, no package internals, design-token-only styling (no style, className or
// stylesheet; src/main.tsx alone loads the token pipeline's three), no raw <button>/<input>,
// generated client only. Modules stay independent: no module imports a sibling, and no code
// outside the modules imports into one. The generated API schema and build output are not linted.
export default [
  { ignores: ["dist/**", "src/api/**"] },
  ...terpBoundaries,
];
