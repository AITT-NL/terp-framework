# 0219 — A release builds its conformance suite into an image of its own

- **Status:** Proposed on 2026-11-23. Built in 0.44.0. Held by
  `tests/architecture/test_release_suite.py` (the render, the base, the plan, `sign` and the
  manifest's reader), `test_deployment_generator.py` and `test_deployment_generated.py` (the
  generator's owned paths and modules), and `test_cli_verify.py`'s manifest fixture (the
  `generated` check's scope).
- **Date:** 2026-11-23.
- **Relates:** amends [ADR 0187](0187-in-the-generated-state-the-framework-renders-the-build-files.md):
  a fifth generated file, `conformance/Dockerfile.prod`, a fifth base in the base-image table,
  and `sign` (decision 6) recording `outputs.suite`. Follows
  [ADR 0198](0198-a-static-site-is-a-web-unit-the-framework-builds-from-a-recipe-it-owns.md),
  whose site image is rendered where its lock is committed, and
  [ADR 0216](0216-the-release-manifest-lists-every-migration-history-its-image-runs.md), whose
  `outputs.migrations` is a field added without a new `schemaVersion`. The suite is the one
  [ADR 0200](0200-a-release-is-signed-only-over-a-green-release-profile.md)'s gate runs. The
  request is the managed-deployment design's (its section 11.35, the verify stage), which a
  runner reads it by.

## Context

A runner that deploys to production runs the release's conformance suite at its `verify` step,
against a disposable stack of the release's exact digests, before anything of production is
touched; a release that names no suite is refused where a job verifies. The suite exists: it is
the Playwright tests of an app's `conformance/` directory, on `@terpjs/conformance`, which
`terp verify --profile release` runs in the release's CI against a development stack. But no
release carries it. `sign` files that run's verdict alone (ADR 0200); the suite, its command and
what it reads are nowhere in the manifest; and no image of it is built, while a runner has no
checkout to build one from. The suite reads three values: `TERP_E2E_BASE_URL`, which it requires
with no default, and an administrator's `TERP_E2E_ADMIN_EMAIL` and `TERP_E2E_ADMIN_PASSWORD`.

Three things in `sign` assumed every image it checks is a service's: that what `build` pushed is
exactly the profile's images, that every image not marked `web` is the backend and is compared
with the tree, and that the gate inspected the one such image.

## Decision

1. **The generator renders the suite's Dockerfile** where the checkout commits
   `conformance/package-lock.json`, as it renders the site's where the site's lock is: a fifth
   owned path, `conformance/Dockerfile.prod`, a constant of the framework release that takes
   nothing from the declaration. `generate` takes `conformance_lock`, and every caller passes it:
   the render check, `terp deployment adopt`, and `sign`'s render with the pinned `terp-arch`, which
   passes it only to a generator whose signature takes it.
2. **On Playwright's own image.** The base-image table gains `playwright`, by digest, its tag
   naming its Playwright release (`mcr.microsoft.com/playwright:v1.62.1-noble`); the table's
   reader refuses a tag that names none. That image holds the browsers of one Playwright release,
   so the build refuses a lock whose `@playwright/test` is another, naming both and the way
   forward. The suite is installed with `npm ci --ignore-scripts` and runs as the image's own
   unprivileged `pwuser`, which owns the directory Playwright writes its results to.
3. **The plan builds it** where the commit holds `conformance/Dockerfile.prod`: the generator's
   in the generated state, the app's own under `"build": "own"`. It is an image no service runs,
   named `<project>-conformance-prod` after `[project].name` as the generator names the others,
   built from the checkout's root as the frontend is. Refused, each named: a suite whose lock is
   not committed or takes a package from a path; a project name that makes no image name; a name
   a service's image already has; and a declaration without exactly one web unit of the app's own
   (a `web` unit with no datastore kind and no recipe), which is the unit the suite drives.
4. **`sign` checks it as every image** in the registry, and describes it from its lock, as a web
   image is described from its own. It is not compared with the tree (that is the backend's),
   not the gate's image, not in `outputs.services` or `outputs.units`, and not in the resolved
   deployment.
5. **The record**, `outputs.suite`, added without a new `schemaVersion`:
   - `image`, the suite's entry in `outputs.images`;
   - `command`, `["/suite/node_modules/.bin/playwright", "test"]`, the image's own command, which
     a runner gives with nothing added;
   - `target`, the unit the suite drives;
   - `reads`, the names under which it reads `address`, `email` and `password`:
     `TERP_E2E_BASE_URL`, `TERP_E2E_ADMIN_EMAIL` and `TERP_E2E_ADMIN_PASSWORD`.

   A runner gives the target's address and a throwaway administrator under those names, and
   nothing else. `terp promote`'s reader holds a record that is present to this form: an image
   the release built that no service runs, a non-empty command, a target, and three distinct
   variable names.

## Consequences

- An app that commits its suite's lock is told by `terp verify --only generated` to render and
  commit `conformance/Dockerfile.prod`, as it was told of the site's. The template ships no lock,
  so a new app gets the file once it commits one.
- A release of an app with a suite pulls Playwright's image to build it, and a runner pulls the
  suite's image only for a job that verifies. No release of an app without one changes.
- The framework moves the Playwright base and the template's `@playwright/test` together. An app
  that pins another release fails its release build with the version to pin.

## Not done

- Running the image: that is a runner's `verify` step. The release gate still runs the suite from
  the checkout, as before.
- An app with more than one web unit of its own is refused a suite; which one a suite drives is
  for a later decision, when one has two.
- `terp maintenance` compares the bases of the images the release plan reads for the app's
  services, which the suite's is not, so it does not yet say when the Playwright base moves.

## Alternatives considered

- **The suite as a compose service under a profile.** A profile service is no part of a release,
  and as a unit no deploy starts it would be a second kind of unit in every reader of the
  deployment.
- **A Node base that installs the browser** with `npx playwright install --with-deps`. The browser
  would follow the lock with no version check, at the cost of installing operating-system
  packages at build time, which no other release image does, and of one more host the build
  fetches from.
- **A browser image the runner carries**, with the release carrying the suite's files alone. The
  suite's Playwright and the runner's browser would be two versions held in step from two
  repositories, and the release would not name what verifies it.
