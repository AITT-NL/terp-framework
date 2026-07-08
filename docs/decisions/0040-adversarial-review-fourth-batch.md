# 0040 - Adversarial review, fourth batch: privilege-inversion, public-write, and three residual leaks

- **Status:** Accepted
- **Date:** 2026-06-29
- **Context phase:** Phase 3 finish (harness) + Phase 5 (scaffolding) hardening,
  after a red-team pass over ADRs 0027–0039
- **Relates:** [ADR 0037](0037-finish-universal-rule-set.md) (the universal rule set —
  `mutations_require_write_role` is the rule this batch corrects), [ADR 0004](0004-typed-principal-role.md)
  / [ADR 0022](0022-role-model-agnostic-and-tenant-aware-login.md) (the role-model-agnostic
  guarantee the inversion fix restores), [ADR 0006](0006-cross-cutting-controls-and-opinionation-policy.md)
  (the two-layer runtime + build-time discipline, and the governed escape hatch),
  [ADR 0036](0036-distributed-throttle-store.md) (the throttle store this batch adds a boot
  guard for), [ADR 0039](0039-scaffolding-cli-and-copier-template.md) (the generated `.pyi`
  this batch makes type-bearing), and the prior adversarial batches
  [ADR 0014](0014-adversarial-review-hardening.md) / [ADR 0026](0026-adversarial-review-second-batch.md)
  / [ADR 0028](0028-adversarial-review-third-batch.md).

---

## Context

A fourth red-team pass over the secure-by-construction thesis surfaced five leaks,
two with real teeth:

- **F1 (privilege inversion).** `mutations_require_write_role` (ADR 0037) was advertised
  as "the write tier must outrank the read floor," but the implementation matched only
  the literal role **name** `VIEWER`. It did **no rank comparison**, so it was blind to a
  default-ladder inversion (`Policy(read=ADMIN, write=EDITOR)` — a reader needs *more* than
  a writer) and to **every custom role ladder** (`Policy(read=MEMBER, write=MEMBER)` — the
  exact role-model-agnostic configuration ADR 0004 / 0022 promote). The runtime guard
  (`build_guard`) enforces the read and write requirements **independently** and never
  asserts `write_rank ≥ read_rank`, so the claimed runtime backing did not cover the
  property the rule named — a hollow two-layer.
- **F2 (public write).** `Policy.public(reason=…)` drops authentication for the whole
  module, so a `POST`/`DELETE` under it is an **unauthenticated write**. No rule noticed
  (`mutations_require_write_role` only inspects `write=` kwargs, which a public policy
  lacks), so applying `Policy.public` to a module that also has writes silently shipped a
  world-writable surface.
- **F3 (secret leak).** `schemas_exclude_sensitive_fields` (ADR 0037) used a regex that
  required a name to *end* in `secret`, so `secret_key` / `private_key` / `salt` / `pwd`
  slipped through a hand-rolled Read DTO.
- **F4 (false confidence).** The generated `terp_core.pyi` (ADR 0039) emitted
  `def name(*args, **kwargs) -> Any` for every function — no usable type information for the
  "typed contract."
- **F5 (silent at scale).** Production boot fails closed on a non-durable audit sink, but
  **not** on the per-instance default throttle store (ADR 0036), so a multi-instance deploy
  silently diluted the rate limit and the login lockout by the worker count.

## Decision

Ship the corrections on the established two-layer + governed-escape-hatch model.

### 1. Privilege inversion enforced by rank, with the missing runtime layer (F1)

`mutations_require_write_role` now compares **ranks**: it flags a write tier at the read
floor (`write=VIEWER`, preserved) **and** a statically resolvable default-ladder inversion
(`write_rank < read_rank`, including a write that omits to the lower `EDITOR` default under
a raised read tier). A **custom** role's rank is not knowable from a source scan, so the
new boot check `create_app → _validate_policy_write_tiers` is the universal runtime half:
for every module that exposes a mutating route under a non-public `Policy`, it fails the
boot closed (`BootError`) when `write_requirement.min_rank < read_requirement.min_rank` —
for **any** role model. Equality is allowed (a flat or admin-only model is legitimate);
only a strict inversion is refused. This is the genuine two-layer the rule name promised.

### 2. Public modules are read-only unless justified (F2)

A new build-time rule `public_modules_are_read_only` flags a `Policy.public` module that
exposes a mutating route. A genuinely public write (sign-up / contact form / webhook) stays
available through the **governed escape hatch** — a justified
`# arch-allow-public-modules-are-read-only: <reason>` marker, ratcheted by the escape-hatch
budget — so an unauthenticated write becomes visible and budgeted rather than silent. Like
`canonical_module_shape` (ADR 0037) it is build-time governance: the runtime posture
(public means no auth) is intentional and unchanged. The bundled auth login is a public
`POST` but lives in the capability package (not an `app/modules/<name>`), so the
app-module-scoped rule does not touch it and the example budget stays `{}`.

### 3. Broadened secret-field detection (F3)

`schemas_exclude_sensitive_fields` now matches a credential name as an underscore-delimited
word — `password` / `passwd` / `pwd` / `passphrase`, any `secret` component
(`secret_key` / `client_secret`), `api_key` / `private_key`, `salt`, `credentials`, and a
*trailing* `token` (`access_token`, not the benign `token_type` / `token_version`).

### 4. A type-bearing generated stub (F4)

`terp api-docs` now emits the **real** signature (parameter names + annotations, defaults
rendered as the `.pyi` `...` idiom, non-literal defaults no longer breaking the stub) for
every public function, instead of `(*args, **kwargs) -> Any`.

### 5. Shared-throttle-store boot guard (F5)

`create_app(require_shared_throttle_store=True)` fails the boot closed unless the wired
`throttle_store` is marked shared via `mark_shared_throttle_store(...)` — mirroring the
durable-audit-sink and `require_token_revocation` boot guards. It defaults `False`, so the
per-instance default (ADR 0036) is unchanged unless a deployment opts in.

## Consequences

- The role-model-agnostic guarantee (ADR 0004 / 0022) now extends to the write-tier
  fitness check: a custom ladder can no longer ship a reader-can-write inversion, caught at
  boot whatever the role names.
- Two new build-time rules join `_ALL_RULES`, the self-completeness meta-test, and the
  generated `terp guide rules` surface (ADR 0030); the example app stays a `{}` budget.
- `mark_shared_throttle_store` / `is_shared_throttle_store` and
  `require_shared_throttle_store` are additive; the vendored core mirror (ADR 0034) is kept
  byte-exact. The gate stays 100% line coverage.
- Honest scope: the generated `.pyi` still emits minimal class stubs (`class X: ...`); full
  member stubs are deferred (the markdown reference and the live package carry the detail).

## Enforcement

- F1: `test_mutations_require_write_role` (default-ladder inversion + custom/public/read-only
  cases) and `test_create_app_fails_closed_on_an_inverted_write_tier` (+ the equality and
  read-only-router boot cases). F2: `test_public_modules_are_read_only`. F3: extended
  `test_schemas_exclude_sensitive_fields`. F4: `test_api_docs_generate_contract` asserts a
  real, parseable signature. F5: `test_create_app_requires_a_shared_throttle_store_when_asked`
  + `test_create_app_accepts_a_marked_shared_throttle_store`. Gate stays 100%.
