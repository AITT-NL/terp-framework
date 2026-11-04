# 0196 — A person can open, prove, recover and close their own account, behind a switch that is off

- **Status:** Proposed (awaiting review). Built in 0.36.1 in `terp-cap-users`:
  `SelfService`, the five routes of `build_accounts_module`, the sealed account tokens, the
  `identity_account_token` table that makes them single-use, and the construction refusals.
  Held by `tests/architecture/test_self_service_accounts.py`, and by the example app's
  evidence for the Terp Standard's `self-service-accounts` runtime security cases
  (terp-spec 0.43.0), `apps/example/tests/test_runtime_security_cases.py`.
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

### 2. An account exists only once its address is proven, with a password its owner chooses

`POST /sign-up` takes an address and nothing else, and creates no account. It mails the
address a sealed token carrying the address, and records the token's digest in an
`identity_account_token` row. That audited row is the write the mail is queued on: the mail
is queued from inside the row's own write unit, so with the durable outbox the two commit, or
roll back, together (ADR 0150). Queued before it, the mail would be an enqueue of its own,
committed first, and a row that then failed to write would leave a mail whose link nothing
redeems. The row holds no address and nothing else that differs between one address and
another. `POST /verify` takes the token and the password the account opens
with. It checks the token first and the password policy second, so a guess at a token is
always a failed redemption and never a policy answer, and a password the policy refuses
leaves the token usable for a better one. Only then does it create the account, at the viewer
rank, the lowest of the platform's tiers and the default of every provisioned account. An app
that holds new accounts for approval declares it, and the account is created inactive: ADR
0142's state, admitted by an administrator's activation.

The password is chosen at redemption, by whoever reads the mail, rather than sent with the
request. An earlier draft took it with the request and sealed its hash into the token, which
let anyone who asked choose the password of an account the mailbox's owner then opened by
following the link: an account its owner believes is theirs, with a password someone else
knows.

So an unproven address leaves no account and no personal data, there is no "pending" state
to clean up, and the token is single-use twice over: its row is stamped when it is redeemed,
and once the account exists, a second token for the same address is refused too. Addresses
are compared without regard to case, so two spellings of one mailbox are one address and
never two accounts: a self-service account is stored with its address lower-cased, and a
sign-in reaches it in any spelling, because the identity capability's lookup tries the
address as written and then lower-cased. An account provisioned with capitals keeps signing
in as it was written.

### 3. A request about an address answers the same way, and does the same work, whether or not an account exists

`POST /sign-up` and `POST /password-reset` answer `202` with the same body and the same
headers in every case, and every request sends its address exactly one message. A sign-up
for an address that already has an account mails a notice that it has one instead of a link;
a reset for an address with no active account that signs in with a password mails a notice
that there is no password to reset. In every case a token is sealed, its row is recorded and
one message is queued, so neither the answer, nor the work, nor the table tells the cases
apart, and a relay that is down fails every request alike instead of only the ones that
would have carried a link. Only the message's words differ, and they go to the address, the
one party entitled to know.

An earlier draft mailed nothing for a reset it could not honour. On the in-process job queue,
which sends inside the request, that made a relay outage and the time an answer took tell an
account from no account; the durable outbox narrowed it to one queued row, and nothing made
production run the outbox. One message for every request removes the difference instead of
depending on which queue an app runs.

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
slows down; the two redemptions by caller, a failed redemption counting; and closing by
account and caller, a wrong password counting.

The throttle also keeps a backstop on each identifier across every source. For a request
about an address that is the address, so many callers together are slowed on one mailbox.
A redemption names no address, so its identifier is the caller itself: one identifier for
every redemption would be one counter that everyone spends, and enough bad tokens from
anywhere would hold up everyone's good one, a lockout by another name. Per caller, bad
tokens slow only the caller that sent them.

### 6. Closing an account takes the password again, and ends every session

`POST /me/close` is the one authenticated route, open to any signed-in rank. It requires the
current password, so a stolen access token cannot close the account, and refuses an account
that signs in only through a provider, which an administrator closes instead. It refuses the
last active administrator. Then it revokes every session, through the token epoch and the
refresh families, and does what the app declared, in one audited write:
`AccountDeletion.SCRUB` (the default) deactivates the account and replaces its address and
password, so the row stays for references and the audit trail while the person's data goes;
`AccountDeletion.REMOVE` deletes the row.

A reference to a user declared `RESTRICT` or `NO_ACTION`, or declaring nothing, refuses that
delete (ADR 0133), so what such a reference does when an account goes is the app's decision,
and it is asked for when the module is built. Building it with `REMOVE` is refused while the
metadata holds a reference that would refuse the delete, naming each one (table, column,
action) and both remedies: declare `CASCADE` or `SET NULL` on it to let the row go, or declare
`SCRUB` to keep the row. What the build cannot see is a reference the app's metadata does not
hold: a table another program owns, or a model imported after the build. A close meets that
one at run time. The delete's write has then rolled back, so nothing has changed, and the
account is scrubbed instead, with a warning that names the cause and both remedies. Closing
never stops halfway, the person's data goes either way, and the person is not left with an
account they asked to close because of a schema choice they cannot see; refusing the close
with a 409 was the alternative, and it would have kept a person's account open over an
operator's oversight.

### 7. Every step is audited, and the address never is

Each write goes through the users capability's audited boundary. The address is a
`Personal` field, so the audit trail, the log and the job payload's log line withhold it.
The token table holds a token's digest and never the token, so a reader of the database
cannot recover one from it.

The queued message was the exception. The outbox row that carries a mail held its recipient
and its text, a link's token included, in plaintext, and the outbox keeps dispatched rows. A
token there stays usable until it is redeemed or expires, within the hour for a reset by
default, so a reader of the database inside that window could have redeemed it. [ADR
0199](0199-a-queued-mail-is-sealed-at-rest.md) (proposed 2026-11-04) closes it: the queued
message is sealed at rest, and `terp secrets reseal` reaches it inside the outbox's JSON
payload.

## Guarantees (contract-ready)

Stated for any stack that offers self-service accounts, each with the reference runtime
control. The Terp Standard states them as its `self-service-accounts` runtime security cases
(terp-spec 0.43.0), which name the probe and its controls.

| Guarantee | Reference control |
|---|---|
| A request about an address answers identically, and sends the address exactly one message, whether or not an account exists for it | `AccountsService.request_sign_up`, `request_password_reset` |
| An account is created only by redeeming a token sent to its address, with the password given at redemption | `AccountsService.verify_sign_up` |
| A verification or reset token works once | `AccountTokenService.live` and `consume`; the account's existence; the token epoch |
| A token expires, and its expiry is inside the sealed token | `open_account_token` |
| A token cannot be read or forged without the app's secret, and never reaches a server in a URL | `SealingDomain("users.account")`; the fragment link |
| Repeated public requests back off per caller and never lock out | `LoginThrottle` on the declared store; the per-caller redemption counter |
| A self-registered account starts at the viewer rank, and an app that approves accounts creates it inactive | `UsersService.create_verified` |
| Closing an account requires the password and revokes every session | `UsersService.close_account` |
| Half-configured, the capability refuses to be built, `REMOVE` included while a reference it can see would refuse the delete | `SelfService.__post_init__`, `build_accounts_module` |

## Consequences

- A consumer app gets sign-up, proof of address, recovery and closing in one declaration,
  with the failures above designed out rather than left to each app.
- Mail copy ships in English as the capability's default, and an app passes its own text
  through `AccountMessages`; localized mail per recipient is a later addition.
- The routes are an API. The pages a link opens are the app's: they read the token from the
  fragment and post it.
- No catalog rule is added. Like ADR 0054, this is capability mechanics with no authored
  pattern to police; its guarantees went to the spec as runtime security cases instead.
