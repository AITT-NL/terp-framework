# 0001 — Terp namespace, brand, and Phase 1 kernel scope

- **Status:** Decision 1 **Accepted** · Decision 2 **Accepted (in principle)** ·
  Decision 3 **Proposed** (promote on evidence from the first vertical slice)
- **Date:** 2026-06-22
- **Context phase:** Phase 0 (boundary design + empty skeleton)
- **Supersedes/relates:** [`AGENTIC_PLATFORM_DESIGN.md`](../../AGENTIC_PLATFORM_DESIGN.md)

> This log separates **decided facts** (safe to encode in the canonical design
> now) from **proposed strategy** (recorded, but not promoted into the design's
> §13 gates until the first vertical slice provides evidence). Keeping the two
> apart is itself a drift‑control measure.

---

## Decision 1 — `terp.*` namespace and Terp brand (Accepted)

**Decision.** The platform is **Terp** ("Trusted Enterprise Reinforced Platform",
tagline "Build on high ground"). The authoritative identifiers are:

| Aspect | Value |
|---|---|
| Python import namespace | `terp.*` (PEP 420 namespace package) |
| Backend distributions | `terp-core`, `terp-arch`, `terp-cli`, `terp-cap-<name>` |
| Capability import path | `terp.capabilities.<name>` |
| npm packages | `@terp/*` |
| CLI command | `terp` |

`platform.*` is forbidden (it shadows a Python stdlib module). The design doc was
authored against a placeholder namespace; this decision **rebrands it at the
source** rather than layering a contradicting addendum on top.

**Name availability (verified Phase 0).** PyPI `terp` and `terp-core` are free;
npm bare `terp` is taken (an unmaintained 2014 package), so the scoped `@terp/*`
is the correct path and the `@terp` org is claimed at publish time.

**Why rebrand the doc instead of an addendum.** An addendum that overrides an
unchanged body is a permanent internal contradiction — guaranteed long‑term
drift. Renaming at the source keeps the doc and the build in agreement.

**Consequences / enforcement (two‑layer, per design §5).**
- The design doc, README, and all package/app/template source use `terp.*`.
- The Phase‑0 extraction docs and this decisions log retain the historical
  `agentic_platform` mentions deliberately (to explain the override); they are
  the only place that token legitimately survives.
- Build‑time guard: [`tests/guardrails/test_no_placeholder_namespace.py`](../../tests/guardrails/test_no_placeholder_namespace.py)
  fails if the placeholder identifier reappears in the canonical/code locations.

---

## Decision 2 — prior art is a pattern corpus, not the abstraction source (Accepted in principle)

**Decision.** Treat prior art as a **test
corpus, cautionary tale, and pattern mine** — evidence of recurring pressures
(what agents break, what needs guardrails) — **not** as the abstraction to
generalise. The durable abstraction Terp builds around is:

> module manifest (`ModuleSpec`) + public API surface + runtime policy
> enforcement + capability contracts + conformance tests.

**Consequences.**
- "Carve `terp-core`" (design §13 Phase 1) means *re‑author the smallest correct
  kernel*, not "copy an existing app's core concepts and rename".
- Architecture tests are ported as an **invariant catalog**, not as a prior app's exact
  AST machinery (delegate generic checks to Tach/deptry/ruff; hand‑roll only the
  domain rules).

---

## Decision 3 — Narrow the Phase 1 kernel; defer the rest to a vertical slice (Proposed)

**Decision (proposed).** Phase 1 ships the **smallest kernel** that lets one real
module exist and be enforced:

1. `ModuleSpec`, `Policy`, `Roles`
2. Error envelope (English/locale‑neutral defaults)
3. `BaseTable` (UUID / timestamps / OCC `version`)
4. `BaseSchema` / `BaseUpdateSchema`
5. Pagination primitives
6. `SessionDep` seam
7. Internal discovery / composition hooks
8. Public/private API enforcement tests (`terp.core` vs `terp.core._internal`)

**Deliberately deferred** until the first vertical slice (a real module + a
neutral example app) gives evidence of the right shape:
- `BaseService` — useful, but CRUD inheritance risks becoming a "god abstraction"
  if frozen before two or three real module shapes exist.
- A default `foundation/` layer — start with core + capabilities + app modules;
  introduce `foundation` only if a neutral app proves the need.
- Tenant‑filter **binding** (the session‑level predicate) — core defines the
  `TenantScoped` marker/protocol; the **tenancy capability** owns the semantics.
- Audit auto‑emission and richer discovery — shaped by the slice, not assumed.

**Phase 1 status (2026-06-22).** The narrow kernel (items 1–8) is **built and
green** in `terp-core` (the `terp.core` public surface + `terp.core._internal`,
enforced by `tests/architecture/`). The deferred items above remain deferred
pending the first vertical slice.

**Status rationale.** Promoting these into the design's §13 gates now would freeze
opinion into doctrine before proof — exactly the premature‑abstraction failure
this decision warns against. Re‑evaluate after Phase 1's slice; promote what holds.

**Open questions for review.**
- Does the first example module live in `template/` or a `terp-examples` package?
- Minimum capability set the slice needs to be meaningful (auth + identity only?).

---

## Decision 4 — Evidence from the first slice (Proposed)

The `apps/example/` **`notes`** slice — a neutral secure-CRUD module over
packaged `terp.core`, with a minimal composition + auth seam built *in the app*,
**8 end-to-end tests green** (CRUD, OCC stale→409, pagination, error envelope,
deny-by-default 401/403, boot-closed on missing policy) — produced this evidence
for Decision 3's deferrals.

**Promote into the kernel next — clearly generic, zero domain logic:**
- `create_app(specs)` — deny-by-default mounting + fail-closed on a missing
  `Policy`. The app's version contains no `notes`-specific code.
- `build_guard(policy)` — the policy→guard mapping (unauthenticated → 401;
  method-aware read/write role → 403). The app should not re-derive authz.
- The `AppError`→envelope exception handler — generic; pairs with `create_app`.
  (Per-request `request_id` should move to a RequestId middleware.)
- A `Page[T]` pagination envelope — `NotesPage` was hand-built boilerplate.
- A `Principal` protocol + the `get_principal` seam — core/`create_app` defines
  the seam; the **auth capability** supplies the implementation.

> Promoting on a single consumer is safe *here* precisely because these pieces
> carry **no domain logic** — a second consumer cannot change their shape, so the
> YAGNI risk that justified deferral does not apply to them.

**Keep deferred — needs a 2nd, divergent module to fix the shape:**
- `BaseService` — `NoteService` is ~40 lines of get/list/create/update(OCC)/
  delete boilerplate, so the pull is real; but CRUD shape varies (relations,
  eager-loading, soft-delete, tenant scoping). Settle it after a 2nd module, not
  on one example.
- `foundation/`, tenant-filter binding, audit auto-emission — untouched by this
  slice; still deferred.

**Recommended next step.** Extract a thin `terp.core.app` (`create_app` + guard +
error handler + `Page`) from the slice so the app declares specs only — then add
a 2nd example module to settle `BaseService`. (Alternative: proceed to Phase 2
capabilities starting with **auth**, which is what fills the `get_principal`
seam.)

**Open questions now answered by the slice.** The first example module lives in
`apps/example/app/modules/` (not `template/` / `terp-examples`); the slice
needed only a stubbed principal seam — real auth is the first capability to build.

Status: **Proposed** (awaiting review).

---

## Decision 5 — Recommendations executed: `terp.core.app` + `BaseService` shipped (Accepted)

Both promotions from Decision 4 are now built and green (**33 tests**).

**`terp.core.app` (Accepted).** `create_app`, `build_guard`, the
`AppError`→envelope handler, the `Principal` + `get_principal` seam, and `Page[T]`
now live in the kernel. The example app **declares specs only**
(`create_app([notes, tasks])`); the app-local `bootstrap.py` / `security.py` were
deleted.

**`BaseService[Model, Create, Update]` (Accepted).** Settled by **two divergent
consumers** (the design's bar):
- `notes` uses it **wholesale** — `NoteService` collapsed to `model = Note`.
- `tasks` overrides exactly the divergent points — `base_query` (soft-delete),
  `delete` (soft), `list` (status filter) — and inherits `create` / `update`.

The shape that made it fit: uniform OCC-bearing `create` / `update` + an
**overridable `base_query`** that `get` / `list` / `delete` build on. Soft-delete
composed by overriding one method; the **same hook hosts tenant scoping later**,
so the kernel stays tenancy-agnostic (the tenancy capability overrides
`base_query` rather than core baking in a predicate).

**Still deferred (genuinely not yet evidenced):** a `foundation/` layer, the
tenant-filter *binding* (core ships `SoftDeleteMixin` + the `base_query` hook; the
session-level predicate is the tenancy capability's job), and audit auto-emission.

**Recommended next:** Phase 2 — the **auth** capability, which fills the
`get_principal` seam (replacing the app's test-only override) and is the first
real `terp-cap-*`.

Status: **Accepted** — shipped in `terp-core` 0.1.x; proven on `notes` + `tasks`.

---

## Decision 6 — First capability: `terp-cap-auth` (Accepted)

The first opt-in capability ships: `terp.capabilities.auth` — Argon2 password
hashing, HS256 JWT access tokens, and a `get_principal` provider (Bearer →
`Principal`). The kernel gained a `principal_provider` seam on
`create_app` / `build_guard` (the slice's evidence) so an auth capability fills
`get_principal` cleanly — no dependency-override hacks.

**Decoupled from the user store.** Auth takes an app-supplied
`authenticate(email, password) -> Principal | None` callback; it never owns users
(the identity capability will). Proven end-to-end: the example app's notes/tasks
tests now run against **real Bearer JWTs**, plus login-flow tests (Argon2 verify,
bad password / unknown user / tampered token → 401).

**Namespace validated:** `terp-cap-auth` ships `src/terp/capabilities/auth/` and
co-installs with `terp-core` under one PEP 420 `terp.*` namespace.

**Still deferred:** identity (persisted users), refresh-token rotation,
brute-force lockout / rate-limit, pluggable SSO (OIDC/SAML), and entry-point
capability discovery (the app wires `auth` explicitly for now).

Status: **Accepted** — shipped as `terp-cap-auth` 0.1.0.

---

## Decision 7 — `terp-cap-identity` + entry-point discovery (Accepted)

The second capability ships: `terp.capabilities.identity` — a persisted `User`
store (Argon2-hashed passwords) + `IdentityService` (CRUD + `authenticate`). It
**backs the auth login flow**: the example app now wires
`IdentityService().authenticate`, replacing the in-memory store. `UserRead` never
exposes `hashed_password`.

**Entry-point discovery is live.** A capability declares a `terp.capabilities`
entry point resolving to a `ModuleSpec`; `create_app(discover_capabilities=True)`
mounts it (and registers its models) with **no composition-root edit** — the
design's Phase 2 gate. Proven: identity's admin `users` router (admin-only RBAC)
is mounted purely by discovery and tested end-to-end. The auth login route now
takes a `SessionDep` so DB-backed authenticators work.

**Layering:** identity → auth → core (identity uses auth's hashing). Two
capabilities + core now co-install under one PEP 420 `terp.*` namespace.

**Still deferred:** refresh-token rotation, lockout / rate-limit, pluggable SSO,
the `access` (RBAC grants) and `tenancy` capabilities, and packaged Alembic
migrations across capabilities.

Status: **Accepted** — shipped as `terp-cap-identity` 0.1.0.

---

## Decision 8 — `terp-cap-tenancy`: tenant scoping on the `base_query` seam (Accepted)

The third capability ships: `terp.capabilities.tenancy` — tenant scoping as an
opt-in capability, validating Decision 5's claim that **the kernel stays
tenancy-agnostic**. A model becomes tenant-scoped by mixing in `TenantScopedMixin`
(a non-null, indexed `tenant_id`) and giving its service `TenantScopedService`,
which overrides the kernel's `BaseService.base_query` hook to filter every read by
the current tenant and stamps `tenant_id` on create. The current tenant lives in a
`ContextVar` set via `tenant_context(...)`. **Zero kernel change** — exactly the
seam `BaseService` was documented to host.

**Fail-closed.** A missing tenant context matches no rows on read and raises
`TenantContextError` on write. Scoping lives in the service's `base_query`; a
deliberate raw query is the explicit, greppable escape hatch. Proven by **5 tests**
(per-tenant read isolation, create-stamps-tenant, missing-context reads nothing,
missing-context write rejected, raw-query escape hatch).

**Why `base_query`, not a session-level event.** The design sketched a
session-level predicate (`with_loader_criteria` injected on `do_orm_execute`) for
"isolation by construction" over *raw* queries too. That pattern targets a mapped
class or a declarative mixin whose column is accessible on the base; **SQLModel's
`TenantScopedMixin` is an unmapped Pydantic mixin**, so
`with_loader_criteria(TenantScopedMixin, lambda cls: cls.tenant_id == ...)` raises
`AttributeError` while building the option (the column resolves only on the
concrete, mapped subclass). The `base_query` override references the concrete
`self.model.tenant_id`, which *is* mapped — so it is both correct and the
already-proven composition seam. Raw-query isolation (which needs a SQLAlchemy
*declarative* tenant base rather than a SQLModel mixin) is recorded as a future
enhancement, not a blocker.

**Library capability.** `terp-cap-tenancy` declares **no** entry point — it ships
no router or models to mount; it is imported directly by the modules it scopes. It
co-installs with `terp-core` + `terp-cap-auth` + `terp-cap-identity` under one
PEP 420 `terp.*` namespace.

**Still deferred:** an HTTP `TenantMiddleware` (resolve the tenant from the
verified token / host and set `tenant_context` per request) and a JWT `tenant`
claim; the `access` (RBAC grants) capability; raw-query (session-level) isolation;
and packaged Alembic migrations across capabilities.

Status: **Accepted** — shipped as `terp-cap-tenancy` 0.1.0 (**47 tests green**).

---

## Decision 9 — `terp-arch` enforcement harness + `ModuleSpec.requires` boot check (Accepted)

The fitness harness ships for real (it was an empty stub): `terp.arch` is a
versioned dependency clients **run** against their own `app/` but **cannot edit**
(design §5.10, §8). It is **7 precise, non-heuristic AST rules**, each the
build-time half of a two-layer control paired with a fail-closed runtime control:

| Rule | Runtime control it backstops |
|---|---|
| `no_internal_imports` | the `terp.core` public surface vs `terp.core._internal` |
| `no_cross_module_imports` | leaf-module independence (no sibling imports) |
| `modules_declare_policy` | `create_app` deny-by-default `BootError` on a missing `Policy` |
| `routes_declare_response_model` | the API boundary (no bare ORM/data leaves a route) |
| `no_raw_session_construction` | the `SessionDep` seam (no hand-built `Session`/engine) |
| `input_str_fields_have_max_length` | every input `str` caps length |
| `tenant_scoped_models_use_scoped_service` | tenancy isolation (Decision 8) |

The last rule **closes the one gap** in the service-level tenancy design: a
`TenantScopedMixin` model whose service extends plain `BaseService` (which would
return every tenant's rows) is now rejected at build time, so the `base_query`
scoping cannot be silently bypassed. `check_app` / `assert_app_clean` orchestrate
all rules; an `ArchViolation` prints `file:line: [rule] message`, so a red run
names an exact, fixable spot. Client usage is one line: `assert_app_clean("app")`.

**`ModuleSpec.requires` is now enforced at boot (was inert).** `create_app`
validates every collected spec's `requires` against the installed/declared set and
raises `BootError` **before mounting any router** (design §4.3) — a module that
declares a dependency it didn't get fails closed instead of half-booting.

**Dogfooded.** `tests/architecture/test_arch_harness.py` proves each rule (1)
fires on the breach it targets and (2) does **not** false-positive on correct
code, and runs the whole harness against the real `apps/example/app` (clean);
`requires` boot tests live in `test_core_app.py`. `terp-arch` is bumped to 0.1.0
and is already a `uv` workspace member, so `uv run pytest` installs it. Suite:
**47 → 57 tests green**.

**Scope kept deliberately narrow.** Generic layering and dependency hygiene stay
delegated to Tach / import-linter + deptry / pip-audit (design §8); only the
domain-specific secure-by-default rules are hand-rolled, and they are precise
rather than heuristic so a green run is meaningful.

**Still deferred:** the escape-hatch budget ratchet (a governed opt-out), the
Tach / import-linter + deptry / pip-audit wiring, a docs-parity test (rules ↔
documented invariants), and `test_vendored_core_unmodified` (Phase 6).
`ModuleSpec.services` / `events` wiring stays inert until a DI consumer / eventbus
capability exists (avoid premature abstraction, Decision 3), and `BaseService`
commit-ownership remains an open design decision.

Status: **Accepted** — `terp-arch` 0.1.0; **57 tests green**.

---

## Decision 10 — Governed escape-hatch opt-out: justified suppression + budget ratchet (Accepted)

Decision 9's first deferral ships: `terp.arch` now has the **governed opt-out**
the secure-by-default model promises (design §1.4, §5, §8) — *"a secure default
**and** a visible, greppable, budgeted opt-out."* Every harness rule is still
fail-closed; an author who must breach one does so **in the open, with a reason,
and against a budget that can only shrink**.

**Three coupled controls.**

1. **Justified suppression.** A `# arch-allow-<rule>: <reason>` comment on a
   violation's own line suppresses *exactly that rule, on that line*. The mapping
   is mechanical (`no_internal_imports` → `arch-allow-no-internal-imports`), so a
   marker can never silence a different rule, and a stray marker on a clean line
   silences nothing. Suppression is applied **centrally** in `check_app` over the
   collected violations — the seven rule functions are untouched, so the opt-out
   surface is one small, audited code path rather than seven.
2. **Fail-closed on a missing reason.** A marker with no justification does **not**
   suppress; it is re-reported as `escape_hatch_requires_justification`. The only
   way to clear the breach is to add a reason — never to opt out silently.
3. **Budget ratchet.** `check_escape_hatch_budget(app, budget_path=...)` counts
   every `# arch-allow-*` token in the app tree and requires an **exact** match to
   a checked-in JSON budget (`{marker: count}`). A count that *rose* needs a
   justified bump in the same change; one that *dropped* must be lowered to lock in
   the win; an unbudgeted marker is rejected outright. Exact-match (not "≤") is
   what makes removals ratchet the ceiling down.

**Opt-outs cannot be used un-governed.** `assert_app_clean` — the one-line client
entry point — now **refuses to pass** an app that contains any `# arch-allow-*`
marker unless a `budget_path` is supplied. So the budget is not an optional extra
a client might forget; using the escape hatch *requires* governing it.

**Why this shape.** The mechanism is derived from a conventional
escape-hatch budget (per-marker JSON counts, exact match, "justify a rise / lock
in a drop"), but re-authored clean: markers key off **rule names** (self-
documenting, 1:1 with the harness) instead of ad-hoc semantic tags, and the
suppression + governance live in the shipped, un-editable harness rather than in
client test code — so a client cannot weaken the opt-out by editing the checker,
only by spending budget.

**Dogfooded.** New tests in `test_arch_harness.py` prove a justified marker
suppresses its rule; a reason-less one fails closed; a marker only affects the
rule it names; the budget accepts an exact match and rejects an unbudgeted marker,
a rise, and a stale entry; and an opt-out without a budget makes
`assert_app_clean` fail. The example app carries an **empty** budget
(`apps/example/escape-hatch-budget.json` = `{}`) and uses zero opt-outs — the
strongest posture, asserted as a dogfood. Suite: **57 → 66 tests green**.

**Still deferred:** Tach / import-linter + deptry / pip-audit wiring, the
docs-parity test (rules ↔ documented invariants), and
`test_vendored_core_unmodified` (Phase 6).

Status: **Accepted** — `terp-arch` 0.1.x; **66 tests green**.

---

## Decision 11 — HTTP `TenantMiddleware` + JWT `tenant` claim (Accepted)

Decision 8's first deferral ships: the tenancy capability can now bind the current
tenant **per HTTP request** from the caller's verified token, closing the loop
from login to scoped query without the kernel learning about tenants.

**Two pieces, split along the existing decoupling seams.**

- **auth owns the claim.** `create_access_token(..., tenant=...)` signs an optional
  `tenant` claim; `decode_access_token` returns it on `AccessTokenClaims.tenant`
  (absent → `None`). The kernel `Principal` stays **id + role only** — tenancy is
  *not* baked into core's identity type. auth also ships a ready-made resolver,
  `tenant_from_bearer(request) -> uuid | None`, that reads the signed claim.
- **tenancy owns the binding.** `TenantMiddleware` is a **pure-ASGI** middleware
  that calls an app-supplied `resolve_tenant(request)` and runs the request inside
  `tenant_context(...)`. It is deliberately *not* a Starlette `BaseHTTPMiddleware`:
  that runs the downstream app in a separate anyio task, so a `ContextVar` set in
  its `dispatch` would not be visible to the endpoint. A pure-ASGI middleware sets
  and resets the context in the **same coroutine** that awaits the downstream app,
  so the scope is reliably visible to sync endpoints (anyio copies the context
  into the threadpool) and is reset on the way out — no cross-request leak.

**Same decoupling as auth↔identity.** auth never learned where users live (it
takes an `authenticate` callback); likewise tenancy never learns how a tenant is
read (it takes a `resolve_tenant` callback). The app composes them — exactly the
shape Decision 8 anticipated:

```python
from starlette.middleware import Middleware

app = create_app(
  [...],
  principal_provider=get_principal,
  middleware=[Middleware(TenantMiddleware, resolve_tenant=tenant_from_bearer)],
)
```

**Fail-closed, end to end.** A request with no token (or a tenant-less one)
resolves to `None`, so every `TenantScopedService` read returns nothing and a
write raises `TenantContextError` → HTTP 500 `tenant_context_missing`. The tenant
is only as trustworthy as the **signed** token that carries it.

**Dogfooded.** `apps/example/tests/test_tenant_middleware.py` proves the token
round-trips the claim; the middleware binds it, leaves it unset without a token,
and does not leak it between requests; and a `TenantScopedService` mounted on the
real `create_app` isolates rows by token-tenant over HTTP (tenant A sees only its
rows; a token-less write is rejected). The example `build()` is left unchanged —
it has no tenant-scoped module, so wiring the middleware there would be decorative;
the capability is proven by a representative composed app instead (consistent with
how Decision 8 proved tenancy). `terp-cap-tenancy` gains a direct `starlette`
dependency (the middleware is an HTTP concern). Suite: **66 → 73 tests green**.

**Still deferred:** raw-query (session-level) isolation — the service-level
`base_query` scoping + this request binding cover ORM reads; a SQLAlchemy
declarative tenant base (for `with_loader_criteria`) remains a future enhancement
(Decision 8). Wiring the tenant into the example login flow waits on the
identity capability gaining a tenant association.

Status: **Accepted** — `terp-cap-tenancy` 0.1.x; **73 tests green**.

---

## Decision 12 — `terp-cap-access`: RBAC permission grants + a principal-seam generalisation (Accepted)

The fourth capability ships and fills the remaining base-profile authorization
slot (§13 Phase 2: core + auth + **access** + identity + users + projects). The
kernel `Policy` guard enforces the **coarse, global role ladder**
(`VIEWER < EDITOR < ADMIN`); access adds **fine-grained, per-permission**
authorization *on top of* it, without changing the kernel's authz model.

**The grant primitive.** A `Grant` is one immutable fact — *subject `subject_id`
holds the open, app-defined `permission` token* (e.g. `"reports:export"`) — with a
composite-unique `(subject_id, permission)` so a grant is idempotent. The model is
deliberately generic: application-specific audience vocabularies, visibility axes,
and scope taxonomies stay in higher layers or dedicated capabilities. The
dependency-direction discipline is the important invariant:
`subject_id` is an **FK-less UUID**, so this low layer never imports the higher
identity/app tables that reference it — access stays a leaf those layers depend on.

**Two-layer enforcement.** The runtime control is `require_permission(permission)`
— a fail-closed dependency a module mounts on a route: unauthenticated → 401, no
grant → 403, grant present → allowed. `AccessService` provides the grant algebra
(`grant`/`revoke`/`has_permission`/`permissions_for`, building on `BaseService` for
get/list/delete). A self-registering, **ADMIN-only** `access` router administers
grants and mounts purely by entry-point discovery (no composition-root edit) —
managing who holds a permission is itself privileged.

**Kernel generalisation: the principal seam now reaches route bodies.** Until now
`create_app` passed the configured `principal_provider` only into the policy
*guard*; a route or route-level dependency that did `Depends(get_principal)` got
the kernel's unauthenticated default. `create_app` now also registers a non-default
provider as a dependency **override** for `get_principal`, so any dependency can
read the caller through the public seam. This is what lets `require_permission`
live in `terp-cap-access` depending on **`terp-core` only** — it never imports
auth; it reads `get_principal`, which the app points at auth. The change is inert
for a bare kernel (default provider ⇒ no override), so the Phase-1 kernel tests are
unaffected.

**Dogfooded.** `apps/example/tests/test_access_api.py` proves the grant algebra
(idempotent grant, safe revoke, per-subject isolation); the `require_permission`
trichotomy (401 / 403 / 200) over HTTP on a composed app; and the discovered admin
router (ADMIN grants/lists/revokes; a non-admin gets 403; an unauthenticated caller
401). `terp-cap-access` co-installs under the one PEP 420 `terp.*` namespace and is
a `uv` workspace member. Suite: **73 → 82 tests green**.

**Still deferred:** object-level scoping (a grant bounded to a specific resource —
the conventional polymorphic `scope_type`/`scope_id`, re-authored FK-less) is a
clean additive enhancement, not built until a consumer needs it; group/role
aggregation of grants; and wiring `require_permission` into an example module
(the capability is proven by a representative composed app, as tenancy was).

Status: **Accepted** — `terp-cap-access` 0.1.0; **82 tests green**.





