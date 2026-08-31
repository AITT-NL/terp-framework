# 0107 — The dev server names who may frame it

- **Status:** Accepted
- **Date:** 2026-08-31
- **Relates:** [ADR 0104](0104-the-spa-document-carries-its-own-security-headers.md) (the document
  security headers this amends — §4's dev-server mirror is the paragraph that changes),
  [ADR 0103](0103-the-ideology-one-pattern-enforced-escapable-by-proof.md) (escape by explicit
  declaration through a proven method — the shape this takes),
  [ADR 0101](0101-a-development-only-channel-into-a-running-app.md) (the precedent for a control
  that is deliberately different in development and absent in production),
  [ADR 0062](0062-production-deployment-profile.md) (the production nginx policy, unchanged here).

---

## Context

ADR 0104 gave the SPA document its own security headers, and 0.12.0 mirrored that policy's
*origin* rules into the Vite dev server so that a CSP-incompatible pattern — an agent reaching
for a CDN chart library is the case that motivated it — fails on the first run instead of at
deploy. That mirror was assembled by copying the production policy and relaxing only what Vite's
own machinery forces.

It copied `frame-ancestors 'none'` along with the rest, and that directive is the one part of the
policy for which production and development do not have the same audience. The production
document is served to a browser. The development document is served to a browser **inside a
workbench preview pane**: Terp Studio embeds the running dev server in an iframe, which is how a
person building an app with an agent sees the app at all.

So the mirror shipped a dev server that refuses the only thing that ever embeds it. The failure
is silent in the worst way. Chromium blocks the frame with `ERR_BLOCKED_BY_RESPONSE` and paints
its generic frame-refusal page, which reads:

```
localhost refused to connect.
```

That sentence describes a network failure. The stack is healthy, the port is published, the page
loads perfectly in a new tab, and every instinct sends the reader to ports, bind addresses and
environment variables first. It cost an afternoon on the first app that upgraded into it, and no
gate in either repository noticed: the framework had no test that framed a dev server, and the
workbench had none that loaded a real app in a real iframe.

Two further observations shaped the fix rather than just the diagnosis.

**The directive served none of the mirror's stated purpose.** Everything ADR 0104 §4 set out to
catch early is caught by other directives: a CDN script by `script-src`, an external stylesheet
by `style-src`, a cross-origin fetch by `connect-src`. `frame-ancestors` governs only who may
embed the dev server, and in development the answer is not "nobody".

**The right origin cannot be written in a template.** A workbench's origin is a deployment fact,
not a framework fact: `http://localhost:8420` on a laptop, `https://studio.example.nl` behind a
client's reverse proxy. A literal would be wrong for someone on the day it was written.

## Decision

**In the dev server, `frame-ancestors` is declared rather than literal.** One environment
variable, `TERP_DEV_FRAME_ANCESTORS`, carries exactly one origin. Unset, blank or malformed keeps
`frame-ancestors 'none'`, so the strict posture is what a hand-run `terp docker dev` gets and the
escape is visible, greppable and deliberate — ADR 0103's shape, not a relaxation.

`frontend/vite.config.ts` validates the value against an anchored
`^https?://[A-Za-z0-9.-]+(?::\d{1,5})?$` and refuses anything else back to `'none'`, with a
console warning. The compose workbench passes `${TERP_DEV_FRAME_ANCESTORS:-}` into the `web`
service. **Production is untouched:** the nginx policy of ADR 0104 still says
`frame-ancestors 'none'`, unconditionally and with no knob.

### One origin — never a list, never a wildcard

A preview pane has exactly one embedder, so a list buys no capability that anyone can name, and
`*` would let any page on the network frame a dev server that is holding a signed-in session.
Both are refused by the pattern rather than by convention.

The validation is not decoration. The policy is assembled by joining directives on `"; "`, so a
value carrying a semicolon would append directives of its own and rewrite the entire policy —
`http://a.example; script-src *` is one string away from disabling the CSP the surrounding work
exists to enforce. Anchoring at both ends is what makes that unreachable, and the gate asserts
the anchors specifically.

### Where this does *not* go

Two alternatives were considered and rejected, both of which would have put the fix in the
workbench instead.

**The workbench proxies the preview on its own origin** and rewrites the header. Same-origin
means no framing question at all. It is rejected by a decision the workbench already holds: a
preview served from the workbench's own hostname would carry the operator's workbench session
cookie into untrusted, agent-written app code. That trade is worse than the problem.

**Drop the iframe and make "open in a new tab" the only route.** Cheapest of all, and it removes
the pane the workbench is built around, along with the click-to-select bridge that depends on it.

## Consequences

- An app rendered from a template **before** this ADR has no dev CSP at all and previews as it
  always did. An app pinned at exactly 0.12.0 carries the hardcoded `'none'`, ignores the
  variable, and stays blocked until it upgrades — so the workbench has to *explain* a blocked
  frame rather than show a blank pane. That is the half of this fix that helps an app which has
  not upgraded yet.
- Development and production policies are no longer byte-identical in this one directive. ADR
  0104 §4's claim of exact origin parity now carries a named exception, and the comment in
  `vite.config.ts` states it where the next reader will be.
- The template copy and the example app's copy of the policy are held **byte-identical** by
  `tests/architecture/test_template.py`. Only the example can be evaluated in a browser (it is a
  workspace member with vite installed), so byte identity is what makes one measured run an
  assertion about both.

## The policy must not be cacheable — amended 2026-08-31

Shipping the declaration was not enough, and the gap was found by a person who had done
everything right: they upgraded their app to a template that permits framing, and their
browser went on refusing it. Another browser, freshly opened, worked.

The dev server sent `Cache-Control: no-cache` with an ETag derived from the document body.
`no-cache` does not mean "do not reuse" — it means "revalidate before reusing", so the
response is *stored*. Vite answers a revalidation with a bare `304 Not Modified`, and
RFC 9111 keeps the headers a 304 omits, so the browser goes on enforcing the
`Content-Security-Policy` it saved earlier. The body does not change when this policy does,
so the ETag matches and the stale policy is reused indefinitely.

**The dev document therefore sends `Cache-Control: no-store`.** A security header whose
cache key does not include the header must not be cacheable at all. The rule lives in the
same `server.headers` block as the policy, and the gate asserts both are there and
byte-identical across the template and example copies — a one-sided drift in the cache rule
passed the first version of that check, which is the same failure this ADR is about, one
directive over.

Measured against a server reproducing Vite's shape (body-derived ETag, bare 304), with the
policy flipped from deny to allow while the body stayed identical:

| dev document sends | after the policy changes |
| --- | --- |
| `Cache-Control: no-cache` | **still blocked** — the stale policy is still enforced |
| `Cache-Control: no-store` | framed |

The first row is the bug as it was experienced. Note what no amount of server-side
diagnosis could have done here: a workbench reading the app's header over HTTP gets the
*fresh* policy while the browser holds a stale one, so the two cannot be compared. That is
the argument for making the header uncacheable rather than for detecting the divergence.

## Measurement

Chromium's half was measured, not reasoned about: a real dev-server header on one origin, framed
from a page on another, with `@playwright/test` driving Chromium.

| `TERP_DEV_FRAME_ANCESTORS` | header emitted | framed? |
| --- | --- | --- |
| unset | `frame-ancestors 'none'` | no — `ERR_BLOCKED_BY_RESPONSE` |
| the embedder's origin | `frame-ancestors http://127.0.0.1:18497` | **yes** |
| a different origin | `frame-ancestors http://127.0.0.1:19999` | no — `ERR_BLOCKED_BY_RESPONSE` |
| `*` | `frame-ancestors 'none'` | no — `ERR_BLOCKED_BY_RESPONSE` |

The third row is the one worth keeping: the declaration is scoped to the origin named, not a
blanket "may be framed". Config resolution was measured through Vite's own
`loadConfigFromFile`, so the values above are the header the real dev server sets, not a
reimplementation of the logic; a blank value, whitespace, a bare host with no scheme, a
`javascript:` URL, two space-separated origins and a trailing `; script-src *` all resolved to
`'none'`.
