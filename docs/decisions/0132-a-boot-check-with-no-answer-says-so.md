# 0132 — A boot check that gets no answer says so, instead of rendering nothing

- **Status:** Accepted and implemented. The boot session check carries a deadline,
  `AuthSession.unreachable()` separates "nobody is signed in" from "nobody answered",
  and `RequireAuth` renders a stated failure on the second. Held by
  `packages/frontend/react-core/src/RequireAuth.unreachable.test.tsx`.
- **Date:** 2026-09-09
- **Relates:** [ADR 0031](0031-session-management-token-revocation-and-login-lockout.md) (the boot refresh this
  guards), [ADR 0104](0104-the-spa-document-carries-its-own-security-headers.md) (where the
  "loud on purpose" reasoning was already written down), [ADR 0103](0103-the-ideology-one-pattern-enforced-escapable-by-proof.md)
  (the audience: people who cannot debug a blank page)

## Context

The single least diagnosable failure the stack could produce was also one of its most
ordinary causes: the backend is not running.

The bootstrap issues `POST /api/v1/auth/refresh` before anything renders. The dev server
proxies `/api` to the backend, and when that target is dead the fetch does not fail — it
**hangs**. So the promise never settled, `loading` stayed true for the lifetime of the
page, and `RequireAuth` rendered its `pending` slot, which defaults to nothing. The
observable result was a blank page, an empty `#root`, three console messages, zero
errors and zero warnings. Nothing in the app, the console or the network panel named the
cause.

Two smaller things compounded it. The obvious liveness probe against the dev server's
own origin answered `200` with the SPA, because Vite serves `index.html` for any
unproxied path — fixed separately. And "nobody is signed in" and "the server never
answered" were the same branch, so even a fetch that *did* fail rendered a login form
that could not possibly succeed, sending the reader to check their own password for a
problem that was not theirs.

The framework had already written down the right principle, in the `vite.config.ts` this
same release shipped: *"Loud on purpose. The symptom otherwise is a blank preview pane
and a CSP violation in a console nobody is looking at."* It was not applied one layer up,
to the app's own first request.

## Decision

**The boot requests carry a deadline.** `AbortSignal.timeout(BOOT_REQUEST_TIMEOUT_MS)`
on the boot refresh and on the `/me` load that follows it, so a hang becomes a failure
that can be reported. Guarded for a runtime without `AbortSignal.timeout`, which
degrades to the old behaviour rather than throwing during boot.

**Boot only, deliberately not a client-wide default.** A file upload through the files
capability legitimately runs longer than any timeout that would help here, so a blanket
one would abort correct work in order to fix a diagnosis problem.

**Three states where there were two.** `AuthSession.unreachable()` is true when the boot
check got no answer at all. A resolved response — including a 401 — is an *answer*, and
leaves it false. `RequireAuth` gained an `unreachable` slot which, unlike `pending`,
does **not** default to nothing: it renders a stated failure, because a blank screen is
the failure being fixed and a login form is the wrong answer to it.

**It is loud in both places.** The screen tells whoever is looking at the app; a
`console.warn` naming the API's address and the timeout tells whoever has devtools open,
which for this failure is the person most likely to be looking.

## Consequences

Every app built with `renderTerpApp` gets the stated failure without changing a line —
the bootstrap renders `RequireAuth` without an `unreachable` override, so the framework
default applies.

Two existing test fixtures had to change, and what they were doing is worth recording
because it is the same conflation this ADR removes: they modelled "signed out" by
letting the boot fetch fail outright, which is the state a *dead backend* produces. A
signed-out visitor's browser receives a 401. The fixtures now say that.

A third had to change for an environment reason rather than a real one: `renderTerpApp`
with no `baseUrl` produces a relative URL, which Node's `fetch` cannot parse at all, so
those tests were relying on a rejection no browser would produce. They now pass an
absolute base URL, which is also what a real app does.

The two new strings are in the framework vocabulary and translated, so the message
follows the app's locale like every other framework string.
