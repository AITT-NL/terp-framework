import terpBoundaries from "@terpjs/eslint-boundaries";

// Terp's frontend boundary enforcement (the analog of the backend `terp check` gate): app modules
// stay independent and on the centralized contract — no cross-module imports, no package internals,
// design-token-only styling, no raw <button>/<input>, generated client only. The generated API
// schema and build output are not linted.
export default [
  { ignores: ["dist/**", "src/api/**"] },
  ...terpBoundaries,
];
