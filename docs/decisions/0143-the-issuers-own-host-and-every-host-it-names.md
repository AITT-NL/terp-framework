# 0143 — The issuer's own host, and every host it names

- **Status:** Accepted and implemented. Discovery, JWKS and the token exchange go out
  through `terp.capabilities.egress`; `OIDCClient` takes the egress `sender` / `resolve`
  / `observer` seams in place of `http_factory`, and `terp-cap-oidc` declares no HTTP
  client. The capability carries no escape-hatch budget. Held by
  `tests/architecture/test_oidc.py` and `tests/architecture/test_capability_arch.py`.
- **Date:** 2026-09-18
- **Relates:** [ADR 0142](0142-one-transport-and-the-caller-that-brings-its-own-policy.md)
  (the transport this one no longer needed to reimplement),
  [ADR 0117](0117-the-egress-capability-the-rule-was-already-naming.md) (the capability,
  and the consequence this finally makes true),
  [ADR 0058](0058-pluggable-sso-oidc.md) (the capability being routed),
  [ADR 0136](0136-a-security-rule-does-not-stop-at-the-module-tree.md) (the widening that
  made these two markers exist at all)

---

## Context

The OIDC capability held the last two `arch-allow-no-raw-outbound-http` markers in the
platform: one on the protocol client, which really did make requests, and one on the
router, which imported `httpx` solely to spell the type of an injectable factory. Both
carried `review-by: 2026-12-31`.

The obvious move — hand `OIDCClient` an `EgressClient` — does not work, and finding out
why is most of this decision. `EgressClient` is a **policy**, and the centre of that
policy is `allowed_hosts`: exact hostnames, no patterns, empty permits nothing.
Something has to fill it in before the first request, and for OIDC nothing can.

An IdP's endpoints are not properties of its issuer. They are fields in the discovery
document, which is fetched *from* the issuer, and a provider in wide use answers
discovery on one hostname, serves its token endpoint on a second and its JWKS on a
third — all three under the same organisation, none of them derivable from the issuer's
own hostname. So an allowlist of `{issuer host}` refuses two of the three calls a login
makes, and the symptom is that SSO stops working at the first attempt after an upgrade.
An allowlist the operator fills in by hand has the same failure with a worse shape: it
is correct for whoever tried it, wrong for the next provider, and the thing that goes
wrong is an outage in the one flow nobody can work around, because being locked out is
the failure mode.

This is worth stating plainly rather than designing around quietly: **for this caller
the allowlist cannot be a constraint.** The hosts are not knowable until the document
that names them has been read, and the document is read over the network. Any allowlist
derived after that point is derived from the same source it would be guarding against.

What *can* constrain is the other half of the policy — which addresses a host is allowed
to resolve to. That half needs no advance knowledge, because it asks a question about an
address rather than about a name.

There is also a protection the local client never had, and it is the reason this is a
security change and not a tidy-up. Nothing checked the addresses of anything. A
discovery document could name a `jwks_uri` or a `token_endpoint` on a loopback address,
an RFC-1918 address or the cloud-metadata address, and the client would fetch it — and
in the token endpoint's case, post the **client secret** to it. The issuer is
operator-configured and so is semi-trusted, which is why this was never alarming; it is
also exactly the trust a compromised or merely misconfigured IdP spends.

## Decision

**One `EgressClient` per provider host, built lazily and cached, and the address rule
is: the issuer's own host may resolve into a private range, and a host the discovery
document introduced may not.**

The operator named the issuer, so an IdP on the internal network is a deployment shape
they chose — it is how on-premises SSO looks, and a capability that refused it would be
secure and unusable, which is the kind of secure that gets worked around instead of
configured. Every other host arrives from the far end. A party that can edit its own
discovery document does not thereby get to choose which network this server reaches
into.

The rest of the policy follows from the same principle:

- **`allowed_hosts` is that one host.** It refuses nothing that was not already going
  to be refused, and it is kept because it is a *record* — the policy object names who
  this provider talks to, which is what the observer and any egress audit see. Calling
  it a constraint would be the overstatement this ADR started by rejecting.
- **The scheme allowance follows the issuer's own scheme.** An `https` issuer admits
  only `https` endpoints, so a discovery document cannot downgrade the connection the
  operator configured — which matters most at the token endpoint, where the client
  secret goes. A plain-`http` issuer (permitted outside production already) admits
  both, so local development works. One rule rather than a second switch.
- **The timeout and the read cap are this capability's `MAX_RESPONSE_BYTES` and
  `_HTTP_TIMEOUT_SECONDS`**, unchanged in value, now carried on the policy and enforced
  by the shared transport instead of a local streamed read.

**The injectable seam changes shape.** `http_factory: Callable[[], httpx.Client]` is
replaced by the egress `sender`, `resolve` and `observer` seams on `OIDCClient`,
`build_oidc_router` and `build_oidc_module`. This is a breaking change to public API and
there was no version of it that was not: the old seam's type *is* an HTTP client, so
keeping it means keeping the import the markers were for.

## Consequences

**Provider calls are SSRF-checked and address-pinned for the first time.** A discovery
document that names an internal or metadata address is refused rather than fetched, and
the connection goes to the address that passed the check rather than to whatever the
name resolves to a moment later.

**`http_factory` is gone.** An application that injected one — in practice, a test —
passes `sender=` instead. The `resolve` seam is not optional for a test that uses a
hostname it does not own: left out, the name goes to real DNS, fails to resolve, and is
refused, which is a green test for the wrong reason.

**The capability has no escape-hatch budget.** Both markers were removed rather than
re-justified, and `oidc` rejoins the list of capabilities that pass the whole harness
outright. `terp-cap-oidc` drops `httpx` and declares `terp-cap-egress`, which makes ADR
0117's recorded consequence — "`httpx` becomes a dependency of exactly one
distribution" — true for the first time since it was written.

**An SSO login is now visible to the egress observer**, like every other outbound call
in the platform. That hook is where metering and egress auditing attach, and provider
traffic was the last kind of outbound call no observer could see.
