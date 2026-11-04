# 0196 — A person can open, prove, recover and close their own account, behind a switch that is off

- **Status:** Proposed (awaiting review). Built in 0.36.1 in `terp-cap-users`:
  `SelfService`, the five routes of `build_accounts_module`, the sealed account tokens, the
  `identity_account_token` table that makes them single-use, and the construction refusals. Held by `tests/architecture/test_self_service_accounts.py`. Its
  guarantees are written to become the self-service capability contract in the Terp
  Standard, with black-box probes, as a later spec record.
- **Date:** 2026-11-03. 0182 and 0183 are reserved for other records and 0184 to 0193 are taken;
  0194 to 0197 are this series.
- **Relates:** extends [ADR 0013](0013-users-capability-and-identity-boundary.md) (the users
  capability is the audited write boundary over identity); applies
  [ADR 0142](0142-provisioning-an-account-is-not-admitting-it.md) (an account that exists and
  may not be used yet is inactive, and activation admits it),
  [ADR 0147](0147-a-lockout-is-a-weapon-a-backoff-is-a-control.md) (back off, never lock out),
  [ADR 0036](0036-distributed-throttle-store.md) (a store each process keeps is correct
  for one instance),
  [ADR 0128](0128-the-gate-asks-whether-the-app-would-boot-in-production.md) (a production
  refusal is answerable off the production host),
  [ADR 0150](0150-mail-leaves-through-one-declared-relay.md) (mail leaves through the declared
  relay, on the jobs seam, with the write it is about),
  [ADR 0148](0148-a-route-declares-its-own-posture-not-its-neighbours.md) (each route declares
  its own posture), [ADR 0031](0031-session-management-token-revocation-and-login-lockout.md)
  and [ADR 0054](0054-refresh-token-sessions.md) (revocation through the token epoch and the
  refresh families), [ADR 0190](0190-a-field-declares-itself-personal.md) (an address is
  personal data). Supersedes nothing.

---

## Context

The consumer is an app with consumer accounts, often reached from a native mobile client: a
member signs up on their own, proves their address, recovers a forgotten password and can
close the account from inside the app, which mobile app stores require.

The users capability has only operator operations: list, provision, get, update,
deactivate, reactivate and reset a password, each by an administrator. So every such app
writes the public half itself, and the public half is where the classic failures live: a
sign-up or reset form that says "no account with that address", a reset token that works
twice or never expires, a link that carries the token into a server log, a public route
nothing throttles, and an account deletion a stolen access token can perform.

## Decision

### 1. Off by default, on with a reason, refused when half-configured

`build_accounts_module(SelfService(reason=..., users=..., throttle_store=..., link_base=...))`
mounts the routes, under `/api/v1/accounts`. An app that does not build it has none of them.
Building it is refused:

- with a blank reason, as `Policy.public_write` refuses one;
- before `configure_mail` was called, because every route that sends mail would fail at its
  first send instead;
- in production with a `link_base` that is not `https`. The token rides the link's
  fragment, which a browser never sends, but a page loaded over plaintext can be rewritten
  in transit to read it. As for an OIDC provider, the verdict is an environment-independent
  `production_problems()`, and outside production the same state is logged as one a
  production boot refuses (ADR 0128).

The module declares the `MAIL_SEND` job, so a boot whose job catalog lacks it is refused
(ADR 0150).

A throttle store that is not shared is accepted, and building the module says so in a
warning. That is the platform's own stance for its throttle (ADR 0036): a store each process
keeps is correct for one instance, and refusing it would break something that is not wrong.
It would also make a shared backend a prerequisite of every production app that offers
sign-up, which pushes the app towards writing sign-up itself. An app that runs several
instances declares a store marked shared, and its backoff is then global.

### 2. An account exists only once its address is proven

`POST /sign-up` takes an address and a password, checks the password policy, and creates
no account. It mails the address a sealed token carrying the address and the password's
**hash**, never the password, and records the token's digest in an
`identity_account_token` row. That audited row is the write the mail is queued on, so with
the durable outbox the mail commits with it (ADR 0150); it holds no address. `POST /verify`
redeems the token and only then creates the account, at the viewer rank, the lowest of the
platform's tiers and the default of every provisioned account. An app that holds new accounts for approval declares it, and the account
is created inactive: ADR 0142's state, admitted by an administrator's activation.

So an unproven address leaves no account and no personal data, there is no "pending" state
to clean up, and the token is single-use twice over: its row is stamped when it is redeemed,
and once the account exists, a second token for the same address is refused too.

### 3. A request about an address answers the same way whether or not an account exists

`POST /sign-up` and `POST /password-reset` answer `202` with the same body in every case. A
sign-up for an address that already has an account mails that address a notice instead of a
token; a reset for an address with no active, password-holding account mails nothing. Both
paths do the same costly work and the same write: the password is hashed, a token is sealed
and its row is recorded in every case, so neither the time an answer takes nor the table tells
the cases apart. With the durable outbox,
which production runs, the remaining difference is one queued row.

### 4. Tokens are sealed, short-lived, single-use, and never reach a server

A token is sealed with its own key derived from `SECRET_KEY` (a `SealingDomain`), so its
content cannot be read or forged without the app's secret, and it rotates like every sealed
value. It carries its purpose and its expiry: 24 hours for a sign-up and 1 hour for a reset by
default, each capped. Redeeming one needs both its seal and its unused, unexpired row, and
spends the row. A reset token is also bound to the account's token epoch, so it dies with
any revocation that comes after it was mailed. The link puts the token
in the URL **fragment**, which a browser never sends, so it cannot reach a server log, a
proxy or a `Referer` header.

### 5. Public routes back off; they never lock anyone out

Every route takes the auth capability's backoff (ADR 0147) on a store the app supplies: the
two requests by address and caller, each request counting, so a flood of mail to one address
slows down; the two redemptions by caller, a failed redemption counting.

### 6. Closing an account takes the password again, and ends every session

`POST /me/close` is the one authenticated route, open to any signed-in rank. It requires the
current password, so a stolen access token cannot close the account, and refuses an account
that signs in only through a provider, which an administrator closes instead. It refuses the
last active administrator. Then it revokes every session, through the token epoch and the
refresh families, and does what the app declared: `AccountDeletion.SCRUB` (the default)
deactivates the account and replaces its address and password, so the row stays for
references and the audit trail while the person's data goes; `AccountDeletion.REMOVE`
deletes the row.

### 7. Every step is audited, and the address never is

Each write goes through the users capability's audited boundary. The address is a
`Personal` field, so the audit trail, the log and the job payload's log line withhold it.

## Guarantees (contract-ready)

Stated for any stack that offers self-service accounts, each with the reference runtime
control. They are the self-service entry of the capability contracts the Terp Standard is to
gain, where each will also name a black-box probe.

| Guarantee | Reference control |
|---|---|
| A request about an address answers identically whether or not an account exists for it | `AccountsService.request_sign_up`, `request_password_reset` |
| An account is created only by redeeming a token sent to its address | `AccountsService.verify_sign_up` |
| A verification or reset token works once | `AccountTokenService.live` and `consume`; the account's existence; the token epoch |
| A token expires, and its expiry is inside the sealed token | `open_account_token` |
| A token cannot be read or forged without the app's secret, and never reaches a server in a URL | `SealingDomain("users.account")`; the fragment link |
| Repeated public requests back off and never lock out | `LoginThrottle` on the declared store |
| A self-registered account starts at the viewer rank, and an app that approves accounts creates it inactive | `UsersService.create_verified` |
| Closing an account requires the password and revokes every session | `UsersService.close_account` |
| Half-configured, the capability refuses to be built | `SelfService.__post_init__`, `build_accounts_module` |

## Consequences

- A consumer app gets sign-up, proof of address, recovery and closing in one declaration,
  with the failures above designed out rather than left to each app.
- Mail copy ships in English as the capability's default, and an app passes its own text
  through `AccountMessages`; localized mail per recipient is a later addition.
- The routes are an API. The pages a link opens are the app's: they read the token from the
  fragment and post it.
- No catalog rule is added. Like ADR 0054, this is capability mechanics with no authored
  pattern to police; its guarantees go to the spec as a capability contract instead.
