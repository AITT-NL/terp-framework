# 0006 - Cross-cutting controls roadmap and the opinionation policy (Tier A/B/C)

- **Status:** Accepted
- **Date:** 2026-06-24
- **Context phase:** Post Phase C (deciding how far framework opinionation goes)
- **Supersedes/relates:** [docs/IMPLEMENTATION_PLAN.md](../internal/IMPLEMENTATION_PLAN.md) §10,
  [ADR 0002](0002-control-plane-and-auditable-module-authority.md) §3.2,
  [ADR 0005](0005-security-middleware-and-structured-logging.md)

---

## Decision

Terp will keep adding "always correct by default" cross-cutting controls, but
**every such control must be classified into one of three tiers**, and the tier
dictates how opinionated the framework is allowed to be. This is the rule that
lets Terp relieve a consumer of *implementing* cross-cutting concerns without ever
removing their ability to *configure* them — preserving "applicable to any company
or business case."

| Tier | Meaning | Opinionation |
|---|---|---|
| **A — Mandatory** | No business app should skip it. On by default; opt-out is explicit, justified, and **budgeted**. | Maximal: fail-closed runtime control + build-time test. |
| **B — Defaulted, overridable** | Varies by company. A typed control-plane registry ships a safe default; the consumer overrides the *values*, never the *shape*. | The shape is fixed; the content is the consumer's. |
| **C — Optional sugar** | Authoring convenience; never the only path. A module may always drop to native FastAPI/SQLModel with the same arch rules applying. | Provided but avoidable. |

**The governing rule (the "quadruple").** A concern may become a framework control
only if it ships as all four of:

1. a typed control-plane registry with a **safe default**,
2. a **fail-closed runtime control**,
3. a **build-time test** (terp-arch or the kernel suite), and
4. a **budgeted escape hatch**.

If a candidate cannot be expressed as that quadruple, it is a *product* decision,
not a framework control, and it stays out of `terp.core`.

## Roadmap classification (recorded so it is not forgotten)

- **Tier A, built:** authz, error envelope (incl. the catch-all 500), OCC,
  pagination caps, input caps, security headers/CORS/rate-limit/body-size/
  request-id, structured logging + PII redaction.
- **Tier A, next (Phase D):** **audit log of mutations**, auto-emitted from the
  single `BaseService.create/update/delete` chokepoint, with central redaction/
  retention and a budgeted opt-out (`AuditPolicy`).
- **Tier B, planned:** **password policy** (length/complexity/breach — today only a
  `max_length` DoS cap exists, i.e. *no* strength policy), account lockout,
  per-request access logging, **`__tablename__` required + table-name pattern**,
  **route prefix/suffix promoted into the control plane** (today `/api/v1/{name}`
  is hardcoded).
- **Tier C, planned:** a **CRUD router factory** (`build_crud_router(...)`
  returning a native `APIRouter`) and `terp new module` scaffolding.

## Model / route / schema authoring stance

Abstract by **assembling native primitives, not replacing them**:

- **Level 1 (adopt):** an opt-in CRUD router factory + stricter `BaseTable` rules.
  Kills router drift while staying native and verifiable.
- **Level 2 (avoid as the only path):** a declarative model/route DSL. It fights
  SQLModel/FastAPI idioms, caps flexibility, and moves bugs into an opaque
  generator. Code-gen stays in the CLI scaffolding (readable Level-1 output the
  consumer owns), never a runtime black box. Code remains the source of truth.

## Phase C hardening folded in with this decision

Reviewing the shipped Phase C slice surfaced four Tier-A correctness defects, fixed
before proceeding (they complete controls rather than add features):

1. **Logging redaction** now lives on every **handler** (not only the root
   logger), closing a child-logger bypass; sensitive `extra=` fields are redacted.
2. **CORS preflight** responses now carry request-id + security headers (those
   middlewares wrap CORS).
3. **`no_adhoc_middleware`** also catches the `@app.middleware("http")` decorator
   form.
4. **Catch-all exception handler** renders unexpected errors as a generic
   `internal_error` 500 envelope (logged with the request id), so a bug never
   leaks a stack trace nor escapes the uniform contract.

## Consequences

- New cross-cutting work is scheduled by tier; Tier-A items are prioritised and
  must arrive as the full quadruple.
- The next implementation track is **Phase D (audit) as the highest-value Tier-A
  gap**; password policy and the table-name/`__tablename__` rules are the leading
  Tier-B follow-ups; the CRUD router factory is the leading Tier-C item.
- No company-specific value is baked into `terp.core`: Tier-B registries hold the
  *shape*, the consumer supplies the *content*.

## Decision

Status: **Accepted** — adopt the Tier A/B/C opinionation policy and the quadruple
rule; the Phase C hardening is landed (**182 passed, 100% line coverage**).
