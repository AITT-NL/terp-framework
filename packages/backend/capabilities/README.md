# `packages/backend/capabilities/` — `terp-cap-*` (Phase 2)

Opt‑in cross‑cutting capabilities, each its own `terp-cap-*` distribution.
Built so far: **`auth`, `identity`, `access`, `audit`, `eventbus`, `tenancy`,
`users`, `groups`, `files`, `webhooks`, `oidc`, `outbox`, `sync`, `redis`,
`jobs_celery`, `scheduler_apscheduler`, and `scheduler_celery_beat`**.
Capabilities that expose a router
**self‑register** via a `terp.capabilities` entry point
(`create_app(discover_capabilities=True)`); a **library** capability like
`tenancy` or **`identity`** ships no router and is imported directly by the code
that uses it.

Each capability is its own distribution `terp-cap-<name>` importing as
`terp.capabilities.<name>` (PEP 420 namespace: no `__init__.py` at
`src/terp/` or `src/terp/capabilities/`; only the leaf
`src/terp/capabilities/<name>/__init__.py` exists).

Built capabilities (design §3.1, §6):

| Capability | Distribution | Import |
|---|---|---|
| **identity** (library) | `terp-cap-identity` | `terp.capabilities.identity` |
| **auth** | `terp-cap-auth` | `terp.capabilities.auth` |
| **tenancy** (library) | `terp-cap-tenancy` | `terp.capabilities.tenancy` |
| **access** (RBAC) | `terp-cap-access` | `terp.capabilities.access` |
| **users** | `terp-cap-users` | `terp.capabilities.users` |
| **groups** (permission-bundling user groups) | `terp-cap-groups` | `terp.capabilities.groups` |
| **files** (pluggable storage) | `terp-cap-files` | `terp.capabilities.files` |
| **audit** | `terp-cap-audit` | `terp.capabilities.audit` |
| **eventbus** | `terp-cap-eventbus` | `terp.capabilities.eventbus` |
| **webhooks** (outbound webhooks, sealed secrets) | `terp-cap-webhooks` | `terp.capabilities.webhooks` |
| **oidc** (SSO via OpenID Connect) | `terp-cap-oidc` | `terp.capabilities.oidc` |
| **outbox** (durable event delivery) | `terp-cap-outbox` | `terp.capabilities.outbox` |
| **sync** (data synchronisation) | `terp-cap-sync` | `terp.capabilities.sync` |
| **redis** (shared Idempotency/Throttle/Cache stores, ADR 0078; realtime tickets / OIDC state behind `[realtime]` / `[oidc]`, or both with `[all]`) | `terp-cap-redis` | `terp.capabilities.redis` |
| **jobs_celery** (Celery job backend) | `terp-cap-jobs-celery` | `terp.capabilities.jobs_celery` |
| **scheduler_apscheduler** (APScheduler backend) | `terp-cap-scheduler-apscheduler` | `terp.capabilities.scheduler_apscheduler` |
| **scheduler_celery_beat** (Celery beat backend) | `terp-cap-scheduler-celery-beat` | `terp.capabilities.scheduler_celery_beat` |

The **base profile** (design §13, Phase 2) is core + auth + access + identity +
users. Capabilities are discovered via **entry points** (installable)
so adding one mounts its router and exposes its models to migrations without
editing any composition root.
