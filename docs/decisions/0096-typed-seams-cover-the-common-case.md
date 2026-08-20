# ADR 0096 — Typed seams cover the common case, or code goes around them

- Status: Accepted
- Date: 2026-08-20
- Relates to: ADR 0092 (the generated route table this extends), ADR 0044 (`GET /me`),
  ADR 0017 / ADR 0029 (the predicate registries the permission projector mirrors),
  ADR 0004 / 0022 (role rank — what the UI gate had and why it was not enough),
  ADR 0041 (the generated, gitignored typed client), ADR 0059 (no severity dial: every
  boundary violation is an error, which is why a refusal's *wording* is a control)
- Rejects, with reasons: a general-purpose `Dialog` component; `terp.arch` owning
  sibling-package import graphs (§Alternatives)

## Context

Friction reported from building a control-plane-plus-worker app on Terp. The report's own
framing is the useful part: it separated "rules that are satisfiable but annoying" from
**holes** — a checked seam that does not cover the common case, so the compliant path is
not available and code goes around it. Four of those, and they share one shape.

Verifying them first changed the list, which is worth recording because it is the reason
this ADR is smaller than the report:

- Two were **already closed**. The lease-with-heartbeat gap is ADR 0095. The
  "declared-but-unreachable filter" defect — described as *built into* `resolve_filters` —
  was fixed in `2d9c618`, which is an ancestor of the 0.6.1 the reporting app pins;
  `filtering.py` checks the name *before* dropping `None` and its docstring argues that
  exact case.
- One was **wrong as framed**. `--profile full` already regenerates the typed client from
  the live app and then typechecks against it, which is stronger than a drift check because
  the client is gitignored (ADR 0041) — there is nothing to drift from.
- One turned out to argue **against** the fix requested for it (§4).

What remains is genuine, and the common shape is: the seam checks the thing the framework
found easy to check, and the *case authors actually have* falls outside it. A seam that
covers 60% of uses is not 60% of a guarantee — it is close to none, because the 40% takes
the whole screen out of the checked path with it.

## Decision

### 1. Route search params: the query string joins the checked table

`useTerpNavigate` took `to` and `params`. Every list screen's filters, sort and page cursor
live in the **query string**, so a screen with a filter had to reach for the router's own
`useNavigate` / `useSearch` — and lost path and param checking on the way out. The reported
app had five of six screens outside the seam. The guarantee ADR 0092 bought was therefore
absent on the majority of screens, which is close to the worst possible distribution: it
held exactly where a typo was least likely.

A manifest route now declares its keys (`search: ["status", "page"]`), `terp routes` emits
a second `TerpRouteSearchTable`, and `useTerpNavigate` / the new `useRouteSearch(path)` are
checked against it. Three deliberate limits:

- **Keys, not types.** Every value is `string | undefined`. A query parameter is text and
  is absent until set; parsing `page` into a number is the screen's business. Declaring a
  *validation* language here would be a much larger seam and would put coercion rules in a
  manifest, where they cannot be tested against the screen that reads them.
- **Replace, not merge.** `navigate({ to, search })` replaces the search. Merging reads as
  convenient and is wrong for the case this exists to serve: clearing a filter means
  sending the key as `undefined`, and a merge would keep the old value — so "clear" would
  silently not clear. A screen that wants to keep other keys passes them, which is also the
  only form that stays checkable against the declared set.
- **Only declared keys are returned.** `useRouteSearch` does not surface a key the route
  did not declare, so a stray key someone hand-typed into the URL cannot reach a screen's
  logic. The declaration is the surface.

A route that declares no keys gets `Record<never, never>`, so passing `search` to it is a
typecheck error rather than a value dropped silently into the URL; before `terp routes` has
generated, the shape stays loose, so an app that has not adopted is unaffected.

### 2. `GET /me` projects the caller's named permissions

`useCan` compares role **rank**, because rank was all the wire carried. A screen whose
write needs a named grant (`definitions.publish`) had nothing to ask: it hid by rank as a
proxy and handled the 403 anyway — showing a button it knew might fail, or hiding one the
user was entitled to. Both are wrong, and neither is detectable from the client.

`CurrentUser` now carries `permissions`, filled through a **registry seam**
(`register_permission_projector`) rather than an import: the access capability registers its
grant lookup at import, exactly as a scope predicate does, so auth and identity never import
the capability that owns grants and an app that mounts no grant capability projects an empty
tuple. Several projectors union (grants plus, say, a licence-derived set).

`usePermissions()` / `useHasPermission(name)` read it, and `Authorized` takes an optional
`permission` **alongside** `action` — both must pass, which is what the server does: a
`Policy` carrying a `Permission` enforces the permission's rank floor *and* the grant, so a
UI checking one of the two would disagree with the endpoint in one direction or the other.

The DTO field and both hooks say the same thing in their docstrings: this is a **display**
input. The guard re-checks every request, and a client that treats the list as authority has
moved the gate to the wrong side of the wire.

### 3. Downloading a generated artifact

`useFileDownload` covers a stored `FileMeta` id. An artifact the backend **generates** — a
revision's evidence bundle, a CSV export — has no stored id, and the only routes to it were
a raw `fetch` (refused: one typed egress path) or a raw `<a href>` (no bearer token, so it
401s or silently saves an error page under the intended filename). The reported outcome was
the feature being dropped.

`useEndpointDownload()` reaches any authorized GET through the session client and hands the
bytes over as a named download; `saveBlob` is the blob-to-anchor dance extracted once, with
the object-URL revoke in a `finally` (the leak every hand-rolled copy forgets), and
`useFileDownload` now uses it too. `path` is a plain string — unusually — because the
generated client is keyed by the app's own schema, which this package cannot see, and a
byte-stream route is app-specific by nature. Everything that matters is still the client's:
base URL, bearer token, credentials, and a rejection on non-2xx instead of a saved error
body. An unfilled `{placeholder}` fails closed rather than requesting a literal `{id}`.

### 4. The dialog refusal states the alternative, and we ship no general `Dialog`

The report asked for a general `Dialog`: the boundary lint bans raw `<dialog>` and react-core
ships only `ConfirmDialog`, so "a ban with no replacement is only obeyable by not building
the feature."

The cited evidence says otherwise, and it is the reporting app's own comment:

> *Editing happens in the expanded row rather than a modal because react-core ships no
> general dialog — **and it turns out to be the better shape anyway**: the row stays
> visible, so the finding that sent the author here is still on screen while they fix it.*

The feature was built, differently, and better. Shipping a general `Dialog` would remove the
pressure that produced that outcome, and would do it on the strength of a report whose own
example contradicts the request. So we do not ship one.

What *is* a real defect is the refusal's **wording**. "Use ConfirmDialog" is right for a
confirmation and wrong advice for an edit form, and an author who reads it for one concludes
the framework is missing something and the rule cannot be obeyed. Under ADR 0059 every
violation is an error with no severity dial, which makes the message the control: it is the
only thing standing between a refused build and a correct fix. The `dialog` refusal now
names the alternatives (a routed page, or an expanded row beside the thing it edits) and
asks for a report rather than a raw `<dialog>` if neither fits. `BOUNDARY_SPEC` grew a
`restrictedElementGuidance` map so any other element whose named replacement does not fit
every case can say so; every element without an entry keeps its plain one-line refusal.

### 5. Sibling-package boundaries: `terp guide package-boundaries`

An app whose worker cannot run under the gate keeps a second top-level package, and the
report wanted `terp check` to own the "these two never import each other" contract —
replacing six hand-rolled AST tests.

We are answering with a recipe, not a rule, because the platform has already delegated
this: `[tool.importlinter]` in our own `pyproject.toml` is how the layer-0 keystone is
expressed a second, tool-independent way, and AGENTS.md says generic layering checks belong
to import-linter while only domain-specific rules are hand-rolled. A checked-in contract
expresses all three of their boundaries (no `app` from `engine`, no `engine` from `app`,
plugins only via the registry) and fails with the offending import chain. Their
SQL-literal-containment test is `no_dynamic_sql`, which already exists. The new guide topic
writes that out, including the two-command gate (`terp check` over `app/`, `lint-imports`
over both) and the point that neither package may import the other but **both may import a
third** — which is how a shared contract package replaces twin modules pinned by a
drift test.

## Alternatives considered

**A general-purpose `Dialog` component.** Rejected in §4 on the report's own evidence. If a
case arrives that neither a routed page nor an expanded row covers, the refusal now asks for
it to be reported — and that report will carry the design constraints this one did not.

**`terp.arch` gaining a declarable package-graph rule.** Rejected in §5: it would be a
second, weaker copy of import-linter inside a harness whose stated scope is Terp semantics.
The cost of the recipe is one config block in the app; the cost of the rule is a graph
engine we would then own.

**Typed / validated search params.** Rejected for now in §1: it puts coercion in a manifest,
away from the screen that reads the value. Declaring the *keys* removes the failure the
report actually hit (a screen outside the checked seam) without that.

**Putting `permissions` in the access token instead of `/me`.** Rejected: a token is cached
until it expires, so a revoked grant would keep showing its button for the token's lifetime,
and grants would inflate every request header. `/me` is already the live-record read (ADR
0044) — it resolves through the revocable principal provider, so the projection is as fresh
as the identity beside it.

## Consequences

- A list screen can stay inside the checked seam. Adopting is per route (`search: [...]` in
  the manifest, then `terp routes`); a route that declares nothing behaves exactly as before.
- `GET /me` gained a field. Additive and defaulted, so an existing client ignores it — but
  the committed OpenAPI contracts and the pinned `/me` bodies regenerate, which is the churn
  in this change.
- A UI can hide precisely what the server would refuse. It can also now *lie* more
  convincingly if someone treats the projection as authority, which is why three docstrings
  and the DTO field all say it is display-only.
- The `dialog` refusal is longer. That is the point: it is the only thing an author sees at
  the moment they are blocked.
- Still open, deliberately: FK labels on list DTOs (a convention decision — a declared
  read-only label field versus a batch `?ids=` — that belongs with the DataView repository
  seam), a `terp-cap-secrets` reference-and-provider seam, and deriving
  `layout-contract.json` from one declaration instead of two.
