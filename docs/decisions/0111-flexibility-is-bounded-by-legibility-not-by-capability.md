# 0111 — Flexibility is bounded by legibility, not by capability

- **Status:** Proposed — decisions 1-5 are ready to accept; decision 6 names the one place
  flexibility must give way to control, and which invariants go in its envelope is not mine to
  settle
- **Date:** 2026-09-02
- **Relates:** [ADR 0103](0103-the-ideology-one-pattern-enforced-escapable-by-proof.md) (the
  ideology this generalises), [ADR 0110](0110-an-app-declares-which-parts-of-its-dev-topology-are-load-bearing.md)
  (the first instance of the pattern, and the evidence it works),
  [ADR 0106](0106-the-verify-profile-is-open-at-the-app-end.md) (an open end already conceded),
  [ADR 0099](0099-the-component-gap-and-what-is-not-in-it.md) (the name-a-consumer test,
  applied here to declarations), and in terp-studio ADR 0013 (the deployed app's database is a
  mode, not a variable — the concrete deployment freedom this must not spend)

---

## Context

The question this answers was put plainly: Terp exists so that people with little or no software
development knowledge can build secure applications through an agent. To serve many use cases we
seem forced to sacrifice either flexibility or control. Constrain deployment to one
framework-defined method and the preview and the deploy environments become controllable — but a
client who needs different containers, different networking, or a different system architecture is
then locked out until we implement it. Leave the shape open and an agent, which will do whatever
the gates permit, breaks the dev loop or the deploy the first time it improvises. So: how much do
we constrain, and where? Do we accept that some things are impossible until the framework
implements them? Is maximum flexibility even compatible with a controlled environment for
non-technical users?

The instinct behind the question — that there is a real limit here and it cannot be designed away
— is correct. But the axis is wrong, and getting the axis right moves most of the cost somewhere
much cheaper.

## The reframing

"Flexibility versus control" describes a dial, and there is no dial. There are three different
things a platform can constrain, and they have nothing in common except the word.

**Capability** — what an application may contain or do. A rule here genuinely costs use cases:
forbid Redis and the app that needs Redis is not buildable.

**Usage pattern** — how a thing is done when the framework already offers a way to do it. The
ideology already refuses flexibility here, correctly: a second way to do an already-supported
thing is a cost with no benefit.

**Legibility** — whether the application can answer a small, fixed set of questions that a tool
has to ask in order to manage it. Which service serves the interface. How to know when it is
ready. Where the deploy unit is and how to health-check it. What configuration it needs. Where
migrations run.

The observation that resolves the question is that **Studio never needed uniformity. It needed
answers.** An application can be arbitrarily strange and still answer all five questions. A
perfectly conventional application can stop answering them at any time — and did: nothing in a
repository said which parts of `docker-compose.yml` were load-bearing, so an agent could publish
a fixed host port, break project isolation, and pass every check in the platform.

So the constraint worth enforcing is not a shape. It is: **remain legible, and be as arbitrary as
you like.** That is a restriction on *silence*, not on capability, and restrictions on silence are
nearly free — they remove nothing an application can do.

This is not a new idea in this platform; it is one we have already had twice without naming it.
`layout-declaration.schema.json` in the spec exists so that "a build-time checker and a running
app read the same bytes and neither can hold a different answer — and so a tool that edits files,
rather than code, can read and rewrite these choices." ADR 0110 rediscovered the same shape for
dev topology. Naming it makes it a policy instead of a coincidence.

## Decisions

### 1. Three kinds of rule, and only one of them is conformance

**Security invariants** are conformance rules: the app must be built the approved way. This is the
one place conformance is right, and the justification is the audience — someone who cannot
evaluate a security trade-off must not be offered one. Enforced by default, escapable only by an
explicit, greppable, budgeted declaration. Unchanged from ADR 0103.

**Legibility contracts** are truth-about-self rules: the app may be shaped however it likes and
must describe the parts a tool has to navigate. Never conformance. Enforced by a verify rule that
compares the declaration against reality, and *never* by asking whether the reality is approved.

**Everything else** is the application's own business, and carries no rule at all.

A proposal that cannot say which of the three it is, is not ready.

### 2. The legibility test

> Does this constraint remove a **capability**, or does it remove **silence**?

Removing silence is always allowed and needs no further argument. Removing a capability requires a
safety argument the intended audience could not have made for themselves. "A tool would find this
easier" is not such an argument, and it is the one that will keep being offered.

### 3. The degradation test — who loses when an app is illegible?

When an application declares something we do not understand, or declares nothing at all, the
**tool** loses a feature and says so out loud. The **application** never loses the ability to run,
build, or deploy.

`unmanaged: true` is the reference shape: verify goes quiet, Studio reports that it cannot
determine the app's status, and the app works exactly as before. An unknown role is information,
not an error. An app with no declaration passes.

If the answer to "who loses?" is "the app", the design is wrong, whatever else recommends it. This
test is the one that keeps a legibility contract from quietly turning into a permitted-topology
gate, which is the failure mode every instance of this pattern will drift toward.

### 4. The framework owns the socket, not the plug

The original question offers two options — wait for the framework to implement a capability, or
allow anything and lose control. There is a third, and it is where most of the value is.

For each thing a client might need that we have not shipped, the framework's job is to define
**what such a thing must declare about itself** — its containers, how to tell it is healthy, its
configuration keys, where its migrations live, its security posture — and not to define its
implementation. A capability a client builds themselves, declaring those facts, is then as
first-class to our tooling as one we ship. The framework's own capabilities become reference
implementations of a public socket rather than the only permitted plugs.

The consequence is the one that matters for the business question: the number of use cases the
platform serves stops being bounded by **the number of capabilities we have shipped**, and becomes
bounded by **the expressiveness of the declaration vocabulary**. The first grows one release at a
time and gates every client who needs something new. The second grows rarely, and grows
*compatibly* — by decision 3, a vocabulary entry a toolchain does not recognise is information, so
adding one is never a breaking change.

So the answer to "do we accept that things are impossible until the framework implements them" is:
**mostly no, and the way out is a vocabulary rather than a catalogue.** Where a client builds their
own, our tools should be able to see it, and the honest cost is the next decision.

### 5. Declaration vocabularies belong in the spec

A legibility contract read by two programs is a contract, and a contract needs one owner. Today
`workbench.json` is defined in the framework's CLI, and the evidence that this is the wrong home
is already in the tree: the framework and Studio each wrote their own reader, with their own
defaults, and they disagreed about which fields existed — Studio parsed six fields nothing
consumed, including the escape hatch it then ignored.

The spec already owns exactly this kind of document (`layout-declaration.schema.json`,
`assurance-profile.schema.json`) and is versioned independently of the platform for exactly this
reason. Declaration schemas go there, so that a Studio and a framework on different versions can
still agree on what an application said about itself. The framework keeps the enforcement; the
spec keeps the words.

## The trade-off that is real, and where it actually falls

Maximum flexibility and a controlled environment for a non-technical audience are compatible in
capability, and genuinely incompatible in one place. Naming that place precisely is more useful
than accepting a vague trade.

The product promise to someone who cannot read a stack trace is not "your app will never break".
It is: **when it breaks, you are told what to do about it, in words you understand.** Keeping that
promise requires a closed table of recognised failures, each paired with a remedy that is a button
— which is what `preview_diagnosis` is. An application that deviates from the pattern produces
failures that are not in the table.

So the cost of flexibility is not capability. **It is guided recovery.** The further an application
is from the pattern, the more its failures route to "let the agent look at this" instead of "press
this button". That is a continuous slope rather than a cliff, it is honest, and it is acceptable
precisely because the open exit is a capable one: an agent that can read the log is a genuinely
good fallback in a way that "here are sixty lines of output" never was.

Stated that way it also becomes something a client can be told before they choose, rather than
discovered afterwards: *this app is one Studio can manage and diagnose* versus *this app is one
Studio can run, and when it breaks the agent handles it*. Both are supported. Only the second is
a second-class citizen, and only in the one respect named here.

This holds for the inner loop, where every failure is retryable. It does **not** transfer to
infrastructure, where the trade is irreversibility rather than recovery — see decision 6, which is
the one place in this document where flexibility really does give way to control.

### 6. Infrastructure is the exception, and it needs a third layer

Deployment **is** partly a control-versus-flexibility question, and the first draft of this
document denied it by filing the whole deploy surface under legibility. That was wrong. Two things
make infrastructure different in kind from the dev loop, and both cut against the argument above.

**The failure mode inverts.** A misconfigured dev stack does not come up, and you find out in
seconds. A misconfigured deployment comes up perfectly and you find out from a bill, a breach
notification, or a column that is no longer there. Legibility catches "this does not work". Only
conformance catches "this works, dangerously" — and a declaration cannot help here, because the
danger is not a lie. "The database is published on 0.0.0.0" can be a completely truthful,
checkable declaration of a catastrophe. Decision 2 asks whether a constraint removes capability or
removes silence; for infrastructure that question is not sufficient, because the harm does not come
from silence.

**The open exit stops being capable.** The trade in the previous section rests on "let the agent
look at it" being a genuinely good fallback, and it is — for a stack that will not start. It is
not a fallback for a storage account that was public for six hours, or a migration that has
already run against customer data. Dev failures are retryable. Some infrastructure failures are
not, and irreversibility is the property that makes conformance the right instrument.

The audience settles it. Networking, secrets, blast radius, data residency and backup are
precisely the trade-offs someone with little development knowledge cannot evaluate, which is the
justification decision 1 already gives for conformance in security. Infrastructure *is* security.
The three-way split in decision 1 still holds; what changes is the assignment — for a deployment,
security invariants cover far more of the surface than they do for the inner loop.

So a deployment has three layers, each with its own rule, instead of one dial.

**Layer 1 — the safety envelope. Conformance, enforced at the deploy boundary.** A small closed
set of properties that must hold of *any* deployment whatever its shape: no datastore reachable
from a public network; secrets arrive from a secret store and never from a file in the repository;
TLS terminated at the edge; every stateful resource names a backup; a destructive scope requires
explicit confirmation. These constrain **properties, not topologies** — an app may use any
containers, any networking, any provider and still satisfy every one of them. That is what makes
the envelope compatible with maximum flexibility rather than a contradiction of it, and it is the
real answer to "is it even possible": yes, for whatever can be stated as an invariant over any
topology. Escapable only by an explicit, greppable, budgeted declaration with a reason — and for
the invariants that can lose customer data, the escape should require a person rather than an
agent.

The enforcement point has to move, and this is the expensive part. For the inner loop a build-time
file check suffices, because the blast radius is one laptop. For infrastructure it does not: an
agent can pass `terp verify` and still deploy something dangerous, because the danger is in the
rendered result rather than in the source. So the envelope is checked against the **resolved plan**
at deploy time, and where a provider allows it, asserted against what actually exists afterwards.

**Layer 2 — legibility. Declaration, truth-checked, never gating.** Which unit is the app, how to
health-check it, where migrations run, what a rollback is. Optional: absence means a workbench
cannot drive the deploy and says so, and the app still deploys by its own means. This is the part
the first draft had right, and decision 3 applies to it unchanged.

**Layer 3 — topology. Free.** Service count, images, languages, extra containers, network
arrangement, provider. No rule at all. This is where the freedom Studio's ADR 0013 protects
actually lives, and nothing here touches it.

This makes the consequence for ADR 0110 decision 5 sharper than the "never describe versus never
gate" fork the first draft offered. That decision's reasoning — deployment freedom survives
because nothing gates it — is a claim about *topology*, and about topology it is correct. It does
not follow that *safety properties* should be ungated, and reading it that way is why the deploy
surface has no envelope today. Decision 5 should be **split** along these layers, not reworded.

**What stays genuinely open, and needs a person.** Which invariants belong in the first envelope,
and what the enforcement point is for each provider. The five above are a starting proposal, not a
decision: an envelope drawn too wide becomes the permitted-topology gate this whole document
argues against, and one drawn too narrow is theatre. This is the question to answer before any of
it is built.

**And the concession this forces.** For the safety envelope, some things really are impossible
until the framework implements them. A client needing a shape the envelope cannot yet express
safely waits, or takes a reviewed escape with a human signature. That is the one place where "not
yet" is the right answer — and it is a much smaller place than "not until we ship the capability",
because an envelope constrains properties rather than shapes.

## Consequences

- Every future constraint proposal has to name its kind (decision 1) and pass the two tests
  (decisions 2 and 3). "An agent might break it" justifies a *declaration*, never a restriction.
- `workbench.json`'s schema moves to the spec, and the framework and Studio readers are derived
  from one document rather than written twice. This is a real migration with a version seam, not a
  file move.
- The capability socket (decision 4) is the largest piece of new work the platform has in front of
  it, and nothing here specifies it. What this ADR does is say that it is the right work — and
  that shipping more capabilities is not a substitute for it.
- The deploy-time safety envelope (decision 6) is the second largest, and the one with a deadline
  attached, because every deployment made before it exists is one that nothing checked. It also
  introduces a kind of gate this platform does not have yet: one that runs against a resolved plan
  rather than a file, at the moment of deploying rather than at build time.
- A tiering of manageability becomes describable in the product, which is a change to how Studio
  talks about an app and not only to how it manages one.

## Alternatives considered

**Constrain the method: one framework-defined way to deploy, preview and run.** The control is
real and the cost is the platform's reach. It also fails the ideology's own test — enforcement
aimed at *what* can be achieved rather than *how* — and it does not even buy what it promises: a
declared method still drifts unless something checks it, so the check is doing the work and the
restriction is only doing harm.

**Maximum flexibility with no declarations.** Fails immediately in an agent-written codebase for
the reason ADR 0103 already gives: a rule that exists only as prose is not a control. Without
declarations there is nothing to check, so Studio must guess, and a wrong guess is confidently
wrong. This is the situation ADR 0110 replaced, and the symptom was a preview that would not come
up, diagnosed by hand.

**Grow the capability catalogue faster instead.** Treats the symptom. Every unshipped capability
is still a locked door, the catalogue can never be complete, and each addition is a permanent
maintenance obligation. Worth doing on its own merits; not an answer to this question.

**Let the app extend the failure table too.** Tempting, since it is decision 4 applied to
diagnosis, and rejected for now on decision 3: a remedy offered for a failure it does not fix
costs a destroyed database to discover, and a remedy an app declared for itself is one nobody
reviewed. A capability declaring its own failure signatures is a narrower version worth revisiting
once the socket exists.
