# 0084 — Runtime applicability: the two-layer doctrine, classified per rule

- **Status:** Accepted
- **Date:** 2026-07-13
- **Relates:** [ADR 0006](0006-cross-cutting-controls-and-opinionation-policy.md)
  (the Tier-A quadruple this refines), [ADR 0080](0080-terp-standard-rule-catalog-and-violation-corpus.md) /
  [ADR 0081](0081-terp-standard-consumable-findings-schema-and-layers.md) /
  [ADR 0082](0082-repo-split-readiness-spec-as-a-package.md) (the catalog this
  contract lives in), Terp Standard **v0.5.0** (the spec release that carries it).

---

## Context

The platform docs stated the two-layer doctrine as universal: *"each security
rule is a fail-closed runtime control **and** a build-time test."* The Terp
Standard catalog told a different story: of 58 rules, only 7 declared a
`runtime` enforcement entry, and `catalog/schema.json` could not express
whether the other 51 lacked a runtime half by decision, by omission, or by
nature. Both failure modes were live:

- **Under-declaration.** The framework owns fail-closed runtime controls whose
  docstrings name their build-time twin, yet the catalog did not declare them —
  e.g. `_validate_policy_write_tiers` calls itself "the universal runtime half
  of `mutations_require_write_role`", `_validate_public_modules_read_only` and
  `_validate_router_response_models` refuse at boot, `_without_managed_columns`
  strips managed columns at the write chokepoint, and the write-guarded session
  re-scopes raw reads (`apply_row_scope`). The one *stated* discipline the docs
  had was invisible in the one place another stack would look.
- **Over-claiming.** Many rules police the *authored artifact*: import form,
  string literals, justification markers, checked-in budgets, repository
  layout. Their invariants are erased (compiled away) or already materialised
  (DDL applied) by the time the app runs. No runtime seam can enforce "this SQL
  string was written as a literal" — pretending otherwise would weaken the
  doctrine everywhere it *does* hold.

## Decision

### 1. The classification model

Every catalog entry carries a mandatory `runtime` block:

| `runtime.applicability` | Meaning | Contract |
|---|---|---|
| `required` | The invariant (or the threat it exists to stop) is observable in the running system, and the reference implementation owns a fail-closed control for it on a seam it mediates (request guard, write chokepoint, session, composition/boot, slot verification). | The entry **must** declare the control as a `kind: "runtime"` enforcement entry; its `ref` must resolve to a real symbol in the cited package (framework parity test). |
| `not-applicable` | The invariant is a property of the authored artifact — source form, import graph, markers, checked-in files, migration-produced DDL — erased or materialised before the app serves, so no runtime seam the framework owns (or could soundly own) can enforce it. | The entry must **not** declare a runtime enforcement entry and **must** carry a non-empty `rationale` stating why. |
| `deferred` | A runtime control would add *independent fidelity* (dynamic composition, cross-package symbols) **on a seam the framework already owns**, but has not shipped: an explicit, reviewed gap. | Same shape as `not-applicable`: no runtime entry, mandatory `rationale` naming the seam. Shipping the control flips the state to `required`. |

The dividing test is *attribution and ownership*, not imagination: a state is
`required` only when a shipped, framework-owned seam refuses the violation
fail-closed; `deferred` only when the seam exists and the maintainers' own
sibling controls demonstrate the fidelity gain (never "a check is conceivable
somewhere"); everything else states in its rationale why the build-time layer
is the control *by nature of the invariant*.

### 2. Fail-closed enforcement of the contract itself

- Spec suite (`tests/test_standard.py`): the schema makes `runtime` mandatory
  on every entry; `test_runtime_applicability_is_coherent` fails when a
  `required` rule lacks a runtime enforcement entry, when an exempt rule
  declares one, or when an exemption lacks a rationale.
- Framework suite (`tests/architecture/test_spec_catalog.py`): every declared
  runtime ref must resolve to a real `class`/`def`/`function` in the cited
  package's sources (`_RUNTIME_TOOL_SOURCES`, extended with `terp.migrations`
  and `terp.capabilities.files` for the newly declared controls).
- This is a spec contract change: the new field is **mandatory for catalog
  entries** (a v0.4 schema validator rejects v0.5 entries), while read-only
  consumers of entries and findings are unaffected. Terp Standard `VERSION`
  bumps to **0.5.0** — per the spec README's explicit pre-1.0 policy, a
  changed contract bumps the minor (the strongest signal 0.x semver carries).

### 3. The classification (58 rules)

**`required` — 21 rules** (the two-layer discipline holds, and is now declared):

| Rule | Fail-closed runtime control |
|---|---|
| `backend/modules_declare_policy` | `build_guard` — deny-by-default request guard at mount |
| `backend/mutations_require_write_role` | `build_guard` (method→tier at request time) + `_validate_policy_write_tiers` (boot refusal, any role ladder) |
| `backend/public_modules_are_read_only` | `_validate_public_modules_read_only` — boot refusal without `Policy.public_write(reason=…)` |
| `backend/safe_methods_are_read_only` | `build_read_only_request_binder` — safe-method requests bound read-only; chokepoint refuses writes |
| `backend/mutations_emit_audit` | `WriteGuardedSession` — raw session writes fail closed |
| `backend/no_raw_app_routes` | `_freeze_app_route_registration` — post-composition registration refused |
| `backend/no_raw_connection_access` | `WriteGuardedSession` — `session.connection()` gated (the `get_bind()` residual is the build-time half's job) |
| `backend/reads_use_base_query` | `apply_row_scope` — request session re-scopes raw ORM reads idempotently |
| `backend/base_query_not_overridden` | `apply_row_scope` — same backstop; an override cannot drop scope |
| `backend/no_manual_scope_filtering` | `apply_row_scope` + managed-column strip + delete-chokepoint stamping |
| `backend/no_manual_ownership_checks` | `apply_object_authz` — per-row write authorization at the chokepoint (403 fail-closed) |
| `backend/no_manual_actor_stamping` | `_save` — chokepoint stamps actor columns unconditionally; manual stamps never survive |
| `backend/input_schemas_exclude_managed_columns` | `_without_managed_columns` — managed columns stripped from every inbound payload |
| `backend/response_model_not_table_model` | `_validate_router_response_models` — boot refusal, cross-package/nested-router fidelity |
| `backend/policy_refs_resolve` | `validation_errors` (`ControlPlane`) — boot refuses undeclared authorities |
| `backend/no_adhoc_permission_literals` | `requirement_from` — typed normalization refuses bare strings (TypeError) |
| `backend/events_reference_catalog` | `emit` — producer chokepoint refuses uncatalogued/shadow events; boot validates declared emits/subscribes |
| `backend/jobs_reference_catalog` | `enqueue` — producer chokepoint refuses uncatalogued jobs (execution re-checks via `run_job`) |
| `backend/no_adhoc_config_decrypt` | `decrypt_config` — fails closed unless called from the one registered call site (`register_decrypt_call_site`) |
| `backend/no_raw_file_references` | `load_for` (`terp.capabilities.files`) — delegated reads fail closed on undeclared reference columns |
| `frontend/layout-contract` | `verifySlotChildren` — fail-closed runtime DOM slot check (ADR 0079) |

**`not-applicable` — 31 rules.** Source-form / build-artifact invariants, each
with a per-rule rationale in its catalog entry. The recurring shapes:

- *Import/reference form* (erased at runtime; the sanctioned path legitimately
  uses the same primitive in-process): `no_raw_outbound_http`,
  `no_adhoc_background_runtime`, `no_internal_imports`,
  `no_cross_module_imports`, `session_imported_from_sqlmodel`,
  `no_raw_session_construction`, `no_app_instantiation`,
  `no_adhoc_logging_config`, and the frontend
  import/authoring rules (`no-cross-module-imports`, `no-deep-imports`,
  `no-style-imports`, `no-inline-styling`, `token-styled-elements`,
  `router-links`, `generated-client-only`, `no-eval`, `no-dom-html-injection`,
  `no-unsafe-href`, `no-unsafe-target-blank`).
- *Literal/marker form*: `no_dynamic_sql`, `no_hardcoded_credentials`,
  `no_destructive_migrations`, `escape_hatch_budget`,
  `ungoverned_escape_hatch`, `frontend/escape-hatch`.
- *Materialised build artifacts / authoring shape*: `canonical_module_shape`,
  `no_manual_table_schema`, `no_unique_columns_on_soft_delete_models`,
  `table_models_use_base_table`, `tenant_scoped_models_use_scoped_service`,
  `input_str_fields_have_max_length` (a declared cap **is** runtime-enforced by
  validation; only its absence is invisible to any seam).

**`deferred` — 6 rules.** A shipped sibling (or partial) control demonstrates
the seam and the fidelity gain; the gap is now explicit instead of silent:

- `routes_declare_response_model`, `schemas_exclude_sensitive_fields` and
  `list_routes_paginate` — the boot route-scan seam
  `_validate_router_response_models` already occupies could refuse each
  (an undeclared response model, a credential-shaped DTO field, a bare
  `list[...]` list envelope — all visible on the composed route table). For
  pagination, what ships today does not refuse the violation: `PaginationDep`
  caps `skip`/`limit` fail-closed only for routes that opt in, and the
  `@terp/conformance` probe observes the envelope from outside.
- `no_adhoc_middleware` and `no_dependency_overrides` — the composition freeze
  seam `_freeze_app_route_registration` already occupies.
- `tables_have_migrations` — the migration runtime already fails closed on
  FK-wired unowned tables (`assert_no_homeless_tables`) and on pending declared
  revisions (`assert_migrations_current`); a standalone missing history — the
  case the rule exists for — is visible to the same seam's live metadata but
  not yet refused.

### 4. Doctrine wording

The blanket claim is retired. `AGENTIC_PLATFORM_DESIGN.md` (§2, the §5
security-model preamble, the §5.10 rule-catalog header, the §14 risk table),
[AGENTS.md](../../AGENTS.md), [README.md](../../README.md) and the Copilot
instructions now state: two-layer enforcement applies to every rule whose
invariant runtime can observe (`required`); a source-form rule is
build-time-only **by recorded decision** with its rationale in the catalog.
Nothing in this ADR weakens any existing control — it *declares* fifteen
previously undeclared runtime halves and makes the remaining gaps reviewable.

## Consequences

- Another stack implementing Level 3 knows exactly which 21 rules need a
  runtime counterpart and what the reference control is; 37 rules are
  explicitly exempt (31 `not-applicable`, 6 `deferred`) with reasons a
  reviewer can veto.
- A new rule cannot ship unclassified (schema-mandatory field), cannot claim
  `required` without a resolvable control, and cannot carry a contradictory
  declaration (coherence test).
- The six `deferred` entries are the agreed backlog for closing real seam
  gaps; flipping one to `required` is a control implementation plus a one-line
  catalog change.
- Certification is two-staged across the repo seam (ADR 0082): the spec
  repository's `certify-against-reference` CI job substitutes the candidate
  spec for the pinned release and runs the framework's parity + corpus
  certification (so an unresolvable ref or a bad corpus case cannot reach a
  release), and the framework's later `terp-spec` / `@terp/spec` pin bump —
  the required companion change when adopting v0.5.0 — re-certifies the same
  contract in the framework's own standing gate.
- Spec consumers reading v0.5.0 entries see a new block they may ignore; the
  Studio spec matrix can render the classification without interpreting it
  (display metadata, per ADR 0083's fail-closed join).
