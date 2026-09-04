# 0114 — Terp supplies the inside of a deployable, and says nothing about the between

- **Status:** Proposed (awaiting review). Decisions 1–3 describe what already exists and
  need only ratification; decision 4 is a roadmap and is unbuilt; decision 5 is a
  documentation obligation that falls due with the first item of decision 4.
- **Date:** 2026-09-04
- **Relates:** [ADR 0111](0111-flexibility-is-bounded-by-legibility-not-by-capability.md)
  (the three kinds of rule, and the deployment layers this completes),
  [ADR 0110](0110-an-app-declares-which-parts-of-its-dev-topology-are-load-bearing.md)
  (legibility as a shipped instance, and the "three APIs, two frontends" boundary),
  [ADR 0087](0087-declared-module-dependency-edges.md) (the declared edge that makes a
  split legible at all), [ADR 0027](0027-packaged-migrations-per-package-histories.md)
  and [ADR 0070](0070-per-module-schema-layout.md) (the data half of the same asset),
  [ADR 0045](0045-durable-outbox.md) and [ADR 0008](0008-event-bus-catalog-and-typed-emit.md)
  (the guarantees a split spends), [ADR 0088](0088-service-principal-credentials.md)
  (the sanctioned-path-must-be-easier argument, applied here to egress),
  [ADR 0062](0062-production-deployment-profile.md) (the reference hosting target)
- **Designed in:** [docs/internal/PLATFORM_REACH.md](../internal/PLATFORM_REACH.md) —
  decision 4's five sockets, worked through to seams, enforcement and tests, alongside
  the application-kind gaps that turn out to have the same shape.

---

## Context

A platform is asked, sooner or later, which architectures it supports. Terp has no
answer written down. `AGENTIC_PLATFORM_DESIGN.md` §12 covers *repository* topology —
one monorepo, many published packages, and when to split the repo — and stops there.
ADR 0111 covers *infrastructure* and reaches a clear verdict: topology is layer 3, free,
"service count, images, languages, extra containers, network arrangement, provider. No
rule at all." ADR 0110 makes the same point from the other side, listing "three APIs;
two frontends; no frontend" among the things a legibility check must never call red.

Both of those are statements about what is **not gated**. Neither is a statement about
what is **supplied**, and the two get read as one.

That conflation is not hypothetical, and it is not the reader's fault. An author — very
often an agent — asks whether an application can be built as three services, finds
nothing that refuses it, and correctly concludes that it may. What nothing in the
repository tells them is that the platform will hand them the inside of each of those
three services and nothing that runs between them: no client to call the next service
with, no bus that crosses a process, no trace that survives the hop, no principal that
arrives at the far end. Each of those absences is discovered one at a time, at the point
of use, by someone who has already committed to the shape.

The absences are also uneven in a way that misleads. Terp is *conspicuously* good at
several things that look adjacent to a distributed system and are not: a durable outbox
that appends on the business write's own session; leases with epoch fencing; a job seam
with a broker adapter that carries `actor_id` / `tenant_id` / `request_id` across the
wire; shared throttle, idempotency and cache stores whose absence is a boot failure in a
multi-instance deployment. Every one of those is machinery for **many processes over one
database**, which is a different problem from many services over many databases, and
they are easy to mistake for evidence that the second is covered too.

There is one place where the silence is worse than silence: an app module that needs to
call another service. `no_raw_outbound_http` refuses `httpx` / `requests` / `urllib` /
`socket` inside `app/modules/*`, and the sanctioned egress capabilities are webhooks
(outbound *push*), OIDC, and a `SyncSource` the app writes — which, placed in a module,
trips the same rule, so it has to be lifted out of the module tree or take a budgeted
escape hatch. There is no capability whose job is "call something". So the platform's
only advice on the most ordinary act in a multi-service system is a prohibition with
nowhere to go, and the path of least resistance is an escape hatch. ADR 0088 already
settled how to think about that: "the sanctioned path has to be *easier* than the wrong
one, or it will not be taken."

## The distinction this ADR adds

ADR 0111 named three kinds of **rule** — security invariants, legibility contracts, and
the application's own business. That classification is about what the platform *refuses*.
It is complete for its purpose, and it does not settle the question above, because a
thing can be permitted and unsupplied at the same time.

For any architectural choice there are three independent questions:

- **Is it refused?** — the ADR 0111 axis. For topology, the answer is always no.
- **Is it supplied?** — does the platform ship the parts, with its guarantees attached?
- **Is it legible?** — can a tool find, drive and diagnose the result?

Terp today answers **not refused** for every topology, **supplied** for exactly one, and
**legible** for the development loop of one app. Those three answers are all defensible.
Only their combination is misleading, and only because it has never been written down.

## Decisions

### 1. Name the shape Terp supplies

**One deployable, many processes, one database, one contract, one identity authority.**

The processes are already first-class and already several: the API (`uvicorn` over
`create_app`), the durable worker (`terp jobs worker`), the scheduler
(`terp jobs scheduler`), and the one-shot migration (`terp migrate upgrade`, ordered
before the API serves and backed by the fail-closed boot guard). Horizontal scale-out of
the API is supported and is honest about its prerequisites: `require_shared_throttle_store`,
`require_shared_idempotency_store`, `require_shared_cache_store`, `require_durable_jobs`,
`require_durable_leases` and `require_token_revocation` each turn a single-instance
default into a boot failure rather than a silent dilution.

Four things follow from "one deployable", and they are the load-bearing half of the
sentence:

- **The enforcement surface is one tree.** The rules run over one `app/`, and the module
  dependency graph is validated from the specs mounted in one process. Modules split
  across repositories are modules the platform can no longer see.
- **The transaction is the consistency boundary.** An in-process event handler runs
  inside the producer's open transaction and may reach it through
  `current_event_session()`; the outbox row commits with the write that caused it. Every
  no-dual-write guarantee Terp makes is bought with that shared transaction.
- **The contract is one OpenAPI.** `@terpjs/contract` is generated from one app's export,
  `TerpProvider` takes one `baseUrl`, the production profile serves the SPA same-origin
  behind one `/api` proxy, and `generated-client-only` refuses every other egress from
  the browser.
- **Identity has one authority.** Tokens are minted against one store; a service
  principal authenticates a program *into* an app. Nothing exchanges a token for another
  audience, and nothing carries the human actor across a hop.

None of this forbids a second service. It states what the second service does not
inherit.

### 2. The module graph is the decomposition asset, and it is unusually good

The reason to write decision 1 down without embarrassment is that Terp's monolith is
already a cuttable one, which most are not. The parts are shipped and enforced:

| Asset | What it gives an extraction |
|---|---|
| `ModuleSpec(requires=...)` (ADR 0087) | Every sibling dependency is a declared arrow, read statically, granting four slots and never the router |
| `module_dependency_graph_is_acyclic` | Boot refuses a cycle by name — the one rule of the three with a runtime half |
| Per-package Alembic histories (ADR 0027) | The module's schema history is already its own, with its own version table |
| `table_ownership_is_not_split` | The tables that move are exactly the tables the package declares |
| `DB_SCHEMA_LAYOUT=per-module` (ADR 0070) | Physical separation of those tables without touching a model |
| A second `build_*()` composition root | N deployables out of one tree today, each with its own module set, capability profile, guard and OpenAPI — the example app already ships two |

The last row is the practical answer for most consumers who think they want services:
a second entry point over the same code and the same database costs a function, and it
keeps every guarantee in decision 1.

What the checklist does **not** give is the part everyone assumes it does. Cross-module
foreign keys are expected — the per-module schema recipe keeps other packages' labels on
the `search_path` precisely so "cross-module FK targets resolve" — and one engine is a
recorded posture, with a read-replica seam noted as additive and unbuilt. A module can be
lifted into its own process cheaply. Lifting it into its own **database** is a data
migration and a rewrite of every cross-module read, and no rule in the platform will tell
you which ones those are, because they are not imports.

### 3. State the price of a split once, so it is not rediscovered

An application that moves a module into its own deployable with its own database gives
up four things it did not have to ask for:

1. **In-process event delivery.** `dispatch_in_process` is the only dispatcher. The
   durable variant persists an outbox row and drains it with a worker that runs
   *in-process* handlers, so `emit` crosses a process boundary only through a shared
   database and never a network. Cross-service choreography is hand-built on webhooks or
   a consumer the app writes.
2. **The no-dual-write guarantee.** It is the same transaction or it is a saga. The
   outbox makes local atomicity free and says nothing about a remote effect.
3. **One audited actor.** Actor and tenant stamping ride the job envelope across a
   broker; they do not ride an HTTP call, and the far end's audit trail will name an
   integration rather than a person.
4. **One typed client.** An app can generate its own paths and pass them to
   `useTerpClient`, so several typed clients are reachable — but `/me`, session refresh,
   nav resolution and realtime tickets all resolve against a single backend.

This list is the ADR's most useful paragraph and the reason it is worth a file: each item
is knowable today only by reading the source that implements it.

### 4. The between is a socket, not a catalogue

ADR 0111 decision 4 already fixes the method — the framework defines what a thing must
declare about itself rather than shipping every implementation — and it applies here
without amendment. What follows is therefore a short, ranked list of **sockets**, not a
promise of services. Every item is additive: none changes an existing single-deployable
app, and by ADR 0111 decision 3 an unrecognised declaration is information rather than an
error.

1. **A declared egress capability.** Allowlist, timeouts, bounded retry with jitter, a
   breaker, sealed credential custody, egress audit, and outbound correlation headers.
   This is first because it is the only place in the platform where the wrong path is
   currently the easy one, and because it also unblocks a `SyncSource` written where it
   belongs — inside the module that owns the entity.
2. **A relay-backed `EventDispatcher`.** The seam exists and the outbox already proves it
   is swappable without touching a call site. Keep the outbox as the transactional
   producer; add a relay that publishes drained rows to a broker, and a typed subscriber
   entry point on the far side, so `emit` can cross a boundary without a shared database.
3. **Trace context, in and out, in the middleware that already owns request-ids.** The
   correlation identifier survives the job seam today and dies at every HTTP hop.
4. **A deploy-unit legibility vocabulary**, generalising `workbench.json` past one
   compose file: which units exist, which image each is, its health path, which unit owns
   which migrations, what a rollback is. Per ADR 0111 decision 5, the words belong in
   `terp-spec` and the enforcement stays in the framework.
5. **Audience-scoped service tokens with an on-behalf-of claim**, so decision 3's third
   loss becomes recoverable and the far end can audit the human.

Items 1–3 are capabilities and cost a release each. Item 4 is a schema and costs a
version of the spec. Item 5 is an extension of ADR 0088's subject kinds, not a second
authorization path — the same constraint that ADR imposed on itself.

### 5. Until then, say it out loud

ADR 0111's degradation test asks who loses when an application is illegible, and requires
that the tool lose the feature, say so, and leave the application working. The same test
applies to an application that is *unsupplied*, and the answer must be the same shape: a
three-service Terp application still builds, still deploys, still passes every gate, and
still satisfies the deploy-safety envelope — which constrains properties and never
topology. What it loses is platform-supplied connective tissue, and the loss is silent
today.

So this is a documentation obligation with a deadline: the guide topic and the generated
`AGENTS.md` must state which shape is supplied and what the alternatives forgo, and they
must say it **before** an author chooses rather than after. Until decision 4 lands, the
honest sentence is short: *Terp supplies one deployable and the processes around it; a
second deployable is permitted, unsupplied, and yours to connect.*

## Consequences

- Consumers get an answer to a question the repository could not previously answer, and
  agents building on Terp get it in the place they already read.
- Nothing is refused that was permitted before. Decision 1 is a description; decision 3
  is a price list; only decision 4 adds anything, and every item of it is additive.
- The framework acquires a stated gap. That is the point: a gap named in an ADR is a
  roadmap, and a gap discovered at the point of use is a surprise.
- ADR 0111's "the number of use cases stops being bounded by the number of capabilities
  we have shipped" holds only where a socket exists. Between two deployables there is no
  socket yet, so today that boundedness is real — which is worth stating plainly rather
  than letting the general principle imply otherwise.

## Where this stands

Decisions 1–3 are descriptions of the tree as it is on 0.17.0 and can be ratified without
code. Decision 4 is unbuilt in all five items and unscoped. Decision 5 falls due with
item 1 of decision 4, and is cheap enough to land earlier.
