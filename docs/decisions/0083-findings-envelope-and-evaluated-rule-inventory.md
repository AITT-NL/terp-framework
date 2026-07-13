# 0083 — The findings envelope: checks publish their own evaluated-rule inventory

- **Status:** Accepted
- **Date:** 2026-07-12
- **Relates:** [ADR 0080](0080-terp-standard-rule-catalog-and-violation-corpus.md) /
  [ADR 0081](0081-terp-standard-consumable-findings-schema-and-layers.md) (the
  catalog and finding format this joins verdicts to) and
  [ADR 0059](0059-strict-frontend-boundary-and-escape-hatch-budget.md) (the
  boundary + budget ratchet the frontend half realises).

---

## Context

A driving tool (Terp Studio's spec matrix, a CI annotator) wants to render the
Terp Standard **rule by rule** with a per-rule verdict for a project. Findings
alone cannot support that: a rule with zero findings is only "passing" if the
run actually evaluated it. The consumer must never supply that knowledge
itself — its own catalog copy can be newer or older than the project's pinned
toolchain (version skew), and some enforcement is conditional (the escape-hatch
budget ratchet only runs when a budget is supplied; the slot-typed layout
contract only when the app has opted in, ADR 0079). Two failure modes follow if
the inventory is assumed: a rule the toolchain never ran renders green, and an
opt-in rule that is simply not enabled renders green. A third lurked in the
lint script itself: `eslint . && terp-boundaries-budget` short-circuits, so a
boundary violation hid budget drift from the same run.

## Decision

Every machine-readable check artifact **publishes the inventory it actually
enforced**, and the consumer joins findings to the catalog exclusively through
that inventory (fail closed: no inventory → no verdict, never green).

1. **Backend** — `terp check --format json` gains `rules`: the live registry
   plus the escape-hatch governance half matching the execution mode
   (`escape_hatch_budget` only when a budget was supplied — the ratchet then
   subsumes ungoverned-marker detection; `ungoverned_escape_hatch` otherwise
   and always).
2. **Frontend** — one bin, `terp-boundaries-lint`, replaces the script chain:
   it runs the app's own ESLint config **and** the budget ratchet in-process
   (both halves always run; the exit code is the combined verdict) and prints
   one findings envelope on stdout, humans on stderr:

   ```json
   { "terp_findings": 1, "tool": "@terp/eslint-boundaries",
     "rules": ["frontend/…"], "not_applicable": ["frontend/…"],
     "findings": [{ "rule", "path", "line", "message" }],
     "unattributed": [{ "path", "line", "message", "reported_as" }] }
   ```

   `rules` is `catalogRuleIds()` (parity with `catalog/frontend/` is locked by
   findings.test.js) minus the opt-in rules the app has not enabled, which move
   to **`not_applicable`** (today: `frontend/layout-contract` without a
   checked-in `layout-contract.json`) — a consumer renders those as "not
   applicable", never as passing or unknown. Findings are attributed through
   the published `catalogRuleId` mapping (ADR 0081's finding shape); messages
   outside the boundary stay visible under `unattributed`.
   `terp-boundaries-budget --format json` emits the same envelope standalone.

## Consequences

- A consumer can state, per catalog rule: pass (in `rules`, no findings), fail
  (findings), not applicable (published as such), or unknown (the toolchain
  published nothing — a pre-upgrade project or a crashed check). No state is
  ever inferred from the consumer's own catalog version.
- The envelope (`terp_findings: 1`) is a published, versioned seam consumed
  outside this repository (the Studio); changing its shape is a contract
  change and bumps the marker version.
- The template/example lint script is a single command (`terp-boundaries-lint`),
  so budget drift can no longer hide behind a failing boundary lint.
