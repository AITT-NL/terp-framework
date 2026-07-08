# 0053 - The dev workbench: first-admin bootstrap, a seed seam, and a Postgres Compose stack

- **Status:** Accepted
- **Date:** 2026-07-01
- **Context phase:** Phase G (deployment to containers) — the runnable-workbench slice
- **Relates:** [ADR 0027](0027-packaged-migrations-per-package-histories.md) (packaged
  migrations — `terp migrate upgrade`), [ADR 0013](0013-users-capability-and-identity-boundary.md)
  (the admin-only users surface this bootstraps *around*), [ADR 0032](0032-password-policy-tier-b.md)
  (the password policy the bootstrap admin is still held to), [ADR 0044](0044-current-user-me-endpoint-and-who-am-i-seam.md)
  (the `/me` endpoint the seeded login exercises).

---

## Context

The platform could be built and tested, but not *run and used*: after `terp migrate upgrade`
there was no way to obtain a first login. The admin-only `/users` API cannot mint the **first**
administrator (no admin exists yet to authorize the call — a chicken-and-egg), and there was no
seam for demo data. There was also no container story at all (Phase G was unstarted): the
example ran only under pytest, and the default `DATABASE_URL` is an *in-memory* SQLite with no
startup `create_all`, so a live boot had no schema.

The goal was a workbench a developer (or an agent) can start with one command and actually work
against — the example dogfooding it, and a generated repo getting the same.

## Decision

Ship three seams, plus a Compose workbench, and scaffold them into the template.

1. **`terp user create <email> [--role]`** — provision (or confirm) a user straight against the
   app's store through the audited `UsersService` chokepoint. Idempotent. The password is read
   from an environment variable (`TERP_USER_PASSWORD`) or an interactive prompt — **never a
   command-line argument**, so it cannot leak into shell history or the process table. This is
   the out-of-band bootstrap for the first administrator and the sanctioned production path.

2. **`terp seed`** — run an app-declared seed callable (default `app.seed:seed`) in one
   write-guarded session. **Fail-closed: it refuses to run when `ENVIRONMENT=production`** (seed
   data is dev/demo only). Each app owns its `app/seed.py`; the example seeds a usable admin +
   editor and a few notes/tasks/journal/projects **through the real audited services**, so
   seeding itself exercises audit, events, actor-stamping, ownership, and tenancy. Idempotent, so
   a container may seed on every boot.

3. **A Postgres-backed Compose workbench** (`docker compose watch`, wrapped by
   **`terp docker dev`**): `db` (Postgres, prod-parity — the config layer refuses SQLite in
   production anyway) → one-shot `migrate` → one-shot `seed` → `api` (uvicorn `--reload`) + `web`
   (Vite), health-gated by `depends_on` conditions and the kernel's `/health` endpoints. Editing
   source live-syncs into the running containers. Host ports are configurable and the database is
   internal-only, so the workbench never collides with services already on the host.

4. **Template parity.** The copier template renders the same seam (`app/seed.py`), Dockerfiles,
   `docker-compose.yml`, and `.env.example`, so a generated repo gets `terp docker dev` too.

Supporting change: `bind_audit_actor` is re-exported from `terp.core` (the public actor-stamping
seam) so seed / background code binds the acting principal through the top-level surface.

Rationale:

- **Bootstrap is a real operation, not a hack.** Minting the first admin is a legitimate,
  audited, policy-enforced write; making it a first-class CLI (rather than a documented raw-SQL
  snippet) keeps it on the secure path and available to every Terp app.
- **Secrets never touch argv.** Reading the password from the environment or a prompt is the
  secure-by-default choice; a `--password` flag would be a standing leak.
- **Seed data is dev-only by construction.** The production refusal is a fail-closed runtime
  control (paired with a test), so `terp seed` cannot scribble demo rows into a real store.
- **Production parity in dev.** Running Postgres (not SQLite) in the workbench exercises the same
  migrations, pool, and readiness path a deployment uses, so "works on the workbench" means more.
- **The example is the proof; the template is the parity.** The `apps/example` workbench is
  validated live end-to-end; the template renders the same shape for real users.

## Consequences

- A developer goes from a clean checkout to a seeded, running, log-in-able app with one command.
- Two-layer enforcement holds: the `terp seed` production refusal and the `UsersService` password
  policy are fail-closed runtime controls, each paired with a build-time test; the Compose
  topology is guarded by a structure test.
- The Compose/Dockerfile in the template are aspirational until the `terp-*` packages are
  published (like the existing `uv sync` CI and `@terp/*` frontend deps) — the *shape* is correct
  and the example proves the mechanism.
- `terp docker dev` is a thin wrapper over `docker compose watch`; a repo without Docker still
  uses `terp dev` (local uvicorn + Vite).
