# 0211 — The modules an app mounts do not depend on a setting

- **Status:** Proposed on 2026-11-10. The owner decided the principle on 2026-11-09 (ADR
  0209, *Open*); this ADR is the change that builds it.
- **Date:** 2026-11-10.
- **Amends:** [ADR 0209](0209-a-new-app-pins-who-can-reach-what-and-the-check-names-each-widening.md),
  closing its open item on a module that only mounts under a setting, and
  [ADR 0058](0058-pluggable-sso-oidc.md): the OIDC router may be built with no provider.
- **Relates:** [ADR 0139](0139-who-can-reach-what-is-pinned-not-merely-reportable.md) (the
  authorization surface is composed, then compared) and
  [ADR 0084](0084-runtime-applicability-classification.md) (a rule's runtime
  half is classified, with its tracking when deferred).

## Decision

An app hands `create_app` the same modules in every environment. A module whose
configuration differs per environment is mounted always, and its routes answer a typed
refusal while it is not configured. A rule, `module_list_is_unconditional`, refuses a module
list decided under a condition, and the OIDC capability gains the state that makes the
compliant form possible.

## Context

The access check composes the app and records who can reach each route (ADR 0139, ADR
0209). It composes it wherever it runs: on a developer's machine, in CI, in a deploy tool's
sandbox. A module mounted only where a setting is present is in the surface in one of those
places and absent in another. The template did exactly that with its SSO routes, which it
mounted only when `OIDC_ISSUER` was set, and the example app mounted its own only outside
production. Neither is deception. Both mean the record a reviewer approved is not the
surface a deployment serves, and both make a later check that compares the two at startup
refuse an honest app.

Mounting the SSO routes always was not possible: the OIDC router refused an empty provider
list, because a provider's configuration is validated when the app starts.

## What changes

1. **The OIDC router takes no provider when the app says it may have none.**
   `build_oidc_module(providers, resolver, allow_no_provider=True)` builds the same two
   routes with an empty list. Each then answers `SsoNotConfiguredError`: 503, code
   `sso_not_configured`, so a client can tell it from an unknown provider (404). Without the
   keyword an empty list is still a construction error, and the message names the keyword.
2. **The rule.** `module_list_is_unconditional` follows the list handed to `create_app` back
   through the file that builds it and refuses each place it is decided under a condition:
   a conditional expression among its elements, a change under an `if`, a loop, a `try` or a
   `match`, a comprehension or a `filter` that drops elements, a helper that returns it
   under a condition, and the same through a parameter to the function's callers in that
   file. Its message names the compliant form. It has the usual marker and budget.
3. **The template and the example app comply.** The template builds its SSO module with the
   providers the environment configures, an empty list where it configures none, and names
   it in the list unconditionally. The example app does the same with its development
   provider, which production does not have.
4. **The rule's runtime half is deferred, with its tracking.** The running system can
   observe the consequence: whether the composed routes are the ones the committed surface
   records. That comparison at startup is the control ADR 0209 leaves open, because it runs
   the app's own code against its own record. Until it is decided, the catalog records the
   rule as `deferred` and names that seam.

## What it does not do

- It does not follow a list into another file. A module list built elsewhere, a module
  object that is itself `None` under a condition, and a list chosen by a boolean operator
  are recorded as the rule's residuals. The second fails at composition where the condition
  does not hold, because `create_app` refuses an entry that is no module.
- It does not make a capability's behaviour the same everywhere. What a mounted route does
  may depend on a setting; whether it exists may not.
- It does not touch discovered capabilities, which `create_app` mounts by what is installed.

## Consequences

- An existing app whose module list is conditional turns red on this release, with the
  remedy in the message. `copier update` brings the template's form.
- An app with SSO routes mounted and no provider configured has two more public routes
  than before, each a refusal. Its authorization surface gains them once, and is then the
  same everywhere.
- The startup comparison, if it is approved, no longer refuses the honest case this ADR
  removes.
