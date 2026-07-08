# 0062 - Production deployment profile (Phase G completion)

- **Status:** Accepted
- **Date:** 2026-07-03
- **Context phase:** Phase G (deployment to containers) — the prod-profile half left
  open by [ADR 0053](0053-dev-workbench-and-seed-seam.md) (the dev-workbench slice)
- **Relates:** [ADR 0027](0027-packaged-migrations-per-package-histories.md) (the boot
  guard the profile's migrate-then-serve ordering pairs with),
  [ADR 0024](0024-health-endpoints-and-pool-config.md) (the health endpoints the
  healthchecks probe), [ADR 0063](0063-lockstep-release-and-publish-pipeline.md) (the
  release pipeline that publishes the images)

---

## Context

Every runtime artifact in the repository was a **dev** artifact: editable installs and
`uvicorn --reload` in the backend image, the Vite dev server as the only frontend serve
path, a compose file with a fallback dev `SECRET_KEY` and a mandatory seed. The
IMPLEMENTATION_PLAN's Phase G prod profile ("prod guardrails on, secrets via env")
was explicitly unbuilt, and `terp.core.config`'s production fail-fast guardrails — the
runtime half of a two-layer control — had no build-time or CI counterpart proving a
deployable production shape actually exists.

## Decision

**Ship a production profile beside the dev workbench, with the same topology and
two-layer enforcement.**

1. **Backend `Dockerfile.prod` (example + template):** multi-stage — stage 1 builds
   wheels for every terp distribution with `uv build`; stage 2 is a clean
   `python:3.13-slim` runtime installing only the wheels (no source tree, no editable
   installs, no build tooling), non-root (uid 10001), read-only-FS compatible, a
   `HEALTHCHECK` on `/health/live`, and a plain `uvicorn` CMD (no `--reload`). The same
   image backs the one-shot `migrate` job and the `api` server.
2. **Frontend `Dockerfile.prod` + `nginx.conf` (example + template):** stage 1 runs
   `vite build`; stage 2 serves the bundle from `nginxinc/nginx-unprivileged` (non-root,
   port 8080) with an SPA fallback, immutable-asset caching, gzip, and an `/api/`
   reverse proxy to the backend service. **SPA topology decided: same-origin behind
   nginx** — the browser never crosses origins, so production needs no CORS
   configuration; a split-origin deployment remains possible via
   `BACKEND_CORS_ORIGINS`.
3. **`docker-compose.prod.yml` (example + template):** `db → migrate (one-shot) → api +
   web`, with `ENVIRONMENT=production` (arming the config fail-fast guardrails),
   `:?`-required `SECRET_KEY` / `POSTGRES_PASSWORD` (no dev fallback — compose fails
   fast), **no seed service** (`terp seed` refuses production; the sanctioned bootstrap
   is `terp user create` with `TERP_USER_PASSWORD`), restart policies and healthchecks
   on the long-running services, and no source watch (immutable images).
4. **Two-layer guard:** the runtime control is the config fail-fast + the
   pending-migrations boot guard; the build-time half is
   `tests/architecture/test_prod_profile.py` (structure tests over both profiles and
   both image pairs: no seed, required secrets, no `--reload`, multi-stage wheel
   builds, non-root, SPA fallback + same-origin proxy, example↔template parity) **and**
   `.github/workflows/prod-smoke.yml`, which builds and boots the prod profile in CI
   and proves it end-to-end: readiness, `terp user create` bootstrap, login through the
   nginx proxy, an authenticated `/me` round-trip, and `terp seed` refusing production.
5. **Hosting target decided: single-host Docker Compose** is the reference deployment,
   documented in `docs/DEPLOYMENT.md` (topology, environment reference, upgrade /
   backup / scaling notes). Kubernetes / PaaS artifacts are deferred until a consumer
   proves the need (generalise on evidence); the profile's shape maps 1:1 onto an
   init-container/Job when it comes.

## Consequences

- A client can deploy a generated repo to a single host with two secrets and one
  compose command; forgetting either secret fails fast at compose level, and an unsafe
  configuration refuses to boot at app level.
- The dev workbench is untouched (`Dockerfile` / `docker-compose.yml` keep live-sync
  ergonomics); dev and prod share one topology, so conformance e2e keeps guarding the
  shape both profiles use.
- The prod images build from the monorepo tree today; publishing them (and consuming
  published terp packages in client Dockerfiles) is ADR 0063's release pipeline.
- TLS termination stays outside the profile (load balancer / reverse proxy), and the
  refresh cookie is `Secure` in production — deployments must front HTTPS.
