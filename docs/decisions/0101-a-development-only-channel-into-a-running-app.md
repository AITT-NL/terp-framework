# 0101 — A development-only channel into a running app

- **Status:** Accepted
- **Date:** 2026-08-24
- **Relates:** [ADR 0094](0094-attribute-keyed-styling.md) (the `data-terp` markers this reads,
  and the inventory ratchet that keeps them a closed set),
  [ADR 0079](0079-slot-typed-layout-contracts.md) (`verifySlotChildren`, the other consumer of
  those markers at runtime), and
  [ADR 0006](0006-agent-execution-boundary.md) (the quadruple this deliberately does not
  complete — see §5)

---

## Context

An operator watching their app in a tool that embeds it — the Studio renders the real app under
`docker compose watch`, in an iframe, on its own origin — has no way to point at anything. They
see a button they want changed and have to describe it: *"the blue one at the top of the list
page"*. The tool cannot help, because a cross-origin iframe is opaque to it by design.

The information needed is already in the DOM and already closed. Every sanctioned component
stamps `data-terp` on its root, the inventory is 200 pinned names, and `markers.test.ts` fails in
both directions on a name added or removed. *"Which component is this?"* is a question the page
can already answer. What was missing was anyone to ask it, and a way to ask.

The reason nobody had added one is the reason to be careful: a `postMessage` listener inside every
app the platform ships is a surface on every app the platform ships.

## Decisions

### 1. It exists only in a development build

The whole module sits behind `import.meta.env.DEV`, which a production build folds to `false` and
strips the module with. A deployed app has no listener at all — not a disabled one, not a
configurable one, not one behind a flag somebody can leave on. Everything below is therefore
about a developer's own machine and a preview of an app being worked on.

This is the same mechanism the template already uses for its dev sign-in credentials, and the
same reasoning: the safest version of a development affordance is one that cannot exist in
production.

The consequence is that this claim cannot be tested at runtime — `import.meta.env.DEV` is true
under vitest. So the gate is asserted the way the repo asserts other build-time facts: on the
source, that the expression is still written and that there is exactly one call to the installer
in the package. A bundler folds that expression *textually*, which is also why the call site
writes it out rather than reading it through a helper.

### 2. The tool speaks first, and only it is answered

The app never announces itself. It records the origin of the first well-formed handshake and
replies to that origin alone, thereafter.

That is not only prudence, it is the only mechanism available: the Studio builds a preview URL by
overwriting the path and clearing the query and fragment, so there is no channel to configure an
origin through — and the two are deliberately *different* origins, because a preview on the
Studio's own host would carry the operator's session cookie into app code.

### 3. Structure, never content

A reply carries `data-terp` markers, element tag names and a bounding rectangle. It carries no
text, no values, no attributes, nothing an app puts data in.

An app under development is an app with real data in it. A channel that could read the page would
be a way out for that data — from a dev machine, but out. The rule is asserted rather than
described: the test serialises a whole reply and fails if the words on the page appear in it.

### 4. The app draws its own highlight

A tool cannot paint over a cross-origin iframe, so pointing at something happens on this side or
not at all. One outline, from the token layer, on an attribute — removed with the mode, and with
the bridge.

### 5. ADR 0006's quadruple is not completed, and here is which halves are missing

Present: a **typed protocol with a safe default** — select mode is off, the protocol name carries
its own version, and the whole thing is absent in production — and a **fail-closed runtime
check**: every message is validated for protocol, kind and shape, and anything from another
origin is dropped without a reply.

Absent: a **build-time rule** and a **budgeted escape hatch**. A lint rule would have nothing to
check, because this is not something an app writes — it is one call inside `renderTerpApp`, and
the thing a rule would police (an app installing its own listener) is not a pattern that exists.
An escape hatch has nothing to be an exception to: there is no rule here for an app to break, and
nothing to opt out of in a build where the module does not exist.

Stated rather than left as an absence, per ADR 0100 §6's precedent — so the gap is a decision
someone can revisit rather than an oversight someone rediscovers. What would change it: an app
gaining a way to configure or extend the bridge. At that point there is something to write, and
therefore something to check.

## Consequences

- The marker inventory becomes load-bearing in a second way. It was a styling contract and a slot
  contract; it is now also the vocabulary a tool uses to name a component to an agent. Renaming a
  marker already fails `markers.test.ts` in both directions, so nothing new is needed — but the
  reason to keep that ratchet just grew.
- The protocol is versioned in its own name (`terp.preview.1`). A Studio and an app can be from
  different releases, and a version mismatch has to be silence rather than a half-understood
  conversation: an app that does not recognise the name ignores the message, which is what an
  older app does with a newer tool and the reverse.
- Twelve assertions, nine mutations, all red — including the two that took a second attempt. The
  first was an unreachable `if (asker === null)` guard in the reply path, which no test could
  reach because the origin check upstream already made it impossible; the state model now carries
  the origin in the select-mode variable itself, so "picking is on" and "there is someone to
  answer" are one fact and the branch is gone rather than untested. The second was the reply
  TARGET: nothing asserted that a selection is addressed to the asker rather than to `"*"`, and a
  wildcard target is readable by whatever frame happens to be the parent — indistinguishable from
  a correct reply by looking at the message.
