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
stamps `data-terp` on its root, the inventory is a pinned list, and `markers.test.ts` fails in
both directions on a name added or removed — that file is where the names are, and how many there
are is a question to ask it rather than a number to copy into prose. *"Which component is this?"*
is a question the page can already answer. What was missing was anyone to ask it, and a way to
ask.

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

### 2. The tool speaks first, the first one wins, and it is answered where it asked from

The app never announces itself. It records the origin **and the window** of the first well-formed
handshake and answers that one alone, thereafter. A second party cannot take the conversation
over and cannot start one.

First-come rather than validated, and that is worth saying plainly: there is nothing here to
validate an origin *against*. The Studio builds a preview URL by overwriting the path and clearing
the query and fragment, so there is no channel to configure an origin through — and the two are
deliberately *different* origins, because a preview on the Studio's own host would carry the
operator's session cookie into app code. The one origin value that is refused outright is the
opaque `"null"`: it is what a sandboxed iframe, a `file://` page and a `data:` URL all report, so
adopting it would adopt the next one of those too.

The window is kept alongside the origin because the origin alone does not say where to send the
answer. `window.parent` is the embedder only when there IS an embedder; open the app in a tab and
`window.parent` is the app itself, so a reply addressed there reaches nobody while looking like it
worked. Keeping the sender also means a second document on the *same* origin — a tool's own popup
beside its preview — cannot drive a conversation it did not start.

### 3. Three things leave, and they are named exhaustively

A reply carries `data-terp` markers, element tag names, and the route path the page is on. No
text, no values, no attributes, nothing an app renders data into.

The route path is listed rather than glossed. This section said *"structure, never content"* and
sent it anyway, which is not true of `/records/42`: a route path carries an identifier. It is sent
because *"which component"* is not a useful answer without *"on which screen"*, and it is the same
string already visible in the address bar of the frame the asker is displaying. A bounding
rectangle used to leave as well; nothing consumed it, so under *no field without a reader* it does
not.

Markers and tags are checked against the shape every name in the inventory has — lowercase
letters, digits and hyphens, bounded in length — and a step that fails is dropped rather than
sent. This code cannot tell a component's marker from a string an app put in the same attribute,
and the chain ends up in a sentence handed to an agent; an unchecked one is the app writing that
sentence. Both halves of the bridge make that check, because neither is the other's guarantee.

An app under development is an app with real data in it. A channel that could read the page would
be a way out for that data — from a dev machine, but out. The rule is asserted rather than
described, and in two directions: the test serialises a whole reply and fails if the words on the
page appear in it, and it pins the reply's KEYS, because serialising cannot see a field somebody
adds later.

### 4. The app draws its own highlight

A tool cannot paint over a cross-origin iframe, so pointing at something happens on this side or
not at all. One outline, from the token layer, on an attribute — removed with the mode, and with
the bridge.

### 5. ADR 0006's quadruple is not completed, and here is which halves are missing

Present: a **typed protocol with a safe default** — select mode is off, the protocol name carries
its own version, and the whole thing is absent in production — and a **fail-closed runtime
check**: every message is validated for protocol, kind, shape and sender, and anything from
another origin, another window or an opaque origin is dropped without a reply.

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
- Every refusal in this module has a mutation behind it and every one of them is red;
  `previewBridge.test.ts` is the list, and it is the place to count. Four took a second attempt
  and are worth naming, because each was a gate that passed with the bug in place. An unreachable
  `if (asker === null)` guard in the reply path, which no test could reach because the origin
  check upstream already made it impossible — the state model now carries the asker in the
  select-mode variable itself, so "picking is on" and "there is someone to answer" are one fact
  and the branch is gone rather than untested. The reply TARGET, which nothing asserted was the
  asker rather than `"*"` — a wildcard target is readable by whatever frame happens to be the
  parent, and indistinguishable from a correct reply by looking at the message. The reply
  DESTINATION after that: `window.parent` under a spy that jsdom makes equal to `window`, so a
  reply that would have reached nobody in a real tab looked correct in the suite. And the
  single-installer scan, which globbed `.tsx` only while most of this package is `.ts` — proved
  blind by adding a call to a `.ts` module and watching it stay green.
