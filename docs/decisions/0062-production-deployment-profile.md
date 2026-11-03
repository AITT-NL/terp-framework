# 0062 - Production deployment profile (Phase G completion)

- **Status:** Accepted; amended 2026-10-21 (the template's images install the committed locks, in layers)
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

## Amendment (2026-10-21): the template's images install the committed locks, in layers

Decision 1 said the runtime installs "only the wheels", and for the template that was true of
what the image held and not of where its versions came from. The template's backend image
installed the app wheel with `uv pip install`, which ignores `uv.lock` and resolves every terp-*
and third-party package from the index during the build; the ASGI server and the database
driver were named on that command line unpinned. Its frontend image ran `npm install`, which
rewrites a lock that disagrees with `package.json`. Both copied the whole checkout before
installing anything, so every edit re-ran every install. An image could therefore ship versions
the gate had never run and the dependency audit had never read.

1. **The locks are the install.** The backend image runs `uv sync --locked --no-dev` and the
   frontend image `npm ci`, and both refuse a lock that disagrees with its manifest. `uv sync`
   and not a hashed `uv export`: a lock that names pre-release wheels vendored under
   `.terp-dist/wheels` records them by path and without a hash, which a `--require-hashes`
   install refuses, and `--locked` is uv's own answer to whether the lock still matches the
   manifest. The server and the driver are runtime dependencies of the app, so the lock pins
   them. The template's CI installs the same way (`uv sync --locked`, `npm ci`).
2. **Layers follow their inputs.** The manifest and the lock first, the dependencies installed
   from them in their own layer, the app last; the runtime image is the base, the locked
   environment and the app. The web image copies nothing from outside `frontend/` but the
   vendored tarballs. Neither production Dockerfile carries a BuildKit cache mount, so a
   release build cannot read a cache a development build wrote; the images do need BuildKit,
   for bind mounts between stages and an optional COPY pattern.
3. **The build context holds no secret.** `.dockerignore` carries every pattern `.gitignore`
   keeps out of a commit, matching the same paths, held to it by
   `tests/architecture/test_template_build_inputs.py`.

`apps/example` keeps decision 1 as written: it builds from the monorepo with every terp
distribution as a local wheel, and has no lock of its own to install.
