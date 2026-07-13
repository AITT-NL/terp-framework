# 0085 — The Terp Standard's AppSec scope: Terp rules + a delegated, pinned generic baseline

- **Status:** Accepted
- **Date:** 2026-07-13
- **Relates:** [ADR 0033](0033-generic-enforcement-in-ci.md) (the generic
  backstops this makes normative for generated projects),
  [ADR 0080](0080-terp-standard-rule-catalog-and-violation-corpus.md) /
  [ADR 0083](0083-findings-envelope-and-evaluated-rule-inventory.md) (the
  catalog and envelope the boundary is stated against),
  [ADR 0084](0084-runtime-applicability-classification.md) (the sibling
  doctrine clarification in the same spec release).

---

## Context

The Terp Standard catalogs Terp-specific architectural controls plus a
selected set of security-sink prohibitions (`no_dynamic_sql`,
`no_hardcoded_credentials`, `no-eval`, `no-dom-html-injection`, …). It has no
rules for command injection, path traversal, unsafe deserialization, weak
security randomness, secrets in logs, or browser auth material in web storage.
Meanwhile the platform repo runs a generic ruff-bandit (`S`) baseline in CI
(ADR 0033) — but the client **template** shipped no such baseline, so a
generated project's only generic AppSec was whatever its authors added
themselves. Two readings of the catalog were possible ("Terp covers AppSec"
vs. "Terp covers Terp"), and the difference is a silent security gap.

## Decision

**The Terp Standard claims Terp-specific secure architecture, not complete
application security.** The catalog's admission rule and the generic baseline
are made explicit and testable:

### 1. Scope boundary (normative, stated in the spec README)

A rule belongs in the catalog only when Terp provides a **privileged seam** or
a **more precise invariant** than a generic checker can state — a framework
chokepoint to pair with (ADR 0084), a refused-surface entry, a trait/registry
the rule holds code to. Generic vulnerability classes a stock analyzer already
detects well are **delegated, not duplicated**: the catalog never grows an
entry whose only content is "what Bandit rule Sxxx says". (This is why there
is deliberately no `backend/no_shell_injection` — `S602`+ already owns it.)

### 2. The delegated baseline (reference stack, Python)

- **What:** ruff with the bandit-derived `S` rules — covering `exec`/dynamic
  code (S102), shell/command injection (S602–S609), unsafe deserialization
  (S301+), weak hashes (S324), non-crypto randomness in security contexts
  (S311), bind-all interfaces (S104), SQL string construction (S608), and the
  hardcoded-secret heuristics — with exactly the sanctioned excusals from
  ADR 0033: `S101` (assert), `S105`/`S106` (name-based secret heuristics the
  typed config seam already governs), and per-file test excusals
  `S603`/`S607`/`S311`.
- **Where:** the platform repo (repo-wide, blocking CI job — unchanged), **and
  every generated project**: the copier template now ships the same
  `[tool.ruff.lint]` baseline, a blocking `uv run ruff check .` CI step, and
  ruff in the dev dependency group.
- **Cannot be silently disabled:** the generated project's own architecture
  test (`tests/test_architecture.py`) **parses** the baseline stanza and fails
  on any weakening — a dropped `S` select, a widened `ignore`, a non-test
  `per-file-ignores`, an exclude covering app code, or a CI workflow that no
  longer runs `uv run ruff check .` — so disabling the baseline requires
  editing the project's own gate: a visible, reviewed decision. On the
  platform side,
  [tests/guardrails/test_appsec_baseline.py](../../tests/guardrails/test_appsec_baseline.py)
  fails the build if the root baseline, the template baseline (its `[tool.ruff]`
  stanza is parsed as TOML and held to the exact sanctioned select/ignore/
  exclude sets), the template CI step, or the in-project ratchet's own checks
  drift — and the `template-acceptance` job runs `uv run ruff check .` against
  a rendered project, so the shipped baseline is proven green end-to-end, not
  just present.

### 3. Findings separation

Baseline findings are **never** attributed to Terp catalog ids: the findings
schema's `rule` pattern admits only `backend/<snake>` / `frontend/<kebab>`
catalog ids, and the envelope (ADR 0083) carries non-catalog messages under
`unattributed` (frontend) or the check's own tool output (backend `ruff`
runs as its own named check). A conformance consumer therefore renders Terp
verdicts and baseline verdicts as distinct lanes by construction.

### 4. Honest coverage limits (recorded, not papered over)

The delegated baseline does **not** cover path traversal, secrets-in-logs, or
browser-storage auth material as detection classes. Terp's adjacent controls
are constructive rather than detective: streamed storage behind declared
`FileRef` references (ADRs 0056/0057) for file access, central logging
redaction on every handler (ADR 0006) for log hygiene, and the session/refresh
model (ADR 0054) for token handling. If any of these classes later earns a
*detective* rule, it must enter through the catalog's admission rule above —
a privileged seam, not a Bandit clone. The TypeScript surface's generic
baseline is not yet delegated to an external tool: the catalog's own sink
prohibitions (`no-eval`, `no-dom-html-injection`, `no-unsafe-href`) plus the
typed egress path are the current floor, and a future delegation would follow
this ADR's shape.

### 5. No decorative taxonomy metadata

CWE/OWASP mappings are **not** added to catalog entries: no governance
consumer exists (the Studio spec matrix renders title/intent/layer as display
metadata only), the delegated baseline's own documentation already carries
CWE mappings for the generic classes, and unmaintained mappings would decay
into exactly the kind of unverifiable prose the "docs can't lie" discipline
exists to prevent. The same consumer-first bar applies to stable finding
fingerprints: today the Studio's carry-forward is check-scoped
(`plan_scoped_run`) and its per-rule matrix joins on rule ids and inventories
(ADR 0083), so no consumer joins on *individual finding identity* — the
envelope stays as-is until one does.

## Consequences

- "Terp-conformant" and "passed the generic AppSec baseline" are two named,
  separately-testable claims; a generated project ships with both wired and
  cannot lose the second one silently.
- The catalog stays small and defensible: every entry holds a seam or a
  precision claim, and reviewers can reject Bandit-duplicating rules by
  pointing at the admission rule.
- Adopting a newer ruff only changes the baseline via the template/lockfile
  path, visible in review; weakening the select/ignore sets — or carving app
  code out with an exclude or per-file ignore — fails the guardrail test on
  the platform side and the architecture test on the project side, and a
  template that would not pass its own baseline fails the acceptance job
  before it ships.
