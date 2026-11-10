# 0210 — The browser origins an API allows are each environment's own

- **Status:** Proposed on 2026-11-10. The owner chose the side that changes on the same day:
  the framework reads the setting, and no tool writes origins into an app's source.
- **Date:** 2026-11-10.
- **Amends:** [ADR 0005](0005-security-middleware-and-structured-logging.md), its CORS
  surface: a third declaration beside `CorsPolicy.allow([...])` and
  `CorsPolicy.disabled(reason=...)`.
- **Relates:** [ADR 0062](0062-production-deployment-profile.md) (the profile passes
  `BACKEND_CORS_ORIGINS` to the api), [ADR 0129](0129-the-job-actor-has-a-conventional-address.md)
  (the other value a control plane takes from its environment),
  [ADR 0197](0197-a-public-site-is-a-client-of-an-app-and-the-framework-defines-its-socket.md)
  (a site whose pages call the API from a browser is a client on another origin), and
  terp-studio ADR 0094 decision 6 (a hostname record says whether its origin may call the API).

## Decision

A control plane may declare `CorsPolicy.from_environment()`. The allowlist is then the list
the environment names in `BACKEND_CORS_ORIGINS`, read when `create_app` composes the app. An
environment that names no origin serves no cross-origin access. An entry that is not an
origin as a browser sends one refuses the boot, in every environment. The template declares
it for both of its variants.

## Context

Which origins may call an API from a browser is a fact of where the API is deployed. One
build runs on a test address and on a production one, and a deploy tool that keeps a
hostname per environment renders the origins that may call the API into the variable the
generated profile already passes to the api, `BACKEND_CORS_ORIGINS`.

The framework never read that variable to allow anything. It read it once, to refuse `*`.
The allowlist came from `CorsPolicy.allow([...])` in the app's source, and the template
declared `CorsPolicy.disabled(reason="server-to-server")`. So an origin written into the
variable was accepted without a word and refused by the browser, with nothing in any log on
either side. 0.41.0 corrected the template's documentation, which had told people to list
origins there. This ADR corrects the mechanism.

The other side could have changed instead: a deploy tool could write the origins into the
app's control plane. That puts an environment's fact into a commit, gives every environment
the origins of all of them, and has a tool editing the source it deploys. It was put to the
owner and declined.

## What changes

1. **`CorsPolicy.from_environment()`** is a declaration: `configured`, with no origin of its
   own. It takes the same `allow_credentials`, methods and headers as `allow`. The
   production refusal "CORS is unset" names it first among its three answers.
2. **`create_app` resolves it before any boot check**, in the module that already resolves
   the job principal from `JOB_SYSTEM_ACTOR_ID` (`terp.core._settings_plane`). An empty list
   leaves the CORS middleware out, the state `disabled` declares.
3. **An entry that is not an origin is a `BootError`**, in development too. A browser sends
   `Origin` as scheme, host and optional port, in lower case, with no path and no trailing
   slash, and the middleware compares exactly. `https://app.example.com/` never matches, so
   accepting it would reproduce the silent failure this closes. The message names the entry
   and the form. `*` is refused the same way: with this declaration there is no wildcard.
4. **A plane that does not read the variable says so when it is set.** One warning at boot,
   naming the declaration. It stays a warning: an app that fixed its origins in source and
   also has the variable set is not broken, only unclear. Whether that should become a
   refusal is under *Open*.
5. **The template declares it**, with and without a frontend. A new app therefore behaves
   as before where the variable is empty, which is every app whose SPA is served same-origin,
   and a deploy tool's per-environment origins take effect with no change to the app.
6. **`terp inspect control-plane`** shows it as a fourth mode, `from-environment`, with the
   variable and the origins the inspected plane was composed with.

## What it does not do

- It does not read the variable for an app that declares `allow` or `disabled`. An existing
  app keeps the CORS it declared until it changes one line.
- It does not decide which hostnames call the API. That is the deploy tool's record, or the
  operator's `.env`.
- It adds no rule to the catalog. Nothing in source can be checked here: the invariant is a
  value of the running environment, and its control is the boot refusal.

## Consequences

- An existing app adopts it by replacing its `cors=` line, or with `copier update`.
- A deploy tool that already renders the variable needs no change. One that renders an origin
  with a trailing slash or a path now stops the boot, with the entry named.
- The same image serves different origins per environment, which is the point, so the origins
  are not in the authorization surface or the API contract.

## Open

- Whether a set variable that the control plane does not read should refuse a production
  boot instead of warning. It would turn a silent state into a loud one for every existing
  app that has the variable set and declares its CORS in source.
