# 0110 — An app declares which parts of its dev topology are load-bearing

- **Status:** Accepted
- **Date:** 2026-09-02
- **Relates:** [ADR 0103](0103-the-ideology-one-pattern-enforced-escapable-by-proof.md) (one
  pattern, enforced, escapable by proof — the shape of the escape here),
  [ADR 0106](0106-the-verify-profile-is-open-at-the-app-end.md) (the profile this check joins),
  [ADR 0107](0107-the-dev-server-names-who-may-frame-it.md) and
  [ADR 0101](0101-a-development-only-channel-into-a-running-app.md) (two earlier seams between an
  app and a workbench, both development-only for the same reason).

---

## Context

An app's `docker-compose.yml` is edited constantly, and increasingly by an agent rather than by a
person. Almost all of that is the app's own business.

A small part of it is not. Which service serves the interface, which serves the API, and through
which environment variables their host ports arrive are load-bearing facts: change them and the
app still builds, still runs, and still passes every check — while any tool that has to *find* the
app stops being able to. Two projects can no longer run side by side the moment one hard-codes
`5173:5173` instead of `${WEB_PORT:-5173}:5173`, and nothing in the repository says that matters.

Nothing recorded the distinction, so nothing could tell an agent it had just crossed it. The
symptom arrived much later and somewhere else: a preview that would not come up, diagnosed by
hand, in a tool.

Two non-reasons, worth stating because they are the tempting ones:

**Not because a workbench needs it.** A workbench could keep guessing, and the guess is not even
wrong today — every app rendered from this template has the same five services, because the
template is the only thing that makes one. That guess is exactly what fails silently the first
time an app legitimately differs.

**Not to standardise how apps are built.** The opposite. The reason to write the shape down is so
a check can tell the difference between *an app that changed* and *an app that broke its own
declaration* — which is what makes it safe for apps to differ at all.

## Decisions

### 1. `workbench.json` records the load-bearing parts, and nothing else

A `schemaVersion`, the compose file it describes, a list of `services` with a `role`, and the
environment names through which the source root and the framing grant arrive. `terp verify --only
workbench` joins the standard profile.

### 2. It is a partial description, not a whitelist

Services the declaration does not name are not the workbench's business. Redis, a worker, a virus
scanner, a second frontend, a message bus, an optional container the platform ships later, or the
app's own equivalent of one — all pass untouched, because the check never asks what a service is
*for*. An exhaustive list would convert a description into a permitted-topology gate, which is the
thing this must not become.

The corollary matters as much: a role this toolchain does not know is information, not an error.
Otherwise adding a role becomes a breaking change for every app that already shipped one.

### 3. The rule is *truth about self*, never *conformance*

Red: a declared role points at a service that does not exist; a service that declared a host-port
variable publishes a fixed port instead; a declared environment seam the compose file never reads.
All three are the declaration lying about the app.

The third arrived late and matters as much as the other two. The `env` block names how the source
root and the framing grant reach the containers, and it was the half nobody checked — so an agent
could rename `TERP_DEV_HOST_ROOT` in the compose file, leave the declaration behind, and hot reload
would die while the app still built, still ran and still passed every other check. That is the
silent class this ADR exists for, in the one place the first draft left uncovered. It is checked as
*read somewhere*, never *read by a particular service*: which container needs the value is the
app's business, and requiring one would be conformance.

Never red: an undeclared service; the absence of a service we happen to know about; three APIs;
two frontends; no frontend; a service that publishes nothing; a role we have never heard of; an
app that declares no `env` seam at all; a port published on an ephemeral host port (`ports:
["5173"]`), which cannot collide and so cannot break the thing the fixed-port rule protects.

### 4. The escape ships in the same change as the rule

`{"unmanaged": true, "reason": "..."}` turns the check off. A reason is required — an escape nobody
can review is a hole, not an escape — and a workbench reading it falls back to its configured
commands and reports honestly that it cannot determine the app's status.

This is ADR 0103's shape, and it is deliberately available on day one rather than added later when
somebody hits the wall. Without it, this ADR would be a restriction on what may be built.

### 5. Development only, and the boundary is a control rather than a sentence

The declaration describes `docker-compose.yml`. It must never be consulted for, validated against,
or extended to the production profile. Real deployments differ in ways this platform has already
had to accommodate — an external managed database, a shared estate, a client's own cluster — and
that freedom lives in the production profile precisely because nothing gates it. Extending this
check there would take it away.

So a declaration whose `compose.file` names a deployment profile is **refused**, and that refusal
is the decision rather than a note under it. Writing "never the production profile" in this
document was not enough: `compose.file` accepted any path, so a single edit could aim the check at
a deploy profile and quietly convert it into a gate on deployment topology. In a codebase whose
changes are written by agents, a boundary defended only by prose is a boundary the next agent walks
through — the same reasoning that puts every other rule here behind a check.

### 6. The template seeds it once; the app owns it afterwards

`workbench.json` goes in copier's `_skip_if_exists`, alongside `environment.schema.json` and
`layout-contract.json`. Overwriting it on every upgrade would make it a description of the
template rather than of the app, which is the opposite of its purpose.

There is a useful consequence. `docker-compose.yml` *is* template-owned and is three-way merged on
upgrade. If a merge moves the app away from what its declaration says, the check goes red and the
upgrade is visibly unfinished — instead of silently producing an app no tool can find its way
around.

### 7. An app with no declaration passes

A no-op success, like the other generator-backed checks. Upgrading the toolchain must never turn an
app's gate red over a file it has not adopted.

## Consequences

- The `web` service gains a healthcheck in the same release. That is not part of the declaration —
  it is the plain gap it exposed: `db` and `api` had one and the frontend did not, so
  `docker compose up --wait` returned before the one service a person actually looks at was
  listening. It earns its place for anyone running `terp docker dev` in a terminal, with or
  without a workbench.
- `terp verify --only workbench` is one file read. It runs early in the profile because it answers
  "can a tool still navigate this app", which conditions what a later red means.
- The declaration is a second place the topology is written down, and a second place is a place
  that can drift. That is the trade being made: drift between the file and the compose file is now
  *checked*, where drift between the compose file and a tool's assumptions was not.
- The check found its first real defect in this repository: `apps/example` declared a
  `sourceRoot` seam its compose file does not use (the in-repo example mounts `./app` directly and
  has no host-root indirection). The declaration was corrected. A rule that catches something on
  the day it lands is the cheapest kind of evidence that it was worth adding.
- Only what a declaration *claims* carries a checked field. `containerPort` was seeded and read by
  nothing in this toolchain or in a workbench, so it is gone: a declared fact nobody consumes is a
  fact that can rot unnoticed, which is the opposite of the point.

## Alternatives considered

**Infer the roles from the compose file.** A heuristic — "the service publishing 5173 is the
frontend" — is a guess with no failure mode: when it is wrong it is confidently wrong, and there
is nothing to check it against. That is the situation this replaces.

**Put the knowledge in the workbench instead.** It already was, and duplicated: this repository and
a workbench had independently written the same `docker compose ps` parser and the same
failed-service diagnosis. Knowledge about an app that lives only in a tool cannot be checked by the
app's own gate, which is where an agent's mistake has to surface.

**Make the declaration exhaustive, listing every service.** Turns every added container into a
declaration change, and turns the check into a permitted-topology gate. Rejected on decision 2.

**Ship the rule now and the escape later.** The rule without the escape is a statement that every
Terp app must have a Compose-shaped development loop. That is not true today and should not become
true by omission.
