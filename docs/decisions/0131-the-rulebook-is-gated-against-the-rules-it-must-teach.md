# 0131 — The rulebook an agent reads is gated against the rules it must teach

- **Status:** Accepted and implemented. The generated `AGENTS.md` teaches the operations
  catalog, the job actor, module tests, the production refusals, the clipboard seam and
  the port range; two tests in `tests/architecture/test_template.py` hold it against the
  platform's own refusal messages and the CLI's guide-topic registry.
- **Date:** 2026-09-09
- **Relates:** [ADR 0103](0103-the-ideology-one-pattern-enforced-escapable-by-proof.md)
  (agentic coding is what makes a machine-readable surface the primary interface),
  [ADR 0126](0126-a-capability-publishes-its-operation-set.md) and
  [ADR 0130](0130-an-apps-own-operations-live-outside-the-template-catalog.md) (the rule
  golden rule 9 now states), [ADR 0125](0125-a-declared-job-names-the-actor-its-writes-are-stamped-with.md)
  and [ADR 0129](0129-the-job-actor-has-a-conventional-address.md) (golden rule 10),
  [ADR 0128](0128-the-gate-asks-whether-the-app-would-boot-in-production.md) (the check
  golden rule 12 points at)

## Context

The template's `AGENTS.md` is the file every agent working in a generated app reads
before it changes anything. It went seven releases without a word about the two rules
whose violation refuses an upgraded app's boot — folding a capability into the operation
catalog by splatting its published set, and naming the actor a declared job's writes are
stamped with.

It was not stale relative to the template. It was **byte-identical** to the template's
own copy for that entire span, which is exactly why nothing caught it: the only staleness
anything checked was the app's copy against the template's. Staleness of the template's
copy against the platform's rules was checked by nothing at all.

That is a sharper failure here than it would be in most repositories, because of what
this platform is for. The code is written by an agent, so an agent will do whatever the
gates and the briefing permit; a rule that exists only in a changelog is not a control,
because nothing stops the next change from being written around it. The report that
surfaced this put it plainly: one line saying "fold capabilities in by splatting
`<CAP>_OPERATIONS`, never by naming their operations" would have been enough, instead of
reading the whole changelog to find it.

There is an irony worth recording. `terp upgrade --check` argues that a stale `AGENTS.md`
"briefs every agent from the wrong rulebook" — and the same critique landed one level up,
on the copy the template itself ships.

## Decision

**The rulebook is brought current**, with the rules an app actually breaks: the
operations catalog and its two halves, the job actor and where it now comes from, that a
module owes tests, the four production refusals a control plane can carry, the clipboard
seam, the outbound-HTTP capability, `emit_disclosure`, and the port range — the `terp
dev` line had been teaching 8000 and 5173 three releases after they moved.

**And it is gated, two ways, both derived rather than hand-kept.**

`test_the_template_rulebook_names_every_production_boot_refusal` calls the platform's
declaration-decided refusals, extracts every identifier and sanctioned constructor the
messages name, and requires each to appear in the rulebook. A release that adds a
production refusal naming a new field fails until the rulebook says so. The messages are
*called*, not pattern-matched out of the source — a source scan of the same functions
picked up unrelated identifiers from the rest of each module, which is the kind of
almost-working check that passes for the wrong reason.

`test_the_template_rulebook_lists_every_guide_topic` compares the rulebook's topic index
against the CLI's live registry. It caught nothing today (the lists agree), and it is
still worth having: a release that adds a topic and leaves the index alone makes the new
topic undiscoverable to the one reader that file exists for.

**What the first gate deliberately does not do** is judge the sentence around the
identifier. It cannot tell a good explanation from a bad one, and pretending otherwise
would be theatre. It refuses a rulebook that has never heard of a field the platform
refuses a boot over, which is the failure that actually happened.

## Consequences

Adding a production refusal now costs a line in the template's rulebook. That is the
intended price: a refusal nobody was told about is a refusal discovered on deployment
day.

The gate reads the template's copy, not any app's. An app whose own `AGENTS.md` has
fallen behind is still only reported, by `terp upgrade --check`, and deliberately so —
scaffolding legitimately lags, and a gate on any gap would be noise.
