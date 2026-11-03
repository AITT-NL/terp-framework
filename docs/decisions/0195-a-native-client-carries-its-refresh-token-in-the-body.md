# 0195 — A native client carries its refresh token in the body, on routes that refuse a browser

- **Status:** Proposed (awaiting review). Built in 0.35.1: `NativeClients`, the two routes,
  the browser-provenance refusal and the reference app's opt-in, with its committed contract
  and authority baseline. The one governed escape-hatch marker decision 7 spends was agreed
  by the owner before it was added. Held by `apps/example/tests/test_native_refresh.py`,
  `test_login_wiring.py` and the authority-baseline and contract tests.
- **Date:** 2026-11-03. 0182 and 0183 are reserved for other records; 0184 to 0191 are taken,
  0192 is claimed by a proposal under review, 0193 is the site socket and 0194 the API
  contract baseline.
- **Relates:** extends [ADR 0054](0054-refresh-token-sessions.md) (one refresh-token family,
  rotated, reuse-detecting, revoked through `revoke_sessions`; this adds a second carrier and
  changes nothing about the first); keeps [ADR 0031](0031-session-management-token-revocation-and-login-lockout.md)
  (the 15-minute access token) and [ADR 0088](0088-service-principal-credentials.md) (a
  machine re-authenticates and gets no refresh token); applies
  [ADR 0148](0148-a-route-declares-its-own-posture-not-its-neighbours.md) (each route declares
  its own public posture) and [ADR 0139](0139-who-can-reach-what-is-pinned-not-merely-reportable.md)
  (the new routes arrive as a reviewed diff of the authority baseline); serves
  [ADR 0194](0194-an-apps-api-contract-is-a-committed-file.md) (an app that never opts in sees
  no change to its contract). Supersedes nothing.

---

## Context

The consumer is an app with a native mobile client and consumer accounts: a member signs in
on a phone and expects to stay signed in for weeks, while the access token lives for 15
minutes (ADR 0031).

ADR 0054 carries the refresh token in an `HttpOnly; Secure; SameSite=Strict` cookie scoped to
`/api/v1/auth`, and `/refresh` reads only that cookie. Every one of those properties is a
browser property. `HttpOnly` hides the cookie from page script; `SameSite` stops a cross-site
page from sending it. Outside a browser there is no page script and no site, so to a native
client a `Set-Cookie` is just a response header.

A native client can keep that header. Some native HTTP stacks keep a cookie store, and
others keep none unless one is configured. Where one exists it is the wrong place rather
than a missing one: it is ordinary application data, not the operating system's keychain or
keystore, which is where a credential that lives for weeks belongs. So a native client today has three ways to stay signed in, and each is worse
than the standard shape. It keeps the password on the device and logs in again every 15
minutes. It leaves a long-lived credential in a general-purpose cookie store. Or it scrapes
`Set-Cookie` into the keychain and replays a hand-built `Cookie` header, a protocol nobody
specified.

The standard shape is the OAuth 2.0 token response: the refresh token in the JSON body,
stored by the client in secure platform storage, presented in the body to refresh.

## Decision

### 1. Opt-in, with a reason, off by default

`build_login_module(..., native_clients=NativeClients(reason="..."))` turns the native routes
on. A blank reason is refused at construction, as `Policy.public_write` refuses one, and so is
`native_clients` without the refresh seams, because a native refresh is a rotation in the same
store. An app that does not declare it mounts nothing new: its routes, its contract and its
authority baseline are unchanged.

### 2. Two routes of their own

- `POST /api/v1/auth/native/login` takes the `/login` body and runs the same steps: the
  throttle, the credential check, the second factor, the same token epoch and tenant claim.
  It answers `{access_token, refresh_token, token_type}` and sets no cookie.
- `POST /api/v1/auth/native/refresh` takes `{refresh_token}` and answers the same shape with
  the rotated token.

Both are public by their own `route_policy` (ADR 0148), and `/native/login` carries the
credential rate limit `/login` carries.

The first sketch of this put a client-kind declaration on `/login` and an optional body on
`/refresh`. Routes of their own are preferred for three reasons. The browser routes stay
exactly what ADR 0054 reviewed, with no new parsing path on the endpoint every page load
calls. An app that never opts in sees no change to its contract, where a new optional field
on `LoginRequest` would turn every adopted app's contract check red on upgrade for a feature
it never asked for (ADR 0194). And "a request that presents both carriers is refused"
becomes one rule per route instead of a precedence question.

### 3. One family, one rotation, one revocation

The native routes call the same `refresh_issuer` and `refresh_rotator` seams `/login` and
`/refresh` call. A native session is a family like any other: single-use rotation, reuse
detection that revokes the whole family when a rotated token is replayed outside the grace
window, the same idle and absolute lifetimes, and the same `revoke_sessions` chokepoint for
logout, deactivation, a role change and a password reset. The carrier differs and nothing
else does. Logout is unchanged: `POST /logout` with the bearer revokes every family of the
user.

### 4. A native route refuses a browser, and the browser routes never read a body token

A request to either native route that carries an `Origin` header, any `Sec-Fetch-*` header
or the refresh cookie is refused with a typed 403 before any credential is read. A browser
attaches `Origin` to every `POST`, current browsers add `Sec-Fetch-*` headers to every request
over HTTPS, and page script can neither remove nor forge either, because they are forbidden
header names. So script running
in the app's own page, an injected payload included, cannot reach a route that hands out a
body token, and cannot turn a cookie session into one. A native client sends none of these
headers.

A hybrid app, a page inside a native shell, is the case to name. Its page usually runs at a
custom-scheme origin, cross-site to the API, so the `SameSite=Strict` cookie is never sent,
and its native HTTP bridge sends no browser headers. Such an app calls the native routes from
its native layer, keeps the refresh token in native secure storage, and hands its page only
short-lived access tokens. A page that holds the refresh token has given up exactly what the
cookie protects, and the guide says so.

The browser routes are untouched: `/refresh` reads only the cookie, as ADR 0054 has it, and
never a body.

### 5. A credential route accepts no `Idempotency-Key`

The idempotency middleware stores a completed response and replays it to a retry of the same
key before the route runs. On a route that mints a credential that is two defects: the stored
response is a live credential in the replay store for a day, and a replay hands it out again
without running the route, so the rotation that detects a stolen refresh token never sees the
reuse. The store key folds in `Authorization` and `Cookie`, and a native refresh carries
neither, so a captured request, key and body token included, would have kept yielding its
successor. The cookie routes had the same shape.

So `/login`, `/token`, `/refresh` and both native routes refuse the header with a typed 400
(`idempotency_key_not_accepted`). The middleware then stores the refusal, harmless to replay,
and never a token. A client retries one of these routes by sending it again without a key.

### 6. The grace window and logout are ADR 0054's, deliberately

The rotation grace window applies to a native session as it does to a cookie. A mobile network
loses responses, and a retry after a lost response is the benign race ADR 0054 allows for;
removing the window for native clients would sign people out on every dropped reply. The fork a
thief could make inside the window is the bound ADR 0054 already accepted, and an app that wants
none sets `REFRESH_ROTATION_GRACE_SECONDS` to 0 for every session.

A native client whose access token has expired refreshes first and then calls `/logout` with
the new bearer. A lost device is revoked through deactivation or a password reset, the
chokepoint every session shares. A `/native/logout` that takes the body token is a later
addition if a client needs one.

### 7. The token is minted to be returned once, and the client keeps it in secure storage

The `refresh_token` response field is the credential the route exists to mint, exactly as
`AccessToken.access_token` is. The `schemas_exclude_sensitive_fields` rule rightly flags a
credential-shaped field on a response, and the access token already carries the governed
marker for this case. The native response needs the same marker once more, which moves the
auth capability's `arch-allow-schemas-exclude-sensitive-fields` budget from 1 to 2. That is
the one escape this decision spends, and the owner agreed to it before it was added.

The guide tells a native client to keep the token in the operating system's keychain or
keystore and nowhere else, and to treat a 401 from `/native/refresh` as signed out.

## Two-layer enforcement

- **Runtime, fail-closed:** a browser-provenance header or the refresh cookie on a native
  route is a 403; an `Idempotency-Key` on any credential route is a 400; an invalid, expired,
  revoked or reused body token is a 401, and a reuse revokes the family, as for the cookie.
- **Construction:** a blank reason, or native clients without the refresh seams, is refused
  when the module is built.
- **Tests:** a rotated body token replayed revokes its whole family; a request carrying both
  the cookie and a body token is refused; a request with browser provenance is refused on
  both native routes; a captured refresh request resent with its key yields no successor and
  the reuse is still seen; every credential route refuses the key; an app that does not opt in
  has neither route; the reference app opts in, and its committed authority baseline and
  contract record the two routes.

No `terp.arch` rule is added: like ADR 0054, this is framework mechanics with no authored
pattern to police.

## Consequences

- A native client stays signed in with a credential kept in secure platform storage, rotated
  on every refresh and revocable through the chokepoint every other session uses.
- An app that does not opt in is byte-for-byte unchanged.
- The reference app opts in, so the routes are exercised by its suite and appear in its
  committed baseline and contract.
