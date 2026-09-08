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
    // These tests contend for the machine rather than with each other, and losing that
    // contention is how they fail: four different fetch-bound assertions across four CI
    // runs, always one file of eighty-one, each passing on its own. Widening the async
    // budget was tried first and did not fix it (1s to 3s to 4s), and it has nowhere left
    // to go -- a toast's 5s lifetime is the ceiling. So remove the cause rather than the
    // tolerance: a jsdom + React + fetch file is heavy, a small runner has four vCPUs, and
    // eighty-one of them at once starve each other's timers. It costs wall clock and buys
    // a green that means something.
    fileParallelism: false,
  },
});
