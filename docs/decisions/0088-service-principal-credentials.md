# 0088 — Service-principal credentials: a machine is a subject kind, not a special user

- **Status:** Accepted
- **Relates to:** [0004](0004-authentication-capability.md),
  [0012](0012-role-ranks.md), [0013](0013-permission-grants.md),
  [0016](0016-audit-capability.md), [0022](0022-identity-capability.md),
  [0031](0031-session-revocation.md), [0054](0054-oidc-capability.md),
  [0058](0058-escape-hatch-budget.md), [0076](0076-write-chokepoint.md),
  [0084](0084-runtime-applicability.md)

## Context

Terp had exactly three ways to obtain a token, and all three end at a human:
`POST /login` (email + password), `POST /refresh`, and the OIDC callback. Nothing
in the platform could authenticate a *program*.

That gap is not neutral, because the work still has to get done. An integration —
a nightly sync, a webhook consumer, a deployment job — needs credentials, so
somebody creates an account for it. The path of least resistance shapes what that
account looks like:

- It is a **user row with a fake email**, because that is the only subject the
  platform knows how to authenticate.
- It gets **admin**, because nobody wants the 3 a.m. page when the job hits a
  permission it turns out to need, and there is no cheap way to find out which
  permissions those are up front.
- Its password is **shared and permanent**, because rotating it means editing a
  secret store and a scheduler at the same time, and because no mechanism ever
  makes anyone renew it.
- It is **indistinguishable in the audit log** from the person it is named after.

We watched exactly this happen while building fast-sync: the engine authenticated
as a human operator and, because a per-module grant would have had to be worked
out by hand, that operator was an administrator. The platform did not force this;
it simply offered nothing else.

The temptation is architectural, so the fix has to be too. It is not enough to
document "don't do that" — the sanctioned path has to be *easier* than the wrong
one, or it will not be taken.

## Decision

A machine principal is a **new subject kind flowing through the existing
authorization pipeline**, not a second authorization path.

1. **The subject kind is signed into the token.** `SubjectKind` (`user` /
   `service`) is a claim minted by `create_access_token` and read back by
   `decode_access_token`. It is *signed* rather than *inferred* ("look the id up
   in users, then in service accounts") because inference makes a subject present
   in both tables resolve by lookup order rather than by what the credential
   actually is. A **missing** `kind` reads as `user`, so no token in flight is
   invalidated by the deploy that introduces this. An **unknown** `kind` is
   rejected, never coerced to a default — a build that does not understand a
   credential must not treat it as the subject type with the broadest reach.

2. **`ServiceAccount` lives in the identity capability**, alongside `User`, and is
   deliberately shaped like it where it matters: a role rank, an `is_active` flag,
   and a `token_version` epoch. That shape is the point — machines are then
   authorized and revoked by *the same code* that handles people, rather than by a
   parallel implementation that will drift. It carries two things a user does not:
   a `client_id` / `hashed_secret` pair, and an `expires_at`.

3. **Authentication is client credentials at `POST /token`**, in the auth
   capability, mirroring the existing split (identity owns the store and the
   verification; auth owns the route and the mint). The route mounts only when the
   app wires the seam, so nothing changes for apps that do not want machine
   credentials.

4. **Authorization ignores the kind entirely.** `Principal.kind` is carried so
   audit and app code can *tell*, and so an app can explicitly refuse one kind at a
   specific route — but the guard, the role ladder, the permission grants and the
   revocation contract are byte-for-byte the ones users get. A separate
   authorization path for machines is precisely how machines end up with more
   authority than intended.

5. **Provisioning is a CLI command, `terp service-account create`,** which prints
   the client id and the secret once. `--role` is *required*: the whole purpose is
   that an integration's authority is chosen rather than inherited. Neither the
   client id nor the secret is an input, so a credential can never be provisioned
   with a value somebody typed. `--expires-in-days` defaults to 365 rather than to
   "never".

## Consequences

- **Expiry is a first-class property of a credential.** A machine credential
  outlives the ticket that justified it and the person who created it; an end date
  it must be renewed past is the only thing that reliably forces a second look. A
  non-expiring credential remains possible, but only by asking for it in writing.
- **The secret is write-once.** Only its hash is stored, so a leaked database does
  not hand over working credentials, and there is no command to read a secret back
  — a lost secret is re-provisioned, not recovered.
- **An unknown client id costs the same as a wrong secret.** `authenticate_client`
  burns a dummy verification on the unknown / inactive / expired branches, so the
  endpoint does not become a client-id oracle.
- **The machine path is half-wireable, so it is refused at construction.**
  Supplying a client authenticator without a service token-version resolver would
  mint machine tokens at a stale epoch: the credential would work exactly once, in
  the mint response, and fail forever after. That is a configuration mistake that
  presents as an intermittent runtime bug, so it fails at boot instead.
- **No throttle on `POST /token`, deliberately.** The per-account lockout that
  protects `/login` would, on this endpoint, let anyone who learns a client id take
  an integration offline at will. The secret is 256 bits of machine-generated
  entropy rather than something a person chose, so the guessing attack the lockout
  exists to stop does not apply.
- **No refresh cookie on the machine path, deliberately.** A refresh token is a
  workaround for a human not being available to re-enter a password. A machine
  holds a durable secret and simply re-authenticates.
- **Provisioning, use and revocation are audited** through the ordinary
  `BaseService` write chokepoint (ADR 0076). This mattered enough to change the
  design: the first implementation wrote to the session directly and would have
  needed an audit escape hatch, which was the signal that it was modelled wrong. A
  standing grant of authority to something that cannot be asked what it did is
  exactly the thing whose lifecycle needs a record.

## Alternatives considered

- **A `is_service` flag on `User`.** Cheapest to build, and it is what apps do by
  hand today. Rejected: it puts machines in the table whose write paths assume a
  person (password policy, password reset, email uniqueness, self-service
  endpoints), and it gives a machine credential the exact affordances — a
  resettable password, a login form — that make it hard to reason about.
- **Inferring the subject type at validation time.** Rejected as above: correctness
  would depend on lookup order between two tables.
- **A full OAuth 2.0 client-credentials grant** (scopes, client registration,
  introspection). Rejected for now: Terp already has a role ladder and permission
  grants, and a second, parallel authority vocabulary is worse than a smaller
  surface. `POST /token` deliberately borrows the shape without the machinery.
- **mTLS or signed-request credentials.** Stronger, and not ruled out later, but
  they push a certificate lifecycle onto every deployment. The bar this ADR has to
  clear is "easier than logging in as an admin", and a bearer secret clears it.
