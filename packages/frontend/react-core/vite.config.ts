import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// Vite + Vitest config for @terp/react-core. The React plugin handles TSX. The default
// environment is node (headless client/logic tests); component tests opt into jsdom with
// a `// @vitest-environment jsdom` docblock so the node-based tests keep their fetch/Response.
export default defineConfig({
  plugins: [react()],
  test: {
    environment: "node",
    setupFiles: ["./vitest.setup.ts"],
    include: ["src/**/*.test.ts", "src/**/*.test.tsx"],
  },
});
