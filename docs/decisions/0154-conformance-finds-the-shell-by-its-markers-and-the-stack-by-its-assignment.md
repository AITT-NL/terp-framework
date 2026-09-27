# 0154 — Conformance finds the shell by its markers, and the stack by its assignment

- **Status:** Accepted and implemented. `@terpjs/conformance` locates every element its
  base-profile flows touch by a pinned `data-terp` marker and holds each to a role and a
  non-empty accessible name; `terp verify --only conformance` hands the suite the address this
  checkout publishes; the template's suite has no address of its own and its CI job assigns the
  workbench's ports. Held by `tests/architecture/test_conformance_markers.py`,
  `tests/architecture/test_template_conformance_job.py`,
  `tests/architecture/test_verify_conformance_address.py`,
  `tests/architecture/test_dev_host_ports.py`, the react-core marker, style and component tests,
  and the end-to-end run in `template-acceptance`.
- **Date:** 2026-09-27
- **Relates:** [ADR 0134](0134-the-lifecycle-has-one-driver-and-a-workbench-is-not-it.md)
  (host ports are an assignment, and a start without one refuses),
  [ADR 0105](0105-localization-is-a-checked-contract.md) (an app's interface is in the app's
  languages), [ADR 0094](0094-attribute-keyed-styling.md) and
  [ADR 0079](0079-slot-typed-layout-contracts.md) (what a marker already is: a component's
  identity for its styling and its slot check),
  [ADR 0003](0003-conformance-and-coverage-gate.md) (the conformance suite as a gate)

---

## Context

The project template ships a Playwright suite and a CI job that brings up the Docker workbench
and runs it. On a freshly generated app that job could not pass, for three independent reasons,
any one of which was enough:

1. **The stack never started.** The workbench publishes its host ports through required
   variables, so an unassigned checkout is refused rather than parked on a default another
   checkout may hold (ADR 0134). The job never assigned them, and a runner has no `.env` — it is
   gitignored, because a machine's ports do not belong in history. `docker compose up` stopped
   at `required variable WEB_PORT is missing a value`.
2. **The suite pointed at the wrong port.** Its config fell back to `localhost:5173`, the
   container's port, which the workbench stopped publishing on the host when the ports moved
   into the range Terp owns. Nothing set the real address: not the job, not `terp verify`. On a
   runner that address is empty; on a developer's machine it is whatever else happens to listen
   there, which on the machine this was measured on was an unrelated application's dev server.
3. **The helpers only spoke English.** `login()` waited for a heading named "Sign in", filled
   fields labelled "Email" and "Password" and clicked a "Sign in" button; `logout()` clicked a
   menu item named "Sign out"; the template's own spec looked for a "Primary" navigation. The
   template starts an app in Dutch. Measured on a fresh render: the login heading is
   "Inloggen", and both of the template's tests fail on it before any app code exists.

Nothing in this repository could see any of it. `template-acceptance` built and type-checked the
generated frontend and ran its backend tests; it never started the generated stack. The
framework's own conformance lane runs the example app, whose compose file keeps in-range port
defaults and whose interface is English, so it stepped around the first two defects and was
blind to the third by construction.

## Decision

### The base-profile flows locate by marker

A helper that every app composes cannot choose a language, and an accessible name is language.
It is also not always fixed within one: the account menu's trigger is named after the signed-in
user's own email and role when the sidebar is expanded (WCAG 2.5.3), which is why `logout()`
already found it by marker. That reason now covers everything the base-profile flows touch.
The markers are react-core's pinned inventory (`markers.test.ts`), so a rename is a failing test
and a release note, never a silent break.

| Element | Marker path |
|---|---|
| Sign-in heading | `login-title` |
| Email / password | `login-email` / `login-password`, then `input` |
| Submit | `login-submit`, then `button` |
| Account menu trigger | `user-menu`, then `menu-trigger` |
| Sign out | `user-menu-sign-out`, then `menu-item` |
| Primary navigation | `appshell-nav` |

Four of those markers are new, and they are wrappers rather than attributes on the controls,
because one element carries one marker and each control's marker is already its styling: an
input's rules key on `input`, a button's on `button`, a menu item's on `menu-item`. The wrappers
are `display: contents`, so they generate no box. Measured in Chromium against the unmodified
build, every box on the login card and in the account menu is identical to the pixel, the menu's
accessibility tree is unchanged, and `End` still lands focus on sign-out.

`loginHeading(page)` and `primaryNavigation(page)` are exported so an app's own specs assert the
signed-out and signed-in states without restating a marker, and `submitLogin(page, credentials)`
exists for a spec about a sign-in that must be refused.

### And holds every one of them to a role and a name

Locating by marker alone would have dropped the one guarantee a name-based locator gave for
free: `getByLabel("Email")` could not find an unlabelled field, so the suite failed on exactly
the defect a screen-reader user would hit. Each element a helper touches is therefore asserted
visible, exposing the role a user perceives, and carrying a non-empty accessible name
(`toHaveAccessibleName(/\S/)`). The existence of a name is checked; its language is not.
Measured: with the email field's label emptied, `login()` fails on the Dutch app with
`Received string: ""`.

### The address is the checkout's assignment, and there is no default

`terp verify --only conformance` now resolves the suite's address the way compose resolves the
port it publishes: `TERP_E2E_BASE_URL` if the caller already knows it; otherwise the app's
web-port variable (named by `workbench.json`, `WEB_PORT` by default) from the process
environment, then from `.env`. It passes the result to the suite and prints it as the first
line of the check's output.

When there is no answer it refuses before the suite starts, naming both ways out, and it does
not fall back. A fallback port is the default ADR 0134 removed from the compose file for a
reason that applies here unchanged: with no assignment this checkout's stack cannot be up, so a
literal reaches another checkout's stack, or another application's, and reports on that.

The template's Playwright config reads the same variable and refuses to load without it. The
suite can still be run by hand; the person running it names the stack, or runs it through the
gate that knows. The template's CI job runs `terp ports assign` before it starts the workbench.

### The gate that keeps it that way

`template-acceptance` proves, for every variant, that the generated compose file refuses an
unassigned checkout and resolves once `terp ports assign` has run. For one variant it then runs
the generated app's own conformance job end to end, Docker workbench included: the staged
wheels and tarballs go into `.terp-dist/`, where the template's Dockerfiles already look for
pre-release builds, and the job's steps run as the generated workflow runs them, through
`terp verify` with no address given. Statically, the template's conformance job must assign
before it starts the workbench, the template's suite config and CI workflow are among the files
that may not dial a port outside the Terp range, and no base-profile flow may locate anything by
its wording.

## Consequences

- An app's own specs are untouched. One that already uses English names on an English interface
  keeps passing; `login()` and `logout()` now also work on an app in any other language.
- An app that replaces the built-in sign-in screen (`renderTerpApp({ login })`) must render
  `login-title`, `login-email`, `login-password` and `login-submit` for `login()` to find its
  controls, or sign in from its specs its own way. Before this, it had to render the same
  English names instead.
- `npm test` in a generated app's `conformance/` no longer runs with nothing set; it says to run
  it through `terp verify` or to set `TERP_E2E_BASE_URL`.
- react-core renders four wrapper elements it did not render before. They carry no box and no
  style of their own, and a rule on them that is not `display: contents` fails the style tests.

## Alternatives considered

**Locate by name, in the app's language.** The helper would read the app's catalog, or be
handed the strings. That couples a package every app composes to each app's catalog and to the
framework's own strings, and it still leaves the trigger whose name is the user's email.

**Pin the browser to English.** It would make the suite depend on how an app chooses its locale,
exercise a language the app's users may never see, and still fail an app that ships no English.

**Locate by `type` and `autocomplete` inside `login-form`.** It works for the form and not for
sign-out, puts two kinds of handle side by side, and neither kind is pinned anywhere.

**Put the new markers on the controls.** An element has one `data-terp`. Replacing `input`,
`button` or `menu-item` with a part name would unstyle the control.

**Run the template's non-Docker loop in `template-acceptance`.** `terp dev` against a SQLite
file drives the same suite through the same check, without an image build. It was the first
plan, on the assumption that the workbench images could only install the published packages and
so could never run the code under test. They can: the template's Dockerfiles read `.terp-dist/`
for exactly this, and measured on a local run the backend image carried the staged `terp-cli`
and the frontend image the staged react-core. With that, the dev loop only skips things — the
compose file, the images, their healthchecks and the seed one-shot, which is most of what the
generated job does and all of what had never been run.
