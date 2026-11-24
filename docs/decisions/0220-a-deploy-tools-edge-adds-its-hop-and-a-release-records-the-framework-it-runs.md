# 0220 — A deploy tool's edge adds its hop, and a release records the framework it runs

- **Status:** Proposed on 2026-11-24. Built in 0.45.0. Held by
  `tests/architecture/test_edge_hops.py` (the setting and its refusals, the process that does not
  start, the count `create_app` serves on, the boot's line and the platform-owned name),
  `test_release_sign.py` (the record and the lock that pins no single `terp-core`) and
  `test_prod_profile.py` (the platform-owned names).
- **Date:** 2026-11-24.
- **Relates:** amends [ADR 0187](0187-in-the-generated-state-the-framework-renders-the-build-files.md)
  decision 6: `sign` records `inputs.framework`. Follows
  [ADR 0202](0202-an-app-may-be-api-only.md),
  whose template counts the app's own proxies, and
  [ADR 0210](0210-the-browser-origins-an-api-allows-are-each-environments-own.md), whose origins
  are a value of the environment resolved when the app is composed.
  [ADR 0216](0216-the-release-manifest-lists-every-migration-history-its-image-runs.md) added a
  manifest field without a new `schemaVersion`, as this does. The request is the
  managed-deployment design's (its section 11.42, the runner's edge proxy, and TL-6).

## Context

`SecurityConfig.trusted_proxy_hops` counts the proxies an app puts in front of its api in its own
code. The template's count is one in production where a web unit's nginx appends the caller to
`X-Forwarded-For`, and none for an api-only app, which nothing in its profile proxies (ADR 0202).

A runner that serves an environment through a TLS edge of its own, a reverse proxy on the host,
adds one hop in front of whichever unit a route reaches. The edge sets `X-Forwarded-For` to the
address it was called from and discards what the caller sent. The app's source cannot know of
that hop: one image runs behind the edge on one host and is published directly on another. With
the app's own count alone, every caller resolves to the address the last hop sees, the edge's or
the container network's gateway, and the rate limit, the login lockout and the OIDC callback
throttle become one shared bucket for the whole deployment. Where the app counts its web unit's
nginx, `ClientIpMiddleware`'s warning about an undeclared proxy does not fire, because the app
declares a count; it is just one short.

The runner also has to know whether the app it deploys would read the edge's hop at all. An app
on an earlier framework ignores any such variable and serves on its own count. The manifest
records the toolchain that gated and signed the release, `sign` being the operator's newest, but
not the framework the release runs.

## Decision

1. **`TERP_EDGE_HOPS` is a setting**: `0` or `1`, unset (or empty) meaning `0`. It is the deploy
   tool's to set, on the units it serves through its edge. Any other value (`2`, `-1`, `01`,
   `1.0`, `true`; surrounding whitespace aside) refuses the settings, and with them the
   process, at the import of `terp.core`. The refusal says what the variable is and that the
   app's own proxies are counted in `SecurityConfig.trusted_proxy_hops`. One is the only hop an
   edge adds, because it replaces whatever arrived in front of it. A larger count reads past the
   edge's entry, where there is either none, so every caller falls back to the direct peer and
   shares one bucket again, or, where something appends instead, an entry the caller wrote.
   Neither is a real deployment's count, so the bound is part of the control. A deploy tool that
   needs another value raises it in a framework change that says why.

   **It is set only on a unit reached through the edge alone.** On a unit a caller can reach
   directly, the hop would be trusted for an `X-Forwarded-For` entry that caller wrote. This
   rule belongs to the deploy tool, and the framework cannot check it: the app does not know
   how it is reached. The runner keeps it by publishing a served unit's port on the host's
   loopback, for its edge alone.
2. **`create_app` adds it to the declared count**, in the step that resolves the control plane
   from the settings, before any boot check, beside `BACKEND_CORS_ORIGINS` and
   `JOB_SYSTEM_ACTOR_ID`. `ClientIpMiddleware`, and every per-caller control built on
   `client_ip`, serve on the sum, and `app.state.terp_control_plane` carries it. It is added
   whatever the source declares: no declaration takes the edge's hop back. Where it is not 0 the
   boot says once, at INFO, that it added the hop and which entry from the right is the caller,
   because the count served is then not the one in the source.
3. **The name is platform-owned.** `environment.schema.json` may not declare it, and
   `terp env` refuses to, as with `SECRET_KEY` and the other names the platform sets. One owner
   per variable: an app that could set the edge's hop itself would have a second
   way to declare its proxies, and one a deploy tool also writes. The template's control plane,
   its README, `terp guide security` and the deployment guide each say the same thing: count
   only the app's own proxies, never a deploy tool's edge.
4. **`sign` records `inputs.framework`**: `{"terpCore": "<version>"}`, the `terp-core` the
   commit's `uv.lock` pins. That is what the backend image runs, since the comparison holds the
   image's installed packages to the lock. It is recorded without a new `schemaVersion`. A lock
   that pins no single `terp-core` is refused, as one that pins no single `terp-cli` and
   `terp-arch` is: the framework the release runs would be unknown. A deploy tool reads the
   field to know what the app's runtime does. The runner refuses a release it would route
   through its edge if the manifest records a `terp-core` before 0.45.0, or records none.

## Consequences

- Nothing changes for an app served without a deploy tool's edge: the variable is unset, the
  count is the declared one, and nothing new is logged.
- A manifest carries `inputs.framework` from this release's `sign` on, whatever the app pins.
  A reader treats a manifest without it as one signed before the field existed, and so as one
  whose framework is not known.
- `terp inspect control-plane` still reports the count the source declares. The edge's hop is
  a value of an environment, as the origins `CorsPolicy.from_environment()` reads are.
- 0.45.0 is the first `terp-core` that reads the variable, and the version a deploy tool's floor
  names.

## Not done

- A compose `environment:` block that sets `TERP_EDGE_HOPS` in an app's own production profile
  (`"build": "own"`) is not refused by the framework. The generator never writes it, and the
  runner refuses the name in any release it deploys.
- `terp promote` does not read `inputs.framework`. It serves no edge of its own, and the app's
  count stays the declared one there.

## Alternatives considered

- **The app counts the edge in its own code**, with a setting of its own. Each app would
  hand-roll the same environment read, and the one image would need to know where it runs. An
  app that got it wrong would trust an entry its callers wrote.
- **Trusting `X-Forwarded-For` only from given peer addresses**, as nginx's `set_real_ip_from`
  does. That is another model of the middleware, beside the count it already has. The edge's
  address on a container network is the deploy tool's to know and changes with the network,
  and the count is the one fact the runner holds.
- **The field under `inputs.toolchain`.** The toolchain is what gated and signed the release,
  and `sign` is the operator's newest. The framework is what the release runs. One map would
  then mean two things.
- **The runner reads `terp-core` from the backend image's installed packages** in
  `outputs.images`. The version is there, but the runner would have to work out which image is
  the backend's and which entry is the framework. That is a reading of the manifest's layout,
  where this is a field the signer states.
