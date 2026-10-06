import terpBoundaries from "@terpjs/eslint-boundaries";

// Terp's frontend boundary enforcement (the analog of the backend `terp.arch` gate): every source
// file under src/ stays on the centralized contract, not only the modules (ADR 0175), and modules
// stay independent. The generated API schema and build output are not linted.
export default [
  { ignores: ["dist/**", "src/api/**", "playwright-report/**", "test-results/**"] },
  ...terpBoundaries,
];
