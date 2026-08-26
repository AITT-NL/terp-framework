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
    style-src 'self'; img-src 'self' data:; font-src 'self';
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

### 2. `style-src` carries no `'unsafe-inline'` — amended 2026-08-26

As first shipped this policy allowed `'unsafe-inline'` in `style-src`, because
`@terpjs/react-core` injected its token stylesheet as a `<style>` element and a `<style>`
element's rules are inline styles as far as CSP is concerned. That was measured with a control,
and the control mattered: the naive check (reading a CSS custom property) passed with the keyword
*and* without it, because that token comes from the bundled stylesheet rather than the injected
one. Only counting live stylesheets, and seeing a heading render lowercase where a
`text-transform` should have applied, showed the difference.

**The keyword is now gone, because the injector changed.** react-core delivers the sheet through
`document.adoptedStyleSheets`, and a constructable stylesheet is not governed by `style-src` at
all. Measured in Chromium, first in isolation and then against the built example bundle:

| mechanism | under `style-src 'self'` |
|---|---|
| literal `style="…"` attribute in served markup | blocked |
| CSSOM property assignment (`el.style.width = …`) | applies |
| `style.cssText = …` | applies |
| adopted constructable stylesheet | applies |
| `<style>` element with `textContent` | blocked |

Two consequences fall out of that table. The injector works, and so does React's
`style={{ … }}`: React assigns through CSSOM rather than writing a markup attribute, so the
handful of inline styles react-core sets for measured dimensions were never the obstacle they
looked like. Only a literal attribute in server-sent markup is refused, and a client-rendered SPA
sends none.

Against the built bundle the strict policy reported no violations, the sheet arrived adopted
rather than as an element, and a rule only react-core declares (`cursor: pointer` on a button)
applied. The permissive policy behaved identically, so the change is neutral for anyone still
serving the old header.

This matters more than one keyword. `'unsafe-inline'` is not a permission for *our* stylesheet —
it permits **every** inline stylesheet on the page, including one an injection manages to
introduce. Removing it is what makes the frontend XSS rules' defence-in-depth real rather than
nominal, and it is the framework absorbing the cost so every generated app is stricter by
default without its author doing anything.

### 3. Assets get `nosniff` and no CSP

Hashed bundle responses are not documents, so a CSP on them governs nothing. `nosniff` still
earns its place: it stops a mistyped bundle being reinterpreted as something executable.

### 4. The dev server holds the same origin rules — added 2026-08-26

A strict policy in production and none in development means a CSP-incompatible pattern works all
the way to deploy before anything objects. The motivating case is concrete: an agent reaching for
a CDN chart library because that is how the wider ecosystem does it. Under the shipped
arrangement that worked in development, passed review, and broke in production.

The Vite dev server therefore serves the **same origin rules** as production. Measured against a
running dev server in Chromium, the parity is real where it matters:

| attempt from the page | dev server |
|---|---|
| `<script src="https://cdn.jsdelivr.net/…">` | refused — `script-src-elem` |
| `<link rel=stylesheet href="https://fonts.googleapis.com/…">` | refused — `style-src-elem` |
| `fetch("https://example.com/collect")` | refused — `connect-src` |

Two relaxations are dev-only and forced by Vite's own machinery rather than by app code: the React
Fast Refresh preamble is an inline script, and Vite serves imported CSS by injecting a `<style>`
element. Starting from the production policy, the dev server rendered nothing at all — an inline
`script-src-elem` violation — so `'unsafe-inline'` is granted to `script-src` and `style-src`
there and nowhere else.

**That asymmetry is the honest limit of this parity.** Development cannot catch a newly added
inline script or style, because it cannot distinguish one from Vite's own. Production still does.
What development now catches is every third-party origin, which is the failure mode that actually
occurs.

`connect-src` stays `'self'` rather than widening to `ws:`. `'self'` already covers the HMR socket
— measured: the client logs "[vite] connected." with `'self'` alone — and `ws:` would permit a
socket to any host. The gate asserts the narrower form, because the broader one is the plausible
thing to reach for when HMR misbehaves for an unrelated reason.

## Consequences

- **Every newly scaffolded app is hardened by default**, with no action by an app author who could
  not evaluate the trade-off — the design centre ADR 0103 names.
- **An app needing a third-party origin must widen the policy explicitly**, in its own nginx
  config. That is a visible, greppable, reviewable edit, not a silent capability.
- **The runtime half is verified but not yet automated.** The headers were measured on a live
  nginx, and the shipped config is gated statically, but nothing in the suite asserts the header on
  a running production stack. The conformance suite cannot host that probe today: it targets the
  vite dev server by default, which sets none of these.
- **One follow-up remains:** a smoke probe against the production compose stack, to automate what
  was verified by hand here. Both other follow-ups recorded in earlier revisions of this ADR are
  done — the `'unsafe-inline'` removal in §2, and dev/prod parity in §4.
- **The same gap exists in the Studio's own document.** `terp-studio` serves its SPA through
  FastAPI's `StaticFiles` and sets a CSP only on user-uploaded attachment downloads
  (`sandbox; default-src 'none'`, which is correct and worth keeping). Its own document has none.
  That is the same defect in a different repository and is tracked there.
