# 0087 — Declared module dependency edges

- **Status:** Accepted
- **Date:** 2026-07-24
- **Relates:** [ADR 0006](0006-cross-cutting-controls-and-opinionation-policy.md)
  (the two-layer doctrine this rule set is classified under),
  [ADR 0009](0009-authoring-model-and-opinionation-boundary.md) (the module slots
  a declared edge grants access to), [ADR 0084](0084-runtime-applicability-classification.md)
  (why exactly one of the three rules carries a runtime half),
  Terp Standard **v0.19.0** (the spec release that carries the catalog entries).

---

## Context

Terp shipped one rule about modules knowing each other: `no_cross_module_imports`
refused any import of a sibling, absolute or relative, with no way to say yes.
The intent was sound — modules are independent, so a monolith cannot condense out
of them by accident — but the rule had no legal outcome for a dependency that is
*real*.

Dogfooding surfaced the consequence. In a real app, a catalogs module
needed to assert that a connection profile exists before publishing a snapshot
against it — an unremarkable, genuinely one-way dependency on a sibling. The
platform's only sanctioned answer was to invert it, so the app grew:

- a hand-written `Protocol` restating the sibling's method signature,
- a module-global mutable registry the sibling writes itself into at import time,
- a composition-root adapter wiring the two together at start-up.

Three files, mutable global state, an import-order hazard, and a signature that
now has to be kept in sync by hand — to express a coupling the platform still
could not see, check, or render. The rule had not removed the dependency; it had
removed the platform's knowledge of it. That is strictly worse than the coupling
it was defending against: an undeclared edge and a hand-inverted one are the same
arrow, and only the second is invisible.

Meanwhile the platform already had a manifest field named `requires`. Every
module declares a `ModuleSpec`, and `requires` listed the capabilities the module
needs present at boot. The vocabulary for "this module depends on that" existed,
in exactly the place a reader already looks, doing a smaller version of the job.

## Decision

**A module may import a sibling, if and only if it declares the edge in its own
`ModuleSpec(requires=...)`.** `requires` gains a second meaning: it is the
exhaustive list of both the capabilities and the sibling modules the module
depends on. Nothing new is introduced for authors to learn; an existing
declaration is given a larger, and more honest, job.

Three rules bound what a declared edge may do.

### 1. `no_cross_module_imports` — the edge must be declared

Restated, not relaxed. A sibling import is refused unless the *depending* module
names the dependency. The declaration is read statically from
`modules/<name>/module.py`; a `requires=` that is not a literal sequence of
string literals, an unparseable manifest, or a missing one grants **nothing**
(fail closed). The reader intersects the declared names with the modules that
actually exist, so a capability in `requires` never silently becomes a module
edge. Relative imports are resolved to their absolute module before the check,
so import style cannot launder a coupling.

### 2. `cross_module_imports_use_public_surface` — the edge grants four slots

A declared edge grants the dependency's `models`, `schemas`, `service` and
`events` — and nothing else. Specifically:

- **never its router.** A router is an HTTP surface: importing it couples the
  two modules through request/response plumbing, and an in-process call reaching
  a route function walks straight past the policy that guards that route. The
  guard is mounted on the router, not baked into the handler; that is the whole
  point of a deny-by-default mount, and it is exactly why the router is not a
  callable API for a sibling.
- **never an underscore-prefixed internal**, which is the module's own business.
- **never the bare package**, which reveals nothing about what is being used and
  defeats the point of naming a surface.

This is what makes an edge cheaper than the hand-rolled inversion it replaces:
the arrow is legible *and* narrow. Build-time only — the invariant is a property
of the import graph, erased before the app serves (ADR 0084 `not-applicable`).

### 3. `module_dependency_graph_is_acyclic` — edges are one-way

A cycle means two modules that call themselves independent have become one, with
a boot order that only works by luck. This is the one rule of the three with a
**runtime half**, and it gets one for a structural reason: the composition root
already collects every mounted `ModuleSpec`, so the full graph is present, in
memory, on a seam the framework owns. `_validate_requires` therefore refuses to
boot on a cycle, naming every participant. Under ADR 0084 that makes it
`required`, while its two siblings are honestly `not-applicable`.

## Consequences

- **The sanctioned answer is now cheaper than the workaround.** An author with a
  real dependency adds one name to a tuple they already maintain, instead of
  inventing a protocol, a registry and an adapter. Rules that leave the correct
  path more expensive than the evasive one do not get followed; this one closes
  that gap.
- **The dependency graph becomes a first-class, rendered artifact.**
  `terp inspect control-plane` prints each module's `requires`, and the JSON
  output carries it, so "what depends on what" is answerable without reading
  imports.
- **Refusals became directive.** An undeclared sibling import now names the
  manifest and the exact line to add, rather than telling the author that what
  they are doing is impossible.
- **Declaring stays a decision, not a reflex.** The guide topic
  (`terp guide dependencies`) states when *not* to declare an edge: react to a
  sibling through events rather than calling it, extract a third module when two
  modules want each other, and remember that capabilities are not edges.
- **`requires` is now load-bearing in two ways at once.** A future need to
  distinguish a capability requirement from a module edge would mean splitting
  the field; the intersect-with-existing-modules reader is what keeps the two
  meanings from colliding today.
