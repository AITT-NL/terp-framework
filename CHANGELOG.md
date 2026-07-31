# Changelog

All notable changes to the Terp platform. Terp releases **in lockstep**: every backend
distribution (`terp-core`, `terp-arch`, `terp-cli`, `terp-migrations`, `terp-cap-*`) and
every frontend package (`@terpjs/contract`, `@terpjs/react-core`,
`@terpjs/eslint-boundaries`, `@terpjs/conformance`) carries the same version and
publishes from the same tag
(`v<version>`); the gate enforces the lockstep (`tests/architecture/test_release_versions.py`).

The full rationale trail lives in [docs/decisions/](docs/decisions/) — one ADR per
decision, 0001 onwards.

## Unreleased

### Added

- **Strict test isolation (`terp_strict_isolation`).** Snapshot-and-restore is faithful,
  and that is its blind spot: a runtime installed *before* the first test — a stray
  `import app.main` at collection time, a module-scope `create_app()` — is part of the
  snapshot, so it is restored before every test and covers every test equally. The suite
  stays green together and red alone, and 0.5.2's autouse fixture could not see it,
  because nothing had leaked. Set `terp_strict_isolation = true` (or pass
  `--terp-strict-isolation`) and the snapshot is followed by a reset: every test starts
  from the platform baseline, so a test that only ever passed on ambient state fails
  where it stands. It is opt-in because a suite may *deliberately* compose once at
  import, and the platform does not break that under anyone; new projects from the
  template start with it on, and the framework now runs its own suites that way.

### Changed

- **`terp_events` carries a real signature.** The fixture that exists so an app never
  has to import the non-public `configure_events` was handing back a
  `Callable[..., None]` wrapper typed `(catalog: object, *, dispatcher: object | None)`
  — no completion, and no type error for the wrong catalog. It now *is*
  `configure_events`, typed as the exported `InstallEvents` protocol
  (`EventCatalog`, `EventDispatcher | None`), so the app pays nothing for the
  indirection. Annotate the fixture parameter `InstallEvents`.

## 0.5.2 — 2026-07-31

Four things an app could get wrong with no failure to look at. A declaration that
reality does not back, a reality no declaration mentions, and a test suite whose green
depends on collection order all share one shape: nothing breaks, so nobody looks. This
release turns each of them into a refusal at the earliest moment the answer is complete.

### Added

- **Process-global runtime isolation ships with the platform.** `terp-core` now
  registers a pytest plugin (`terp.core.testing`, under `pytest11`), so every app gets
  the `terp_runtime_isolation` autouse fixture without a `conftest.py` line — plus
  `terp_events` (switch the bus on for one test) and `terp_default_runtime` (state the
  baseline instead of inheriting it). `create_app` installs six runtimes into process
  globals, and in a test process the last app composed is still installed when the next
  test runs: a unit test against a bare engine inherits a durable audit sink, and a test
  asserting an event was emitted can pass only because an earlier import configured the
  bus. The framework had always carried the fixture in its own repo-root `conftest.py`
  and never shipped it, so every app had to first meet the hazard as a suite that passes
  together and fails alone. The fixture snapshots and restores rather than resetting, so
  an existing suite pays nothing. Seams register themselves
  (`terp.core.runtime`), and the gate holds the registry against the kernel's own
  `reset_*_runtime` functions so a seventh seam cannot be added and quietly left out.

- **A declaration no base reads is refused** — at class definition (`TypeError`) and
  again at boot (`BootError`). A service that sets `event_map` but forgot to inherit
  `EventEmittingService` is real, correct, reviewed, and does nothing. A base names what
  it consumes (`consumes_declarations`); the kernel needs no knowledge of any
  capability's declaration to spot an inert one. The boot check is not redundant with
  the class check: `__init_subclass__` can only compare against the bases imported so
  far, and "forgot to inherit the base" is usually "never imported the capability", so
  boot is the first point where the answer is complete.

- **A subscription with no handler is refused at boot.** `ModuleSpec.subscribes` says
  the module reacts to an event, while the handler registers as a side effect of
  importing its file. Forget that import — the most ordinary refactor there is — and the
  manifest keeps claiming the subscription while the module hears nothing: no error, no
  log line, just work that never happens. The event-bus registry now reports what it is
  listening for, and `create_app` refuses a claim nothing backs.

- **`backend/emitted_events_are_declared`** (Terp Standard 0.20.0) — a module emits only
  the events its `ModuleSpec` declares. The `emits` list is the module's published
  contract: what the control plane validates, what an operator reads, what another team
  subscribes against. An undeclared emit makes it quietly untrue — the event really does
  go out. Build-time only by recorded decision: an emit call carries no module identity,
  so only the source layout knows which manifest owed the declaration.

### Fixed

- **`terp guide events` names its own package.** The recipe used `EventEmittingService`
  and `LifecycleEventMap` without saying they live in a separate distribution; it now
  gives the line (`uv add terp-cap-eventbus`). It also shows the compliant *conditional*
  emit — the lifecycle map only answers "every write of this shape emits this event",
  and with no shape written down for a state transition the tempting move is to emit
  from a router or a task, outside the write's transaction. Extend `_after_write`, where
  the map already lives.

- **Coverage is measured from process start.** `pytest --cov` instruments after pytest
  has loaded its `pytest11` entry-point plugins, so the kernel imported by terp-core's
  new testing plugin ran untraced and the gate read 89 %. The gate now runs
  `coverage run -m pytest`, and the plugin keeps its own `terp.core` imports inside the
  fixtures so it is never the thing that forces the issue.

- **Pinned spec: 0.20.0**, which catalogs `emitted_events_are_declared`.

## 0.5.1 — 2026-07-30

### Fixed

- **`terp verify` reads the libc gate npm installs by.** The `node_modules` platform
  diagnosis matched a lockfile entry on `os` and `cpu` only. A Linux bundler ships a
  `-gnu` *and* a `-musl` binding for the same os/cpu and npm installs exactly one, so on
  a glibc container the musl packages read as absent and the diagnosis failed all three
  frontend checks on a perfectly healthy tree — before the real command ran, so it also
  hid whatever the truth was, and its prescribed `npm ci` could never clear it. An entry
  constrained to the other flavour is now absent by design, like any other
  foreign-platform entry. A check that cries wolf is worse than no check.

## 0.5.0 — 2026-07-30

Modules get a declared way to depend on each other, machines get a credential of their
own, and least privilege gets cheaper than widening a role. Three questions an app used
to answer by hand — "may this module import that one?", "is this caller a person?",
"how do I grant one permission?" — become platform answers with a check behind them.

### Added

- **A module may declare a dependency on a sibling** (ADR 0087). `ModuleSpec.requires`
  gains its second, larger meaning: the exhaustive list of siblings this module may
  import. An undeclared sibling import stays refused
  (`backend/no_cross_module_imports`); a declared one is allowed, but only into the
  dependency's public surface (`backend/cross_module_imports_use_public_surface`) and
  only if the graph stays acyclic (`backend/module_dependency_graph_is_acyclic`, also
  refused at boot). The alternative was what every real app does instead: a
  hand-rolled seam per edge, invisible to review.
- **A machine is a first-class subject kind** (ADR 0088). Service accounts get a signed
  `kind` claim and a client-credentials grant at `POST /token`, so which store answers
  a token is decided by what the credential *is* rather than by lookup order. Machine
  tokens are revocable on the same epoch mechanism as user sessions, and a credential
  carries an end date by default.
- **`terp grant`** (ADR 0089) — grant, list and revoke a permission by the name an
  operator already uses (an email, a service-account name), validated against the app's
  own catalog and written through the audited service. A grant below the permission's
  minimum role warns loudly instead of storing a row that can never fire.
- **`terp inspect capabilities`** — the adoptable-capability surface, marked with what
  this app already has and what one `uv add` would add. The registry is pinned against
  the real packages, so it cannot drift.
- **Declared request-scoped filters and sorts on `BaseService`** — a service names the
  columns a caller may narrow or order a read by, and the comparison each one permits.
  Anything undeclared is refused rather than ignored, and no filter can widen past the
  service's own scoping.
- **`backend/table_ownership_is_not_split`** (ADR 0090) — a table's model and the
  migration that creates it must live in the same package. Split them and per-package
  scoping hides the table from *both* histories, so drift detection goes quiet on a
  table nobody migrates.
- **`terp guide permissions`** — when to reach for a permission instead of a role.

### Fixed

- **`terp verify` names the cause when `node_modules` came from another platform.** The
  gate died with a raw Node stack naming neither cause nor fix; the lockfile already
  records which optional binary belongs on which platform, so the diagnosis is exact.
- **The production nginx `/api` upstream is substituted at start-up**, so one image
  serves both compose (service name) and a runtime that co-locates the containers in
  one pod (localhost).
- **The 100 % coverage bar is restored.** Coverage only ran in CI, so a batch of work
  accumulated 35 uncovered lines. Two of them turned out to be unreachable guards and
  were removed rather than pragma'd.

### Changed

- **Pinned spec: 0.19.0**, which catalogs the three dependency rules and the owning-package rule.
- **The advertised platform surface is drift-proof** — what the docs claim Terp offers
  is checked against what it ships.

## 0.4.0 — 2026-07-29

A wrong database schema stops being a silent failure. A migration history that was
rewritten rather than extended is refused at build time, a database holding a revision
the code no longer defines is refused at boot, and every generated app gets that boot
guard instead of only the example app.

### Added

- **`backend/migration_history_is_intact`** — a migration history must be one unbroken
  chain from a single first revision, with every revision reachable from it. A deleted
  or renamed parent, a second baseline, and a closed cycle each strand every database
  that applied the old chain, while a database rebuilt from the rewritten history stays
  perfectly consistent with the models — so no drift check can see it.
- **`assert_no_orphaned_revisions`** — the runtime half: an app refuses to serve against
  a database holding a revision the code no longer defines, and reports that distinctly
  from "behind on migrations", because the two need opposite fixes.

### Fixed

- **Generated apps install the migration boot guard.** `migration_check` was wired into
  the example app only, so a rendered project served against a wrong schema until the
  first request that touched the affected table.
- **`terp check` is scoped to the app package** instead of also walking vendored and
  tooling directories.
- **Generated projects pin LF line endings.** On a Windows checkout Git rewrote every
  container-written file to CRLF, turning a real 281/7 change into a 948/674 commit and
  defeating review-by-diff and `git blame`.
- **Self-naming enum members are no longer flagged as hardcoded credentials.**

### Changed

- **Pinned spec: 0.18.0**, whose migration-history rule requires a real baseline.
- **One vitest major across the whole workspace**, and the high-severity frontend
  advisories are cleared.

## 0.3.0 — 2026-07-27

The Terp Standard becomes a dependency you install rather than a repository you
clone, and the deep-import rule starts guarding the scope the packages are
actually published under.

### Fixed

- **`frontend/no-deep-imports` refuses the published scope.** The rule only ever
  matched `@terp/*/src/*` and `@terp/*/dist/*`, so from the moment the frontend
  packages were renamed to `@terpjs/*` an
  `import x from "@terpjs/react-core/src/…"` walked straight past the one rule
  meant to stop it. Deep imports of the published packages are refused again.

### Changed

- **The Terp Standard is consumed as a published package** (ADR 0086). The
  backend resolves `terp-spec` from PyPI and the boundary lint resolves
  `@terpjs/spec` from npm, both pinned by version instead of a git tag — no
  `[tool.uv.sources]` entry and no `github:` dependency. `test_repo_split_readiness`
  now proves both lockfiles resolved the pinned release from a registry, and
  the two ecosystems may not drift apart.
- **Pinned spec: 0.16.0**, which records every rule's enforcing tool under the
  `@terpjs/*` scope the packages publish under.

## 0.2.0 — 2026-07-27

Second release: the enforcement harness grows fifteen rules, and the frontend
stops leaking the host's chrome and locale into a themed app.

### Added

- **Fifteen new architecture rules in `terp.arch`**, each catalog-attributed to the
  Terp Standard and each shipping its `uv run terp guide <rule>` fix recipe:
  - *Time* — `no_naive_datetime` (a naive `datetime` is a silent bug in a
    multi-region app) and `datetime_columns_are_timezone_aware` (a column that
    drops the offset loses the fact permanently).
  - *Optimistic concurrency* — `update_schemas_inherit_base_update_schema` and
    `no_manual_version_assignment`, closing the two ways an app can bypass the
    lost-update guard.
  - *Query correctness* — `offset_queries_declare_ordering` (an unordered
    `OFFSET` silently repeats and skips rows across pages) and
    `path_id_params_are_uuid`.
  - *Migrations* — `alembic_downgrades_not_empty`, so a downgrade path is real
    rather than a stub that pretends to roll back.
  - *Source hygiene* — `no_print`, `no_star_imports`, `no_eval_or_exec`,
    `no_blocking_sleep`, `no_mutable_default_args`, `no_todo_fixme`,
    `no_empty_tests` and `no_oversized_python_files`.

### Changed

- **Terp Standard pinned to v0.14.0** (from v0.13.0) in both consumers — the
  `terp-spec` distribution and `@terpjs/eslint-boundaries` — with the
  `SPEC_VERSION` constants moved in lockstep.
- **npm publishing now uses Trusted Publishing (OIDC)**; the long-lived
  `NPM_TOKEN` secret is gone from the release pipeline.

### Fixed

- **Native browser chrome now follows the token palette.** `color-scheme` is
  declared for both themes, so the `<select>` option popup, natively-drawn
  scrollbars and text carets stop rendering light chrome inside a dark app;
  scrollbars are themed to match.
- **Rows-per-page is a themed menu, not a native `<select>`** — the one control
  in `DataView` that still opened OS-drawn chrome.
- **A stray horizontal scrollbar in `DataViewTable`**, caused by the column
  resize handle being offset past the table's own edge.

### Upgrading from 0.1.0

The fifteen new rules apply to your app the moment you bump. Expect
`uv run terp check` to report findings that 0.1.0 never looked for — each names
the file, the line and the fix recipe. Under 0.x this ships as a minor bump, but
budget it as real migration work rather than a drop-in upgrade.

## 0.1.0 — 2026-07-23

First tagged release of the platform: the secure-by-default backend kernel
(`terp.core`), the base-profile + opt-in capabilities, the `terp.arch` enforcement
harness, the `terp` CLI, packaged per-package Alembic migrations, the frontend contract
(`@terp/contract`) and the first frontend stack (`@terp/react-core` + boundary lint +
conformance suite), the copier client template, the Docker dev workbench, and the
production deployment profile (multi-stage wheel images + hardened compose profile +
`docs/DEPLOYMENT.md`). See ADRs 0001–0082, including the new `terp-cap-redis` shared-store adapters for Redis-backed idempotency, throttling, and cache state.

Late additions on that line:

- **Background jobs preserve row ownership.** The ownership architecture rule
  now rejects a job-bearing app module whose declared CRUD service model omits
  `OwnedMixin`, and `create_app` refuses the same shape at composition. A system
  actor remains an audit identity, not blanket cross-owner maintenance authority;
  such workflows stop for a reviewed maintenance capability instead of deleting
  the owner gate.
- **Centralized first-run frontend design system.** `@terp/react-core` now owns
  stable control typography and intrinsic button sizing, icon-only themed
  preference menus, body-portaled/clamped overlays, normalized number inputs,
  compact page headers, equal-track `HubCard`s, and record-labelled DataView
  navigation. `AppShell` now has a home-linked brand, fixed-size collapsed icon
  slots, a scrollbar-free rail, and a scroll-locked/focus-contained mobile
  drawer; its `renderLink` receives an additive third context argument with the
  framework-owned expanded/collapsed styles (existing two-argument callbacks
  remain valid), and `renderBrandLink` is optional. Packaged users/groups admin
  now follows overview -> dedicated create/detail routes with breadcrumbs,
  page actions and confirmation-gated destructive changes. Nested `HubPage`s
  accept `parents`; the inherited `breadcrumbs` prop remains a compatibility
  alias.
- **`terp verify` — the one-command gate over declared profiles.** The project's
  whole verification surface as data: `--profile quick` (static enforcement:
  architecture gate, boundary lint, typecheck), `full` (the merge bar: + backend
  tests, the delegated AppSec baseline, the production build — exactly the
  template CI's blocking checks), `release` (+ API-docs drift, black-box
  conformance). `--list` prints the manifest a driving tool configures its gate
  from (id, category, command, input scope per check); `--only <check>` runs a
  subset (the change-scoped rerun seam); `--format json` emits the `terp_verify`
  envelope with every Terp Standard check report the checks published carried
  structurally.
- **Check reports (Terp Standard v0.7.0, `app-check-report.schema.json`).**
  `terp check --format check-report` and `terp-boundaries-lint --format
  check-report` emit the spec's self-describing check report — the certified
  `spec_version`, the checker identity, the run verdict, the evaluated-rule
  inventory as catalog ids, and findings in the finding format's shape
  (`fix_hint` = the `terp guide` recipe) — so a consumer joins per-rule verdicts
  to the catalog through one contract on both surfaces. The legacy
  `--format json` report and `terp_findings` envelope keep their published
  shapes; the certified spec version is a build-time constant
  (`terp.arch.SPEC_VERSION`, `SPEC_VERSION` in `@terp/eslint-boundaries`) held
  equal to the pinned spec release by the framework gate.
- **App-declared environment variables.** Every app ships an
  `environment.schema.json` manifest (empty by default) declaring the run-time
  variables it reads beyond the platform-owned set; both compose profiles
  forward the declared keys through one optional `env_file` seam (`.app.env`,
  `required: false`, gitignored/dockerignored). Deploy pipelines render exactly
  the declared keys — undeclared variables stay impossible, secret-marked ones
  stay out of plain records. Guarded by `test_prod_profile.py` /
  `test_compose_workbench.py`.
- **Per-rule verdicts are joinable to the Terp Standard (ADR 0083).**
  `terp check --format json` now publishes `rules` — the evaluated-rule
  inventory that matches the execution mode (the live registry; the budget
  ratchet only when a budget was supplied) — so a driving tool (the Studio's
  spec matrix) can join verdicts to catalog ids without ever claiming "pass"
  for a rule the pinned toolchain never ran. On the frontend, the new
  `terp-boundaries-lint` bin (the analog of `terp check --format json`)
  replaces the `eslint . && terp-boundaries-budget` chain: it runs the app's
  own ESLint config **and** the escape-hatch budget ratchet in one command
  (both halves always run — drift can no longer hide behind a failing lint)
  and publishes one findings envelope on stdout — the evaluated inventory
  (`catalogRuleIds()`), a `not_applicable` list for opt-in rules the app has
  not enabled (`frontend/layout-contract` without a checked-in
  `layout-contract.json`), findings attributed to stack-neutral catalog ids
  via `catalogRuleId` (budget drift as `frontend/escape-hatch`), and an
  `unattributed` bucket that is surfaced, never dropped — while the human
  report stays on stderr. `terp-boundaries-budget --format json` emits the
  same envelope standalone. The template and example lint script is now
  `terp-boundaries-lint`.

- **The two-layer doctrine is classified per rule (ADR 0084, Terp Standard
  v0.5.0).** Every catalog entry now carries a mandatory, machine-checked
  `runtime.applicability` (`required` / `not-applicable` / `deferred`): 21
  rules declare their fail-closed runtime control (15 controls that already
  existed — the write-chokepoint strip, the session re-scope, the boot
  validators, the catalog chokepoints — are now *declared* instead of
  folklore), 31 source-form rules are exempt with per-rule rationales, and 6
  known seam gaps are explicit `deferred` entries (including pagination and
  the missing-migration-history case, whose previously declared "runtime
  halves" did not actually refuse those violations). Tests fail closed on a
  missing, contradictory, or unresolvable classification, and the blanket
  "every rule has a runtime half" wording is retired from the platform docs.
  The spec repository's CI gains a `certify-against-reference` job that runs
  this repo's parity + corpus certification against every candidate spec
  change, closing the pinned-release adoption gap from the other side.

- **The Terp Standard's AppSec scope is explicit and the generic baseline is
  enforced (ADR 0085).** The catalog claims Terp-specific secure-architecture
  rules, not complete application security: generic vulnerability classes a
  stock analyzer detects well (command injection, unsafe deserialization,
  weak crypto randomness) are delegated to the mandatory ruff-bandit (`S`)
  baseline the platform repo already runs — and generated projects now
  inherit it (template `pyproject.toml` config + blocking CI step + an
  in-project ratchet that parses the stanza and pins the CI step), with
  `tests/guardrails/test_appsec_baseline.py` holding the delegation in place
  fail-closed and the template-acceptance job running the baseline on
  rendered output. Classes no stock analyzer detects (path traversal,
  secrets in logs, browser-storage auth material) stay addressed
  constructively, never claimed as detected. Baseline findings stay
  tool-attributed, never mapped to catalog ids.
