# 0162 — Module code asks who is calling through one dependency

- **Status:** Accepted and implemented. `terp.capabilities.identity` exports `CallerDep`,
  `Caller` and `current_caller`. Held by `tests/architecture/test_identity_caller.py`.
- **Date:** 2026-09-28
- **Relates:** [ADR 0089](0089-granting-is-an-operator-command.md) (a subject is
  addressed by an email or an integration's name, never a UUID), [ADR 0088](0088-service-principal-credentials.md)
  (the service account, the second kind of principal), [ADR 0044](0044-current-user-me-endpoint-and-who-am-i-seam.md)
  (`/me`, the resolver this does not reuse, and why)

---

## Context

A route receives a `Principal`: an id, a role and a kind. That is what the guard needs, and
nothing a person would recognise. A module that has to say *who* did something in words — the
operator named on a decision it forwards to another system, the account on a message it sends
— had no supported way to get that name.

The friction was reported from an app whose module forwards an operator's decision and must say
which operator made it. It constructed its own `IdentityService` inside the module and looked
the user up by the principal's id. That works, and it has three costs. It wires a second copy of
something the composition root already built, with its own permission model. It handles a
service account not at all: the lookup is in the user table, so a machine caller is refused as
unauthenticated. And it is the good option. The easier ones an agent reaches for are worse: a
"decided by" field in the request body is whatever the client sends, and an email carried in
the token's claims is stale the moment it changes.

`/me` already resolves the caller, but through a resolver the app passes to `build_me_module`,
and it answers with the whole session payload — the caller's permissions and per-module ranks,
each a query. That is right for a screen that gates on them once per session and wrong for a
dependency that may sit on every write route.

## Decision

**The identity capability exports one dependency.** `caller: CallerDep` on a route yields a
`Caller` with two fields:

- `name` — what the platform addresses the subject by (ADR 0089): a user's email, a service
  account's name;
- `id` — the stable key, which is what to store when a record must point at who did it.

`current_caller` reads the live row through the request's own session and the kernel's
`get_principal` seam, so it needs no wiring and reflects a renamed account as it is now. The
principal's kind decides which table is read, so a service account is never looked up as a
user. An unauthenticated request is refused, and so is a principal whose row no longer exists
— a token for a removed subject reaching a provider that does not check the store — rather than
being named by an id nobody can read.

It lives in identity because identity owns both tables. It is not a kernel seam, because the
kernel cannot name a user store, and it is not a method on `IdentityService`, because an
instance is the very thing a module should not have to build.

## Consequences

- Module code has one answer to "who is calling", and the guide teaches it where it teaches
  the base profile, with the two alternatives it replaces named as the ones not to take.
- The dependency deliberately carries no role or permissions. The guard has already decided
  whether the caller may be there; a module that wants the role reads the principal it already
  has.
