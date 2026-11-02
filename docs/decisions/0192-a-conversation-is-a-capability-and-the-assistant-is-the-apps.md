# 0192 — A conversation is a capability, its stream is an AG-UI profile in the spec, and the assistant is the app's

- **Status:** Proposed (awaiting review). Nothing is built in this repository yet. The event
  vocabulary ships in terp-spec 0.41.0 (`conversation-events.schema.json` with
  `conversation-events.fixtures.json`), which is not published yet; until it is pinned here,
  this record is the design the capability is built to.
- **Date:** 2026-11-02. 0182 and 0183 are reserved for other records.
- **Relates:** reads [ADR 0111](0111-flexibility-is-bounded-by-legibility-not-by-capability.md)
  §4 (the framework owns the socket, not the plug) and decision 5 (a contract two programs
  read lives in the spec), and [ADR 0117](0117-the-egress-capability-the-rule-was-already-naming.md)
  (which read §4 as declining an AI capability, and answered metering with the egress
  observer); follows [ADR 0186](0186-a-declaration-vocabulary-lives-in-the-spec.md) (a
  vocabulary in the spec with fixtures every reader runs, and what a reader does with a
  version it does not know); applies [ADR 0060](0060-projects-is-example-code-base-profile-closure.md)
  (a cross-cutting mechanism is a capability, a business noun is a module); composes
  [ADR 0027](0027-packaged-migrations-per-package-histories.md) (packaged migrations),
  [ADR 0056](0056-files-capability.md) (files), [ADR 0095](0095-expiring-fenced-custody-of-work.md)
  (leases), [ADR 0126](0126-a-capability-publishes-its-operation-set.md) (the operation set)
  [ADR 0176](0176-a-realtime-publish-reaches-every-process-that-serves-the-channel.md)
  (the shared realtime broker) and [ADR 0190](0190-a-field-declares-itself-personal.md)
  (what a person wrote is declared personal); amends the R9 sketch in
  `docs/internal/drafts/platform-reach-open-items.md` (its `{ seq, delta, done }` envelope is
  replaced by the spec's vocabulary). Supersedes nothing.

---

## Context

Several applications built on Terp carry a chat of their own, a person talking to an
assistant, and each one wrote it from nothing. The most complete is the workbench's (Terp
Studio), which fronts coding agents and has been through some ninety of its own decisions on
what a conversation is: text that arrives at its own pace, a tool call as a row on a timeline,
a question the agent asks and ends its turn on, a message sent while a turn runs that either
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
   capability, and that reading is right about what §4 refuses: a framework-shipped plug that
   becomes the only permitted one. It does not refuse the socket. §4 asks for exactly a socket
   for each thing an app needs and we have not shipped: what such a thing must declare about
   itself, with the framework's own implementations as references rather than the only ones.

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
That is the line ADR 0111 §4 draws, and this capability sits on the socket side of it. The
import is `terp.capabilities.conversations`; it depends on `files`, `realtime`, `leases` and
`egress`, and is modelled on `webhooks`, the one capability with a router, owned tables, a
dependency on another capability, packaged migrations and an escape-hatch budget.

**2. The stream is AG-UI 1.0, profiled in the Terp Standard.** terp-spec 0.41.0 fixes the
vocabulary: twelve AG-UI event types, closed; every object closed and every string capped;
a closed `terp.` namespace where AG-UI leaves a name open (`terp.compaction`, `terp.context`,
`terp.handoff`, `terp.question`) and a `metadata.terp` key on the events that need one; ten
stream rules a schema cannot state; `metadata.terp.schemaVersion` on `RUN_STARTED`, refused
when unknown, as ADR 0186 decision 4 asks of a reader that acts on what it reads. This
repository will carry a checked mirror of the schema and fixtures, as it does for the
workbench declaration, and both the producer and the client run every fixture. An AG-UI client
reads the stream unchanged; an AG-UI agent can sit behind the capability.

**3. The assistant is the app's, behind one port.**

```python
class Assistant(Protocol):
    async def run(self, input: RunAgentInput, *, checkpoint: Checkpoint) -> AsyncIterator[Event]: ...
```

`RunAgentInput` and `Event` are AG-UI's: the stored messages, the app's tools in AG-UI's own
`Tool {name, description, parameters}` shape, context, per-run options in `forwardedProps`,
and `resume` entries answering an interrupt. The Assistant yields events and never touches the
database, the stream or a secret; the capability validates every event against the vocabulary,
persists it, and publishes it. An Assistant that needs the person yields `RUN_FINISHED` with an
interrupt outcome. Two reference Assistants ship as **extras**, so the core distribution has no
model dependency: `[claude]` (the Claude Messages API through egress, streaming, with
server-side compaction, refusal fallback and a token budget) and `[agui]` (a remote AG-UI agent
at a declared URL, through egress, its events relayed and normalised to the profile). The
workbench's coding-agent adapters, which run a command-line agent as a subprocess in an
isolated checkout, stay in the workbench: driving a coding agent is a workbench concern.

**4. A run executes in the API process, under a lease.** `POST /conversations/{id}/runs` stores
the message and a run row in one write and returns 202; the run is an asyncio task holding
`hold_lease(LeaseResource.for_row(run))` with a heartbeat, so two processes never run one
conversation and a paused one is fenced out, with a reaper that marks an abandoned run failed
in a sentence. Not a job, against R9's "slow work is a job", because a job handler is
synchronous and the default in-process queue runs a job inline in the request, which would hold
the POST open for the whole run. A worker-run mode on `OutboxJobQueue` and the shared broker is
a later option behind the same port. The client mints `runId`, as AG-UI's input already
requires, and a repeat of the same `runId` with the same body is the same request; a different
body is 409. Text deltas are coalesced on a short tick before publishing, so a fast stream
never trips the broker's per-subscriber backpressure.

**5. Every event is persisted, and replay is by sequence.** An append-only event log per run is
what a reconnecting client reads from, by `after=<seq>`, and what a restart leaves intact. The
realtime capability gains the half it lacks: an `id:` per SSE frame and a cursor on the ticket.
Today it sends bare frames, and a reconnect loses whatever was published meanwhile.

**6. Egress gains a streaming transport, and the model is reached only through it.** The
egress client is synchronous and reads a whole response into memory, so a model stream cannot
pass through it today. The change is an `httpx` transport bound to an `EgressPolicy`: it
resolves and pins the address, applies the SSRF, scheme, time and byte rules, and streams the
body; the provider's SDK takes it as its HTTP client, so the reference Assistant runs inside the
declared allowlist with the socket guard as the runtime half. That is ADR 0117's shape and R9's
"`kind="model"`" defaults: a long read timeout and no retries. An SDK routed around egress is
never the answer.

**7. Storage is the app's database, and erasure is an operation.** Conversations, messages,
attachments, runs, run events, pending messages and interrupts are tables: `BaseTable` with
`OwnedMixin` on the conversation, every child a `Ref(..., on_delete=OnDelete.CASCADE)`, every
string capped, a scope predicate hiding another owner's rows on reads, the user an FK-less UUID
as ADR 0027 has it, list endpoints paginated. Transcripts are not sealed: sealing would defeat
search, and the app's database is the app's. What the capability does owe is a `retention_days`
setting with a reaper, and an audited `erase` operation that deletes one person's
conversations, because the framework has no user-deletion hook (a user is deactivated, never
deleted). A message's text, a conversation's title and an attachment's name are what a person
wrote, so they are declared with `Personal(...)` (ADR 0190): the log, the audit trail and the
event and job definitions withhold their values because the framework reads the declaration,
not because the capability remembers to. An audit record then carries ids, statuses and token
counts.

**8. The surface is a react-core component family in the `WorkspacePage` slot.**
`Conversation` (transcript, composer, the working line, the one strip for every problem),
`ConversationList` and their parts, built on react-core's own primitives and its realtime hook,
admitted into the `WorkspacePage` slot in both halves of the layout contract, with the strings
in both shipped locales. The client's state machine is a logic-only core with no React and no
`@terpjs/*` import, held there by a test, so it can leave as a package the day something
outside Terp asks for it, and not before. react-core's `Markdown` gains GFM tables and a
settled/tail split so a streaming message re-parses only its tail. No new archetype.

**9. The workbench conforms; it does not import.** The workbench takes no dependency on any
framework frontend package, for reasons its own records give (the split boundary, version skew,
and the trap where a broken framework release breaks the tool used to fix it). It keeps its
panel and is held to the vocabulary by a parity test that reads the schema and fixtures from
the `terp-spec` package, as its stylesheet is held to the token manifest.

**10. The questions left open by the design are settled here.**

- **One open question per conversation.** The vocabulary allows one interrupt per run; the
  capability allows one open interrupt per conversation, and a newer message withdraws it.
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
- The workbench and any application on the capability read and write one stream, and an
  AG-UI client from outside Terp can show either.
- Two existing capabilities change for a reason that is not the conversation's: realtime
  gains replay, which any channel can use, and egress gains a streaming transport, which any
  long-lived outbound read can use.
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

**Depending on the AG-UI SDKs in the capability.** Possible, and not needed: the vocabulary is
data in the spec, the capability validates against its mirror, and its event models are written
against the schema. Depending on `ag-ui-protocol` would add a runtime dependency to a
distribution that has none, for types a mirror already holds.

**A provider-specific capability.** A `terp-cap-claude` would be the plug §4 refuses. The
Claude Assistant is one reference implementation, shipped as an extra, beside a remote AG-UI
one, so the socket is visibly the thing being shipped.

**Running every run as a job from the start.** Right for a deployment that runs workers and a
shared broker, wrong as the default: a synchronous handler cannot stream, and the default queue
would run the whole run inside the POST. The port does not change when the mode is added.

## Open

- **Whether the capability should depend on the AG-UI types after all.** Settled above for v1;
  revisited if the profile grows past what a mirror holds comfortably.
- **A reader-only share.** The workbench lets an owner share a conversation with a reader. The
  realtime audience is per principal today; a per-conversation audience is the step that share
  needs, and it is not designed here.
- **A framework-level erasure event.** The capability's `erase` is its own; a user-deletion
  event every capability subscribes to is a separate decision this one does not take.

## How it will be held

The phases are ordered by the coupling between the two repositories' builds: the vocabulary
first (done: terp-spec 0.41.0), then the capability and its surface in one release, then the
template starter and a `terp guide conversations` topic, then the first application moved onto
it. The checked mirror and its test, `tests/architecture/test_conversations.py`, the egress
transport's tests beside `send_pinned`'s, the realtime replay tests, the layout-contract slot
tests in both halves and the logic core's import test are each written with the code they hold.
