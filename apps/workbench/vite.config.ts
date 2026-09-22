import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import type { Plugin } from "vite";

// The workbench dev server. `@terpjs/react-core` ships raw TypeScript and is resolved through
// the workspace link, so Vite compiles it from source — which is the point: a change to a
// component shows up on reload with no build step in between.

/**
 * The fixed identity behind the signed-in specimens (`UserMenu`, `ProfileView`, and
 * `ResourceList`'s write gate). `TerpProvider` boots by exchanging the refresh cookie for an
 * access token and loading `/me`; these two handlers answer that boot with the same user on
 * every run, so a specimen behind the auth seam renders identically without a backend — the
 * same determinism rule every specimen already follows, applied to the session. Rank 30
 * clears the default admin threshold, so the write-gated affordances are in the picture.
 */
const FIXED_USER = {
  id: "00000000-0000-4000-8000-000000000001",
  email: "demo@terp.dev",
  role_name: "Administrator",
  role_rank: 30,
};

/**
 * The declared role ladder behind `admin-user-create`.
 *
 * That specimen mounts the real `UserCreate`, and the screen stopped being self-contained when
 * it started reading the app's own ladder from `GET /api/v1/access/model` rather than hardcoding
 * three ranks (ADR 0022 — the role model belongs to the application). Without an answer the
 * fetch fails, the role `Select` renders with no options and the submit button stays disabled,
 * so the specimen pictured an unusable form and the baseline gated nothing about the layout it
 * exists for: `admin-form` caps the width at 32rem, and only full-width content shows the cap.
 *
 * Three rungs with the packaged names, so the framework's own translations apply and the picture
 * is the same on every run — the determinism rule the fixed user above already follows.
 */
const DECLARED_LADDER = {
  roles: [
    { name: "viewer", rank: 10 },
    { name: "editor", rank: 20 },
    { name: "admin", rank: 30 },
  ],
  permissions: [],
  modules: [],
};

function mockAuth(): Plugin {
  return {
    name: "workbench-mock-auth",
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        if (req.url === "/api/v1/auth/refresh" && req.method === "POST") {
          res.setHeader("content-type", "application/json");
          res.end(JSON.stringify({ access_token: "workbench-fixed-token" }));
          return;
        }
        if (req.url === "/api/v1/me/" && req.method === "GET") {
          res.setHeader("content-type", "application/json");
          res.end(JSON.stringify(FIXED_USER));
          return;
        }
        if (req.url === "/api/v1/access/model" && req.method === "GET") {
          res.setHeader("content-type", "application/json");
          res.end(JSON.stringify(DECLARED_LADDER));
          return;
        }
        next();
      });
    },
  };
}

export default defineConfig({
  plugins: [react(), mockAuth()],
  server: { port: 5175, strictPort: true },
  preview: { port: 5175, strictPort: true },
});
