# 0192 — A conversation is a capability, its stream is an AG-UI profile in the spec, and the assistant is the app's

- **Status:** Proposed (awaiting review). Nothing is built in this repository yet. The event
  vocabulary is proposed for terp-spec 0.41.0 (`conversation-events.schema.json` with
  `conversation-events.fixtures.json`), which is not released yet; until it is pinned here,
  this record is the design the capability is built to.
- **Date:** 2026-11-02. 0182 and 0183 are reserved for other records; 0184 to 0191 are taken.
- **Relates:** reads [ADR 0111](0111-flexibility-is-bounded-by-legibility-not-by-capability.md)
  §4 (the framework owns the socket, not the plug) and decision 5 (a contract two programs
  read lives in the spec); **amends the reading of §4** that
  [ADR 0117](0117-the-egress-capability-the-rule-was-already-naming.md) records in its
  consequences and the R9 draft repeats, that §4 declined a dedicated AI capability (Context,
  point 3), while 0117's own decision, the egress capability and its observer, stands; follows
  [ADR 0186](0186-a-declaration-vocabulary-lives-in-the-spec.md) (a vocabulary in the spec
  with fixtures every reader runs, and what a reader does with a version it does not know);
  applies [ADR 0060](0060-projects-is-example-code-base-profile-closure.md) (a cross-cutting
  mechanism is a capability, a business noun is a module); composes
  [ADR 0027](0027-packaged-migrations-per-package-histories.md) (packaged migrations),
  [ADR 0056](0056-files-capability.md) (files, and their owner-gated delete),
  [ADR 0077](0077-idempotency-keys-for-unsafe-methods.md) (the `Idempotency-Key` seam a run
  request is deduplicated by), [ADR 0095](0095-expiring-fenced-custody-of-work.md) (leases),
  [ADR 0126](0126-a-capability-publishes-its-operation-set.md) (the operation set),
  [ADR 0176](0176-a-realtime-publish-reaches-every-process-that-serves-the-channel.md)
  (the shared realtime broker) and [ADR 0190](0190-a-field-declares-itself-personal.md)
  (what a person wrote is declared personal); places its surface under
  [ADR 0079](0079-slot-typed-layout-contracts.md)'s layout contracts and leaves
  [ADR 0179](0179-a-canvas-fills-the-screen-from-a-page-not-from-a-style.md) (a workspace
  holds one canvas) as it is; amends
  [ADR 0144](0144-one-transport-and-the-caller-that-brings-its-own-policy.md) (one transport
  becomes two, both in egress) and the R9 sketch in
  `docs/internal/drafts/platform-reach-open-items.md` (its `{ seq, delta, done }` envelope is
  replaced by the spec's vocabulary, its "slow work is a job" gives way to decision 4, and its
  reading of §4 is the one amended above).

---

## Context

Several applications built on Terp carry a chat of their own, a person talking to an
assistant, and each one wrote it from nothing. The most complete is the workbench's (Terp
Studio), which fronts coding agents and has recorded, decision by decision, what a
conversation is: text that arrives at its own pace, a tool call as a row on a timeline, a
question the agent asks and ends its turn on, a message sent while a turn runs that either
redirects it or waits behind it, how full the agent's memory is. None of that is specific to
coding agents, and none of it reached another application, because there was nothing to reach
it through.

Three facts make a capability the right shape rather than a library an app copies.

1. **The value is the enforcement, and only the platform can enforce.** A conversation is a
   user's text kept in the app's database and a model reached over the network. What an
   application owes for that is exactly what the framework already enforces elsewhere and a
   copied component cannot: rows owned per user with a write guard and a read scope, a policy
   on every route, an outbound call only to a declared host, an audit record of every write,
   a way to erase one person's data. A chat outside the platform skips all of it, and every
   copy skips it differently.
2. **Two programs read the stream, in different stacks.** The program that runs the assistant
   and the program that shows it each had their own idea of the frames. The workbench's own
   stream, read for this record, carries questions, memory fill and compaction only inside the
   record written after the turn, addresses messages by list index because they have no id,
   and drops the tool call's id on the wire. ADR 0111 decision 5 answers that: the contract
   goes to the spec.
3. **The model is not ours to choose.** ADR 0117 read ADR 0111 §4 as declining an AI
   capability, and the R9 draft repeats it. §4 says neither that nor the opposite: its subject
   is declarations. For each thing a client might need that we have not shipped, it has the
   framework define what such a thing must declare about itself (its containers, how to tell
   it is healthy, its configuration keys, where its migrations live, its security posture), so
   that one a client builds is as first-class to our tooling as one we ship, and the
   framework's own become reference implementations rather than the only permitted plugs. It
   names no AI capability and refuses none. This record amends 0117's reading to that, and
   borrows §4's division by analogy rather than as its mandate: the framework owns a contract,
   the app owns what fills it, and the framework's own implementations are references. Here
   the contract is a port and a vocabulary rather than a declaration, and what fills it is the
   app's model.

The protocol question had an answer outside Terp before it had one inside. AG-UI (the
Agent-User Interaction Protocol, MIT, 1.0 since 2026-09-17, with SDKs for TypeScript and
Python) is an open, event-based protocol between an agent and the interface that shows it. Its
1.0 events map the workbench's stream almost one for one, and its `interrupt` outcome with a
resume entry on the next run is the workbench's "the agent asks you and ends its turn",
structurally.

## Decision

**1. Conversations are a routed capability, `terp-cap-conversations`.** It owns the mechanism:
conversations, messages, runs, the stream, attachments, the queue of messages sent while a run
is going, retention and erasure. It owns nothing about models: no provider, no prompt, no tool.
That is the division ADR 0111 §4 draws for declarations, applied here to a port: the
capability owns the contract, and the app owns what fills it. The import is
`terp.capabilities.conversations`; it depends on `files`, `realtime`, `leases` and `egress`,
and is modelled on `webhooks`, the one capability with a router, owned tables, a dependency on
another capability, packaged migrations and an escape-hatch budget.

**2. The stream's events are AG-UI 1.0, profiled in the Terp Standard.** terp-spec 0.41.0,
proposed and not yet released, fixes the vocabulary: twelve AG-UI event types, closed; every
object the profile defines closed except the three values AG-UI leaves open (an interrupt's
`responseSchema`, and the `content` of a producer's own activity type and the `value` of its
own custom event), which stay open, are held to a bounded nesting depth, and are scanned, keys
and strings alike, for control characters; every string capped; a closed `terp.` namespace
where AG-UI leaves a name open (`terp.compaction`, `terp.context`, `terp.handoff`,
`terp.question`) and a `metadata.terp` key on the events that need one; named event rules and
stream rules for what a schema cannot state; `metadata.terp.schemaVersion` on `RUN_STARTED`,
refused when unknown, as ADR 0186 decision 4 asks of a reader that acts on what it reads.
This repository will carry a checked mirror of the schema and fixtures, as it does for the
workbench declaration, and both the producer and the client run every fixture.

What is AG-UI's is the events, not the transport. Every event a Terp stream carries is an
AG-UI event and parses as one. The transport is the capability's own: a run is started by a
POST that answers 202 (decision 4), and its events are read by an SSE GET opened with a
realtime ticket, with an `id:` per frame and `after=` for replay (decision 5). AG-UI's HTTP
binding is one POST whose response is the stream, so an off-the-shelf AG-UI client does not
open a Terp conversation by itself: it needs an adapter that posts the run, mints the ticket,
opens the GET and passes each event through. The other direction needs none: an AG-UI agent
sits behind the capability through the `[agui]` reference Assistant (decision 3), which is the
client of that agent's own HTTP binding.

**3. The assistant is the app's, behind one port.**

```python
class Assistant(Protocol):
    def run(self, input: RunInput) -> AsyncIterator[Event]: ...
```

`RunInput` and `Event` are the capability's own models, and neither imports AG-UI (the
dependency is an alternative not taken, below). `Event` is written against the spec's schema
and held by its mirror and fixtures (decision 2). `RunInput` holds the subset of AG-UI's
`RunAgentInput` the capability accepts: the thread and run ids, the stored messages, the app's
tools in AG-UI's own `Tool {name, description, parameters}` shape, context, per-run options in
`forwardedProps`, and `resume` entries answering an interrupt. It is held to AG-UI by a
parity test against AG-UI's published input schema, vendored at a pinned AG-UI version: every
field `RunInput` declares is checked against it by name and type, and every `RunInput` the
tests build validates against it, so a field AG-UI renames or retypes fails the build at the
pin bump rather than at a remote agent. That subset is a contract two programs read, so it is
the Terp Standard's to state (ADR 0111 decision 5): an input profile lands in the spec together
with the capability, beside the event vocabulary that 0.41.0 profiles on its own.

The Assistant yields events and never touches the database, the stream or a secret; the
capability validates every event against the vocabulary, persists it, and publishes it. There
is no checkpoint argument: a steer or a cancel takes effect at the next event the Assistant
yields, and an Assistant that wants a safe boundary simply yields nothing until it reaches
one. An Assistant that needs the person yields `RUN_FINISHED` with an interrupt outcome. Two
reference Assistants ship as **extras**, so the core distribution has no model dependency:
`[claude]` (the Claude Messages API through egress, streaming, with server-side compaction,
refusal fallback and a token budget) and `[agui]` (a remote AG-UI agent at a declared URL,
through egress, its events relayed and normalised to the profile). The workbench's
coding-agent adapters, which run a command-line agent as a subprocess in an isolated checkout,
stay in the workbench: driving a coding agent is a workbench concern.

**4. A run executes in the API process, under a lease on its conversation.** Two runs of one
conversation never execute at once, and the queue and the one-open-question rule (decision 10)
rest on that. The lease is a mutex on the conversation, `LeaseResource("conversation_run",
str(conversation.id))`, the `(kind, key)` form ADR 0095 gives for "at most one active run per
pipeline". Not `LeaseResource.for_row(run)`: every run is its own row, so a lease on one
serialises nothing between two. `for_row(conversation)` would serialise them, and the API takes
either; the mutex is chosen because a lease's kind is its reaper's key and names a recovery
(ADR 0095 §5), and what is held is the conversation's one running slot rather than custody of
the conversation row, which is the reason the sync capability keys its lease on the source and
not on a row (ADR 0095 §7). Unlike sync's, this lease is not optional: with no store wired the
seam fails closed with `LeaseError`, so an app that mounts the capability wires
`create_app(lease_store=DatabaseLeaseStore())`.

`POST /conversations/{id}/runs` stores the message and a run row in one write, and in that
write takes the lease with `acquire_lease`, which answers `None` rather than raising when the
lease is held: free, the run starts; held, the run stays queued behind the one executing, its
message pending. It returns 202 either way. The holder takes the next queued run as its own
before it lets go, and releases only in a write that finds none queued, so the queue drains
under the lease one run at a time. Both writes lock the conversation row first
(`SELECT ... FOR UPDATE`), so a run queued while the holder lets go is either seen by
the holder's last write or finds the lease free: none is left queued with nobody to start
it. The run is an asyncio task that heartbeats the lease, so a
paused process is fenced out, and a reaper registered for the kind closes an abandoned run
failed with a sentence.

The task runs on the event loop and does no synchronous work there. Each write to the log,
each heartbeat and the release run in `asyncio.to_thread` with a session opened in that
thread, as the realtime capability's router runs its ticket redemption, its live-principal
check and a synchronous inbound handler, whose `_run_sync_handler` opens its session inside the
thread; a call through the synchronous `EgressClient` runs the same way, and the port says so
to every Assistant. The lease travels between steps as its `Lease` value and is renewed with
`renew_lease` on the step's own session, so no session crosses a thread, and a renewal that
answers `None` stops the run as `LeaseLostError` stops a guard's holder. Only the broker's
`publish`, a coroutine, and the model's stream, through decision 6's transport, are awaited on
the loop.

Not a job, against R9's "slow work is a job", because a job handler is synchronous and the
default in-process queue runs a job inline in the request, which would hold the POST open for
the whole run. A worker-run mode on `OutboxJobQueue` and the shared broker is a later option
behind the same port.

The client mints `runId`, as AG-UI's input already requires, and sends it as the request's
`Idempotency-Key`: a run request is deduplicated by ADR 0077's seam, not by a mechanism of its
own. The route refuses a request whose key is missing or is not its `runId` with a typed 422
before any write, which holds `runId` to the key's alphabet (1 to 128 characters of
`A-Za-z0-9._~-`, which a UUID meets). A retry with the same key and the same body gets the
stored 202 replayed; the same key with a different body is 0077's typed 422
`idempotency_key_mismatch`; a duplicate that arrives while the first is still executing is
0077's typed 409 `idempotency_in_flight`. A run row is unique on its `runId`, which is its
identity rather than a second guard: a duplicate that 0077's store no longer remembers (a retry
under a refreshed token, which 0077 scopes afresh; a per-process store and a retry on another
worker; a key past its replay window) meets that constraint as the framework's 409 for a unique
conflict, never as a second run.

Text deltas are coalesced on a short tick before they are persisted, and what is persisted is
what is published: one log row per coalesced event, so a frame's SSE `id:` is its sequence in
the log (decision 5), and a fast stream never trips the broker's per-subscriber backpressure. A
coalesced `TEXT_MESSAGE_CONTENT` stays within the spec's `maxEventBytes`, 65536 bytes of
compact UTF-8 JSON: the coalescer closes an event before the next delta would carry it past the
bound, and cuts a delta on a character boundary where one alone would, so coalescing never
makes an event a reader must refuse.

**5. Every event is persisted, and replay is by sequence.** An append-only event log per run is
what a reconnecting client reads from, by `after=<seq>`, and what a restart leaves intact.
Because deltas are coalesced before they are written (decision 4), the log holds exactly the
frames that were published, and each frame's `id:` is its sequence. The realtime capability
gains the half it lacks: an `id:` per SSE frame and a cursor on the ticket. Today it sends bare
frames, and a reconnect loses whatever was published meanwhile.

**6. Egress gains a streaming transport, and the model is reached only through it.** The
egress client is synchronous and reads a whole response into memory, so a model stream cannot
pass through it today. The change is a new transport on the egress capability, beside
`send_pinned` rather than in place of it: an asynchronous `httpx` transport bound to an
`EgressPolicy`, which applies the scheme, allowlist, SSRF, time and byte rules, pins the
connection to the address that passed, and streams the body. Its one blocking step, resolving
the name and checking every address it returns, runs in `asyncio.to_thread`; the connection and
every read of the body are awaited on the loop, each read under the policy's read timeout and
the running total under its byte cap, so a slow model holds a coroutine, never a thread or the
loop. The provider's SDK takes it as its HTTP client, so the reference Assistant runs inside
the declared allowlist with the socket guard (ADR 0177) as the runtime half. ADR 0144's one
transport becomes two, both in the egress capability and both built on its `PinnedTarget`, so
the four things that must be right about an outbound request are right in two places side by
side in one package, held by one set of tests, rather than in every caller. That is ADR 0117's
shape and R9's "`kind="model"`" defaults: a long read timeout and no retries. An SDK routed
around egress is never the answer.

**7. Storage is the app's database, and erasure is an operation.** Conversations, messages,
attachments, runs, run events, pending messages and interrupts are tables: `BaseTable` with
`OwnedMixin` on the conversation, every child a `Ref(..., on_delete=OnDelete.CASCADE)`, an
attachment's file a `FileRef`, every string capped, a scope predicate hiding another owner's
rows on reads, the user an FK-less UUID as ADR 0027 has it, list endpoints paginated.
Transcripts are not sealed: sealing would defeat search, and the app's database is the app's.
What the capability does owe is a `retention_days` setting with a reaper, and an audited
`erase` operation that deletes one person's conversations, because the framework has no
user-deletion hook (a user is deactivated, never deleted).

The cascade reaches every row the capability owns. It does not reach an attachment's stored
file: a `FileRef` imposes no foreign key, so a cascade would delete the attachment row and
leave the `File` row and its bytes behind. Erasure and retention therefore remove each
attachment's file through `FileService.remove`, the files capability's own owner-gated,
audited delete, which removes the stored object inside the row delete's own transaction, and
only then delete the conversation.

Everything that holds what a person wrote, or what was written back to them, is declared with
`Personal(...)` (ADR 0190): a message's text, a conversation's title and an attachment's name,
and in the run-event log every field that can carry words, which is a text delta, a tool
call's arguments and its result, a question's text and its answer, and the open values whose
shape the producer chooses (its own activity's content, its own custom event's value). A log row
keeps an event's structure (its type, its ids, a status, the usage counts) in columns of their
own, so what is left undeclared is what carries no one's words. The log, the audit trail and
the event and job definitions withhold the declared values because the framework reads the
declaration, not because the capability remembers to. So an audit record of any of these
writes carries ids, statuses, token counts and the declared fields' keys with their values
withheld (ADR 0190 decision 6): that something was said is on the trail, and what was said
stays in the rows, where erasure and retention reach it. The `File` row's `filename` is the
files capability's field and is not declared today; declaring it, on the model and on the
schemas that carry it, is a small change to that capability made with this one, so an
attachment leaves no name on the trail either.

**8. The surface is a react-core component family, placed in archetypes whose body slots
already suit it.** `Conversation` (transcript, composer, the working line, the one strip for
every problem), `ConversationList` and their parts, built on react-core's own primitives and its
realtime hook, with the strings in both shipped locales. No layout contract changes, because
none has to: under ADR 0079 a slot governs its direct children only, and what an admitted
container holds is the app's to compose.

- **A list beside the open conversation** is a `SplitPage`, the master-detail screen. Its body
  admits only `SplitPane`, and `ConversationList` in the list pane and `Conversation` in the
  detail pane are each pane's own content.
- **A conversation about one record** sits in that record's `DetailPage`, inside a `Card` or
  a `Tabs` panel, which the `standard` contract admits as sections of a detail body.
- **A screen that is the conversation alone** composes the plain `Page`, whose body ADR 0079
  leaves unconstrained as the home for a bespoke screen.

Not the `WorkspacePage`. ADR 0179 admits one `CanvasHost` there, beside the framework states
and a `ConfirmDialog`, because a second block would have to share a height nobody declared, and
this record does not amend it. A transcript is read along a line and grows with what is said,
so it scrolls with its page as any body does; if a conversation turns out to need the height
the shell leaves, that is an amendment to ADR 0179, argued on its own. The client's state
machine is a logic-only core with no React and no `@terpjs/*` import, held there by a test, so
it can leave as a package the day something outside Terp asks for it, and not before.
react-core's `Markdown` gains GFM tables and a settled/tail split so a streaming message
re-parses only its tail. No new archetype.

**9. The workbench conforms; it does not import.** The workbench takes no dependency on any
framework frontend package, for reasons its own records give (the split boundary, version skew,
and the trap where a broken framework release breaks the tool used to fix it). It keeps its
panel and is held to the vocabulary by a parity test that vendors the schema and fixtures byte
for byte from the spec release, as it does for the deployment and development-loop
declarations, and reads its own turns through them.

**10. The questions left open by the design are settled here.**

- **One open question per conversation.** The vocabulary allows one interrupt per run; the
  capability allows one open interrupt per conversation, and a newer message withdraws it. It
  rests on the lease: only the run holding the conversation's lease can open an interrupt, and
  the write that starts the next run under it withdraws the open one.
- **Rewind stamps, erasure deletes.** Rewinding to a message stamps the later ones superseded:
  hidden from the transcript and from the Assistant's input, kept for the audit trail and an
  undo. Only `erase` and retention delete.
- **Per-run options travel in `forwardedProps`.** Effort, or a model from a list the app
  allows, is the Assistant's to honour; the capability stores no per-user preference in v1.
- **Search is the server's.** A lexical, ranked search over titles and message text, because a
  paginated list cannot be searched in the browser.
- **Person-to-person messaging is out of scope.** The transcript, the composer and the stream
  would carry it; if an app needs it, it is a second capability on the same surface, not a mode
  of this one.

## Consequences

- An app adds one distribution, names its Assistant once at composition, grants the operation
  set, and renders one component; the template starter offers it once it is built.
- The workbench and any application on the capability read and write one event vocabulary. An
  AG-UI client from outside Terp reads those events as AG-UI's own, and reaches a conversation
  on the capability through an adapter for the transport (decision 2).
- Two existing capabilities change for a reason that is not the conversation's: realtime
  gains replay, which any channel can use, and egress gains a streaming transport, which any
  long-lived outbound read can use. A third changes by a declaration: files declares
  `filename` personal on its model and schemas (decision 7), which costs no migration (ADR
  0190 decision 1).
- A new set of framework strings reaches every app with a non-English locale, which fails at
  runtime until it carries them; the release note lists the keys.
- The capability touches every registry a new capability touches: the workspace members and
  sources, the capabilities catalogue and the root README, the CLI's capability list with a
  `conversations` guide topic, the architecture harness, the release workflow and the
  publisher table, the migrations conformance labels and domain tables, the three CHANGELOG
  copies, and a pending publisher for the first publish.

## Alternatives considered and not taken

**A library each app imports, outside the platform.** It would reach more readers and enforce
nothing: ownership, the route policy, the declared host, the audit record and erasure would be
each app's to remember. Libraries that do this well for any React app already exist; what they
cannot do is what this capability is for.

**A protocol of our own.** Every frame the workbench sends maps onto an AG-UI 1.0 event, and
what does not (memory fill, a handoff, a compaction) fits the places AG-UI leaves open. A
protocol of our own would be a second one to maintain, and nothing outside Terp would read it.

**Depending on the AG-UI SDKs in the capability.** Possible, and not needed. The events are
data in the spec, and the capability validates against its mirror; the run input is the
capability's own model of the subset it accepts, held to AG-UI by the vendored input schema
(decision 3). Depending on `ag-ui-protocol` would add a runtime dependency to a distribution
that has none, for types the mirror and the vendored schema already hold, and AG-UI's own input
type would accept more than the capability does, where the subset is the point.

**A provider-specific capability.** A `terp-cap-claude` would make one provider's
implementation the only permitted plug, which is what the division borrowed from §4 (Context,
point 3) is there to avoid.
The Claude Assistant is one reference implementation, shipped as an extra, beside a remote
AG-UI one, so the port is visibly the thing being shipped.

**Running every run as a job from the start.** Right for a deployment that runs workers and a
shared broker, wrong as the default: a synchronous handler cannot stream, and the default queue
would run the whole run inside the POST. The port does not change when the mode is added.

## Open

- **Whether the capability should depend on the AG-UI types after all.** Settled above for v1;
  revisited if the profile grows past what a mirror and a vendored schema hold comfortably.
- **A reader-only share.** The workbench lets an owner share a conversation with a reader. The
  realtime audience is per principal today; a per-conversation audience is the step that share
  needs, and it is not designed here.
- **A framework-level erasure event.** The capability's `erase` is its own; a user-deletion
  event every capability subscribes to is a separate decision this one does not take.
- **The actor an erase runs as.** A conversation and a `File` are owned rows, and the built-in
  owner check admits a write to an owned row from its owner only, refusing any other actor and
  an actor-less write ([ADR 0029](0029-object-level-ownership-authorization.md)). A person
  erasing their own conversations passes it as any delete does. An operator erasing someone
  else's does not, and neither does the retention reaper, which runs as the job system actor
  ([ADR 0125](0125-a-declared-job-names-the-actor-its-writes-are-stamped-with.md)); the audited
  seam that lets them is decided with the capability, not assumed here.

## How it will be held

The phases are ordered by the coupling between the two repositories' builds: the event
vocabulary first (proposed in terp-spec 0.41.0, not yet released), then the input profile in
the spec and the capability and its surface in the framework release that pins it, then the
template starter and a `terp guide conversations` topic, then the first application moved onto
it. The checked mirror and its test, `tests/architecture/test_conversations.py`, the run
input's parity test against the vendored AG-UI input schema, the egress transport's tests
beside `send_pinned`'s, the realtime replay tests, a layout-contract test that each placement
in decision 8 passes the `standard` contract unchanged in both halves, and the logic core's
import test are each written with the code they hold.
