# 0037 - Finish the universal rule set: the last four secure-by-default fitness rules

- **Status:** Accepted
- **Date:** 2026-06-29
- **Context phase:** Phase 3 finish — "ship `terp-arch`; delegate layering to a tool"
- **Relates:** [ADR 0003](0003-conformance-and-coverage-gate.md) (the conformance +
  coverage gate and the harness self-completeness meta-test), [ADR 0006](0006-cross-cutting-controls-and-opinionation-policy.md)
  (the two-layer runtime + build-time discipline), [ADR 0020](0020-response-model-not-table-model.md)
  (`response_model_not_table_model`, the leak this set finishes guarding),
  [ADR 0029](0029-object-level-ownership-authorization.md) (per-row authz),
  [ADR 0030](0030-agent-surface-completeness-and-docs-parity.md) (the generated
  `terp guide rules` surface + docs-parity), [ADR 0033](0033-generic-enforcement-in-ci.md)
  (the generic CI backstops). Clears the [STATUS](../internal/STATUS.md) Phase-3
  backlog item "add the remaining secure-by-default rules".

---

## Context

The Phase-3 rule backlog named four remaining universal fitness rules. Each closes
a concrete hole the existing set does not catch:

- A **`*Read` DTO that hand-copies a credential** (`hashed_password`, `access_token`):
  `response_model_not_table_model` rejects returning the table model, but a bespoke
  Read model that mirrors the hash still leaks it.
- A **mutating module whose write tier collapses to the read floor**
  (`Policy(write=Roles.VIEWER)`): the policy is "valid but wrong" — anyone who can
  read can also write. No rule noticed.
- A **module missing one of its canonical files** (`models`/`schemas`/`service`/
  `router`): off-pattern, hard to discover, and the surface the other rules assume.
- The ORM **`Session` imported from `sqlalchemy`** instead of `sqlmodel`: a quiet
  fork onto a second session type beside `SessionDep` / `BaseService`.

## Decision

Ship the four as the universal AST-rule + meta-test pairing the harness already uses
(every `check_*` is wired into `_ALL_RULES`, has a `test_<rule>`, and surfaces in the
generated `terp guide rules`, ADR 0030):

1. **`schemas_exclude_sensitive_fields`** — a response DTO (anything not a `*Create`/
   `*Update` or request body, and not a `table=True` model) must not declare a
   credential-shaped field (`password`/`hashed_password`/`*secret`/`*api_key`/
   `*token`). Input bodies may take a password; a table may store the hash;
   `*_version` counters are exempt.
2. **`mutations_require_write_role`** — a module with a `POST`/`PUT`/`PATCH`/`DELETE`
   route must not set `write`/`write_role=VIEWER`; the write tier must outrank the
   read floor (`Policy.default()` ⇒ `EDITOR`).
3. **`canonical_module_shape`** — a directory that declares a `module.py` must carry
   `models`/`schemas`/`service`/`router`.
4. **`session_imported_from_sqlmodel`** — `Session` is imported from `sqlmodel`,
   never `sqlalchemy`/`sqlalchemy.orm` (complements the runtime `no_raw_session_construction`).

The bearer token in the auth capability's login `AccessToken` response is the one
credential an endpoint exists to mint, so it carries a justified
`# arch-allow-schemas-exclude-sensitive-fields` marker ratcheted by a per-cap budget
(ADR 0014) — auth joins the budgeted-cap cohort. The example app stays a `{}` budget.

## Consequences

- The universal rule set is complete; `_ALL_RULES`, `arch.__all__`, the
  self-completeness meta-test, and the generated guide all stay in lock-step.
- Three of the four back an existing runtime control (response models, deny-by-default
  policy, `SessionDep`/`BaseService`), so the two-layer discipline holds.
  `canonical_module_shape` is an authoring/discoverability convention (build-time only,
  no runtime half), the honest shape per ADR 0006. Gate stays 100%, example budget `{}`.
