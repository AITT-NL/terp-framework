# 0117 — The egress capability the rule was already naming

- **Status:** Accepted
- **Date:** 2026-09-06
- **Relates:** [ADR 0096](0096-typed-seams-cover-the-common-case.md) (a checked seam that
  does not cover the common case is a hole — this is that finding applied to the seam
  the outbound-HTTP rule pointed at),
  [ADR 0051](0051-outbound-webhooks.md) (the SSRF guard this generalises, and the
  capability that becomes its first consumer),
  [ADR 0067](0067-per-module-request-size-allowances.md) (bounding what comes *in*, whose
  shape this borrows for what goes *out*),
  [ADR 0006](0006-cross-cutting-controls-and-opinionation-policy.md) (a seam ships a safe
  default; this one's default permits nothing)

---

## Context

`no_raw_outbound_http` refuses `httpx`, `requests`, `urllib3`, `aiohttp`, `socket`,
`urllib.request` and `http.client` in every application module — and, because it is a
security rule, in that module's tests and migrations too. The refusal told the author
where to go instead:

> outbound HTTP must go through a declared capability with SSRF protection

**There was no such capability.** Nineteen shipped and outbound HTTP was not one of
them. The only SSRF guard in the tree was private to webhook delivery: it validated a
*webhook subscription's* target, raised a *webhook's* 422, and lived inside the
webhooks package, reachable only by installing a capability whose purpose is something
else entirely.

So the rule refused the common case and named a destination that did not exist. ADR
0096 §4 already supplies the verdict for exactly this shape: a checked seam that does
not cover the common case is a hole, because the compliant path is not available and
code goes around it. And the going-around is not hypothetical — it is observable as a
whole foreign-system connector living in a third root package that the architecture
scanner never reaches, fenced off by an import-linter contract. That is a good design
the framework forced and then sanctioned nowhere.

It is not only an implementation gap. `terp-spec`'s catalog entry makes it normative —
"outbound traffic belongs behind a declared capability that centralizes those controls"
— and its reference realisation says outbound calls "go through a declared **egress**
capability". The standard had already named this package. It just had not been written.

## Decision

**Ship `terp-cap-egress` — `terp.capabilities.egress` — and make the four things the
rule calls per-call-site choices into properties of a declaration.**

A **library** capability, like `terp-cap-leases`: no router, no table, no
auto-discovery entry point. Outbound access is not something an application should
acquire by installing a package. It declares an `EgressPolicy` and constructs a client,
and both of those are visible in the composition root.

### The four choices, made once

**The allowlist is exact hostnames, and empty by default.** `api.example.com` does not
admit `evil-api.example.com`, and patterns are refused at construction because a
wildcard is the shape that turns an allowlist into a formality. A policy nobody filled
in permits nothing, so the failure mode of forgetting to configure egress is that
egress does not work — not that it works without limits.

**The SSRF denylist applies to every resolved address, and the connection is pinned to
the one that passed.** Resolving once and connecting to the validated address is what
closes the DNS-rebinding window between the check and the connect; connecting by
hostname after checking would leave it open. Redirects are never followed, because a
followed redirect is a second, unvalidated target — it would hand the far end the power
to choose where the next request goes.

**The timeout is on the policy and has no per-call override.** An unbounded outbound
call is how one slow third party takes a worker pool with it, and the call site is
precisely the place that is tempted to raise the bound "just here". The response is
bounded too, for the same reason an inbound body is: it is attacker-influenced input,
and an unbounded read is an unbounded allocation.

**Every attempt reaches an observer, including the refusals.** This is where metering
and egress auditing attach, and it is the reason the artifact's "meter the AI calls"
request is answered here rather than in an AI capability: what is worth recording is
that a call happened, to whom, and what it cost. The observer deliberately never sees a
body — a seam that handed over payloads would become a second place secrets are read —
and an observer that raises cannot change what happened, because metering is not
allowed to turn a completed call into a failed one.

### The escape hatch is a declaration, not an exception

`allow_private_addresses` opens the denylist. It exists because a sanctioned internal
target is a real deployment shape, and the honest way to serve it is a field in the
composition root that a reviewer can see. It applies to the whole policy rather than to
one host: a policy that needs it relaxes it for everything it can reach, and if that is
too coarse the answer is two clients with two policies — not a per-call flag, which
would put the decision back at the call site this capability exists to take it away
from.

### Webhooks becomes the first consumer, and the denylist moves rather than being copied

The table of forbidden network ranges, the IPv4-mapped-IPv6 unwrapping, the pinned
target and the fail-closed resolver now live in egress. Webhooks imports them and keeps
what is genuinely webhook-shaped: its 422 at the API boundary and the messages a
subscriber sees.

Copying would have been the smaller diff and the worse decision. Two lists of forbidden
network ranges drift, and the one that drifts is the one nobody is looking at. A
capability with no consumers would also have repeated the original mistake in a new
place: a seam that exists and that nothing uses is only evidence that it might work.

## Consequences

**The rule's refusal now names something a reader can act on.** It says which capability,
what to declare, and what the client does — instead of describing a destination in the
abstract.

**Nothing changes for an application that makes no outbound calls**, and nothing is
mounted or migrated by installing the package.

**The two AI-capability prerequisites this repository owed are now one.** ADR 0111 §4
declined an AI capability because the framework owns the socket, not the plug, and
recorded that what the request was actually right about was more general than AI:
transport, timeouts and SSRF are this; metering is one hook on this; auditing the call
is the other prerequisite, and is still open.

**`httpx` becomes a dependency of exactly one distribution.** It was already a
dependency of webhooks; it is now declared where the platform's outbound client belongs,
and every other package reaches the network through it.

## Alternatives considered and not taken

**Put the client in `terp.core`.** The kernel would then carry an HTTP client every
application links whether or not it makes outbound calls, and "does this app talk to
the network" would stop being answerable from the composition root. Capabilities exist
for exactly this: a thing you opt into, visibly.

**Widen the rule's escape hatch instead of building the seam.** Cheaper, and it
concedes the argument: the rule would then refuse a common, legitimate need and hand
out a marker for it, which is a budget line rather than a solution. ADR 0103's bargain
is one pattern, enforced, escapable by proof — and a proof that has to be produced by
every application for the same reason is a missing pattern.

**Let the policy take URL patterns or path prefixes.** Tempting, and it is the wrong
axis. What SSRF is about is which *host* the socket lands on; a path allowlist gives
the comforting appearance of tighter control while the connection is made to exactly
the same place. Hostnames are the thing the guard can actually enforce.

**A per-call timeout override.** The single most requested shape and the one that
undoes the control: every call site that wants a longer bound believes its case is
special, and the aggregate is no bound at all. Two policies for two purposes is the
answer, and it stays visible.
