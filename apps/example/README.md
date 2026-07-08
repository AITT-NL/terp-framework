# `apps/example/` — neutral example app

A company‑agnostic application that consumes the **packaged** `terp.core` and the
opt‑in capabilities. It is the platform's dogfood: every framework guarantee is
exercised end‑to‑end here, and the `terp.arch` harness runs against it clean.

## Layout

- `app/main.py` — the composition root. `create_app(...)` mounts the modules
  behind the deny‑by‑default guard and wires the discovered capabilities
  (auth, audit, events, permissions).
- `app/auth.py` — login wiring; the `auth` capability's `authenticate` callback
  is backed by the `identity` store.
- `app/modules/notes/`, `app/modules/tasks/`, `app/modules/journals/`, and
  `app/modules/projects/` — four neutral secure‑CRUD
  modules in the canonical `models` / `schemas` / `service` / `router` /
  `module` shape. Between them they exercise `BaseTable` + optimistic
  concurrency, `BaseSchema` / `BaseUpdateSchema`, mandatory pagination, the
  uniform error envelope, soft delete, actor stamping, audit auto‑emit, and a
  typed domain event.
- `control_plane/` — the single authority surface: the permission model, the
  security config, the audit policy, and the typed event catalog, declared once
  instead of scattered through the modules.

## Run the workbench

Run it the "right way" — a Postgres-backed stack that seeds a usable admin and live-reloads:

```bash
docker compose -f apps/example/docker-compose.yml watch
```

That brings up Postgres, runs the migrations, seeds `admin@acme.test` (password
`correct horse battery staple`) plus demo notes / tasks / journal / projects, then serves the
API (`:8000`) and the frontend (`:5173`). Open the frontend and log in. Set `API_PORT` /
`WEB_PORT` in a `.env` (see `.env.example`) if those host ports are busy.

Prefer local processes? `terp dev` runs uvicorn + Vite together (SQLite); bootstrap a first
admin with `terp user create admin@acme.test --role admin` and seed with `terp seed`.

## Run it

```bash
uv run pytest apps/example/tests     # or the repo‑wide `uv run pytest`
```

With the workbench running, the app's own browser flows (its notes / tasks / projects / journals
modules) run with Playwright — composing the app-agnostic helpers from `@terp/conformance`
(login, seeded role credentials) with this app's seed expectations in `frontend/e2e/`:

```bash
npm run -w @terp-example/frontend test:e2e     # base-profile flows: npm run -w @terp/conformance test
```

The frontend escape‑hatch budget is empty (`frontend/escape-hatch-budget.json`
→ `{}`); the backend budget (`escape-hatch-budget.json`) carries exactly one
governed opt‑out (`arch-allow-no-manual-ownership-checks: 1`), so the app
passes the architecture harness clean.
