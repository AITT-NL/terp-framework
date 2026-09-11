# 0134 — The lifecycle has one driver, and a workbench is not it

- **Status:** Partly implemented — decision 1 is policy, decisions 2 and 3 ship, and decision 4
  is unbuilt (see "Where this stands").
- **Date:** 2026-09-11
- **Relates:** [ADR 0111](0111-flexibility-is-bounded-by-legibility-not-by-capability.md)
  (flexibility is bounded by legibility — this supplies the fourth test its decision 1 is
  missing), [ADR 0110](0110-an-app-declares-which-parts-of-its-dev-topology-are-load-bearing.md)
  (the first legibility contract, and where the evidence below was found),
  [ADR 0101](0101-a-development-only-channel-into-a-running-app.md) and
  [ADR 0107](0107-the-dev-server-names-who-may-frame-it.md) (two earlier app↔workbench seams),
  [ADR 0063](0063-lockstep-release-and-publish-pipeline.md) (the release this toolchain has no
  command for)

---

## Context

Terp's promise is that an app built on it is operable by its own toolchain. A workbench makes that
operation pleasant, visible, and safe for someone who cannot read a stack trace. It is not supposed
to be the thing that makes it *possible*.

Nothing in the platform says so, and the rule has been applied from memory three times:

- **ADR 0035** refused to make `api` wait on `seed`, on the ground that the framework "may only own
  what a developer *without* a workbench also wants".
- **ADR 0110** admitted the `web` healthcheck because it "earns its place for anyone running
  `terp docker dev` in a terminal, with or without a workbench".
- **`terp env` exists because the rule had already been broken.** Both halves of the platform had a
  values story for a *deployed* environment and neither had one for the machine the code is written
  on; the documented route for a developer was copying an example file and opening an editor.

Three applications, one unwritten rule. ADR 0111 is the document that should hold it and does not.
Its decision 1 names three kinds of rule and its decisions 2 and 3 give two tests, and none of them
asks whether a capability is reachable without a workbench. Its degradation test is the near miss:
it asks who loses when the **app** is illegible and answers "the tool, and it says so out loud". It
never asks who loses when the **tool is absent**.

### The evidence: an assignment no other starter can read

The dev compose file publishes its host ports as `${WEB_PORT:-<web base>}` and
`${API_PORT:-<api base>}`, and those two defaults are exactly the first pair a workbench allocates.
A workbench assigns a pair per project into its own registry and delivers it as process environment
on the `docker compose` command it runs itself.

Every other way of starting the same app — a shell in the project folder, an editor task, an agent
bringing the app up to look at it, `terp docker dev` — runs the same compose file with both names
unset, and therefore lands on the defaults. Because the compose project name is pinned in the file,
the result is not two stacks side by side competing for a port. It is *the same containers*. So the
recovery is not "pick another port", it is "find and stop the stack you did not know you had
started", and the address the workbench is watching never answers in the meantime.

The mechanism that fixes this already exists, and is already in the wrong place. A workbench module
writes the assignment into the project's `.env` — the file Compose loads from the project directory
with no flag and no cooperation from whoever starts the stack — and its own docstring names the
failure above precisely. But it is called on **one** of the paths that assign ports and not on the
others, because nothing in the design makes assigning a port and publishing the assignment one act.
Open an existing checkout in a workbench and it assigns a pair, records it internally, writes
nothing, and the next start from anywhere else collides.

That is the shape of every defect this ADR exists to prevent. Not a missing feature — a capability
that exists on one path and is unreachable from the others.

## Decisions

### 1. The standalone test

> **A capability may not be reachable only through a workbench.** If a workbench can do it, `terp`
> can do it.

This joins ADR 0111's decisions 2 and 3 as the fourth test a proposal answers.

It is a test about **reachability**, not about parity of presentation. A workbench may present an
operation far better, batch it, drive it across many projects at once, or wrap it in a confirmation
an operator needs. What it may not be is the only way to reach it.

When the test fails, the answer is never to remove the workbench's version. It is that the CLI is
missing a command, and that command is the work.

### 2. Host port assignment is a CLI operation, scoped to the host

`terp` owns the assignment; a workbench reads it.

- **The ledger is machine-scoped, not checkout-scoped**, because the resource being allocated
  belongs to the host. A checkout-local record cannot stop two checkouts from claiming one port,
  and a workbench-local record cannot be read by a starter that is not that workbench — which is
  the defect. It lives in a CLI-owned home (`~/.terp/ports.json`), keyed by the checkout's absolute
  path.
- **Assigning and publishing are one operation.** Consult the ledger, skip pairs held for another
  checkout, probe the host, claim the first free pair, record it, and write it into the project's
  `.env` — in one act that cannot half-succeed. The absence of that property is the defect; making
  the two steps inseparable is the fix, and adding a call site is not.
- **Publication keeps the conditions the existing workbench module already established**: refused
  when git would see the result, best-effort otherwise, and never an exception into a start path. A
  machine's ports do not belong in an app's history, and a convenience must not make a checkout
  unreviewable or un-upgradable.
- **The ledger holds every host-port claim, not only the dev ones.** A workbench today allocates
  dev pairs from one set of bases and suggests a deployed environment's published port from
  another, and the two allocators consult different notions of what is taken — the deploy
  suggestion counts the dev pairs, and the dev allocation does not count the deployed ports. The
  separation between the bases is what keeps that from being a live defect rather than anything in
  the design. One ledger over one resource removes the asymmetry instead of widening the gap
  between the bases again.
- **A workbench keeps its registry as a cache of what it read**, and stops being the authority. Its
  own process environment may still outrank the file for a start it makes, so nothing about its
  behaviour changes except where the number comes from.

### 3. A start with no assignment refuses, and names the command

The compose default is what converts a missing assignment into a silent collision, so it goes: the
port interpolation becomes required, and the refusal names the command that fixes it.

Fail-closed must not make the standalone path *harder* — that would break decision 1 in the act of
enforcing it. So `terp docker dev` assigns on demand when the ledger holds nothing for this
checkout. The developer without a workbench types one command and never learns the variable exists.
The refusal is then only reachable by a starter that is neither the CLI nor a workbench — a bare
`docker compose up` — and for that reader the message is the remedy.

### 4. The operations with no CLI form are named here, not discovered later

Applying decision 1 to the lifecycle as it stands: **preview** passes (`terp docker dev`),
**migration** passes (`terp migrate upgrade`), **values** pass (`terp env`), the **gate** passes
(`terp verify`), and **deploy safety** passes (`terp verify --only deploy-safety`).

**Cutting a release and promoting one do not.** Building an exact-SHA artifact set from a detached
worktree, and deploying an existing set without rebuilding it, exist only inside a workbench. The
act is portable — its inputs are a worktree and a SHA, with no workbench concepts in them; what is
workbench-shaped is the *record* of environments and deployment history, not the operation. So
`terp release` and `terp promote` are the two commands this decision owes, and they are named now
so the gap is a decision rather than something the next person to ship without a workbench finds
out.

## Where this stands

**Decision 2 ships as `terp ports`** — `assign`, `show`, `list`, `release` over the
machine-scoped ledger, with assignment and publication as one call, adoption of an answer a
checkout already publishes, `workbench.json` deciding the names, and `unmanaged` left alone.

**Decision 3 ships, as the two halves it had to be.** The template's published host ports are
required rather than defaulted, and `terp docker dev` assigns on demand so the requirement is
invisible to someone who has never heard of the command — shipping the first without the second
would have made the standalone path harder, which is decision 1 broken in the act of enforcing
decision 3. Verified against Compose itself rather than assumed: an unassigned checkout is
refused with `required variable WEB_PORT is missing a value` plus the directive message, and
resolves to the assigned port once `terp ports assign` has run.

Two scope notes that belong in the record rather than in a commit message. `apps/example` keeps
its in-range defaults, because the conformance workflow runs its dev stack with no `.env` and
says so — one checkout on an ephemeral runner, where the collision this removes cannot occur. And
an in-range default stays legal for any app: the template's choice is the template's, not a
conformance rule (ADR 0111 decision 1). What is now illegal is a published host port that answers
neither question — a bare `${VAR}`, which Compose resolves to empty and then reports as a
malformed port, naming neither the variable nor the remedy.

**Decision 4 is unbuilt and unscoped.** `terp release` and `terp promote` are named, not designed.

**And one property is deliberately not claimed yet: a workbench still owns its own assignment.**
Until it reads the ledger, two authorities exist over one resource. They do not fight, because a
workbench publishes into the same file and `assign` adopts what it finds there rather than picking
a second answer — but "they agree" is weaker than "there is one of them", and only the second is
what this ADR decided.

## Consequences

- The port defect closes as a by-product. It is not the reason for the ADR, but it is the reason
  the ADR is worth writing this week rather than next quarter.
- A workbench loses ownership of one thing it owns today, and gains a property it cannot currently
  have: a start it did not make comes up **adoptable** instead of unreachable.
- `~/.terp/` becomes a machine-scoped CLI home. The platform has not had one — a workbench had its
  own — and that is new surface, which is the honest cost of moving the ledger to where every
  starter can read it.
- Decision 4 is two commands the platform does not have. The build behind them largely exists
  behind a workbench port, so this is a move rather than an invention, but it is not a small one.
- **The standalone test will fail on things nobody wants to move**, and that is information rather
  than an error. ADR 0111 decision 3's shape applies: when the CLI cannot reach something, the
  platform says so out loud instead of letting a workbench's version pass as the platform's.

## Alternatives considered

**Call the publish helper at the other assignment sites.** The narrow fix, and it is one more
instance of the defect's own shape — correct on the four paths that exist today and silent on the
fifth. It also leaves the authority inside the workbench, so a starter that is not a workbench is
still reading a compose default.

**Keep the compose defaults and publish harder.** Defaults that collide are what make the failure
silent. A default is right when any value will do; a host port is precisely the case where it will
not, and a default equal to the first allocated pair is the worst available choice.

**Give the CLI a client of the workbench's API.** Inverts the dependency the platform rests on: a
workbench imports no `terp.*` and drives an app through its own toolchain. A framework that has to
phone a workbench is not a framework that works by itself.

**Scope the ledger to the checkout.** Cannot work. The resource is the host's, so two checkouts
each holding a truthful record of its own claim still collide on the same port.
