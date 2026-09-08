import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// Vite + Vitest config for @terpjs/react-core. The React plugin handles TSX. The default
// environment is node (headless client/logic tests); component tests opt into jsdom with
// a `// @vitest-environment jsdom` docblock so the node-based tests keep their fetch/Response.
export default defineConfig({
  plugins: [react()],
  test: {
    environment: "node",
    setupFiles: ["./vitest.setup.ts"],
    include: ["src/**/*.test.ts", "src/**/*.test.tsx"],
    // Above the `asyncUtilTimeout` the setup file configures, so a matcher that cannot
    // find its element loses first and says which element. Equal budgets would let the
    // test time out mid-wait and report nothing useful about the assertion. The ordering
    // is held from the Python side in `test_frontend_async_budget.py`, which is why this
    // comment names no number: an earlier version said "the 5s asyncUtilTimeout" while
    // the setup file configured 3s, and a comment that misstates the code it explains is
    // worse than none.
    testTimeout: 15_000,
  },
});
