# Deploying a Terp app

How to run a Terp application in production (ADR 0062). The reference hosting target is
a **single host running Docker Compose** — the production profile in
`docker-compose.prod.yml`. Kubernetes and PaaS manifests are intentionally deferred until
a consumer proves the need; the profile's shape (one-shot migrate job → immutable API
image → static-SPA web tier) translates directly to an init-container / Job when that day
comes.

## Topology

```
browser ──► web (nginx, port 8080)
              ├── /            static SPA bundle (vite build, SPA fallback)
              └── /api/…  ──►  api (uvicorn, immutable image)
                                 └── db (Postgres 17)
   one-shot, before api serves:  migrate (terp migrate upgrade)
```

- The SPA is served **same-origin** with the API behind nginx, so production needs no
  CORS configuration (`BACKEND_CORS_ORIGINS` stays empty unless you split origins).
- `migrate` runs to completion before `api` starts (`service_completed_successfully`);
  the app's fail-closed boot guard (`PendingMigrationsError`, ADR 0027) backs the
  ordering up at runtime — an API with a stale schema refuses to serve.
- There is **no seed service**: `terp seed` refuses `ENVIRONMENT=production` by design.

## Quickstart (single host)

```bash
export SECRET_KEY="$(openssl rand -hex 32)"     # >= 32 chars, required
export POSTGRES_PASSWORD="$(openssl rand -hex 16)"

docker compose -f docker-compose.prod.yml up -d --wait --build

# Bootstrap the first administrator (the password rides an env var, never argv):
docker compose -f docker-compose.prod.yml run --rm \
  -e TERP_USER_PASSWORD api \
  terp user create admin@your-domain.example --role admin
```

The app is now on `http://<host>:8080` (put your TLS terminator — a cloud load balancer,
Caddy, or certbot-managed nginx — in front; the refresh cookie is `Secure` in
production, so **HTTPS is required** for logins to work in real browsers).

## Environment reference

Production is **fail-fast**: with `ENVIRONMENT=production` the app refuses to boot on a
weak `SECRET_KEY`, `DEBUG=true`, SQLite, CORS `*`, or an insecure refresh cookie
(`terp.core.config`, mirrored by the structure tests in
`tests/architecture/test_prod_profile.py`).

| Variable | Required | Notes |
|---|---|---|
| `ENVIRONMENT` | yes | `production` (set by the profile) |
| `SECRET_KEY` | yes | ≥ 32 chars; JWT signing + config sealing (ADR 0055) |
| `SECRET_KEY_FALLBACKS` | no | Previous keys (JSON list) for zero-downtime rotation (ADR 0076); each ≥ 32 chars |
| `POSTGRES_PASSWORD` | yes | Bundled Postgres; compose fails fast when unset |
| `DATABASE_URL` | derived | Set explicitly for a managed database |
| `BACKEND_CORS_ORIGINS` | no | Deny-by-default; only for cross-origin SPAs, never `*` |
| `DB_POOL_SIZE` / `DB_MAX_OVERFLOW` / `DB_POOL_TIMEOUT` / `DB_POOL_RECYCLE` | no | Pool tuning (ADR 0024) |
| `REFRESH_TOKEN_TTL_SECONDS` / `REFRESH_FAMILY_TTL_SECONDS` | no | Session windows (ADR 0054) |
| `REFRESH_COOKIE_SECURE` | no | Derived on in production; do not disable |
| `DB_SCHEMA_LAYOUT` | no | `per-module` places each package's tables in its own PostgreSQL schema (ADR 0070) |
| `WEB_PORT` | no | Host port for nginx (default 8080) |

### App-declared variables (`environment.schema.json`)

Variables the app itself needs (an SMTP relay, a third-party API key, a feature
flag) are **declared, never invented at deploy time**: add them to the
check-in manifest `environment.schema.json` at the project root — the same
JSON-schema dialect the deploy-target kinds use. Names are UPPER_SNAKE
(`^[A-Z][A-Z0-9_]{0,63}$`); the platform-owned names in the table above may
not be shadowed; `"format": "secret"` marks a value as write-only sealed
custody.

Both compose profiles forward the declared variables through one generic seam:
the backend services read an optional `.app.env` next to the compose file
(`required: false` — plain `docker compose up` works without it). A deploy
pipeline (the Terp Studio) renders exactly the declared keys into that file,
owner-only; deploying by hand, write it yourself. `.app.env` is gitignored and
dockerignored — it may hold secrets and must never be committed or baked into
an image. Frontend (`VITE_*`) values are build-time, not run-time, and do not
belong in this manifest.

## Least-privilege database (optional hardening)

Two opt-in tiers on PostgreSQL, applied in order (ADR 0070 / ADR 0071):

1. **Per-module schemas** — each package's tables live in their own schema instead of
   one flat `public`. Fresh database: set `DB_SCHEMA_LAYOUT=per-module` on the
   `migrate` and `api` services before the first upgrade. Existing database: move it
   in place once (idempotent; data moves with the tables, migration state stays in
   `public`):

   ```bash
   docker compose -f docker-compose.prod.yml run --rm api terp migrate adopt-schemas
   ```

2. **Owner / runtime role split** — migrate as the owning role, serve as a login that
   holds ONLY DML. The database itself then refuses DDL and any write to `public`
   (migration state included), no matter what the app process does:

   ```bash
   # once, as the database admin:
   psql -c "CREATE ROLE terp_rt LOGIN PASSWORD '…'"
   docker compose -f docker-compose.prod.yml run --rm api \
     terp migrate grant-runtime terp_rt
   ```

   Point the `api` service's `DATABASE_URL` at `terp_rt`; keep the `migrate` one-shot
   on the owning role. Run `grant-runtime` as that same owning role — or pass
   `--owner-role <role>` so `ALTER DEFAULT PRIVILEGES` is scoped to it — and future
   upgrades keep the runtime covered automatically (re-running after an upgrade is
   idempotent and cheap). One deliberate boundary: the runtime role spans every
   module's write schema — audit/outbox rows commit atomically with the business
   write on one session (ADR 0007/0045) — so module-to-module isolation stays
   code-enforced, not database-enforced.


## Operational notes

- **Health:** `GET /health/live` (process up) and `GET /health/ready` (DB reachable) on
  the API (ADR 0024); both containers ship `HEALTHCHECK`s and the profile uses
  `--wait`-able healthchecks + `restart: unless-stopped`.
- **Migrations on upgrade:** pull/build the new images, re-run the `migrate` one-shot,
  then restart `api`. `docker compose -f docker-compose.prod.yml up -d --wait --build`
  does all three in order.
- **DBA-gated releases:** where the migration runner may not touch production, render
  the upgrade as reviewable SQL instead — `terp migrate upgrade --sql > release.sql`
  connects to nothing and includes the version-table bookkeeping, so a script-applied
  database still reports current to the boot guard (flat layout; ADR 0072).
- **Transaction-pooling proxies (PgBouncer):** the per-connection `statement_timeout`
  rides a startup parameter such poolers may not pass through. Production refuses
  `DB_STATEMENT_TIMEOUT_MS=0` (a statement timeout is required — fail closed), so
  either run the pooler in session-pooling mode (startup parameters pass through), or
  pin the timeout at the role (`ALTER ROLE terp_rt SET statement_timeout = '30s'`)
  and route the app through a pooler that accepts (or strips) the `options` startup
  parameter while keeping `DB_STATEMENT_TIMEOUT_MS` positive.
- **Backups:** the state lives in the `db-data` volume (and your file-storage backend if
  the `files` capability is on) — snapshot it with your regular Postgres tooling
  (`pg_dump` via `docker compose exec db`).
- **Secrets:** environment only; nothing falls back to a dev default in the prod
  profile. Sealed config values (ADR 0055) decrypt with `SECRET_KEY` — rotating it
  invalidates outstanding JWTs and sealed values, so plan rotations.
- **Scaling caveats (single-instance defaults):** the rate limiter / login lockout /
  idempotency-key replay use in-memory stores by default — multi-instance deployments
  must plug the shared stores (ADR 0036); `terp-cap-redis` ships Redis-backed
  `ThrottleStore` / `IdempotencyStore` / `CacheStore` adapters (ADR 0078). Background
  delivery (outbox / webhooks / scheduler) runs via
  `terp jobs worker` / `terp jobs scheduler` — add those as extra services when you
  enable the corresponding capabilities.
- **Observability:** structured JSON logs with request-ids ship by default (ADR 0005);
  collect container stdout. OpenTelemetry wiring is on the roadmap.

## CI guard

The production profile is itself CI-verified: `.github/workflows/prod-smoke.yml` builds
the prod images, boots the profile, bootstraps an admin with `terp user create`, logs in
through the nginx `/api` proxy, exercises an authenticated round-trip, and asserts that
`terp seed` refuses production. The structure tests in
`tests/architecture/test_prod_profile.py` hold the profile's hardening invariants (no
seed service, no dev secret fallback, no `--reload`, multi-stage wheel images, non-root,
template parity) at every gate run.
