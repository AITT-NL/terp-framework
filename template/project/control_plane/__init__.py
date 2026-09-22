"""The single authority surface — declared once, validated at boot."""

from __future__ import annotations

from terp.core import (
    AuditPolicy,
    ControlPlane,
    CorsPolicy,
    PermissionModel,
    RateLimit,
    SecurityConfig,
    get_settings,
)

from control_plane.operations import operation_catalog

#: Requests a minute to the credential endpoints outside production.
#:
#: `/api/v1/auth/login` and `/token` sit in their own bucket behind
#: `RateLimit.credentials()` — thirty a minute (ADR 0138, keyed by route in ADR 0140).
#: That number is a cost control and it is right for production: both routes run a
#: memory-hard Argon2 verification on the miss path too, which makes them the cheapest
#: place on the whole surface to spend the server's CPU.
#:
#: It is the wrong number for this project's own conformance suite. `@terpjs/conformance`
#: signs in through the real login screen, so a suite grows one real `POST /auth/login`
#: per spec — and thirty is reached long before a real app's suite is, from the single
#: address a CI runner has. The failure does not read as a rate limit: whichever spec
#: crosses the line fails on a missing element, in a module that has nothing to do with
#: authentication, and a different one each run.
#:
#: The app's general `rate_limit` does not cover this. A path matching an override is
#: counted in that override's OWN bucket (ADR 0115) — which is the point, so exhausting
#: one family cannot 429 another — so the credential family needs its own number here.
NON_PRODUCTION_CREDENTIAL_RATE_LIMIT = RateLimit(requests=1_000, window_seconds=60)

control_plane = ControlPlane(
    permissions=PermissionModel.default(),
    security=SecurityConfig(
        cors=CorsPolicy.disabled(reason="server-to-server"),
        # One hop IN PRODUCTION, because that is the stack that has one:
        # `docker-compose.prod.yml` puts the `web` container in front and its nginx
        # appends the caller to `X-Forwarded-For`, and `api` publishes no port of its
        # own, so the proxy is the only way in. Leaving this at the platform's 0 there
        # would resolve every caller to the proxy's address, making the rate limit and
        # every other per-caller control one shared bucket for the whole deployment —
        # symptom: intermittent 429s under ordinary load, which reads as a limit set too
        # low rather than as this line.
        #
        # Zero everywhere else, because the DEV stack is a different shape: it publishes
        # `api` directly on `${API_PORT}` *as well as* running `web`. A request can
        # therefore arrive without passing any proxy, and a trusted hop would let that
        # caller put whatever they like in `X-Forwarded-For` — not merely stepping out of
        # their own rate-limit bucket but attributing their requests to somebody else's
        # address, which poisons the login lockout and the OIDC callback throttle too.
        # Zero is the platform default precisely because an undeclared forwarding header
        # is attacker-supplied.
        #
        # Change the production side if you put another proxy (a load balancer, an
        # ingress, a CDN) in front of `web`; that is a count of hops, not a boolean.
        trusted_proxy_hops=1 if get_settings().is_production else 0,
        # Production declares no override, so the auth mount keeps whatever the platform
        # decides `RateLimit.credentials()` should be. Outside it, the credential family
        # gets a bucket a conformance suite can finish inside.
        #
        # Keyed per ROUTE rather than on the `/api/v1/auth` mount, deliberately. A mount
        # key would cover `/refresh` too, and `/refresh` is exempt on purpose (ADR 0140):
        # it reads a high-entropy cookie and rotates it for the price of a query, and
        # `TerpProvider` posts to it on every mount to restore a session, so its volume
        # tracks page loads rather than login attempts. Naming the two credential routes
        # leaves it on the application's general limit, where it belongs.
        rate_limit_overrides=(
            ()
            if get_settings().is_production
            else (
                ("/api/v1/auth/login", NON_PRODUCTION_CREDENTIAL_RATE_LIMIT),
                ("/api/v1/auth/token", NON_PRODUCTION_CREDENTIAL_RATE_LIMIT),
            )
        ),
    ),
    audit=AuditPolicy.default(),
    # Every route declares the operation it performs (ADR 0102); this is what
    # those declarations are checked against at boot.
    operations=operation_catalog,
)
