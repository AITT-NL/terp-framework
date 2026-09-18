# 0142 — One transport, and the caller that brings its own policy

- **Status:** Accepted and implemented. `terp.capabilities.egress.send_pinned` is public
  API; `EgressClient` and the `WEBHOOK_DELIVER` job both call it, and
  `terp-cap-webhooks` declares no HTTP client among its dependencies. Held by
  `tests/architecture/test_egress.py` and `tests/architecture/test_webhooks.py`.
- **Date:** 2026-09-18
- **Relates:** [ADR 0117](0117-the-egress-capability-the-rule-was-already-naming.md)
  (the capability this completes — and whose stated consequence it makes true),
  [ADR 0051](0051-outbound-webhooks.md) (the delivery seam whose transport this
  replaces), [ADR 0096](0096-typed-seams-cover-the-common-case.md) (a checked seam that
  does not cover the common case is a hole — applied here one level down, to the seam
  *inside* the seam), [ADR 0136](0136-a-security-rule-does-not-stop-at-the-module-tree.md)
  (the widening that put every root under this rule, and inventoried the markers this
  removes one of)

---

## Context

`no_raw_outbound_http` refuses a raw HTTP client in application code and names the
egress capability as the compliant path. Its argument is arithmetic rather than
stylistic: four things have to be right about an outbound request — no redirect
followed, a bounded read, a connection pinned to the address that passed the SSRF
check, and TLS verified against the *name* rather than against that address — and they
are right in as many places as there are clients.

ADR 0117 built the capability and recorded, as a consequence, that "`httpx` becomes a
dependency of exactly one distribution". That did not happen. Three declared it:
`terp-cap-egress`, `terp-cap-webhooks` and `terp-cap-oidc`. The sentence described the
shape the capability was *for* rather than the state the change reached, and nothing
checked it — which is how a claim in a Consequences section becomes the least reliable
prose in a repository.

Webhook delivery is the instructive half, because it did not keep its client out of
neglect. Its target is a URL a subscriber chose, so there is no allowlist to write, and
`EgressPolicy` refuses wildcards precisely because a wildcard allowlist is a formality.
`EgressClient` **is** a policy — allowlist, timeout, response cap, denylist, observer —
and a caller with no allowlist has nothing to hand it. So delivery did its own
validation against this same capability's denylist, and produced a `PinnedTarget` from
this same capability, and then had to open the connection itself, because the code that
opens the connection was private.

That is the ADR 0096 finding one level down. The seam covered the common case; the case
it did not cover was the one caller that had already done the policy work, and the hole
it left was invisible because the code that went around it looked compliant — it used
the capability's denylist and the capability's pinned target, and its opt-out marker
said so truthfully.

The two copies then did what two copies do. The egress transport streams the response
and stops at the policy's cap. The webhook transport read the reply **whole, with no
bound at all**: a subscriber's endpoint could answer a delivery with as much as it
liked and the worker would allocate it. Nothing reads that body — a delivery is judged
by its status code alone — so the unbounded read bought nothing and cost whatever the
far end chose. Neither copy was ever edited wrongly. One of them was improved, and the
other was not there when it happened.

The marker on that import carried `review-by: 2026-12-31`, and its reason was true: the
target really is pinned, redirects really are refused. A true reason is what makes this
kind of debt durable. What the date is for is the question the reason does not answer —
not "is this still safe" but "is this still necessary".

## Decision

**`send_pinned` is public API of the egress capability.** Pinned target, method, body,
headers, timeout and read cap in; an `EgressResponse` out. `EgressClient` calls it.
Webhook delivery calls it through its existing injectable `WebhookSender` seam, and
`terp-cap-webhooks` declares no HTTP client at all.

Exposing a transport that carries no policy is the part of this worth arguing with,
because on its face it is a supported way around `EgressClient`. Three properties bound
it, and none of them is a convention:

- **It takes a `PinnedTarget`, not a URL.** The argument is an address already separated
  from the name it was resolved from, which is precisely what the denylist check
  produces — so the shape of the call is the check. A caller that has not done one has
  nothing to pass. This is a signpost rather than a proof, and worth saying plainly:
  `PinnedTarget` is a dataclass, and nothing stops a determined caller filling it in by
  hand. What it stops is the accident, which is the failure mode that actually occurs.
- **The cap and the timeout are parameters, not defaults.** There is no value a caller
  obtains by omission, so it cannot quietly inherit a weaker bound than it meant to.
- **There is no allowlist in it.** A caller that needs one still has nowhere to put it
  except an `EgressPolicy`, so this function cannot grow into a second, laxer client.

The rule's text is unchanged, and so is its verdict on application code: a module
importing `httpx` is refused and is still sent to `EgressClient`. `send_pinned` is for
a caller that has already done the policy work and would otherwise write the transport
a second time, and the platform has exactly one of those.

## Consequences

**A webhook's reply is bounded, at 1 MiB.** This is a behaviour change: a receiver that
answers a delivery with more than a megabyte now records a failed attempt and retries,
where before it recorded a delivery. No correct receiver meets the bound — it is not a
protocol limit, it is the statement that one endpoint does not get to decide how much a
worker allocates.

**One opt-out is removed rather than renewed.** `terp-cap-webhooks` loses its
`arch-allow-no-raw-outbound-http` budget entry and its `httpx` dependency. A dated
marker is a promise to come back, and coming back means removing it or re-justifying
it — not reading the reason again and agreeing with it.

**ADR 0117's consequence is one distribution from true.** The OIDC capability still
holds two markers and its own client. Its endpoints do not come from a policy; they
come from a discovery document fetched from the issuer, which for a mainstream provider
names hosts the issuer's own hostname does not cover. What its allowlist should contain
is therefore a design question rather than a substitution, and it is decided
separately.
