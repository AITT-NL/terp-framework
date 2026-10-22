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
| `SECRET_KEY` | yes | ≥ 32 chars; signs access tokens and seals values at rest, each through a key derived for that use (ADR 0055, 0189) |
| `SECRET_KEY_FALLBACKS` | no | Previous keys, comma-separated, that only **verify** signatures, each for its own lifetime (ADR 0076, 0189); each ≥ 32 chars, never `SECRET_KEY` itself — see [Rotating `SECRET_KEY`](#rotating-secret_key) |
| `SECRET_KEY_DECRYPT_FALLBACKS` | no | Previous keys, comma-separated, that only **decrypt** values sealed at rest, until `terp secrets reseal` has moved them (ADR 0189); same rules |
| `POSTGRES_PASSWORD` | yes | Bundled Postgres; compose fails fast when unset |
| `DATABASE_URL` | derived | Defaults to the bundled `db` service. Set it to run on a managed/external PostgreSQL — then also drop the `db` service (and the `depends_on` waiting on it) with a compose override |
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

  **Dump the whole database, not a table list.** A Terp schema is not one migration
  history: every table-owning package keeps its own, behind its own
  `alembic_version_<label>` table, and the boot guard refuses to start when any package's
  schema is behind. A restore that drops one of those bookkeeping tables succeeds
  silently — every real table and every row arrives — and then the app fails to start
  with a message about pending migrations, which reads as a deploy problem rather than as
  a bad backup. If you do filter what you dump, `alembic_version_*` is not optional.

  **Rehearse the restore.** Restore into a clean database and start the app against it;
  a backup nobody has restored is a hypothesis. The platform's own PostgreSQL lane runs
  exactly that drill on every push (`tests/architecture/test_migrations_conformance.py`),
  so the shape is there to copy.
- **Secrets:** environment only; nothing falls back to a dev default in the prod
  profile. `SECRET_KEY` rotates without signing anyone out or losing a sealed value —
  follow [Rotating `SECRET_KEY`](#rotating-secret_key) below, in order.
- **Scaling caveats (single-instance defaults):** the rate limiter / login lockout /
  idempotency-key replay use in-memory stores by default — multi-instance deployments
  must plug the shared stores (ADR 0036); `terp-cap-redis` ships Redis-backed
  `ThrottleStore` / `IdempotencyStore` / `CacheStore` adapters (ADR 0078). Background
  delivery (outbox / webhooks / scheduler) runs via
  `terp jobs worker` / `terp jobs scheduler` — add those as extra services when you
  enable the corresponding capabilities.
- **Observability:** structured JSON logs with request-ids ship by default (ADR 0005);
  collect container stdout. OpenTelemetry wiring is on the roadmap.

## Rotating `SECRET_KEY`

`SECRET_KEY` signs (access tokens, the digest a refresh session is found by) and seals (sealed
config, webhook signing secrets, MFA enrolments). A signature lives minutes or days; a sealed value
lives as long as its row and every backup holding it. So a previous key is kept in two lists that
come out at different times (ADR 0189). Nothing is ever signed or sealed with an entry of either.

| List | Does | Drop it when |
|---|---|---|
| `SECRET_KEY_FALLBACKS` | verifies only: an access token for 15 minutes after it was issued, a refresh session until its own expiry | the longest signature lifetime has passed since the deploy that added it: `REFRESH_TOKEN_TTL_SECONDS` (7 days by default) if the app issues refresh sessions, 15 minutes if not |
| `SECRET_KEY_DECRYPT_FALLBACKS` | decrypts only: every value sealed at rest | `terp secrets reseal` reports nothing left under it |

Both are comma-separated, and declared in the template's `environment.schema.json`, so a deploy
pipeline renders them into `.app.env`; deploying by hand, write them there yourself. In
production the app refuses to boot when an entry is weak, is `SECRET_KEY` itself, or appears
twice, and names the entry by position, never by value.

The procedure, in this order:

1. **Swap and keep.** Put the current key in **both** lists and a new one in `SECRET_KEY`, then
   deploy. Every session and every sealed value keeps working.

   ```bash
   # .app.env (the pipeline renders it; by hand, write it next to the compose file)
   SECRET_KEY_FALLBACKS=<the key SECRET_KEY held until now>
   SECRET_KEY_DECRYPT_FALLBACKS=<the key SECRET_KEY held until now>
   ```

   ```bash
   export SECRET_KEY="$(openssl rand -hex 32)"
   docker compose -f docker-compose.prod.yml up -d --wait
   ```

2. **Re-seal.** Run the re-seal in the app's own container, so it reads the deployed environment:

   ```bash
   docker compose -f docker-compose.prod.yml run --rm api terp secrets reseal
   ```

   It rewrites every value sealed under a fallback under `SECRET_KEY`, one transaction per
   table, never overwrites a value the app changed meanwhile, and refuses to run while a
   migration is pending. It is safe to run twice. It exits 0 only when every sealed value opens
   under `SECRET_KEY`; `--check` counts without writing, and `--format json` is for a pipeline.

3. **Drop the decrypt list** once the re-seal reports nothing left, and deploy. Keep the old key
   in your custody for as long as a backup taken before step 2 may be restored: a restored
   database holds values sealed under it, so restoring one means listing the key in
   `SECRET_KEY_DECRYPT_FALLBACKS` again and re-sealing.

4. **Drop the verify list** once the longest signature lifetime has passed since step 1, and
   deploy. Dropping it sooner loses no data; it signs out the sessions still on the old key.

A key you believe has **leaked** goes in `SECRET_KEY_DECRYPT_FALLBACKS` only, never in
`SECRET_KEY_FALLBACKS`: whoever holds it could sign a token that the fallback would honour, so
every session it signed should end at the deploy.

Rotating `POSTGRES_PASSWORD` is a separate change: the bundled database keeps the password it was
initialised with until you change the role's password (`ALTER ROLE`) to match.

## CI guard

The production profile is itself CI-verified: `.github/workflows/prod-smoke.yml` builds
the prod images, boots the profile, bootstraps an admin with `terp user create`, logs in
through the nginx `/api` proxy, exercises an authenticated round-trip, and asserts that
`terp seed` refuses production. The structure tests in
`tests/architecture/test_prod_profile.py` hold the profile's hardening invariants (no
seed service, no dev secret fallback, no `--reload`, multi-stage wheel images, non-root,
template parity) at every gate run.
