# 0104 — The SPA document carries its own security headers

- **Status:** Accepted
- **Date:** 2026-08-26
- **Relates:** [ADR 0103](0103-the-ideology-one-pattern-enforced-escapable-by-proof.md) ("a control
  implemented only in the backend is half-built" — this ADR is the first instance found of
  exactly that), [ADR 0005](0005-security-middleware-and-structured-logging.md) (the backend
  security-header stack this completes), [ADR 0062](0062-production-deployment-profile.md)
  (the production profile whose nginx config this amends).

---

## Context

`create_app` sets a deliberately severe Content-Security-Policy — `default-src 'none';
frame-ancestors 'none'; base-uri 'none'` — on every response it serves. In production the SPA is
served by nginx from its own container, proxying `/api` to the backend so the browser stays
same-origin (ADR 0062).

That arrangement means the strict CSP rides exclusively on **API responses**, and a CSP on a JSON
response governs almost nothing. A JSON body loads no subresources, executes no scripts and
cannot be framed, so `default-src 'none'` there is close to free. The header that decides whether
a third-party script may execute, whether the application may be framed, and which origins it may
connect to is the one on the **HTML document** — and nginx served that document with
`Cache-Control` as its only header. No CSP, no `frame-ancestors`, no `nosniff`, no
`Referrer-Policy`, and no conformance probe anywhere asserting otherwise.

The consequences were live rather than theoretical. Any script element that reached the page —
added by an agent reaching for a CDN chart library, or injected through a dependency — would load
and execute, with no `connect-src` to bound where it could send what it read. The application
could be framed, so clickjacking had no mitigation. And the frontend Standard's XSS rules
(`no-dom-html-injection`, `no-eval`, `no-unsafe-href`) had no defence-in-depth layer behind them:
they reduce the chance of a sink existing, and a CSP is what limits the damage when one does
anyway.

This is precisely the failure ADR 0103 names — a control implemented on one side of the stack and
declared done — and it was found by auditing against that ADR on the day it was written.

## Decision

**The nginx config that serves the document sets the document's own security headers**, in both
the project template and the example app:

```
Content-Security-Policy: default-src 'self'; script-src 'self';
    style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self';
    connect-src 'self'; object-src 'none'; base-uri 'none';
    frame-ancestors 'none'; form-action 'self'
X-Content-Type-Options: nosniff
Referrer-Policy: no-referrer
Cross-Origin-Opener-Policy: same-origin
Permissions-Policy: geolocation=(), microphone=(), camera=()
```

`connect-src 'self'` is sufficient because ADR 0062's same-origin proxy is what the frontend
already depends on, and the Standard's `generated-client-only` rule means all egress goes through
the typed client to that origin. An app that genuinely needs a third-party origin widens this in
its own config — visibly, in one line, which is the point.

### 1. The headers are repeated per location, and that is not redundancy

nginx applies `add_header` from an outer level **only** when the current level declares none of
its own. Both content locations set `Cache-Control`, so a tidy server-level copy of the security
headers reaches neither of them.

Measured against a real `nginxinc/nginx-unprivileged:alpine` rather than reasoned about: with the
headers hoisted to the `server` block — the obvious DRY refactor — the document response came
back carrying `Cache-Control: no-cache` and nothing else, from a container serving 200s. Every
security header was silently gone.

That is a dangerous shape of bug: the config *reads* correct, and the failure is invisible without
inspecting a live response. So `test_frontend_serves_document_security_headers` asserts the
headers inside the document `location` block specifically, and its own comment records why the
refactor it forbids is tempting.

### 2. `style-src` needs `'unsafe-inline'`, and the framework is why

`@terpjs/react-core` injects its token stylesheet at runtime as a `<style>` element built with
`createElement("style")` and `textContent`. That is an inline stylesheet, so `style-src` must
permit it.

Measured, with a control, by serving the example app's built bundle under the candidate policy in
Chromium:

- **With `'unsafe-inline'`:** no violations reported, the injected sheet live, the chrome styled.
- **Without it:** the browser reported a `style-src-elem` violation for `inline`, the document's
  count of live stylesheets fell by one, and the rendering visibly degraded — a heading rendered
  lowercase where the injected sheet's `text-transform` should have applied.

The control mattered: the naive check (reading a CSS custom property) passed in **both** runs,
because that token comes from the bundled stylesheet rather than the injected one. A gate that
only read the token would have reported success while production shipped unstyled.

`'unsafe-inline'` is confined to `style-src`; `script-src` is exactly `'self'`, and the gate
asserts the keyword never appears before `style-src` in the policy.

**Removing it is a framework change, not an app one.** Constructable stylesheets
(`new CSSStyleSheet()` + `document.adoptedStyleSheets`) are not governed by `style-src`, so
adopting them in react-core's injector would let every generated app drop the keyword. That is the
right shape under ADR 0103 — the framework absorbs the cross-cutting concern and every app gets a
stricter default for free — and it is recorded here as the follow-up rather than left implicit.

### 3. Assets get `nosniff` and no CSP

Hashed bundle responses are not documents, so a CSP on them governs nothing. `nosniff` still
earns its place: it stops a mistyped bundle being reinterpreted as something executable.

## Consequences

- **Every newly scaffolded app is hardened by default**, with no action by an app author who could
  not evaluate the trade-off — the design centre ADR 0103 names.
- **An app needing a third-party origin must widen the policy explicitly**, in its own nginx
  config. That is a visible, greppable, reviewable edit, not a silent capability.
- **The runtime half is verified but not yet automated.** The headers were measured on a live
  nginx, and the shipped config is gated statically, but nothing in the suite asserts the header on
  a running production stack. The conformance suite cannot host that probe today: it targets the
  vite dev server by default, which sets none of these.
- **Two follow-ups are recorded rather than done.** Giving the vite dev server a matching policy
  would close the dev/prod parity gap — an agent adding a CDN script would then fail immediately
  instead of at deploy — but vite's HMR needs websocket and inline-script allowances, so it needs
  its own measurement cycle. And a smoke probe against the production compose stack would automate
  what was verified by hand here.
- **The same gap exists in the Studio's own document.** `terp-studio` serves its SPA through
  FastAPI's `StaticFiles` and sets a CSP only on user-uploaded attachment downloads
  (`sandbox; default-src 'none'`, which is correct and worth keeping). Its own document has none.
  That is the same defect in a different repository and is tracked there.
