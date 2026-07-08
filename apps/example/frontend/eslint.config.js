import terpBoundaries from "@terp/eslint-boundaries";

// Terp's frontend boundary enforcement (the analog of the backend `terp.arch` gate): app modules
// stay independent and on the centralized contract. The generated API schema and build output are
// not linted.
export default [
  { ignores: ["dist/**", "src/api/**", "playwright-report/**", "test-results/**"] },
  ...terpBoundaries,
];
