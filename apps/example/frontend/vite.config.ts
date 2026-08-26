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

// The dev server's Content-Security-Policy (ADR 0104 §4). The production nginx
// config serves a strict policy; this keeps development on the same *origin*
// rules so a third-party resource fails the moment it is added rather than at
// deploy. Measured against a running dev server in Chromium: a CDN script, an
// external stylesheet and a fetch to another origin are each refused here, while
// HMR still connects and the chrome renders fully styled.
//
// Two relaxations are dev-only and unavoidable, both from Vite's own machinery
// rather than from app code: the React Fast Refresh preamble is an inline
// script, and Vite serves imported CSS by injecting a <style> element. So
// development cannot catch a *newly added inline* script or style — production
// still does, and that is the asymmetry to keep in mind. Everything else is
// identical, including `connect-src 'self'`, which covers the HMR websocket
// without widening to `ws:` (measured: "[vite] connected." with `'self'` alone).
const devContentSecurityPolicy = [
  "default-src 'self'",
  // 'unsafe-inline': the Fast Refresh preamble. Origins stay 'self', so a CDN is refused.
  "script-src 'self' 'unsafe-inline'",
  // 'unsafe-inline': Vite injects imported CSS as a <style> element in dev.
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data:",
  "font-src 'self'",
  "connect-src 'self'",
  "object-src 'none'",
  "base-uri 'none'",
  "frame-ancestors 'none'",
  "form-action 'self'",
].join("; ");

export default defineConfig({
  plugins: [react()],
  server: {
    // Same policy every dev session, so a CSP-incompatible pattern cannot be
    // introduced unnoticed and discovered only in production.
    headers: { "Content-Security-Policy": devContentSecurityPolicy },
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
