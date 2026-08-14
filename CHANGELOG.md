# Changelog

All notable changes to the Terp platform. Terp releases **in lockstep**: every backend
distribution (`terp-core`, `terp-arch`, `terp-cli`, `terp-migrations`, `terp-cap-*`) and
every frontend package (`@terpjs/contract`, `@terpjs/react-core`,
`@terpjs/eslint-boundaries`, `@terpjs/conformance`) carries the same version and
publishes from the same tag
(`v<version>`); the gate enforces the lockstep (`tests/architecture/test_release_versions.py`).

The full rationale trail lives in [docs/decisions/](docs/decisions/) — one ADR per
decision, 0001 onwards.

## 0.6.1 — 2026-08-14

Friction reported from an app weighing — and then taking — the 0.6.0 upgrade:
the notes that are supposed to justify an upgrade could not be read until after
it, and the release's new rule was simultaneously over- and under-broad in ways
that only surfaced against a real schema graph.

### Fixed

- **`schemas_avoid_positional_tuples` now judges the wire shape, not the
  spelling — and reports every offence in one boot.** Three defects in the
  0.6.0 rule, found together:

  *The runtime half missed the exact shape it exists for.* Its walk over model
  annotations kept only bare classes, so a discriminated-union member — not
  `isinstance(_, type)` — stopped the walk dead, and a `prefixItems` field
  inside that member sailed through unflagged. The boot check now validates the
  **generated OpenAPI document itself**: whatever route a type takes into the
  contract — a union member, a type alias, a generic parameter, a custom
  `__get_pydantic_core_schema__` — its schema is in the document, and a
  positional array shape (`prefixItems`, or the list form of `items`) is
  refused there. That is also what this rule's runtime half was documented to
  do all along.

  *It refused variadic tuples, which are not positional.* `tuple[X, ...]` emits
  byte-identical JSON Schema to `list[X]` — it is the immutable spelling of a
  homogeneous sequence, the natural annotation for a frozen value object — so
  refusing it forced source rewrites with provably zero wire effect while the
  message asserted something false. Both halves now exempt it (the document
  check gets this for free: nothing positional is emitted); a fixed tuple
  nested *inside* one (`tuple[tuple[str, int], ...]`) is still refused.

  *The runtime half raised on the first offence.* An app with many offending
  fields was handed fix-one-reboot-repeat, once per field. One boot now names
  every offending location in a single error, so the whole cleanup is priced
  before the first edit.

- **The lockstep gate now covers the frontend half.** `platform-install` read
  only `metadata.distributions()` — backend wheels — so an app with
  `@terpjs/react-core` pinned a release behind `terp-core` passed the gate and
  the full profile green: a fresh CI install would build the frontend against a
  platform combination that was never released, with the gate as evidence. The
  changelog's "the gate enforces the lockstep" claim was, for an app,
  unenforced on the npm side. The check now also reads **every** app manifest
  that declares a `@terpjs/*` package (discovered, never a named list — the
  template ships pins in both `frontend/package.json` and
  `conformance/package.json`) plus the installed copy under `node_modules` when
  present, so repinning without reinstalling is caught too. `@terpjs/spec` is
  excluded on the same grounds as `terp-spec`: its own release cadence. The
  upgrade recipe's step 3 now names both manifests instead of only the frontend
  one.

- **`terp upgrade --check` now says how to read the *target's* notes, not the
  installed ones.** The release notes ship inside the terp-core wheel so that
  `terp guide changelog` answers offline — which also means the installed copy
  ends at the installed version and structurally cannot describe the release the
  upgrade recipe asks you to judge. Step 1 of the recipe said "read what
  changed" and pointed at that copy; on an app at 0.5.x with 0.6.0 available,
  the step was impossible at the exact moment it mattered, and the reader's only
  move was to go hunting for the repository. Step 1 now prints
  `uvx --from terp-cli==<target> terp guide changelog`: an ephemeral CLI
  resolved from the same index (terp-cli pins terp-core exactly, so the target's
  CHANGELOG comes with it) that prints the target's notes without touching the
  app's environment or its pins. `terp guide changelog` itself now states where
  its notes end and prints the same escape hatch, for the reader who starts
  there instead of at the upgrade check.

### Added

- **Every distribution now says where it comes from.** No terp-\* wheel carried
  `[project.urls]`, so "where do these packages come from" — the first question
  of the hunt above — was answerable only by searching. Every backend pyproject
  now declares `Repository` and `Changelog` URLs, so `pip show terp-core`
  answers it in one step; the npm packages already carried `repository`, and the
  release gate now holds both halves
  (`tests/architecture/test_release_versions.py`).

  Requires spec `0.24.0`.

## 0.6.0 — 2026-08-14

### Added

- **A schema field can no longer cross the wire as a positional tuple
  (`backend/schemas_avoid_positional_tuples`).** A tuple-annotated field serialises
  into the contract as an array whose element types are positional (`prefixItems`, or
  the list form of `items`), and client generators disagree on that shape — so an app
  that exposes a tuple anywhere in its API cannot type its own calls against its own
  API. The reason this earns a rule is the failure mode, not the frequency: the error
  surfaces at the *call site* as an opaque generic mismatch, nowhere near the field
  that caused it, naming two types that print identically unless error truncation is
  disabled. It is a one-line fix per field once you know, and an afternoon until you
  do. Compliant shapes are a nested schema with named fields (when the positions
  differ in meaning) or a homogeneous `list[...]` (when they do not).

  Two layers, and each catches what the other cannot. The build-time half
  (`terp.arch`) reads the annotation and follows a tuple through unions, containers
  and mapping values, so `list[tuple[str, str]]` is caught as readily as a bare one.
  The runtime half walks the composed route table at boot and refuses a positional
  array in the generated document — which also covers a tuple arriving through a type
  alias, a generic parameter, or a custom `__get_pydantic_core_schema__`, none of
  which a source scan can see. Scope is the API boundary only: a DTO, or any model
  used as a request body or response; a tuple in service-internal code is untouched.
  Requires spec `0.23.0`.

- **Route paths and params are checked at compile time, from generated types (ADR 0092).**
  0.5.10 closed half of this: `useRouteParam` stopped a typo'd param from silently reading
  `undefined` *at runtime*. The other half is why the ADR exists — the router is built at
  runtime from the module manifests, so TanStack's type registry is empty and **nothing**
  could check a route path or a param name; a typo'd path was a dead link that shipped
  green, against the platform's own line that a red typecheck means the app does not work.
  The manifests are static data, so the check is now generated from them:
  - `terp routes` (a `terp-routes` bin from `@terpjs/contract`) parses each
    `src/modules/<name>/module.tsx`, reads the `path` literals out of every
    `defineModuleManifest(...)`, and writes a **committed** `src/routes.gen.d.ts` that
    augments `TerpRouteTable` — deduped, sorted, LF-only, so a committed artifact diffs
    cleanly.
  - Three checked seams consume it: `useRouteParams("/records/:recordId")` (exact, per
    route), `useRouteParam(name)` (checked against every declared param name), and
    `useTerpNavigate()` (an undeclared path is a type error; a parameterised route requires
    its params, in the manifest's `:id` spelling, translated to the router's `$id`).
  - `routes-drift` gates it in every verify profile, ordered **before** the typecheck: a
    stale table otherwise reads as a pile of errors in the app's own screens when the real
    fault is one unregenerated artifact. `--check` re-renders and compares, so it needs no
    git, catches a hand-edit, and prints the command that fixes it. `terp dev` regenerates
    as a preflight beside the OpenAPI export.
  - Extraction fails closed: a `path` that is not a plain string literal is refused with
    its file and line, never skipped. A partial table is worse than none — it turns a real
    path into a type error and teaches authors to distrust the check.
  - Opt-in for an existing app: with no `routes` script wired, the preflight and the gate
    are no-op successes carrying the adoption hint (the shape `api-docs-drift` has for an
    uncommitted `docs/`), so upgrading the framework cannot break `terp dev` or turn a gate
    red. The template ships the script, the committed table and the CI step, so a new app
    is gated from its first commit.

  Two things this deliberately does not do. The table covers the app's own manifests only,
  so it never drifts because a dependency's internals changed; packaged-area screens (the
  admin area) read their params through an internal untyped helper, since an app that
  declares no params of its own must not fail on framework code it does not own. And the
  guarantee is itself gated — a compile-time assertion in the example app fails if the
  check ever stops being a check, because that failure is otherwise invisible.

## 0.5.10 — 2026-08-14

Friction reported from building registry and catalog modules on Terp — the
frontend batch. The common shape: the platform had the right opinion and made the
author work around it — a sanctioned component the contract refused, a singleton read
spelled as a one-element list, a normal state spelled as exception control flow, and a
whole class of routing mistakes no layer could turn red.

### Added

- **`useRouteParam` — the fail-closed route-param read (ADR 0092).** `buildAppRouter`
  realises routes at runtime from manifests, so TanStack's type registry is empty in
  every Terp app: no route path or param name is checked anywhere, and the idiomatic
  read was an unchecked cast — `useParams({ strict: false }) as { recordId?: string }`
  — carried by the framework's own admin detail screens. A typo silently yielded
  `undefined` and shipped green, against the platform's own "a red typecheck means the
  app does not work". `useRouteParam("recordId")` returns the declared param and throws
  a directive error for an undeclared name; both admin screens adopt it. The full fix —
  a committed, drift-gated `routes.gen.d.ts` in the `terp openapi` shape — is designed
  in ADR 0092 and lands separately.
- **`useRecord` — the singleton counterpart of `useResource`.** Every detail screen
  spelled its one record as a one-element collection (`list: async () =>
  [unwrap(await client.GET(...))]`, then `items[0]`) — including both packaged admin
  detail screens, now converted. `useRecord({ get }, deps)` returns
  `{ item, loading, error, cause, reload, mutate }`, implemented over `useResource` so
  the two state machines cannot drift. A `get` resolving `null` is a normal absent
  state, not an error — compose with `unwrapOptional`.
- **`unwrapOptional` — absence as data on the client.** `GET .../latest` answering 404
  is a normal state for a snapshot nobody published yet, but expressing it meant
  `try/catch` around `unwrap` filtering on `status === 404` at every call site.
  `unwrapOptional` returns the data, or `null` on a 404, and throws the same `ApiError`
  for every other failure — `BaseService.find` (0.5.9) beside `get`, answered for the
  client.
- **`DataView` rows carry their own state: `getRowTone`.** A validation-driven table
  could only express "this row is refused" as a Badge inside some column — the wrong
  altitude; the *row* is in that state, not one of its cells. `getRowTone={(row) =>
  tone | null}` tints the row/card with the tone's soft token (the exact tokens `Badge`
  uses, so the vocabulary stays one) and stamps `data-tone`; a toned row outranks the
  selection tint.

### Changed

- **`Card` is now allowed directly in `OverviewPage` / `DetailPage` body slots
  (`standard` layout contract).** The README called `Card` "the sanctioned visual
  separation between sections" while the contract refused it in every governed body
  slot — the two disagreed, and the workaround (wrap it in a `Stack`) cost one
  structure-free element. The allowlists now include it, and the previously
  undocumented nesting rule is stated where the contract lives: both halves govern the
  slot's **direct children only**; an allowed container's subtree is the app's to
  compose.
- **`InMemoryDataViewRepository.searchFields` is compile-checked against `getValue`.**
  A misspelled entry resolved to `undefined` for every row, so search silently never
  matched it — no error at any layer. The options are now generic over the field union:
  annotate `getValue`'s field parameter (`(row, field: keyof Ticket & string) =>
  row[field]`) and `searchFields` is checked at compile time (`NoInfer` keeps a typo
  from widening the union). An unannotated `getValue` keeps today's unchecked-`string`
  behavior, so no existing code changes. A runtime dead-field warning was considered
  and rejected: a legitimately optional field that is `undefined` for every current row
  is indistinguishable from a typo.

### Fixed

- **`NavLinkContext` / `useNavLink` are actually importable.** 0.5.4's changelog listed
  them as published, but they were never exported from the package barrel — an app
  could not import what the changelog promised. Exported, with `NavLinkRenderer`.
- **The `DataViewRepository` doc example compiles.** The JSDoc example omitted the
  required `getValue` option; it (and the quick-start) now show the annotated pattern
  that makes `searchFields` compile-checked.
- **`terp seed --seed` says what it is.** The help read as "override where the seed
  lives"; it is a *stage selector* — point it at any `callable(session)` the app
  exposes (`terp seed --seed app.demo:install`) to run only that stage. Help text and
  module docstring now say so; a workbench that already seeded the baseline never needs
  a second full pass.

## 0.5.9 — 2026-08-13

Friction reported from building a publish validator on Terp. All three fixes
share a shape: a platform default that is right for most code and slightly wrong for
code that **reports** rather than aborts — a validator owing its caller every reason at
once, and a route that judges a document instead of storing one. Each moves a guarantee
out of prose or absent code and into something the platform states and enforces.

### Added

- **`ErrorDetail` puts structured reasons in the error envelope.** An `AppError`'s
  `code` classifies the refusal; it cannot also classify each *reason* for it. A
  validator that reported three problems at once therefore flattened three stable
  codes and three document paths into one English `detail`, and the only way for a UI
  to highlight the field that failed was to substring-match prose — a contract nobody
  promised and every message edit breaks. `AppError(..., details=[ErrorDetail(code,
  loc, msg), ...])` now renders a `details` array beside `detail`, shaped like
  FastAPI's own 422 entries so a frontend handles both in one branch. Strictly
  additive: an error carrying no details renders exactly the three documented keys, so
  every existing client is unaffected.
- **`BaseService.find` resolves a row without raising.** Asking "does this id resolve
  *for this caller*?" was spelled `try: … get(…) … except NotFoundError: return None`,
  re-implemented in every service that composes a sibling — and an `except` that later
  grows to span two lookups starts swallowing the wrong one with no sign. `find`
  returns `Model | None` through the *same* `base_query` as `get`, so absence becomes
  data without widening what a caller may see; `get` is now `find(...)` plus the
  raise. Reach for `get` when absence ends the request, `find` when it is one input
  among several.
- **`@read_only` declares "unsafe verb, pure computation".** Terp derives write
  authority from the HTTP method, which is right for almost every route and blind to
  one: the handler that is a `POST` because its *input* is a body, not because it
  writes — validating a candidate document, previewing an import, costing a plan.
  Such a route was pure only by the absence of a write, a guarantee made of missing
  code that holds until an edit adds a line and that no rule and no reviewer is
  prompted to check. `terp.core.read_only` states the intent and both halves of the
  platform enforce it: the new `declared_read_only_routes_do_not_write` rule refuses a
  decorated handler that calls a mutating service method, and `create_app`'s read-only
  binder marks the request read-only so the `BaseService` chokepoint refuses a write
  the rule could not see statically. The same argument `append_only = True` answers for
  a table, answered for a route. Authorization is deliberately untouched — a decorated
  `POST` is still authorized at the write tier, because declaring purity narrows what
  the handler may do, never what the caller must hold.

## 0.5.8 — 2026-08-13

Friction reported from building two modules on Terp, all of the same shape: the
platform knew the answer and made the author find it. Every fix here moves a message
from diagnosis to prescription.

### Added

- **`append_only = True` on a service states that a table is immutable once written.**
  A ledger row, an immutable revision, a captured snapshot achieved immutability by
  *not mounting an update route* — a guarantee that lives in the absence of code and
  evaporates the day someone adds one, with nothing to review against. Declaring it
  puts the refusal at the write chokepoint instead: `update` / `delete` and any
  bespoke `_save` of an existing row fail closed with the uniform 409, whatever the
  route surface looks like. The wrong thing is no longer the easy thing.
- **`terp fmt` formats the files this change touched, not the whole tree.** `ruff
  format .` is the right formatter with the wrong blast radius: on a project whose
  history predates the current ruff version it rewrites files the change never
  touched, so the review diff arrives half signal and half churn and the author's only
  recourse is to `git checkout` each unrelated file — a manual step at exactly the
  moment they were automating one. `terp fmt` defaults to the git-changed set
  (modified, staged, untracked), takes `--check` for the CI shape, and keeps `--all`
  for the deliberate whole-tree pass. Outside a git work tree it formats nothing
  rather than everything.

### Changed

- **The write chokepoint dumps JSON-column fields in JSON mode.** A typed value object
  stored in a JSON column — the natural shape for a document a module validates once
  and stores whole — was dumped in pydantic's *python* mode, so a `UUID` / `datetime` /
  `Enum` inside it reached the JSON serializer as a Python object and died at `flush`
  with `TypeError: Object of type UUID is not JSON serializable`: a message naming
  neither the field, nor the column, nor the fix (a `PlainSerializer` annotation the
  guide never mentioned). The chokepoint knows the column types, so it now dumps
  exactly the JSON-backed fields in `json` mode and leaves every other column its
  native Python value.
- **`terp migrate make` answers both of its walls, in one paste.**
  Autogenerate needs a database at head to diff against, and the settings default is
  in-memory SQLite, so every module author meets this refusal once per module —
  forever, and the recipe was theirs to invent. It now prints the exact two commands
  that work against a throwaway file database (with the PowerShell spelling), names
  the label they passed, and points at `--no-autogenerate` for the hand-authored case.
  The *second* wall got the same treatment: the file database the first refusal sends
  you to is empty, therefore behind head, so `make` failed again — and answering with
  "run `terp migrate status`" would have made one intent cost three round trips. The
  behind-head error now leads with `upgrade` then `make`, spelled against the database
  URL the author is already using. Both recipes are in `terp guide migrations`, so an
  author who reads first meets neither.
- **`no_oversized_python_files` proposes a cut, not just a number.** Naming the cap
  leaves the expensive half — finding the seam — to the author, using information the
  checker already has: it parsed the file, so the connected components of its
  top-level definitions are free. The violation now names the largest group of
  definitions that nothing outside it references, which is a group that can move as a
  unit without leaving a dangling name behind. When a file's definitions all reference
  one another there is no honest seam, and the message stays the bare cap rather than
  inventing a cut that would produce two coupled files instead of one long one.
- **`module_dependency_graph_is_acyclic` reads real imports, not only declarations.**
  A cycle closed by an import whose `ModuleSpec(requires=...)` entry had not been added
  yet was invisible to the gate and surfaced at app startup as a circular-import
  traceback — which names files, not the design mistake, and arrives minutes after the
  edit that caused it. The graph is now declared edges *union* actual imports, so the
  cycle is reported the moment it is written; the message names the cycle path and
  offers an app-level contracts module as the place to lift the vocabulary the two
  modules disagree over.
- **`terp guide service` prices the cost of a pure validator.** A validator that needs
  a fact from another module's table is the common case, and with no pattern written
  down the tempting answer is to hand the validator a session — putting a read outside
  the chokepoint and making it untestable without a database. The guide now shows the
  constructor-threading shape: the calling service looks the fact up, the validator
  stays pure, and the sibling dependency is visible in the manifest as a declared edge.

## 0.5.7 — 2026-08-12

A seam for a feature that lives one layer up: Terp Studio's Themes settings screen
needs a file to write a chosen theme into, and until now there wasn't one.

### Added

- **The frontend starter ships an empty `theme.css` overlay, imported right after
  `@terpjs/contract`'s tokens.** Studio applies a theme to a scaffolded project by
  overwriting one file with a `:root { --token: value; ... }` block; without a
  dedicated file, applying a theme meant hand-editing `main.tsx` or inventing a
  per-project convention. `theme.css` starts empty — the project renders with the
  framework's default tokens until a theme is applied — and only ever redefines the
  tokens a theme customises, so the normal CSS cascade covers everything else. Hand
  edits are safe: Studio only applies a theme when the workspace has no uncommitted
  changes, and the change lands as a normal, reviewable edit, never an auto-commit —
  but they are overwritten the next time a theme is applied.

## 0.5.6 — 2026-08-12

Deployments get a database they can choose, and four silences get a voice. The thread
running through it: the platform already knew the thing, and only said it somewhere
nobody was standing — or, in three cases, said nothing at all until an app hit it.

### Added

- **The production profile reads `DATABASE_URL` from a seam.** It was hardcoded to the
  bundled `db` sidecar, so the only supported topology was the one the profile shipped
  with, and a client who already operates PostgreSQL — a cluster, a DBA, a managed cloud
  database with its own backup and DR regime — had to fork the profile, which moves a
  deployment concern into application source and diverges forever. One line changes:
  `DATABASE_URL: ${DATABASE_URL:-postgresql+psycopg://…@db:5432/…}`. Unset is
  byte-identical to before (`docker compose up` by hand still works with nothing else
  configured); set points the app at any PostgreSQL, and an override drops the
  then-unused sidecar. `POSTGRES_PASSWORD` keeps its fail-fast `:?` guard where it
  belongs — on the `db` service — so a bundled deployment still refuses to start without
  it. Pinned in both the template and the example profile by
  `tests/architecture/test_prod_profile.py`.
- **Production says out loud when idempotency is per worker.** A per-instance store is
  *correct* for a single production instance, so refusing it outright would break a
  deployment that is not wrong — but its absence was silent, and the failure when the
  assumption stops holding is the worst kind: scaling to a second replica turns "this
  mutation runs once" into "once per worker a retry happens to land on", with no error,
  no failed request, and nothing connecting the duplicate rows back to the `--scale` that
  caused them. Boot now states the property it is actually running with and names
  `create_app(require_shared_idempotency_store=True)` as the flag that turns it into a
  refusal. A deployment that already holds the guarantee is not nagged, and local runs
  say nothing.
- **`terp_audit`, the test seam events already had.** A service-level test asserting on a
  durable audit trail found `select(AuditEvent)` returning `[]` — the default sink only
  logs, so nothing was ever written, and *an assertion about an empty result passes*. The
  test reported that audit worked; what it had established was that no sink was
  installed. `terp_audit` (typed `InstallAudit`, the twin of `InstallEvents`) closes the
  asymmetry, and `terp guide testing` now says what an empty audit assertion actually
  proves.
- **`terp guide soft-delete`.** `OwnedMixin` has `ownership` and `TenantScopedMixin` has
  `tenancy`; the third trait had no topic at all, so its rules were only findable after
  you had already made the mistake.

### Fixed

- **`terp migrate make` no longer answers the first question in raw Alembic.** `terp new
  module x` then `terp migrate make x` is the documented workflow, and on the settings
  default (in-memory SQLite) it failed in a 25-line traceback ending in "Target database
  is not up to date" — which names neither the cause nor the fix, and never says
  `DATABASE_URL`. Authoring a revision is a script-tree job, but *autogenerating* one
  diffs the live database; the stateful-command set is now conditional, so
  `make --no-autogenerate` still works with no database configured while the default
  gets the same readable refusal `upgrade` and `check` already give. A
  configured-but-behind database gets `DatabaseBehindForAutogenerateError`, raised in the
  orchestrator so a direct `terp.migrations.make` caller (Studio) gets it too.
- **`SoftDeleteMixin` stops telling you to write the filter the gate refuses.** Its
  docstring still said core installs no global filter and "the caller filters
  `deleted_at IS NULL` explicitly" — true when the trait was written, false since
  `apply_row_scope` took the filter over, and the worst kind of stale: an agent composing
  the mixin reads the mixin, and this one sent it to hand-write the exact predicate
  `no_manual_scope_filtering` refuses. A test pins the docstring to the behaviour
  asserted in the same file.
- **`@terpjs/conformance` now publishes compiled JavaScript.** It exported `./src/index.ts`
  like its siblings, but unlike them it is loaded by Playwright's runner from inside
  `node_modules`, where Node refuses to strip types at all — so an installing app got
  "No tests found" while this repo, whose own suite imports `../src`, saw nothing wrong.
  `prepack` builds the artifact and CI asserts it exists.
- **A generated app's CI generates its typed client before type-checking.** The client is a
  build artifact and git-ignored, so a fresh checkout has none; Vite erases type-only
  imports, so `build` passed and only `tsc` failed — invisible on the blank scaffold and a
  permanent failure the moment a module first calls the API.
- **The lockstep ratchet reads every template manifest, not one named path.** The
  conformance suite pins `@terpjs/conformance` in a second `package.json.jinja` that no
  test looked at; it sat four releases stale. Manifests are now discovered, and a test
  asserts the discovery is not quietly empty.

## 0.5.5 — 2026-08-11

A CLI that can answer "which Terp is this?", a gate that refuses to answer anything when
the install is incoherent, and a release pipeline that can no longer half-publish. The
theme is the same in all three: the platform knew something and only said it where nobody
was listening.

### Added

- **`terp --version`.** Reports the whole lockstep set, not one number — every installed
  `terp-*` distribution, discovered from the environment rather than a hand-kept list, and
  any package that disagrees named with the fix. Terp is pinned by hand across two
  manifests, so the natural failure is a forgotten pin leaving one package a release
  behind, and until now nothing detected it.
- **`terp guide changelog`.** This file, from an installed app: an upgrade you cannot read
  about is one you will not take.
- **`terp upgrade --check`.** Whether a newer Terp exists, without editing a manifest to
  find out.
- **`terp inspect capabilities` reports each capability's version**, so a mixed install is
  visible from the surface that lists what is installed.
- **`platform-install` check in every `terp verify` profile.** A mixed set is a forgotten
  pin, not a supported combination, so a gate run against it proves nothing in either
  direction — a green is not evidence and a red may belong to the mismatch. `terp
  --version` had warned about this since earlier in this release; a warning inside a
  command nobody runs before shipping is not a control. It now refuses, first, and the
  generated project's CI runs the same check before spending the gate.
- **`forwarded_filters_are_declared`.** A filter forwarded to a service that never
  declared it silently returned unfiltered rows. Enforced at runtime *and* build time.

### Fixed

- **A read filter named but valued `None` no longer skips its own declaration check.** The
  name was checked after the value, so the fail-open path was reachable with an empty
  filter.
- **The release can no longer publish to one registry and not the other.** PyPI and npm
  are both immutable, so a version only one accepted can neither be completed nor
  withdrawn — it is burned while still being pinnable, and a lockstep release burns it for
  all sixteen distributions at once. `publish-npm` now runs after `publish-pypi`, the leg
  that builds an artifact and can therefore fail on one, so a rejection leaves nothing
  published and the version free to re-cut. The PyPI publisher pin also moved forward: it
  was frozen at a digest whose bundled twine rejects the metadata today's build backend
  emits, which is exactly how `terp-spec` 0.21.0 was lost.
- **The backend build contexts carry the files the packages force-include.** `terp-core`
  force-includes the repo-root `CHANGELOG.md` (so `terp guide changelog` works from an
  installed app), which fails the image build outright in a context that copies only
  `packages/`. Nothing local catches this: neither the gate nor CI's gate job builds a
  wheel.

## 0.5.4 — 2026-07-31

Five findings from the first app to build real screens on the frontend surface, plus the
tooling half of 0.5.3's isolation story. Every one of them was silent: a documented route
that never matched, a link that reloaded the page, an envelope field CI keys off that was
never a count, a guide teaching an API that does not compile, and a green strict run that
proved less than it looked like.

### Added

- **`--terp-report-runtime-installs`.** Strict isolation resets *before* fixtures run, so
  an autouse installer in a project's own `conftest.py` hands every test a runtime it
  never asked for and a strict run agrees every time — the blind spot 0.5.3 could only
  warn about in prose. The flag compares the state each test starts from with the state
  it ends with and reports, per seam, the tests that installed it. Read the shape of the
  answer: one or two test ids under a seam is a test installing what it needs; every id
  in a package under one seam is a fixture installing it for them.
- **`routerPath()` (`@terpjs/react-core`).** The route spelling the contract documents
  (`/things/:id`) now mounts, alongside TanStack's own `$id`.
- **`NavLinkContext` / `useNavLink()` (`@terpjs/react-core`).** Published by
  `buildAppRouter`, so framework chrome can link through the router.

### Changed

- **`Breadcrumbs` and `HubCard` link through the router by default.** They previously
  emitted a raw `<a href>` — the construct the boundary lint refuses in module code — so
  every crumb click was a full page reload. Passing `renderLink` still overrides; outside
  a Terp router the anchor remains the fallback.
- **`Badge` takes its text as children**, the way every other component in the catalog
  does. `label` keeps working; the two are mutually exclusive in the type.
- **The boundary lint's machine envelope states the verdict** (`"ok": true | false`).
  `terp_findings` was always a *format version* (ADR 0083), but a field named like a
  count, sitting next to `findings`, was read as one by every first reader — including
  CI. The version stays; the answer is now next to it.
- **`terp guide dataview` teaches the real API.** Three of its lines did not compile
  (`InMemoryDataViewRepository` options, a `keyField` prop that never existed, column
  keys). The guide's snippets are now a typechecked `.tsx` fixture pinned to the guide
  text by a test, so neither half can move without the other.
- **`@terpjs/contract`'s `ModuleRoute.path` documents the translation** each adapter
  performs, instead of an example that only worked in one of them.

## 0.5.3 — 2026-07-31

Four findings from the first app to adopt 0.5.2's shipped test isolation, fixed where
they belong: three in the isolation story itself, one in `terp migrate`.

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

- **`terp migrate` refuses an in-memory database.** With no `DATABASE_URL` configured,
  the settings default is in-memory SQLite — so `terp migrate upgrade` printed
  `upgraded: [...]` against a database that ceased to exist when the process did, and
  `terp migrate check`, one line later in the same shell, reported the app behind its
  code. Both outputs were true; the pair was actively misleading, which is worse than
  either failure alone. The stateful commands (`upgrade`, `downgrade`, `stamp`,
  `status`, `check`, `adopt-schemas`, `grant-runtime`) now refuse an in-memory URL —
  any spelling of it — and name the fix. The script-tree half (`make`, `merge`,
  `heads`, `upgrade --sql`) never needed a database and is unaffected.

- **`terp guide testing` leads with what you must still do yourself.** The topic opened
  with "you get isolation for free — no conftest.py line, no opt-in" and only reached
  "isolation does not *install* a runtime your test needs" in the fourth bullet. That
  distinction is the entire migration, and the headline read as "delete your conftest".
  Inverted, with a per-seam table (all six: restored automatically vs installed by you).

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
