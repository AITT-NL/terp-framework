import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The workbench dev server. `@terpjs/react-core` ships raw TypeScript and is resolved through
// the workspace link, so Vite compiles it from source — which is the point: a change to a
// component shows up on reload with no build step in between.
export default defineConfig({
  plugins: [react()],
  server: { port: 5175, strictPort: true },
  preview: { port: 5175, strictPort: true },
});
