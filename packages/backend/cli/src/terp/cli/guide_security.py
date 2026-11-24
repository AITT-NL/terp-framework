"""The ``terp guide security`` topic: the security declaration, refused at production boot."""

from __future__ import annotations

TOPIC = """\
The security declaration (SecurityConfig, refused at production boot)

- ONE declaration, wired on the control plane, read by create_app:
      from terp.core import ControlPlane, CorsPolicy, RateLimit, SecurityConfig
      control_plane = ControlPlane(security=SecurityConfig(
          cors=CorsPolicy.allow(["https://app.example.com"]),
          trusted_proxy_hops=1,
      ))
- FOUR of its states refuse a production boot (SecurityConfig.production_problems();
  create_app raises BootError "insecure production security config"). Each has exactly
  one declaration that answers it:
    1. CORS unset            -> CorsPolicy.from_environment(), .allow([...]) or .disabled(reason=...)
    2. CORS allowing '*'     -> name the origins; a wildcard with credentials is no origin check
    3. rate_limit disabled   -> RateLimit(requests=..., window_seconds=...)
    4. an override disabled  -> an override may LOWER or RAISE a limit, never remove it
  Declining is a full answer and must be said out loud: CorsPolicy.disabled(reason=...)
  is the same-origin deployment's answer, and the reason is the point of it.
  Which browser origins may call the API is a fact of an environment, not of the source:
  CorsPolicy.from_environment() takes the allowlist from BACKEND_CORS_ORIGINS when the app
  is composed (ADR 0210). An environment that names none serves no cross-origin access; an
  entry that is not an origin (a path, a trailing slash, '*') refuses the boot. Without
  that declaration the variable opens nothing, and a boot that finds it set says so.
  `terp verify --only production-readiness` asks these before you ship, so the refusal
  arrives in the gate rather than at the deploy.
- rate_limit_overrides is a PER-PREFIX BUCKET, not a shared counter (ADR 0115):
      SecurityConfig(rate_limit_overrides={"/api/v1/auth": RateLimit.for_credentials()})
  Longest prefix wins; everything unmatched keeps rate_limit. Separate buckets on
  purpose - a credential endpoint and an asset read share a process, not a counter, so
  exhausting one family must not 429 the other. The shape mirrors the per-mount
  max_request_bytes map: one way to scope a limit to a path, not two.
- trusted_proxy_hops: NAME THE PROXY YOU ACTUALLY RUN BEHIND. It defaults to 0, meaning
  the direct TCP peer identifies the caller and X-Forwarded-For is ignored as
  attacker-supplied. Behind one reverse proxy (the shipped nginx profile) set 1, or every
  caller collapses onto the proxy's address and your per-caller controls - the rate limit,
  the OIDC callback throttle - stop being per-caller. The symptom is intermittent 429s
  that look like a traffic spike. Nothing refuses this at boot, because 0 is correct for a
  directly-exposed app: it is a deployment fact only you know.
  Count only the proxies your own code puts in front: a deploy tool that serves the app
  through an edge of its own (the Terp runner) sets TERP_EDGE_HOPS=1, and create_app adds
  that hop to your count (ADR 0220). Never count the edge here as well: one hop too many
  reads past the edge's entry, where there is either none (every caller shares one bucket
  again) or one the caller wrote. TERP_EDGE_HOPS is the deploy tool's, set only on a unit
  reached through its edge alone, so environment.schema.json may not declare it, and a
  value other than 0 or 1 refuses the boot.
- expose_api_docs is a deliberate opt-in, OFF in production: /docs, /redoc and
  /openapi.json are hidden there because a production API's full schema is not public
  information. Development always serves them, and `terp openapi` exports the document
  either way - so turning this on is a choice to publish, not a way to get the file.
  Commit that file instead: `openapi.json` is the app's API contract, the one a mobile
  app or a site in another repository pins, and `terp verify --only api-contract` holds
  it to the API the app serves, naming every change to its shape, the ones that break a
  client first (ADR 0194). Who may call a route is not in it: authz-surface pins that.
- headers ships a safe SecurityHeaders set; max_request_bytes (1 MiB) is the body cap and
  is per-mount overridable (ADR 0067); request_id_header names the correlation header
  ("X-Request-ID") echoed on every response.
- A NATIVE MOBILE CLIENT stays signed in through its own routes, opt-in with a reason
  (ADR 0195): build_login_module(..., native_clients=NativeClients(reason="...")) mounts
  POST /api/v1/auth/native/login, /native/refresh and /native/logout. The first two answer
  the refresh token in the JSON body and run the same rotation, reuse detection and
  revocation as the cookie, its rotation grace window included; /native/logout takes the
  token and revokes its whole family without minting a successor. The client keeps that
  token in the OS keychain or keystore and nowhere else, and treats a 401 from
  /native/refresh as signed out. All three refuse any request with browser provenance
  (Origin, any Sec-Fetch-* header, the refresh cookie) with 403 native_client_only before
  the body is validated, so a browser stays on /login, /refresh and /logout. A HYBRID app
  (a page inside a native shell) calls them from its native layer and hands its page only
  access tokens: a page that holds the refresh token has given up what the cookie
  protects. No route that mints a credential (/login, /token, /refresh, /native/login,
  /native/refresh) accepts an Idempotency-Key; retry without one.
- No terp.arch check applies - there is no module code shape to police. Enforcement is
  the create_app production fail-fast plus the production-readiness verify lane.
"""
