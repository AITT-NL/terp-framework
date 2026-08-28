# Route operations — design notes and the sequenced plan

> **Decision:** [ADR 0102](../../decisions/0102-route-operations-are-declared.md). This file is the
> execution tracker; when it disagrees with the ADR, the ADR wins.
>
> **Audience:** platform/core team + agents. **Status:** in progress.

The goal, in one line: a route declares the operation it performs, so the Studio's permission
viewer can say *"Verwijder een bestand — Beheerder"* instead of
`DELETE /api/v1/files/{file_id} write role:admin —`, and so the platform can guarantee every route
is explained.

## Scope, and how to re-measure it

Every number below rots. Each row carries the command that regenerates it — run the command, do not
trust the number.

| Area | How to count |
|---|---|
| Capability routes to annotate | `grep -rc "@router\.\(get\|post\|put\|patch\|delete\)" --include=*.py packages/backend/capabilities \| grep -v ":0"` |
| Example-app routes to annotate | same, over `apps/example/app/modules` — plus `build_crud_router` call sites, which contribute five routes each |
| Capabilities that cannot use an escape hatch | `_CLEAN_CAPS` in `tests/architecture/test_capability_arch.py` |
| Route-touching Standard rules | rules whose title or intent names a route/endpoint/router in `terp-spec/catalog/backend` |
| Template routes | `find template/project/app -name "router*"` — currently empty, so a new app starts free |

At the time of writing, the bulk of the mechanical work is annotating the capability and example-app
routes, and the subset held to zero opt-outs by `_CLEAN_CAPS` is the part that cannot be deferred.

## Phase 1 — cleanups that stand alone

None of these need the operation seam, and each is independently verifiable. Doing them first keeps
the feature commits small.

- [x] **1.1 One HTTP-method vocabulary.** *(done)* `_MUTATING_METHODS` is declared in
      `terp.core.app` and again in `terp.cli.access`, whose comment already concedes it "mirrors the
      kernel guard's method split (terp.core.app)". Export the split from core; have the CLI import
      it. Leave `terp.arch.rules._support`'s copy alone — it is a *source-form* vocabulary
      (lowercase decorator attribute names), genuinely a different thing from runtime HTTP verbs.
      *Outcome:* the copies had already drifted into a reachable privilege-tier escape — the guard
      authorized every non-mutating method at the read tier while the binder marked only
      GET/HEAD/OPTIONS read-only, so a TRACE route could write. Fixed by phrasing the split as one
      negation. A same-set agreement test would have been vacuous once the constant is shared, so
      the gate is the behavioural one: a write behind TRACE is refused (mutation-checked — reverting
      the binder gives `assert 200 == 500`).
- [x] **1.2 Route markers live together.** *(done)* `PERMISSION_DEPENDENCY_ATTR` is defined in
      `terp.cli.access` but stamped in `terp.capabilities.access.deps`; `READ_ONLY_ATTRIBUTE` is
      correctly in `terp.core.routing` beside its reader. Move the permission marker name to
      `terp.core.routing` and have both the capability and the CLI import it, so the third marker
      (the operation) lands in an established place rather than a fourth one.
      *Gate:* the access graph still reports route-level permissions — mutation-checked by removing
      the stamp and watching the assertion fail.
- [x] **1.3 The factory names its routes after its entity.** *(done)* `build_crud_router` produces
      `list_items` / `create_item` / `get_item` / `update_item` / `delete_item`, so every
      factory-built module is anonymous in the access graph *and* carries FastAPI's generated
      operation ids into the exported OpenAPI. Derive the entity from the read DTO (`ProjectRead`
      → `project`) and name the routes accordingly.
      *Outcome:* names come from the read DTO (`ProjectRead` -> `project`), with a small regular
      pluraliser so the collection route is `list_projects` and `list_companies` rather than
      `list_companys`. A leading underscore is stripped, because a module-private DTO is normal
      input and `_WidgetRead` otherwise produced `list___widgets`. This also repaired every
      factory-built module's OpenAPI `operationId`, which FastAPI builds from the route name — a
      regeneration for existing apps, not a code migration, since only the generated client keys
      off those ids. Mutation-checked: removing the `name=` arguments fails with
      `{'create_item', ...} == {'create_project', ...}`.
- [x] **1.4 One route-discovery helper in `terp.arch`.** *(done)* Several rule modules
      (`http`, `authz`, `occ`, `persistence`, over `_support`) each used to walk the AST for route
      decorators and `add_api_route` calls independently. All six route rules now share one
      iterator, `iter_route_registrations` (`RouteRegistration` in `_support.py`).
      *Gate:* every existing route rule keeps its current findings on the example app and on the
      spec corpus — this is a refactor, so the corpus results are the assertion.
      *Progress:* `routes_declare_response_model` and `list_routes_paginate` migrated first.
      Migrating the walk found a real inconsistency worth recording: those two rules had drifted
      to accept *different* decorator sets — one took `api_route`, the other did not — without
      anyone deciding they should. Both kept their existing surface (now named
      `_PAGINATED_ROUTE_VERBS` and the body-verb filter), because changing which routes a security
      rule governs is not a refactor. `path_id_params_are_uuid` migrated third, and that migration
      closed two real coverage holes: an imperative route (`add_api_route`) was never inspected at
      all, and a keyword-only path parameter (one bare `*` in the signature) took the handler out
      of scope entirely — see STATUS.md for the fixture-proven detail.
      The remaining three are migrated too, closing out this item:
        - `response_model_not_table_model` was decorator-only before migrating, and the imperative
          form — `add_api_route(..., response_model=SomeTableModel)` — was never inspected at all,
          the same shape of gap `path_id_params_are_uuid` closed. Now covered; `api_route` stays
          excluded, preserving this rule's existing body-verb-only surface for the same "not a
          refactor" reason as above.
        - `_safe_reachable_handlers` (`http.py`) required widening the shared
          `_ROUTE_DECORATOR_ATTRS` to add back `head` / `options` — exactly the widening its own
          comment deferred to "when that rule migrates." Every other consumer of the constant
          filters to a narrower verb set that already excludes both, so nothing else changed.
          Covered by a new test exercising both decorators directly, mutation-checked.
        - `authz._has_mutating_route` migrated with no behaviour change. Its pre-migration walk
          carried a redundant generic Call-node branch that matched every real registration a
          second time and, in principle, a bare non-decorator `.api_route(...)` call no test or
          corpus case exercises (and FastAPI's own API gives no reason to write) — dropped.
      Every fix mutation-checked: broken, watched to fail against its unit test and/or the spec
      corpus, then restored.
- [x] **1.5 Drop the method-derived `kind` from the access graph.** Blocked on the Studio no longer
      rendering it (phase 3), so this is the *last* item of phase 1 in time even though it belongs
      here in spirit. Removes the field from `_endpoint_json` and from `_render_access_text`.

## Phase 2 — the core seam (nothing observable yet) — DONE

- [x] **2.1 `terp/core/operations.py`** — `OperationDefinition(id, label)` and `OperationCatalog`,
      mirroring `EventDefinition` / `EventCatalog`: dotted-token id validation, duplicate-id
      refusal, `has_name` / `get` / `missing_*`, `default()` returning empty. Value-matched
      membership (`has_operation`) so a same-id look-alike with a different label is a shadow and is
      rejected, exactly as the event catalog does.
- [x] **2.2 `operation(...)` in `terp/core/routing.py`** — the decorator, `OPERATION_ATTRIBUTE`, and
      `declared_operation(endpoint)`. Applied below the route decorator. Docstring must state, as
      `read_only`'s does, that it changes nothing about authorization.
- [x] **2.3 `ControlPlane.operations`** — the catalog field plus `_operation_errors` in
      `validation_errors`, following `_event_errors`: a declared operation absent from the catalog
      fails the boot.
- [x] **2.4 Coverage mode** — `off` / `warn` / `strict` on the control plane. `strict` refuses a
      mounted route with no declaration at boot; `warn` records them for the graph; `off` is the
      default and changes nothing.
- [x] **2.5 Export from `terp.core`** and add to `__all__`.

*Gates for phase 2 (all mutation-checked, in `tests/architecture/test_core_app.py`):* an
uncatalogued operation refuses the boot with coverage left OFF, so the refusal is not the
coverage check in disguise; a same-id shadow differing only in its label is refused, which an
id-only comparison would accept; an undeclared route boots under `off` and is refused under
`strict`, each half meaningless without the other; and `strict` reaches a route on an included
sub-router.

The nested-router gate needed a second attempt and the reason is worth keeping: asserting only
that the boot failed passed with the traversal broken, because `include_router` keeps the child
as an `_IncludedRouter` whose own `path` is `None` — so a top-level-only walk counts that
wrapper as an undeclared route and still refuses. The test now asserts the nested route's path
appears in the message, which is what distinguishes walking the tree from tripping over its root.

## Phase 3 — the Studio viewer (first user-visible value) — DONE

Works against the current framework ref, because the derived label needs only `endpoint.name`, which
the access graph already carries.

- [x] **3.1 A pure derivation module** in the Studio frontend: verb-frame table → plain-language
      label, reporting whether the label was declared, derived, or a raw name. Frames are
      translated; the noun is left in the app's own vocabulary.
- [x] **3.2 Plain-language authority** from `endpoint.requirement`, handling all three shapes the
      field can hold (`role:x`, `permission:x`, and the prose sentinels `public` /
      `denied (no policy declared)`). Reuse `requirementRank` / `requirementKind` from
      `accessMatrix.ts` rather than re-parsing.
- [x] **3.3 Role names in plain language** for the framework's own ladder, with a custom declared
      role keeping its own name — a project may ship any ladder, and renaming a custom role here
      would disagree with the app's own user-management screen.
- [x] **3.4 Rewrite the endpoint table** to *Actie* / *Wie mag dit*, with method, path and raw
      requirement demoted to dimmed sublines. ADR 0004 forbids hiding them; it only demotes them.
- [x] **3.5 Mark derived-only labels** so the gap is visible, in the same fail-visible spirit as
      `omitted_routes`.
- [x] **3.6 Tolerate a framework that predates the field** — optional in the type, absent means
      derive, as `undeclared_subscribers` already does.

*Gates:* 14 derivation tests plus 5 render tests. Two things the mutation pass caught and that are
worth keeping: asserting the technical subline with `toBeInTheDocument` passed with the whole
subline hidden (`getByText` finds text inside a hidden element), so it asserts `toBeVisible` —
which is the ADR 0004 rule this change rests on. And the browser measurement was wrong twice
before it was right: the probe set `colorScheme` while this Studio themes on `html[data-theme]`,
so both runs had measured the dark palette; with that fixed it showed the action and the subline
both computed to 12px, so the hierarchy rested on colour alone until the action was raised a step.

## Phase 4 — OpenAPI, so the field has a second reader — DONE

- [x] **4.1** A declared operation populates the route's `summary` and `operation_id`.
      `create_app`'s new `_apply_declared_operations` walks the same routes
      `_validate_declared_operations` already confirmed against the catalog, and sets
      `route.summary` / `route.operation_id` from the declaration. Measured, not assumed:
      FastAPI's OpenAPI generator (`fastapi.openapi.utils.generate_operation_summary` /
      `get_openapi_operation_metadata`) reads both fields **live** at schema-generation
      time rather than a value cached at route construction, and `include_router` keeps
      a mounted router's original `APIRoute` objects rather than cloning them — so
      mutating them before a spec's router is ever mounted reaches the exported document
      unchanged either way. Only `APIRoute` carries these fields in OpenAPI; a declared
      operation on a WebSocket route stays validated (no-drift, coverage) but has
      nothing here to populate.
- [x] **4.2** Refuse a hand-written `summary=` on a route that declares an operation — two answers
      to the same promise. Boot-time only for now (no paired `terp.arch` rule; the two
      new Standard rules phase 6 adds are about catalog membership and coverage, not
      this).
- [x] **4.3** Regenerate any checked-in OpenAPI artifacts and confirm the drift checks pass.
      Nothing to regenerate *at this commit*: the example app declares no operations yet
      (that is phase 5), so `test_openapi_contract` / `test_cli_openapi` pass unchanged,
      confirming this phase is a no-op until routes actually declare something. Phase 5
      is where the real regeneration happens, once routes actually declare operations.

*Gates:* two new tests in `test_core_app.py`, both mutation-checked — dropping the
`route.summary` / `route.operation_id` assignment turns the populate test red
(`assert 'Read' == 'Delete a file'`, FastAPI's own name-derived fallback surfacing);
disabling the refusal turns the hand-written-summary test red (`DID NOT RAISE BootError`).
Full suite green, ruff clean, vendored `terp.core` mirror resynced (this phase touches
`packages/backend/core`).

*A real bug, found once phase 5 actually exercised this at scale:* a module's router is a
process-wide singleton built once at import time, and `create_app` is routinely called more
than once over the same router objects in one process — the example app boots its full
profile and its base profile from the same capability routers, and so does any test suite
that builds the same app twice. The second call saw the summary `_apply_declared_operations`
itself had set on the first one and raised the hand-written-summary refusal against its own
prior work. Fixed by comparing `route.summary` to `declared.label` rather than only checking
truthiness — the two can only differ when an author, not this function, set it — with a third
test proving the fix (`create_app` called twice over the same spec must not raise the second
time) and mutation-checked the same way as the other two.

## Phase 5 — annotate the framework

Order matters: the capabilities in `_CLEAN_CAPS` must be clean with **zero** opt-outs, so they
cannot be deferred behind a marker and are done first.

- [x] **5.1** Catalogue and annotate the `_CLEAN_CAPS` capabilities' routes.
- [x] **5.2** Catalogue and annotate the remaining capabilities' routes.
      In practice 5.1 and 5.2 landed together: all eleven capabilities that carry routes
      (`access`, `audit`, `auth`, `files`, `groups`, `leases`, `oidc`, `realtime`, `sync`,
      `users`, `webhooks` — `eventbus` is a library cap with no router) got a real
      declaration for every route with zero escape-hatch markers anywhere, so the
      clean-first ordering never had to matter: nothing needed deferring. Each capability
      gained its own `operations.py` (an `OperationDefinition` constant per route, named
      `<CAPABILITY>_<ACTION>`, id `<capability>.<handler_function_name>`), re-exported from
      the capability's `__init__.py` — the same shape `WEBHOOK_DELIVER` already established
      for a capability-owned `JobDefinition`. `files.delete_file` reuses ADR 0102's own
      worked example verbatim (`FILES_DELETE`, `id="files.delete"`,
      `label="Delete a file"`).
      **A real, wide-reaching bug surfaced doing this at scale, not from any one route's
      annotation:** the no-drift catalog-membership check (`_validate_declared_operations`,
      phase 2) is unconditional by design, so the instant a capability's routes declared
      real operations, every existing test anywhere in the suite that boots an app
      mounting that capability *without* a matching `OperationCatalog` started failing —
      31 tests across 9 files (`test_framework_stack.py`, `test_cli_access.py`,
      `test_cli_leases.py`, `test_cli_openapi.py`, `test_leases.py`, `test_oidc.py`,
      `test_openapi_contract.py`, `test_realtime.py`, `test_sync.py`). None were a design
      flaw in the check itself — each was a fixture built before operations existed,
      constructing `create_app(...)` or a generated CLI test app with no `control_plane=`
      at all. Each file's `create_app` call site(s) now pass an `OperationCatalog`
      containing exactly the operations its mounted capability's routes declare. The two
      committed OpenAPI artifacts (`apps/example/openapi.json`,
      `packages/frontend/contract/openapi.json`) and their generated
      `schema.d.ts` files (in `packages/frontend/contract` and
      `apps/example/frontend`) were regenerated — this is where phase 4.3's
      deferred regeneration actually happens, since routes now declare real
      operations. `apps/example/frontend`'s `tsc --noEmit` and `npm run build`
      both stay clean against the regenerated schema.
- [x] **5.3** Annotate the example app, including the factory-built module via 1.3.
      `notes` / `tasks` / `journals` each declare their five operations directly on the
      hand-written router; `projects` (the `build_crud_router` factory module) passes its
      five via the new `*_operation=` keywords (this item is what phase-5 needed the
      1.3/§7 factory support *for*). Every app-level `OperationDefinition` lives in the new
      `apps/example/control_plane/operations.py`, alongside the capability operations it
      imports and folds into one `operation_catalog` — the same centralisation
      `control_plane/events.py` / `jobs.py` already established, now extended to
      `ControlPlane.operations`. `base_control_plane` shares the same catalog (a superset
      is harmless regardless of coverage, and the base profile mounts a subset of the same
      modules). Coverage stayed at its `OFF` default at the time this item landed;
      phase 6.4 below is where it flips to `strict`.
- [x] **5.4** Decide the kernel routes' treatment. **Exempted explicitly**, not labelled:
      health and friends already had a documented, fail-visible exemption from the
      module-policy dimension (the access graph's `kernel_routes` category, note
      "unauthenticated kernel route (no module policy)") for the same reason an operation
      would not add anything here — they are kernel-owned, identical in every app, and
      read by infrastructure (a load balancer's liveness probe) rather than a person in
      the Studio's permission viewer. Labelling them would also have meant teaching the
      no-drift catalog check about a router mounted outside any `ModuleSpec`, for routes
      whose "who may do this" is already answered by being outside `/api/v1` entirely.
      The existing note now reads "no module policy, no operation" — extending the
      already-explicit exemption to name this dimension too, rather than leaving it as a
      second, silent gap next to the first, documented one.
- [x] **5.5** Ship the Dutch catalog for the framework's own operations, pinned by a completeness
      test against the operation-id set — the same shape as the existing locale completeness test.
      Every operation in `apps/example/control_plane/operations.py`'s `operation_catalog` (run
      `len(operation_catalog.operations)` to see the current count — it grows with every future
      annotation, so it is not restated here) gained a Dutch entry in
      `apps/example/frontend/i18n.json`, keyed by the operation id exactly as the settled item-2
      decision specifies. `files.delete` reuses ADR 0102's own Dutch worked example ("Verwijder
      een bestand") verbatim.
      **A real collision surfaced doing this, not a hypothetical one:** `files.delete` was already
      a UI-text id in `FilesView.tsx` — a delete *button's* caption ("Delete" / "Verwijderen") — a
      different kind of text than an operation's permission-viewer sentence, that happened to share
      one id purely because both namespaces (UI copy and route operations) now live in the same
      `i18n.json`. Checked every operation id against every UI-text id already used in
      `apps/example/frontend/src`; this was the only collision. Resolved by renaming the
      *button's* id to `files.deleteFile` (the smaller, purely-internal change — nothing user-visible
      moves, since its Dutch text is unchanged) rather than moving the already-shipped, ADR-documented
      operation id. The completeness test (`apps/example/tests/test_control_plane.py`) is
      mutation-checked: deleting one operation's Dutch entry turns it red, naming exactly that id;
      it also refuses a Dutch entry that is just the English label copy-pasted verbatim.
      **Two things this does not yet close, found by review rather than left implied:** (a) the
      Studio's own viewer does not read this file at all yet — `endpointAction.ts` copies the
      English `label` verbatim into both its Dutch and English output, so the translation exists in
      the checkout but nothing renders it; wiring that reader is separate, un-started work, and ADR
      0102's amendment now says so honestly instead of implying it already happens. (b) this
      completeness test is hand-written once, against this one app's catalog and i18n file — any
      other app built on the framework gets no automatic protection against a missing translation
      unless it copies this test by hand. Neither is phase 6's job (phase 6 is catalog-membership and
      coverage, not translation completeness), so both are recorded here as open rather than folded
      into a phase they do not belong to.

## Phase 6 — enforcement

- [x] **6.1 `operations_reference_catalog`** (no-drift) and **`routes_declare_operation`** (coverage)
      in `terp-spec`: catalog entry, corpus cases, generated rule docs, guide topic, and the parity
      tests. Shipped as terp-spec 0.29.0 (committed to that repo's `main`; not yet released — see
      the note below). `operations_reference_catalog` mirrors `events_reference_catalog` exactly:
      a bare string or an inline `OperationDefinition(...)` is drift wherever an operation is
      named (the `operation(...)` marker, or a CRUD factory's five `*_operation=` keywords).
      `routes_declare_operation` mirrors `routes_declare_response_model`'s coverage shape, but with
      a real design difference this pairing forced into the open: coverage is the *app's own
      choice* (off/warn/strict), so the rule cannot fire unconditionally the way response-model
      coverage does — it must find the app's chosen coverage level first. The static check reads a
      sibling `control_plane/`'s `OperationCatalog(coverage=...)` (the same convention
      `policy_refs_resolve` already uses for the permissions registry), and also checks inside the
      scanned root itself — the corpus harness copies a case's whole directory into the tree it
      scans and can never place a true sibling, so a corpus case declares its catalog inside that
      tree instead; a real app's convention (control_plane as an actual sibling) is unaffected.
      Both rules' `title`/`intent` passed `test_normative_prose_is_stack_neutral` without needing
      a rewrite — the ADR's own stack-neutral framing carried over directly.
- [x] **6.2 The `terp.arch` checks**, on the phase-1.4 helper (`iter_route_registrations`),
      registered in `_ALL_RULES`, `GUIDE_TOPIC_BY_RULE` (a new `operations` guide topic, with a
      full authoring recipe in `terp guide operations`), and `test_arch_harness.py`'s required
      `test_<rule>` pair — each mutation-checked (dropping the no-drift detection, dropping the
      `build_crud_router` scan, dropping the strict-coverage gate, and dropping the missing-crud-
      operation report each independently turn their test red). Fixed a real gap this surfaced
      immediately: `realtime`'s WebSocket route (`subscribe_websocket`) had been deliberately left
      undeclared in phase 5 on the (wrong) assumption that operations were an HTTP-only concept —
      the *runtime* half already covers WebSocket routes (proven by an existing test), so leaving
      it undeclared would have refused the boot the moment coverage went strict. Declared
      (`REALTIME_SUBSCRIBE_WEBSOCKET`) and translated before proceeding.
- [x] **6.3 Escape-hatch budgets** — no update needed. Every route in every capability and the
      example app already declared a real operation from phase 5, and both new rules' own
      implementations needed zero opt-outs anywhere; `apps/example/escape-hatch-budget.json` is
      unchanged from before this whole effort started (see that file for its current entries — not
      restated here, for the same reason the operation count above isn't). A budget update genuinely
      was not needed, which is itself worth recording rather than leaving unstated.
- [x] **6.4** Flipped `apps/example/control_plane/operations.py`'s `operation_catalog` to
      `OperationCoverage.STRICT`. Both `app.main:build()` and `app.main:build_base_profile()` boot
      successfully under it — measured directly, not inferred from phase 5's own bookkeeping — which
      is the actual proof phase 5's annotation work was complete, not merely believed to be.

**A structural blocker, worth recording precisely rather than working around silently:** the two
new rules are implemented, tested, and registered in terp-framework's source, verified correct by
locally substituting the terp-spec checkout for the pinned release (`uv pip install -e ../terp-spec`,
the same substitution terp-spec's own CI does before a release) — but the *committed* dependency
pins (`pyproject.toml`'s `terp-spec==0.27.0`, `package.json`'s `"@terpjs/spec": "0.27.0"`) stay at the
last real release. Bumping them to `0.29.0` was tried and reverted: `uv.lock` cannot resolve a version
that has not been published (`uv lock` would fail outright), so a phantom pin bump only traded one
kind of inconsistency for another. The one consequence, left as a single clearly-named red test rather
than hidden: `test_backend_catalog_matches_the_rule_registry` fails against the real 0.27.0 catalog
with `rules shipped without a spec/catalog/backend entry: ['operations_reference_catalog',
'routes_declare_operation']` — an accurate description of the actual state (the code is ready; the
release is not), not a regression. It resolves itself the moment terp-spec 0.29.0 is tagged and
published and terp-framework's pins are bumped to match — the one remaining step, and it needs a
human's authorization (pushing a tag is what triggers terp-spec's `release.yml` to publish to PyPI
and npm, an outward-facing, effectively irreversible action once a package version ships).

## Open questions

1. ~~Is `strict` the eventual default, or permanently opt-in?~~ **Settled 2026-08-26: yes, `strict`
   is the destination default**, recorded as an amendment to ADR 0102 (§6). The flip happens in the
   enforcement phase, after the framework's own routes are annotated — doing it sooner refuses the
   boot of every app, this repository's example included.
2. ~~Where do an app's operation translations physically live?~~ **Settled 2026-08-27: the
   operation id is the i18n message id**, and translations live in the app's `frontend/i18n.json`
   — the same catalog ADR 0105 already ships, reused rather than duplicated. Recorded as an
   amendment to ADR 0102 (§3). Phase 5.5 shipped the completeness half (a mutation-checked test
   fails the gate when a declared operation has no matching `i18n.json` entry, or when its entry is
   just the English label copy-pasted). **Not yet true: "so the Studio can read them."** The
   location is settled and the file is populated, but the Studio's own viewer does not read it —
   it currently renders the English label verbatim regardless of locale. Wiring that reader is
   separate work, not started, and not implied to be done by this being marked settled.
3. **Should `operation` subsume `read_only`?** Both are route-level declarations about one handler
   and both now live in `terp.core.routing`. They answer different questions (what this does for a
   person; whether it may persist), so they stay separate — but if a third and fourth marker
   appear, the case for one declaration object with several fields gets stronger, and §5 of ADR 0102
   is the constraint that argument has to clear.
