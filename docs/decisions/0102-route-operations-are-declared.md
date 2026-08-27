# 0102 — A route's operation is declared, not inferred from its name

- **Status:** Accepted
- **Date:** 2026-08-26
- **Relates:** [ADR 0006](0006-cross-cutting-controls-and-opinionation-policy.md)
  (the Tier A/B/C policy and the quadruple rule this control is built to satisfy — and §"Model /
  route / schema authoring stance", whose Level-2 refusal is the guardrail in §5),
  [ADR 0008](0008-event-bus-catalog-and-typed-emit.md) (the catalog-with-no-drift shape copied
  here), [ADR 0011](0011-model-traits-vs-control-plane-policy.md) (a view is never a second
  source of truth), and `terp-studio` ADR 0004 (the plain-language principle the reader-facing
  half of this serves).

---

## Context

The Studio's Permissions tab renders one row per mounted route. A row reads:

```
DELETE   /api/v1/files/{file_id}   write   role:admin   —
```

Its intended reader is an ICT'er without programming experience (`terp-studio` ADR 0004). Four
columns of transport detail is not a permission model they can check, and two of the columns are
worse than merely technical.

**The read/write column carries no authority.** `terp.cli.access._endpoint_json` computes it from
the HTTP method alone. It restates the method badge beside it, and it invites a false reading: the
boot check `_validate_policy_write_tiers` deliberately permits a module to gate reads and writes
at the same tier — its own words are "Equality is allowed (a flat or admin-only model)" — and the
files capability is exactly that shape, `Policy(read=ADMIN, write=ADMIN)`. On that module "read"
never implied "cannot write". The framework already knows the method-derived axis is imperfect:
`declared_read_only_routes_do_not_write` exists precisely because the mapping "is right for almost
every route and blind to one".

The honest per-endpoint fact is already in the payload. `requirement` is the requirement the kernel
guard actually applies to that method, so it is the authority for that one route.

**What the route does has no declared answer at all.** Surveying every route registration under
`packages/backend/capabilities` and `apps/example` (reproduce with
`grep -rhA2 "@router\.\(get\|post\|put\|patch\|delete\)" --include=*.py`) shows the platform's
route names are already a small, regular vocabulary: a verb, an underscore, a noun. Most verbs are
the CRUD five; a handful (`mint_ticket`, `provision_user`, `reap_expired_now`) are domain-specific
and read badly when mechanically reframed. So a label *can* be derived from the name for most of
the surface — and that derivation is what this ADR keeps as its safe default, not what it settles
for.

Deriving alone fails three ways that matter:

1. **It cannot be translated.** A name is source-language English. The Studio is Dutch-first, and
   its audience is the half of the product that most needs plain language.
2. **It cannot be guaranteed.** A derived label is always *available*, so nothing is ever missing,
   so nothing is ever enforced. There is no state in which the platform can say every route is
   explained.
3. **It is anonymous under the factory.** `build_crud_router` names its five routes `list_items`,
   `create_item`, `get_item`, `update_item`, `delete_item` — measured, no entity noun, no summary,
   no docstring. Every module built with the Tier-C factory derives the same five labels, and the
   factory is the path this framework recommends for canonical CRUD.

## Decision

**A route may declare the operation it performs, as a typed reference to an entry in a control-plane
catalog.** The declaration carries a stable id and a source-language label, and nothing else.

This is a Tier-A control in ADR 0006's sense, and it ships as the quadruple that policy requires:

| Requirement | How it is met |
|---|---|
| Typed registry with a safe default | `OperationCatalog` on `ControlPlane`, defaulting to empty; where no operation is declared the label is derived from the route name |
| Fail-closed runtime control | Boot rejects a declared operation absent from the catalog; under strict coverage, boot rejects a route with no declaration |
| Build-time test | `operations_reference_catalog` and `routes_declare_operation` in the Terp Standard |
| Budgeted escape hatch | `# arch-allow-routes-declare-operation: <reason>`, ratcheted by the app's escape-hatch budget |

### 1. It is called an operation, not an action

`terp.core.audit` already defines `AuditAction` — the persistence lifecycle verb
(`CREATED` / `UPDATED` / `DELETED`). A route-level `Action` beside it would put two unrelated
concepts under one word in one namespace. "Operation" is OpenAPI's own term for a method-and-path
pair, which is exactly the unit being named, and it is the term the label's second consumer (§4)
already uses.

The Studio's user-facing column is still headed *Actie* / *Action*. Code vocabulary and
plain-language UI are deliberately allowed to differ; that is the whole content of `terp-studio`
ADR 0004.

### 2. The declaration is a route-level marker, and that seam already exists

`terp.core.routing` is titled "Route-level declarations a module makes about one handler" and has
held exactly one member, `read_only`. The operation declaration is the second, built to the same
shape: a decorator applied below the route decorator, stamping an attribute read through a
predicate rather than directly.

```python
@router.delete("/{file_id}", status_code=204)
@operation(OPS.FILES_DELETE)
def delete_file(file_id: uuid.UUID, session: SessionDep) -> None: ...
```

Choosing a marker over a routing-call keyword is deliberate. It leaves FastAPI's own signature
untouched, keeps the declaration greppable next to the handler it describes, and means the
introspection path is a `getattr`, not a parse.

### 3. The label is an id plus a fallback, never a set of languages

`@terpjs/react-core` already settled how this framework carries translatable text:
`UiText = string | { id: string; message: string }` — "a stable `id` for a translation catalog plus
the source-language `message` used as the fallback", so "an app can go from hardcoded strings to a
full i18n runtime without changing call sites". `LocaleCatalog` is the catalog side, and a
completeness test pins the bundled Dutch catalog to the framework's string keys.

`OperationDefinition` follows it exactly: an `id` that is the translation key, and a `label` that is
the source-language fallback. **No call site names a language.** Adding a language is a new
catalog, not a sweep through every declaration in every app — which is the difference between a
translatable platform and one where "support French" is a breaking change.

**Amended 2026-08-27: the operation id is the i18n message id; translations live in the app's
`frontend/i18n.json`.** This settles the open question of where an app's operation translations
physically live so the Studio can read them with no running app. ADR 0105 gave every generated
app exactly one catalog for this shape — `{sourceLocale, locales: {<locale>: {label,
allowIdentical, messages: {<id>: <message>}}}}` — keyed by the same `{id, message}` pair
`OperationDefinition` already carries. Reusing it costs nothing new: no second catalog format,
no new per-app file, no new wiring, and the Studio reads it the same way it already reads design
tokens and module slots — straight from the checkout.

This does not, on its own, make an operation's translation *complete* the way ADR 0105 makes UI
copy complete. `frontend/no-untranslated-ui` and `frontend/locale-catalogs-complete` inventory
literal JSX/TS copy under `src/**`; neither scans a backend `OperationDefinition`, so a declared
operation with no matching `i18n.json` entry currently fails silently rather than failing the
gate. Phase 5.5 of the route-operations plan is the completeness half this amendment does not
supply on its own: a check shaped like `locale-catalogs-complete` but keyed off the app's
`OperationCatalog` rather than a source scan.

### 4. The label feeds OpenAPI, so it is not a field with one reader

No route in this framework sets `summary` or `operation_id` today; operation ids are FastAPI's
generated mangling and summaries are absent. A declared operation populates both. The permission
viewer is therefore one reader among several — the exported document, generated clients, and
`terp openapi` all improve — which is what makes this declaration pass the "name the consumer"
test that ADR 0099 applies to every addition.

It also makes the reverse a defect: a hand-written `summary=` beside a declared operation is two
answers to the same promise, the failure `declared_read_only_routes_do_not_write` names in its own
intent. The rule refuses it.

### 5. What the declaration must never grow into

ADR 0006 permits an opt-in route factory and refuses "a declarative model/route DSL" as the only
path, because it "fights SQLModel/FastAPI idioms, caps flexibility, and moves bugs into an opaque
generator". An operation declaration is safe while it names *what the route does for a person*. It
becomes the refused DSL the moment it also carries method, path, authorization or response shape.

**`OperationDefinition` carries an id and a label. Adding a routing or authorization field to it is
a decision that must supersede this ADR, not an increment to it.**

The corollary, inherited verbatim from `read_only`: declaring an operation **never changes
authorization**. A route's requirement comes from its module's `Policy` and any route-level
permission dependency, exactly as before. Declaring what a route does narrows nothing about who may
call it.

### 6. Coverage is optional; catalog membership is not

This is the split `terp.core.events` already draws — "the event bus is an optional product feature:
an app that declares no events simply has none, with no ceremony. What the framework *does*
guarantee is no drift".

- **Catalog membership is always enforced.** A declared operation not in the catalog fails the boot,
  and the build-time rule refuses a bare-string or inline-literal operation. There is no mode in
  which an operation can be invented at a call site.
- **Coverage is a per-app setting** with three states: `off` (the default — an app that declares
  nothing behaves exactly as it does today), `warn` (undeclared routes are reported and the Studio
  marks their labels as derived), and `strict` (boot refuses a route with no declaration).

`strict` is the state in which the platform can claim every route is explained.

**Amended 2026-08-26: `strict` is the destination default.** The original text left this open,
and leaving it open was the wrong call — a coverage default is not a detail to settle later,
because every app that adopts the framework in the meantime adopts whichever default it finds.
The platform's stated posture is that the most secure, most enforced standard is the default
(ADR 0103), and a control that is off unless someone opts in is not a default, it is a feature.

The flip is sequenced, not immediate, and the sequence is load-bearing rather than cautious:
`strict` refuses the boot of any mounted route that declares no operation, so switching the
default before the framework's own capability routers and the example app are annotated would
refuse the boot of every app including this repository's own test suite. The default therefore
changes in the enforcement phase, after annotation, and an app that cannot annotate on that
timetable sets `OperationCoverage.WARN` explicitly — a visible, greppable line, which is what the
ideology asks an escape to be.

`off` remains reachable and remains honest about what it is: no coverage guarantee at all.

### 7. The factory declares operations too

`build_crud_router` gains the ability to carry operations for the five routes it builds, and it
names those routes after the entity rather than `item`. A factory-built module is otherwise
undeclarable, which would make `strict` unreachable for exactly the modules the framework tells
consumers to build with sugar.

## Consequences

- **The permission viewer becomes readable**, and loses a column. The access graph stops emitting
  the method-derived read/write `kind`: once the viewer no longer renders it, nothing reads it, and
  a field without a reader is removed rather than kept.
- **The framework must annotate its own routes before it can enforce the rule.** Six capabilities
  are held to "clean with zero opt-outs" by `tests/architecture/test_capability_arch.py`, so their
  routes cannot be deferred behind a budgeted marker. The enforcement phase therefore lands last,
  after the framework is already clean.
- **A scaffolded app pays nothing.** `template/project/app/modules` ships no router, so a new
  project starts with no routes to declare and adopts the vocabulary as it adds modules.
- **A hand-authored label can lie in a way no test catches.** "Delete a file" on a route that soft
  deletes is wrong and mechanically undetectable — a derived label could not drift from its
  function name, and an authored one can. This is a real cost of the decision, accepted knowingly:
  the same cost every docstring in the platform already carries, and reviewable in the same way.
- **Adding a route-level declaration forces two consolidations** that the growth of this seam makes
  overdue: the HTTP method vocabulary duplicated between `terp.core.app` and `terp.cli.access`
  (whose own comment admits it mirrors the kernel), and `PERMISSION_DEPENDENCY_ATTR`, which is
  defined in `terp.cli.access` although it is stamped in `terp.capabilities.access` and belongs
  with the other route markers in `terp.core.routing`.
- **Route discovery in `terp.arch` gets one implementation.** Several rule modules independently
  walk the AST for route decorators and `add_api_route` calls; a nineteenth route-touching rule is
  the point at which that duplication is extracted rather than extended.
