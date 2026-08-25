import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The dev server proxies /api to the running Terp backend, so the app calls the API
// same-origin and there is no CORS to configure in development. The target defaults to
// uvicorn on localhost:8000 (the `terp dev` layout) and is overridable via TERP_API_PROXY
// (the Docker workbench points it at the `api` service).
const apiProxyTarget = process.env.TERP_API_PROXY ?? "http://localhost:8000";

// Some filesystems deliver file events unreliably or not at all, and the failure is
// SILENT: Vite keeps serving the last build it saw, so a frontend edit appears to have
// had no effect and nothing reports an error — long enough to screenshot a screen that
// no longer exists in the source. Docker Desktop bind mounts and volume-backed checkouts
// are the known cases and the compose file sets TERP_DEV_FORCE_POLLING for them, but this
// is NOT Docker-only: a plain Windows checkout on a synced or virtualised drive drops
// them too, which is why the flag is documented in the README rather than only set here.
const usePolling = process.env.TERP_DEV_FORCE_POLLING === "true";

export default defineConfig({
  plugins: [react()],
  server: {
    // The Docker workbench publishes this dev server on a host port behind a reverse
    // proxy / port-forward whose hostname Vite cannot predict (the operator's own host,
    // not localhost) — Vite's DNS-rebinding guard (server.allowedHosts) would otherwise
    // answer any such request with 403. The workbench network is not the public
    // internet (Compose network + operator-controlled host firewall), so trusting the
    // Host header here is the accepted trade-off.
    allowedHosts: true,
    watch: usePolling ? { usePolling: true, interval: 300 } : undefined,
    proxy: {
      "/api": {
        target: apiProxyTarget,
        ws: true,
      },
    },
  },
});
