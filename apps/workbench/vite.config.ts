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

/**
 * The answers behind `admin-hub`, which mounts the real `AdminHub` (ADR 0171).
 *
 * The hub reads four things on mount: the accounts, the active ones (a total under the status
 * filter), the groups, and the trail's activity per day. Fixed here on the same determinism
 * grounds as the user and the ladder above, as a fixture whose parts agree with each other:
 * thirty days ending 4 October that hold 616 changes, broken down by kind and by record type
 * into the same 616, and a last week of 157 against the 147 before it. The dates are fixed
 * rather than relative to today, so the picture does not move with the calendar.
 */
const ADMIN_HUB_COUNTS = [
  4, 2, 28, 35, 22, 31, 19, 6, 3, 33, 41, 27, 30, 24, 5, 2, 26, 33, 22, 41, 19, 4, 2, 31, 27, 38,
  29, 24, 5, 3,
];
const ADMIN_HUB_COUNTS_BEFORE = [
  3, 1, 21, 29, 25, 18, 22, 3, 2, 27, 30, 19, 26, 21, 4, 3, 24, 22, 28, 31, 17, 2, 1, 25, 29, 23,
  20, 26, 3, 2,
];
const hubDay = (offset: number, count: number) => ({
  date: new Date(Date.UTC(2026, 8, 5 + offset)).toISOString().slice(0, 10),
  count,
});
const ADMIN_HUB_ACTIVITY = {
  time_zone: "Europe/Amsterdam",
  days: ADMIN_HUB_COUNTS.map((count, index) => hubDay(index, count)),
  previous_days: ADMIN_HUB_COUNTS_BEFORE.map((count, index) => hubDay(index - 30, count)),
  by_action: [
    { action: "updated", count: 352 },
    { action: "created", count: 158 },
    { action: "disclosed", count: 86 },
    { action: "deleted", count: 20 },
  ],
  by_target_type: [
    { target_type: "Order", count: 221 },
    { target_type: "User", count: 132 },
    { target_type: "Customer", count: 118 },
    { target_type: "GroupMember", count: 96 },
    { target_type: "Group", count: 49 },
  ],
  total: 616,
};
const page = (total: number) => ({ items: [], total, skip: 0, limit: 1 });

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
        const url = new URL(req.url ?? "/", "http://workbench");
        const hubAnswer =
          req.method !== "GET"
            ? undefined
            : url.pathname === "/api/v1/users/"
              ? page(url.searchParams.get("is_active") === "true" ? 42 : 45)
              : url.pathname === "/api/v1/groups/"
                ? page(7)
                : url.pathname === "/api/v1/audit/activity"
                  ? ADMIN_HUB_ACTIVITY
                  : undefined;
        if (hubAnswer !== undefined) {
          res.setHeader("content-type", "application/json");
          res.end(JSON.stringify(hubAnswer));
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
