# 0209 — A new app pins who can reach what, and the check names each change that widens it

- **Status:** Accepted on 2026-11-09 by the owner, with the three recommendations its review
  put forward. A new app's first check is red until its baseline is written. A module list
  may not depend on a setting, as a change of its own (*Open*). And only an owner approves
  a widening (terp-studio ADR 0097). Before building, a check against how the pieces run
  refined two points. `copier update` brings the `pinned` line to an existing app as well
  (item 4). The JSON names what the check cannot see apart from what changed (item 3),
  because the first is code for the agent to fix and only the second is the owner's to
  approve. Revised 2026-11-08 after an independent review, which found three widenings the
  shipped check passed with an empty diff; those are fixed in 0.41.0 on their own (ADR 0139's
  status).
- **Date:** 2026-11-08.
- **Amends:** [ADR 0139](0139-who-can-reach-what-is-pinned-not-merely-reportable.md): its
  opt-in, for an app the template makes, and its consequence that labelling a change would be
  a second authorization model.
- **Relates:** [ADR 0121](0121-a-module-role-is-an-assignment-not-a-policy.md) decision 4
  (what a rung grants is derived, never declared, and the access graph replays the guard), and
  terp-studio ADR 0097, its half: a change that widens who can reach what waits for the app's
  owner.

## Decision

A new app pins who can reach what from its first commit, and the `authz-surface` check labels
every change it reports as a widening or a narrowing. The template declares the pin. The
baseline itself is always written from the composed app, never by hand. A change is a
narrowing only when the guard's own replayed answers prove that nobody gains reach; every other
change is a widening. A tool can then put the widenings, and only those, in front of a person.
An app made before this release keeps the opt-in it has.

## Context

ADR 0139 made the authority surface a committed artifact and made its drift red, but only in an
app that adopts it, and the template adopts nothing. So in a new app, a module made public by
mistake leaves every gate green. That is the one mistake the framework cannot prevent and an
owner can judge. The owner's direction of 2026-11-04 names closing it the improvement that does
most for a non-technical owner, and settles that Studio blocks such a change rather than
reporting it afterwards.

The check also reports its changes as one list of sentences. A tool that must ask an owner
about some changes and not others cannot tell them apart, so it would ask about every change or
about none.

## What it covers, and what it does not

The surface answers one question: **which rung of the role ladder reaches which method and path,
under which requirement.** It does not cover row scope (what a tenant or owner filter lets a
caller see once in), who holds a rung (an assignment, or a role given on first sign-in), or
realtime channels' requirements and audiences. A tool that shows its lines must not promise
more than that.

It sees the modules that `build()` composes where the check runs. A module mounted only when a
setting is present is outside the surface unless that setting is present then.

## What changes

1. **The template pins.** The template's `pyproject.toml` gains
   `[tool.terp.verify] pinned = ["authz-surface"]`, in the release whose `terp verify` reads that
   key: an older one refuses an unknown key, which would take every check out of the run. With
   the line and no `authz-surface.json`, the check is red and names the command that writes the
   file, `terp inspect access --app app.main:build --format surface`. Studio's bootstrap runs
   it after the first install; for an app rendered by hand it is the README's first step.
   Template acceptance does the same on every variant, then runs the check. The template carries
   no baseline of its own: a hand-kept copy would describe the surface rather than derive it,
   which ADR 0121 decision 4 rules out, and it would be wrong for some combination of answers.
2. **Each change is labelled.** A rung *reaches* an endpoint unless its answer is `rank`,
   `no_policy`, `unknown_permission`, `unauthenticated` or `unregistered_role`. A `grant` answer
   reaches: whoever holds the permission gets in. For an endpoint on both sides, a change is a
   narrowing when all three hold:
   - every rung's answer stays, or moves down the order public, allowed, grant, refused;
   - where both answers are a grant, they name the same permission;
   - the endpoint's required grants are the same, or more.

   An endpoint that is gone, or a new one that no rung reaches, is a narrowing too. Everything
   else is a widening: a new endpoint some rung reaches, a rung that gains reach, a grant that
   names another permission, fewer required grants, a change to the role ladder or a
   permission's floor, and a change to a module's `policy` or `access`. A change the check
   reports without a label of its own (the whole-surface line 0.41.0 adds) is a widening too.
   This is set inclusion over the answers `decide` already gives. It judges no change dangerous
   or safe, which ADR 0139 rightly declined to do. It proves only that nobody gains reach, and
   calls everything else a widening.
3. **The output says so.** The text output lists each change under `widens:` or `narrows:`.
   `terp verify --format json` gives the check's result an `authority_changes` list with one
   entry per change. Each entry carries what a person needs to read it: the module; the
   method and path; the operation's label where the route declares one, or `null`; the rungs
   that gain or lose reach, with `anonymous` for a public endpoint; the permissions involved,
   with their labels; the sentence the text prints; and `widens`. What the check cannot see
   goes in a list of its own, `authority_unseen`: a route the access graph cannot place, a
   method and path two routes serve, an app it cannot compose. Those are code to fix, never a
   change to approve, so a tool must not put them in front of an owner. Drift stays red
   either way. The baseline is still regenerated in the same change, so the diff records what
   changed.
4. **Upgrading the packages stays green.** Only the template carries the pin, so a tree with no
   baseline and no `pinned` line still skips with its note. An app that takes the template's
   update with `copier update` gets the `pinned` line too, and its check then names the one
   command that writes the baseline. A framework release that adds an endpoint to a
   capability turns a pinned app's check red, and that is intended: the app's owner has not
   seen the new endpoint.

## Consequences

- Studio can block on widenings with no authorization model of its own.
- The label is conservative. A requirement moved from one permission to another at the same
  floor is a widening, because the people who hold the two may differ.
- `[tool.terp.verify]` accepts a second key beside `checks`: `pinned`, the checks whose artifact
  must exist. For now it accepts only `authz-surface`.
- An app made before this release adopts as ADR 0139 says, with one command and one commit. It
  adds the `pinned` line if it wants a missing file to be red.

## Open

- **A module that only mounts under a setting.** The template mounts its OIDC routes only when
  `OIDC_ISSUER` is set, so the check composes them only where that variable is set. The owner
  decided on 2026-11-09 that a module list may not depend on a setting, which also makes the
  surface the same in every environment. It is a change of its own, because mounting the OIDC
  routes always needs a way for them to refuse while no provider is configured: today the
  provider's configuration is validated when the app starts.
