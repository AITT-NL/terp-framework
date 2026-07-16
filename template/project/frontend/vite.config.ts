import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The dev server proxies /api to the running Terp backend, so the app calls the API
// same-origin and there is no CORS to configure in development. The target defaults to
// uvicorn on localhost:8000 (the `terp dev` layout) and is overridable via TERP_API_PROXY
// (the Docker workbench points it at the `api` service).
const apiProxyTarget = process.env.TERP_API_PROXY ?? "http://localhost:8000";

// Bind-mounted source in the Docker workbench can sit on a filesystem that
// delivers no file events (Docker Desktop mounts, volume-backed checkouts);
// the compose file sets TERP_DEV_FORCE_POLLING so HMR polls instead of missing.
const usePolling = process.env.TERP_DEV_FORCE_POLLING === "true";

export default defineConfig({
  plugins: [react()],
  server: {
    watch: usePolling ? { usePolling: true, interval: 300 } : undefined,
    proxy: {
      "/api": {
        target: apiProxyTarget,
        ws: true,
      },
    },
  },
});
