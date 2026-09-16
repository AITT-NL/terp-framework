import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// The frontend unit-test seam. Kept in its own file rather than folded into
// vite.config.ts on purpose: that file configures the dev server (proxy, CSP, watch
// mode) and is read by `npm run build`, which must not need vitest installed to run.
//
// What this layer is FOR is worth being precise about, because the app already has a
// Playwright suite in conformance/. That one drives a running stack and answers "does
// the app work"; it cannot run without one, and it is not in `terp verify`'s default
// path. This one answers "is this piece right" for the code between those two --
// presentation logic with branches, a formatter, a plural rule, a state reducer, a
// column definition. That code has branches, and before this seam existed the only
// places to exercise them were a browser against a live backend, or nowhere.
export default defineConfig({
  plugins: [react()],
  test: {
    // jsdom by default: in an app, most of what is worth unit-testing renders. A pure
    // logic test costs nothing extra here, whereas a component test in a node
    // environment fails with a message about `document` that explains nothing.
    environment: "jsdom",
    setupFiles: ["./vitest.setup.ts"],
    include: ["src/**/*.test.ts", "src/**/*.test.tsx"],
    // conformance/ is Playwright's; running it here would start a second browser stack
    // inside a jsdom worker and fail in a way that reads like a broken unit test.
    exclude: ["node_modules/**", "dist/**", "../conformance/**"],
    // A jsdom + React file is heavy and a small CI runner has few cores; enough of them
    // at once starve each other's timers and fail on timing rather than on behaviour.
    // Costs wall clock, buys a green that means something.
    fileParallelism: false,
  },
});
