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
    // `fileParallelism: false` used to be here, and is deliberately gone. It was added
    // against an intermittent "unable to find element" -- four different fetch-bound
    // assertions across four CI runs, always one file of eighty-one, each passing on its
    // own -- after widening the async budget had already failed to fix it (1s to 3s to 4s,
    // vitest.setup.ts). A serial run did measurably help, which is why it looked like the
    // answer. The actual cause was a structural race in four admin tests: they clicked a
    // submit control that is disabled until an ambient fetch lands, having waited only on
    // the page heading, so jsdom raised no submit event and the click was LOST rather than
    // late. Serialising widened the odds of winning that race; it did not remove it.
    //
    // With the race removed (`enabledSubmitControl`, admin/admin.test.tsx), the suite was
    // re-measured on a four-vCPU machine -- the class of runner the flag was added for --
    // and ran green nine times out of nine in parallel, in ~33s against ~80s serial. So the
    // wall clock is given back. If this suite starts failing intermittently again, do NOT
    // reach for this flag or the async budget first: find out what the failing test is
    // waiting on, and whether the thing it clicks can be clicked yet.
  },
});
