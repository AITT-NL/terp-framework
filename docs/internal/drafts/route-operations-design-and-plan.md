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

## Phase 4 — OpenAPI, so the field has a second reader

- [ ] **4.1** A declared operation populates the route's `summary` and `operation_id`.
- [ ] **4.2** Refuse a hand-written `summary=` on a route that declares an operation — two answers
      to the same promise.
- [ ] **4.3** Regenerate any checked-in OpenAPI artifacts and confirm the drift checks pass.

## Phase 5 — annotate the framework

Order matters: the capabilities in `_CLEAN_CAPS` must be clean with **zero** opt-outs, so they
cannot be deferred behind a marker and are done first.

- [ ] **5.1** Catalogue and annotate the `_CLEAN_CAPS` capabilities' routes.
- [ ] **5.2** Catalogue and annotate the remaining capabilities' routes.
- [ ] **5.3** Annotate the example app, including the factory-built module via 1.3.
- [ ] **5.4** Decide the kernel routes' treatment — health and friends sit outside any module and are
      already reported separately. Either label them once in the framework or exempt them
      explicitly; an unexplained exemption is the thing this whole change exists to prevent.
- [ ] **5.5** Ship the Dutch catalog for the framework's own operations, pinned by a completeness
      test against the operation-id set — the same shape as the existing locale completeness test.

## Phase 6 — enforcement

- [ ] **6.1 `operations_reference_catalog`** (no-drift) and **`routes_declare_operation`** (coverage)
      in `terp-spec`: catalog entry, corpus cases, generated rule docs, guide topic, and the parity
      tests. Normative prose must stay stack-neutral — `test_normative_prose_is_stack_neutral`
      forbids naming FastAPI or a decorator in the rule text.
- [ ] **6.2 The `terp.arch` checks**, on the phase-1.4 helper, registered in `_ALL_RULES` — a
      meta-test in `test_arch_harness.py` fails if a `check_*` function is not registered.
- [ ] **6.3 Escape-hatch budgets** updated wherever a marker is genuinely needed, each with a
      justification.
- [ ] **6.4** Flip the example app to `strict` as the worked reference.

## Open questions

1. ~~Is `strict` the eventual default, or permanently opt-in?~~ **Settled 2026-08-26: yes, `strict`
   is the destination default**, recorded as an amendment to ADR 0102 (§6). The flip happens in the
   enforcement phase, after the framework's own routes are annotated — doing it sooner refuses the
   boot of every app, this repository's example included.
2. ~~Where do an app's operation translations physically live~~ so the Studio can read them without
   a running app? **Settled 2026-08-27: the operation id is the i18n message id**, and translations
   live in the app's `frontend/i18n.json` — the same catalog ADR 0105 already ships, reused rather
   than duplicated. Recorded as an amendment to ADR 0102 (§3). Phase 5.5 still owes the
   completeness half: nothing yet fails the gate when a declared operation has no matching
   `i18n.json` entry.
3. **Should `operation` subsume `read_only`?** Both are route-level declarations about one handler
   and both now live in `terp.core.routing`. They answer different questions (what this does for a
   person; whether it may persist), so they stay separate — but if a third and fourth marker
   appear, the case for one declaration object with several fields gets stronger, and §5 of ADR 0102
   is the constraint that argument has to clear.
