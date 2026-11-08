# 0209 — A new app pins who can reach what, and the check names each change that widens it

- **Status:** Proposed on 2026-11-08, for the owner's review before anything is built.
- **Date:** 2026-11-08.
- **Amends:** [ADR 0139](0139-who-can-reach-what-is-pinned-not-merely-reportable.md): its
  opt-in, for an app the template makes, and its consequence that labelling a change would be
  a second authorization model.
- **Relates:** [ADR 0121](0121-a-module-role-is-an-assignment-not-a-policy.md) decision 4
  (what a rung grants is derived, never declared, and the access graph replays the guard), and
  terp-studio's record of its half: a change that widens who can reach what waits for the
  app's owner.

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

## What changes

1. **The template pins.** The template's `pyproject.toml` gains
   `[tool.terp.verify] pinned = ["authz-surface"]`. With that line and no `authz-surface.json`,
   the check is red and names the command that writes the file. Studio's bootstrap runs that
   command after the first install. For an app rendered by hand, it is the README's first step.
   Template acceptance does the same on every variant, then runs the check. The template carries
   no baseline of its own. A hand-kept copy of the surface would describe it rather than derive
   it, which ADR 0121 decision 4 rules out, and it would be wrong for some combination of the
   template's answers.
2. **Each change is labelled.** For an endpoint on both sides, a change is a narrowing when all
   three hold:
   - every rung's answer stays, or moves down the order public, allowed, grant, refused;
   - where both answers are a grant, they name the same permission;
   - the endpoint's required grants are the same, or more.

   An endpoint that is gone, or a new one that no rung reaches, is a narrowing too. Everything
   else is a widening: a new endpoint some rung reaches, a rung that gains reach, a grant that
   names another permission, fewer required grants, and any change to the role ladder or a
   permission's floor. This is set inclusion over the answers `decide` already gives. It judges
   no change dangerous or safe, which ADR 0139 rightly declined to do. It proves only that
   nobody gains reach, and calls everything else a widening.
3. **The output says so.** The text output lists each change under `widens:` or `narrows:`.
   `terp verify --format json` gives the check's result an `authority_changes` list with one
   entry per change: the module, the method and path (or `roles` or `permissions` for the
   ladder), the rungs that gain or lose reach, the sentence the text prints, and `widens`.
   Drift stays red either way. The baseline is still regenerated in the same change, so the
   diff records what changed.
4. **Upgrading stays green.** Without the `pinned` line, the check still skips with its note. A
   framework release that adds an endpoint to a capability turns a pinned app's check red, and
   that is intended: the app's owner has not seen the new endpoint.

## Consequences

- Studio can block on widenings with no authorization model of its own.
- The label is conservative. A requirement moved from one permission to another at the same
  floor is a widening, because the people who hold the two may differ.
- `[tool.terp.verify]` accepts a second key beside `checks`: `pinned`, the checks whose artifact
  must exist. For now it accepts only `authz-surface`.
- An app made before this release adopts as ADR 0139 says, with one command and one commit. It
  adds the `pinned` line if it wants a missing file to be red.
