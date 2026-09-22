# 0106 — The verify profile is open at the app end

- **Status:** Accepted
- **Date:** 2026-08-28
- **Relates:** [ADR 0033](0033-generic-enforcement-in-ci.md) (generic checks are delegated to
  off-the-shelf tools), [ADR 0085](0085-appsec-scope-and-delegated-baseline.md) (the delegation
  precedent this generalises), [ADR 0103](0103-the-ideology-one-pattern-enforced-escapable-by-proof.md)
  (enforce a pattern; never limit a capability), and the `package-boundaries` check, which is the
  special case this ADR turns into a rule.

---

## Context

`terp verify` is documented as the single source of truth for "what does green mean" — the gate a
human, an agent, CI and a driving tool all run. That claim was true of the platform's checks and
false of the app's, because `PROFILES` was a literal dict in `terp/cli/verify.py`. An app could
select from it (`--only`) and could not add to it.

Apps do have checks of their own. A sidecar package that is not the app package and therefore
outside the default architecture scan; an invariant over the app's own domain; a drift check on an
artifact the app generates. Each of those had two places to live, and both are outside the command
that defines green:

* a pytest wrapper that shells out to the real console script, so the check runs only when someone
  runs the backend suite — and reports as a test failure rather than as the check it is; or
* a step in a CI workflow, which freezes at the template version the app was rendered from and is
  invisible to every other driver of the profile.

The cost is not theoretical, and the platform has already paid it once. `terp guide
package-boundaries` prescribes import-linter contracts plus `lint-imports` in CI, while this same
profile is documented as exactly what CI enforces — two statements that could not both be true for
an app that followed the guide. The fix (commit `9ed3bce`) added one check that runs the app's
declared contracts, conditional on `[tool.importlinter]` being present in `pyproject.toml`. Its own
comment records the friction: without it, "every such app writes the same pytest wrapper".

That fix was correct and too narrow. It closed the case the platform had anticipated, and left the
general shape — *an app has a check the platform did not think of* — exactly where it was. The same
report that prompted this ADR raised the same friction twice more (dependency hygiene, a sidecar
package's architecture scan) against a profile that could not be reached in either case.

There is a general pattern here worth naming, because it recurs: **the platform delegates a generic
concern to an off-the-shelf tool in its design records, runs the tool on itself, and never wires it
for apps.** Each time, the app hand-rolls the missing check, in a place the gate does not read.

## Decision

**An app declares extra checks in its own `pyproject.toml`, and they are part of the profile.**

```toml
[[tool.terp.verify.checks]]
id = "engine-architecture"
command = "terp check --package engine"
profile = "quick"
scope = ["engine/**"]
```

Six keys, no more: `id`, `command`, `profile`, `scope`, and the optional `category` and `requires`.
The shape deliberately reads like the `[[tool.importlinter.contracts]]` an app already writes next
to it, and produces the same `VerifyCheck` the platform's own table is made of — so a declared
check is indistinguishable from a built-in in `--only`, in `--list`, and in the `terp_verify`
envelope a driving tool reads.

Four properties carry the decision.

### 1. It rides the ratchet, it does not sit beside it

`profile` names the **cheapest** profile the check joins; it then runs in every superset, exactly as
a built-in does. `quick` also means `full` and `release`. There is no fourth profile for app checks,
because a second gate is a gate that gets skipped.

Declared checks run **after** the platform's floor, so a red from Terp's own rules still reports
first: the floor decides whether the rest of the run means anything.

### 2. It composes into no assurance lane

The assurance-lane vocabulary is normative in the Terp Standard, and lanes compose from the check
ids they **name**. A declared check is named by no lane, so it contributes to none — by
construction, not by a rule someone has to remember. An app may extend its own gate; it may not
thereby restate, or satisfy, a claim the spec defines.

This is the property that makes the seam safe to open at all, and it is the one `9ed3bce` found
first: `package-boundaries` belongs to no lane either.

### 3. It fails closed on every branch

A declaration that does not parse is a **refusal**, never a skip. Unknown keys are refused rather
than ignored, so a typo'd `profil` cannot silently drop the check. An id that collides with a
platform check is refused, because `--only` could not tell the two apart and the assurance claim
composes by id — a shadowing check would report on a lane it never ran. A `category` outside the
set a driving tool can file is refused, because findings with nowhere to land are findings nobody
reads. An empty `scope` is refused, because scope is the input claim a change-aware runner uses to
prove a rerun unnecessary, and a check with no declared inputs can never be skipped safely.

The reasoning is uniform: a seam that drops what it cannot parse hands the app a gate that is green
because the app's own check never ran. That is precisely the failure this seam was opened to
remove, and it would be worse coming from the seam itself.

### 4. An app that never adopts it is untouched

No table, no extra checks, no note. Upgrading the framework must never add a check to a gate nobody
declared, and must never print advice about a seam on every run of every project.

### 5. A consumer files a category it does not know; it does not discard the check

§3 refuses an unknown `category` at the **app-declaration** boundary, and that refusal is right
there: it is loud, it names the file to fix, and the person who can fix it wrote the line. This
clause is the other end of the same seam, where the refusal is neither loud nor fixable — a
**driving tool parsing the manifest**, whose unknown category came from the platform rather than
from the project.

The two directions are not symmetric, and treating them as one is how a gate fails green. When the
platform adds a category — `frontend-tests` in 0.23.0 is the worked example — a consumer holding a
hardcoded list meets a word it has never seen in a document it did not write and cannot edit. If it
rejects the document, it falls back to whatever list it shipped with, and the project's real gate is
silently replaced by the tool's memory of an older one. Nothing is red. The full and release tiers
quietly run a subset, and the tool reports pass.

So, for any tool that configures itself from this manifest:

* **Degrade per entry, never wholesale.** A check whose category is unfamiliar is filed under a
  documented fallback bucket and **still runs**. Its findings land somewhere general rather than
  nowhere; the alternative is not running the check at all, which is strictly worse than filing it
  imprecisely.
* **Discard an entry only when it is unusable.** That is an entry with no `id` or no `command` —
  there is nothing to run and nothing to attribute. Every other missing or unfamiliar field has a
  defensible default.
* **Never answer from a hardcoded copy.** If the manifest cannot be obtained at all, say that the
  gate definition is unavailable; do not silently present a baked-in list as the project's gate.

The platform holds up its half. `verify_manifest()` publishes `categories` — the vocabulary the
document was written with — so "a category I have not seen" and "a document I should not trust" stop
being the same observation. And `tests/fixtures/verify-manifest.full.json` is checked in and held to
the live manifest by the suite, so a consuming repository can assert its parser against the real
shape rather than against a hand-copied sketch of it. The category vocabulary was already pinned
twice inside this repository (the runtime constant and the suite's independent statement of it); the
fixture extends that pinning across the boundary the seam was written for.

## Consequences

`terp verify` now means what it has always claimed to mean: the whole gate, not the platform's half
of it. A driving tool that configures itself from `--list` gets the app's checks for free, without
knowing they exist.

The platform stops needing to anticipate a tool in order for an app to gate on it. That is the
ADR 0103 clause applied to the gate itself — enforce a pattern (a check is declared data with a
scope and a profile), never limit a capability (which check).

`verify_manifest` takes an optional project root. Without one it yields the platform floor, which
keeps every existing caller correct and makes "the floor" nameable in its own right.

The trade accepted here is that an app can put a slow or flaky command in `quick`. That is the
app's own gate to get wrong, it is visible in `--list`, and it is strictly better than the same
command living in a pytest wrapper where nothing shows it at all.

## Alternatives considered

**A plugin entry point.** Rejected: it makes a check a package rather than a line, needs a release
to change, and the declaration would then be invisible in the one file a reviewer reads to learn
what an app gates on.

**Anticipate the tools.** Add `deptry`, then the next tool, then the one after — the `9ed3bce`
approach continued. Rejected on the evidence: three separate reports of the same friction against a
table that had already been extended once for exactly this reason. The general case was the
finding.

**Let a declared check join a lane.** Rejected: the lane vocabulary and each lane's requirement
level are the spec's, and an app-side declaration that could satisfy `appsec-baseline` would make
the release-assurance claim mean whatever the app said it meant.
