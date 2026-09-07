import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The dev server proxies /api to the running Terp backend, so the app calls the API
// same-origin and there is no CORS to configure in development. The target defaults to
// uvicorn on localhost:22100 (the `terp dev` layout) and is overridable via TERP_API_PROXY
// (the Docker workbench points it at the `api` service, and `terp dev` passes the port it
// actually bound -- so this literal is the last resort for a bare `npm run dev`, not the
// value either supported loop relies on).
const apiProxyTarget = process.env.TERP_API_PROXY ?? "http://localhost:22100";

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
// A LIST of exact origins, and never a wildcard. This started as one origin, on
// the reasoning that a preview pane has exactly one embedder — and that premise
// was wrong in a way that cost real time. One WORKBENCH has several names: the
// same machine answers as `localhost`, as `127.0.0.1`, as its hostname and as a
// LAN address, and a browser's CSP check compares exact strings. Whoever's
// address bar said the other spelling got a blank pane, from an app that was
// correctly configured, with a policy that named the "right" origin. Every name
// the workbench legitimately answers on has to be in the list.
//
// A bounded list of exact origins is not the thing the wildcard ban was about.
// `*` would let any page on the network frame a dev server that is holding a
// signed-in session; naming the four addresses of one developer machine does
// not. So: whitespace-separated (CSP's own syntax), every element validated,
// count capped, and one bad element refuses the WHOLE value rather than being
// quietly dropped — a partially applied security header is the kind of thing
// that looks fine until the one origin you needed is the one that was skipped.
//
// The policy below is assembled by joining on "; ", so a value carrying a
// semicolon would otherwise append directives of its own and rewrite the entire
// thing. That is what the anchors on each element are for.
const FRAME_ANCESTOR_ORIGIN = /^https?:\/\/[A-Za-z0-9.-]+(?::\d{1,5})?$/;
//: Enough for every name one workbench answers on, few enough that a runaway
//: value cannot turn the header into a page of origins.
const FRAME_ANCESTOR_LIMIT = 8;

function declaredFrameAncestors(declared: string | undefined): string {
  const value = (declared ?? "").trim();
  if (!value) return "'none'";
  const origins = [...new Set(value.split(/\s+/))];
  const refuse = (why: string): string => {
    // Loud on purpose. The symptom otherwise is a blank preview pane and a CSP
    // violation in a console nobody is looking at.
    console.warn(
      `[terp] TERP_DEV_FRAME_ANCESTORS ${why} (${JSON.stringify(value)}); ` +
        "frame-ancestors stays 'none' and this app cannot be embedded in a preview.",
    );
    return "'none'";
  };
  if (origins.length > FRAME_ANCESTOR_LIMIT) {
    return refuse(`lists more than ${FRAME_ANCESTOR_LIMIT} origins`);
  }
  const bad = origins.find((origin) => !FRAME_ANCESTOR_ORIGIN.test(origin));
  if (bad !== undefined) {
    return refuse(`contains ${JSON.stringify(bad)}, which is not a bare scheme://host[:port]`);
  }
  return origins.join(" ");
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
    // In the range Terp owns, not Vite's own 5173. `terp dev` passes `--port`
    // explicitly and the Compose file pins the container side, so the one caller
    // this default serves is a developer running `npm run dev` by hand -- which
    // is exactly the case that used to land on top of whatever else they had
    // running on 5173.
    port: 21100,
    // Same policy every dev session, so a CSP-incompatible pattern cannot be
    // introduced unnoticed and discovered only in production.
    //
    // `no-store`, not `no-cache`. The two are easy to mix up and the difference
    // was a live defect: `no-cache` means "revalidate before reusing", so the
    // browser still STORES the response, and Vite answers a revalidation with a
    // bare `304 Not Modified` carrying no headers. RFC 9111 keeps the stored
    // headers that a 304 omits — so the browser goes on enforcing the CSP it
    // saved earlier. The ETag is computed from the document body, which does not
    // change when this policy does, so the stale policy is reused indefinitely:
    // measured, an app upgraded to a template that permits framing was still
    // refusing it in a browser that had visited before the upgrade, while a
    // fresh browser worked. A security header whose cache key does not include
    // the header must not be cacheable at all.
    headers: {
      "Content-Security-Policy": devContentSecurityPolicy,
      "Cache-Control": "no-store",
    },
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
