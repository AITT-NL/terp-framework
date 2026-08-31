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

// Who may embed this dev server in an iframe. Production's answer is `'none'`,
// and so is the default here: a Terp app is not framed. The one legitimate
// embedder is the workbench that previews an app while it is being built, and
// its origin cannot be written into this file — it is a deployment fact, a
// laptop's `http://localhost:8420` or a client's `https://workbench.example.nl`
// behind a reverse proxy. So the embedder is DECLARED at runtime through
// TERP_DEV_FRAME_ANCESTORS, and every other case — unset, blank, malformed —
// stays `'none'`. Nothing here is quietly permitted: an undeclared embedder is
// a refused embedder.
//
// One origin, never a list and never a wildcard. A preview pane has exactly one
// embedder, so a list buys no capability, and `*` would let any page on the
// network frame a dev server that is holding a signed-in session. A value that
// is not a bare scheme://host[:port] is refused back to `'none'` rather than
// forwarded: the policy below is assembled by joining on "; ", so a value
// carrying a semicolon would otherwise append directives of its own and rewrite
// the entire thing.
const FRAME_ANCESTOR_ORIGIN = /^https?:\/\/[A-Za-z0-9.-]+(?::\d{1,5})?$/;

function declaredFrameAncestors(declared: string | undefined): string {
  const origin = (declared ?? "").trim();
  if (!origin) return "'none'";
  if (!FRAME_ANCESTOR_ORIGIN.test(origin)) {
    // Loud on purpose. The symptom otherwise is a blank preview pane and a CSP
    // violation in a console nobody is looking at.
    console.warn(
      "[terp] TERP_DEV_FRAME_ANCESTORS is not a bare scheme://host[:port] " +
        `origin (${JSON.stringify(origin)}); frame-ancestors stays 'none' and ` +
        "this app cannot be embedded in a preview.",
    );
    return "'none'";
  }
  return origin;
}

// The dev server's Content-Security-Policy (ADR 0104 §4, ADR 0107). The
// production nginx config serves a strict policy; this keeps development on the
// same *origin* rules so a third-party resource fails the moment it is added
// rather than at deploy. Measured against a running dev server in Chromium: a
// CDN script, an external stylesheet and a fetch to another origin are each
// refused here, while HMR still connects and the chrome renders fully styled.
//
// `frame-ancestors` is the one directive that may differ from production, and
// only by declaration — production is served to browsers, development is served
// to a workbench that has to show it.
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
  // 'none' unless a preview workbench declares its origin (see above).
  `frame-ancestors ${declaredFrameAncestors(process.env.TERP_DEV_FRAME_ANCESTORS)}`,
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
