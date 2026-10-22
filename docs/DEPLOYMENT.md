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
export TERP_RELEASE_TAG="$(git rev-parse --short=12 HEAD)"   # required, new per release

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
| `TERP_RELEASE_TAG` | yes | The tag of this release's images, `<project>-backend-prod:<tag>` and `<project>-frontend-prod:<tag>` (ADR 0185): a Docker tag, new for every release, so the previous release's images stay on the host and can be started again. Compose fails fast when unset; it cannot tell a stale value from a new one, so set it per release. Platform-owned: `environment.schema.json` may not declare it |
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

A value only a deployment needs is declared `"requiredIn": ["production"]` rather than
`required`, so the development loop is not asked for it. An outgoing mail relay is the common
case: `MAIL_FROM` and `SMTP_HOST` are required where production runs, the relay is external,
and every environment that is not production gets a mail catcher offering TLS instead, its
authority named in `SMTP_CA_FILE`. A real relay outside production is an operator's choice for
that one environment, kept with the deploying tool's environment policy and never in the
app's files. `uv run terp guide mail` has the declaration block.

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
- **Builds install the committed locks:** the template's backend image runs `uv sync
  --locked --no-dev` and its web image `npm ci`, so an image holds exactly what `uv.lock` and
  `frontend/package-lock.json` record, and a lock that disagrees with its manifest stops the
  build. Commit both locks; `uv lock` and `npm --prefix frontend install` bring them along with
  a dependency change, and `terp verify --only locks` refuses an app with a `deployment.json`
  whose lock is missing or stale before a build finds out. The images are layered (manifests and locks, then the dependencies, then
  the app), carry no BuildKit cache mount, and need BuildKit, the builder of every `docker
  compose` build.
- **Migrations on upgrade:** pull/build the new images, re-run the `migrate` one-shot,
  then restart `api`. With a new `TERP_RELEASE_TAG`,
  `docker compose -f docker-compose.prod.yml up -d --wait --build` does all three in order,
  and leaves the previous release's images under their own tag.
- **Starting the previous release again:** set its `TERP_RELEASE_TAG` and run
  `docker compose -f docker-compose.prod.yml up -d --wait --no-build`. `--no-build` is the
  point: the profile builds the images it names, so with `--build`, or with an image of that
  tag pruned, compose would build this checkout and run it under the old tag. Across a
  migration the previous release's `migrate` refuses a database it does not know; restore
  the backup taken before the upgrade first.
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
  profile. Sealed config values (ADR 0055) decrypt with `SECRET_KEY` — rotating it
  invalidates outstanding JWTs and sealed values, so plan rotations.
- **Scaling caveats (single-instance defaults):** the rate limiter / login lockout /
  idempotency-key replay use in-memory stores by default — multi-instance deployments
  must plug the shared stores (ADR 0036); `terp-cap-redis` ships Redis-backed
  `ThrottleStore` / `IdempotencyStore` / `CacheStore` adapters (ADR 0078). Background
  delivery (outbox / webhooks / scheduler) runs via
  `terp jobs worker` / `terp jobs scheduler` — add those as extra services when you
  enable the corresponding capabilities. The reference app (`apps/reference`) runs both,
  and a companion service, on the backend image in both of its compose profiles.
- **Observability:** structured JSON logs with request-ids ship by default (ADR 0005);
  collect container stdout. OpenTelemetry wiring is on the roadmap.

## The deploy declaration

`deployment.json` at the project root tells a tool that deploys the app which units the
profile runs, how each answers whether it is ready, which migration histories each owns and
what holds state (ADR 0184). The template writes one describing `db`, `migrate`, `api` and
`web`; keep it true when the profile grows, and `terp verify --only deployment` (also run by
`terp check`) says where it is not. It never asks whether a topology is approved, and deploy
policy (who may publish, approvals, gate policy) never belongs in it. The bundled database is
pinned by digest to the datastore table the framework release publishes, so a `docker compose
pull` cannot move it under a running deployment. `uv run terp guide deployment` has the rules.

## Releasing and promoting (`terp release`, `terp promote`)

A declared app can be released as a signed, exact-commit set of images and deployed from it
without a checkout or a rebuild (ADR 0187 decision 6). The release is three jobs, and each is
meant to run on a fresh host that is discarded after it, because the second one runs the app:

| Job | Runs from | Holds | Writes |
|---|---|---|---|
| `terp release build` | the operator's toolchain, never the app's environment | a push credential for this release's repositories | the images, and `terp-release-build.json` (BuildKit's digests) |
| `terp release gate` | a clean checkout of the commit, with the app's environment | at most a pull credential | `terp-release-gate.json` (the release profile's assurance claim, the schedule catalog) |
| `terp release sign` | the signer image (`packages/backend/cli/signer/`) | a way to reach the signer, never the key | `release.dsse.json`, the manifest, an SBOM and a package list per image |

`build` reads the commit from git's object store and builds from that pristine tree in a
BuildKit builder of its own, with fresh bases and no cache; `sign` reads the same commit and the
pushed images as data, holds the backend image's app files, bytecode, installed set and wheel
to the commit and its lock, scans the SBOMs and the history, and signs. Where one machine runs
all three, say so: `--hosts shared` is recorded in the manifest, and the guarantee becomes "the
host is trusted".

`terp promote release.dsse.json --public-key <trusted.pub> --project-dir <dir>` verifies the
envelope before reading it, pulls each image by its signed digest, tags it
`<project>-backend-prod:<tag>` (and the frontend's), writes the carried profile into `<dir>`
and runs it with the release's `TERP_RELEASE_TAG`, the variables the profile names and nothing
else of your environment: put `.app.env` and the secrets there as for a hand deploy. It reads
every `alembic_version_*` table before the migration step (`<dir>/.terp/versions-before-<tag>.json`),
runs the step exactly once, and starts the rest with `--no-build --pull never`. If the deploy
fails and the version tables are as they were, starting the previous release again is
restore-free, and `--undo-to <its envelope>` does it after that release's own `terp migrate
check`; if the step changed them, going back is a restore. A rollback in an invocation of its
own (`--rollback`) has no such reading and is refused until you restore the backup taken
before the release that followed the target and say so with `--restored`.

Both commands need `terp-cli[release]` and refuse without it.

## CI guard

The production profile is itself CI-verified: `.github/workflows/prod-smoke.yml` builds
the prod images, boots the profile, bootstraps an admin with `terp user create`, logs in
through the nginx `/api` proxy, exercises an authenticated round-trip, and asserts that
`terp seed` refuses production. The structure tests in
`tests/architecture/test_prod_profile.py` hold the profile's hardening invariants (no
seed service, no dev secret fallback, no `--reload`, multi-stage wheel images, non-root,
template parity) at every gate run, and `tests/architecture/test_template_build_inputs.py`
holds the template's images to their locks, their layer order and a build context with no
secret in it.
