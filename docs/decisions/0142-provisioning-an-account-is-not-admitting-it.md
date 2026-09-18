# 0142 — Provisioning an account is not admitting it

- **Status:** Accepted and implemented. `FederatedIdentityService` takes
  `provisioned_active: bool = True`; under `False` a first SSO login writes the user row
  and its federated link and still returns `None`, so the account waits for an
  administrator exactly as a deactivated one does. Held by
  `apps/example/tests/test_federated_identity.py`.
- **Date:** 2026-09-17
- **Relates:** [ADR 0058](0058-pluggable-sso-oidc.md)
  (the provisioning seam this completes),
  [ADR 0031](0031-session-management-token-revocation-and-login-lockout.md)
  (the `is_active` re-check this reuses)

## Context

JIT provisioning lets an application say *whether* it provisions
(`allow_provisioning`), *whose* identities qualify (`allowed_email_domains` /
`provision_allowed`), and *at what rank* the account lands (`provisioned_rank`). All
three are admission rules evaluated once, at the moment of the first login, and the
account they admit is live the instant it exists.

The gap is that there is no fourth answer: "let them ask, but not in yet." The ordinary
shape for an internal tool is that anyone the directory vouches for may request an
account and a human decides whether it opens. Every part of that is expressible here
except the deciding.

`provisioned_rank` looks like the escape and is not, because **the lowest rank is not
"no access"**. A rung is a floor that modules read, so the bottom of the ladder is
already whatever an application's `role:viewer` routes chose to expose — which in a
data-heavy application is routinely the whole read surface. An application can pass a
raw integer below the lowest named rung, since the parameter is an `int`; it then has a
principal with a rank no access model declares, no screen that explains the state, and a
user looking at an application that silently does nothing. A mechanism with no story.

The consequence is that the admission rule has to carry weight it was not shaped for.
A domain allowlist is a statement about a *directory*, not about a person, so
"everyone in these domains may read everything at the viewer floor" becomes the
deployment's access policy by composition rather than by choice — and it becomes that
policy on the day SSO is switched on, which is the day nobody is looking for it.

## Decision

`FederatedIdentityService(provisioned_active=False)` provisions into the state the
platform already has for an account that exists and may not be used.

Two properties make it a whole answer rather than a flag:

**The rows are written and the login is still refused.** The user and the link are
created — so the request is recorded, auditable, and visible in the admin surface — and
`resolve_or_provision` returns `None` anyway. Returning the user would have undone the
feature: the `is_active` check guards the *linked* path, which a first login never
reaches, so handing the row back would mint a session for an account that is inactive in
the database, the one state a caller has no way to notice because it receives a
principal like any other.

**Activation is the only act that admits them.** Every later attempt takes the linked
path and is refused by the same `is_active` check that holds a deactivated account. No
second state is invented, no "pending" column is added, and the administrator's control
is the one they already know.

The default stays `True`, and a test pins it: a flipped default is a silent lockout of
every deployment that never asked for this.

## Consequences

An application that wants approval-gated self-service now declares it in one keyword
rather than choosing between open registration and no SSO at all. The refusal is
deliberately indistinguishable from every other refusal in this service, so it cannot be
used to enumerate which identities are known.

What this does **not** do is watch the directory. An account admitted once stays
admitted until someone deactivates it; membership that changes at the source is not
noticed here. That remains the argument for a reconciliation capability, and this ADR
is not it.
