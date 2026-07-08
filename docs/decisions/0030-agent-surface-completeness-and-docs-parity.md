# 0030 - Agent-surface completeness: the "docs can't lie" parity layer

- **Status:** Accepted
- **Date:** 2026-06-28
- **Context phase:** Phase 3 (enforcement harness) → Phase 5 (agent experience)
- **Relates:** [ADR 0019](0019-agent-onboarding-and-discoverability.md) (the layered
  onboarding model — this ADR realizes its accepted-but-unbuilt **"docs can't lie"
  parity test** and its **"generated + parity-tested over hand-written"** principle),
  [ADR 0006](0006-cross-cutting-controls-and-opinionation-policy.md) (the two-layer
  discipline — and how it applies to a *documentation-coverage* control, not a security
  one), [ADR 0029](0029-object-level-ownership-authorization.md) (object-level ownership
  authorization — the feature that shipped **undocumented for agents**, the live test
  case here). Mirrors two existing completeness guards: the harness self-completeness
  meta-test (`test_arch_harness.test_harness_registers_and_tests_every_rule`) and the
  capability drift guard (`test_capability_arch.test_every_built_capability_is_covered`).
  Source of truth: [AGENTIC_PLATFORM_DESIGN.md](../../AGENTIC_PLATFORM_DESIGN.md) §8
  (the parity test), §9 (agent-experience), §10 (agent-visibility).

---

## Context

Terp's **enforcement** layer is already self-policing: the harness self-completeness
meta-test refuses a `check_*` rule that is not registered *and* tested, the 100%
line-coverage gate refuses dead code, the capability drift guard refuses an
unscanned capability, and the escape-hatch budget ratchets opt-outs. Each is a
*build-time completeness control* that makes a class of omission fail the build.

The **agent-facing documentation** layer had no such guard. An agent working in a
*consumer* repo does not read `.venv` / `site-packages`; it learns Terp by reading
`AGENTS.md` and running `terp guide` and the gate (ADR 0019). So a pattern that is
undocumented *there* is, for an agent, invisible — yet nothing made the build fail
when a new rule / trait / seam shipped without a `terp guide` recipe or an `AGENTS.md`
line, and nothing caught a stale "enforced by `X`" claim rotting as the harness evolved.

This was not hypothetical. The most recent feature — object-level ownership
authorization ([ADR 0029](0029-object-level-ownership-authorization.md): `OwnedMixin`,
the `no_manual_ownership_checks` rule, the `register_object_authz_predicate` seam, the
`journals` dogfood) — shipped with **no `terp guide` recipe and no `AGENTS.md` line**.
The full gate stayed green at 100% coverage. Nothing reminded the author, because the
agent-facing surface was the one layer the platform did not hold to its own
"self-completeness + generate-don't-duplicate" standard.

## Decision

Apply Terp's own instinct — a **build-time self-completeness meta-test** plus
**generate, don't duplicate** — to the agent-facing surface, so the gate refuses to go
green when a new pattern is undocumented for agents or a documented claim no longer
resolves.

1. **Generate the enforced-rules surface; never hand-list it.** `terp guide rules` is a
   **projection of the live registry** `terp.arch.rules._ALL_RULES` — each rule's bare
   name + its docstring headline, sorted deterministically (so the output is
   snapshot-stable and independent of registration order). Adding a rule surfaces it
   automatically; there is no second, hand-maintained rule list to drift. The harness is
   imported lazily, so plain `terp guide` / `terp inspect` need not load it. A new public
   `guide_topics()` is the **single source of truth** for the topic set — the CLI's
   argparse `choices` and the parity/guide tests both derive from it, retiring the
   hand-duplicated `_TOPICS` list in `test_cli_guide.py`.

2. **The parity meta-tests (`tests/architecture/test_docs_parity.py`).** Each is
   fail-closed and exercised on **both** the real tree (clean) **and** a synthetic
   breach (so the guard provably bites), exactly as every `terp.arch` rule test asserts
   the breach *and* the clean case:
   - **Rule→guide completeness** — the generated surface covers every `_ALL_RULES`
     member with a non-empty headline (true by construction once generated; the test
     locks the contract and the synthetic case proves a partial projection would fail).
   - **No dangling claims** (the literal design-§8 test) — across `AGENTS.md`,
     `template/AGENTS.md`, and the full `terp guide` text, every snake_case token
     presented as "`<name>` rule" resolves to a real `_ALL_RULES` member, every
     `test_…` reference (or `tests/**.py` link) resolves to a real test function/module,
     and every backticked "enforced by `X`" claim resolves to a real rule or test.
     An explicit **drift-guarded allowlist** carries any legitimate non-rule reference,
     and is itself checked for stale entries (an allowlisted token that no longer appears
     in any surface fails) — mirroring the capability drift guard. The check asserts
     against the **generated** projection + this small map, never "every rule name string
     appears verbatim in prose", so correct authoring stays green and only genuine
     omissions fail.
   - **Trait/seam coverage** (the check that catches `OwnedMixin`) — every public model
     trait (`*Mixin`) and capability seam (`register_*_predicate`) in
     `terp.core.__all__` is referenced somewhere in `terp guide`, minus a drift-guarded
     allowlist of the always-on traits folded into `BaseTable`
     (`UUIDPrimaryKeyMixin` / `TimestampMixin`), which an agent never composes directly.

3. **Retroactively document object-authz** (proving the new guards bite, then go green).
   A new dedicated **`ownership`** guide topic teaches `OwnedMixin` +
   `register_object_authz_predicate`, naming the read-side `register_scope_predicate`
   seam for owner-scoped reads (a governed predicate today, built-in sugar later — ADR
   0029); actor-stamping (`ActorStampedMixin`) is folded
   into the `service` topic; and a **one-line ownership golden rule** is added to both
   `AGENTS.md` and `template/AGENTS.md` ("never hand-roll an `owner_id` check; compose
   `OwnedMixin` — the `no_manual_ownership_checks` rule enforces it"), kept terse and DRY
   per ADR 0019(b) by pointing at `terp guide ownership` rather than duplicating the
   recipe. The generated rules surface now includes `no_manual_ownership_checks` with no
   hand edit.

4. **Two-layer discipline, applied honestly to a documentation-coverage control.** ADR
   0006's two-layer rule — every *security* control is a fail-closed runtime control
   **and** a build-time test — governs security boundaries. This is a **completeness
   control over documentation**, not a runtime security boundary, so it ships as a
   **build-time meta-test only**; inventing a spurious "runtime half" would be
   cargo-culting the form without the substance. The structural analogue of the runtime
   layer here is **generate-don't-duplicate**: the rules surface *cannot* drift from the
   rules it documents because it *is* the registry projection, and the build-time
   meta-tests guard only the hand-written remainder (the recipes, the golden-rule lines,
   the "enforced by" claims). This is precisely the shape of the existing harness
   self-completeness meta-test, which is likewise build-time-only.

5. **Keep the guard meaningful — document, don't allowlist, a genuine must-know.** The
   trait/seam check flags everything an agent composes or calls directly. The *only*
   allowlisted traits are the always-on ones folded into `BaseTable`; the other
   primitives the check surfaced (`ActorStampedMixin`, `register_scope_predicate`) are
   **documented** rather than allowlisted, because allowlisting a real must-know would be
   weakening the guard to make it pass — the same discipline as "never weaken a guard."

## Consequences

- A new architecture rule appears in `terp guide rules` automatically; a new model trait
  or capability seam, or a stale "enforced by `X`" claim, now **fails the gate** until it
  is documented for agents. The exact gap ADR 0029 fell through is closed.
- The agent self-onboarding loop is now self-honest: `AGENTS.md` → `terp guide` → the
  gate, with the gate refusing to certify a surface that lies or omits. ADR 0019's
  "docs can't lie" backlog item is realized.
- Object-level authorization is now fully agent-discoverable: the `ownership` topic, the
  golden-rule line in both `AGENTS.md` surfaces, and the generated rule entry.
- The example app and every capability stay arch-clean; budgets unchanged (`{}`). 452
  tests, 100% framework line coverage.
- **Out of scope, sequenced as follow-ons** (design §9/§10, still tracked in
  [docs/internal/STATUS.md](../internal/STATUS.md)): `terp api-docs` (generated
  `docs/platform-api.md` + `.pyi` with a golden-snapshot parity test — the same "docs
  can't lie" instinct applied to the API contract), `terp new module` scaffolding, the
  vendored read-only `vendor/terp-core/` + `test_vendored_core_unmodified`, and an
  optional packaged skill / MCP server. This slice ships only the parity keystone.
