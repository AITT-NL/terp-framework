# 0197 — A public site is a client of an app, and the framework defines the socket it plugs into

- **Status:** Proposed (awaiting review). Amends [ADR 0123](0123-marketing-websites-are-not-a-terp-application-kind.md)
  §4, the closing paragraph of §1 and the first of its consequences, and keeps the reasoning
  of its §1–3 and all of §5. Revised 2026-11-03 after review: a site reads published content
  from a public route with no credential in its build, it claims no conformance level, and
  §1's closing paragraph is amended openly rather than said to stand. Nothing is built by this
  record: the contract baseline, the rules profile, the lint preset, the starter and the deploy
  recipe are each a later change of their own, listed under "How it will be held". Revised
  2026-11-04: decision 5 no longer says the generated-client rule keeps a page from calling the
  app, and says what does. Item 5 of "How it will be held" is amended by
  [ADR 0198](0198-a-static-site-is-a-web-unit-the-framework-builds-from-a-recipe-it-owns.md)
  (proposed 2026-11-04): the static `web` recipe and a second `web` unit land in the standard
  and the framework's generator.
- **Date:** 2026-11-03. 0182 and 0183 are reserved for other records and 0184 to 0193 are taken;
  0194 to 0197 are this series.
- **Relates:** amends [ADR 0123](0123-marketing-websites-are-not-a-terp-application-kind.md)
  (§4, and its consequence that nothing here changes for websites); applies
  [ADR 0111](0111-flexibility-is-bounded-by-legibility-not-by-capability.md) decision 4 (the
  framework owns the socket, not the plug) and decision 5 (a declaration two programs read lives
  in the spec); stays inside [ADR 0181](0181-terp-supplies-the-inside-of-a-deployable.md)
  decision 1 (one deployable, one contract, one identity authority),
  [ADR 0090](0090-a-table-has-one-owning-history.md) (a table has one owning history) and
  [ADR 0060](0060-projects-is-example-code-base-profile-closure.md) (a business noun is an app
  module, not a capability); uses
  [ADR 0088](0088-service-principal-credentials.md) (why a build is handed no service principal:
  one is authorized exactly as a person with its role), [ADR 0184](0184-a-deployment-declares-its-units.md) (the deployment declaration and
  the owner of each fact in it), [ADR 0124](0124-a-declared-variable-may-name-the-services-that-see-it.md)
  (a variable names the services that see it, so the API's base URL reaches only the
  build unit), [ADR 0084](0084-runtime-applicability-classification.md)
  (the runtime-applicability vocabulary), [ADR 0093](0093-semantic-token-layer-and-named-themes.md)
  (the token layer that travels) and [ADR 0104](0104-the-spa-document-carries-its-own-security-headers.md)
  (the security-header posture a static host can carry); reaffirms
  [ADR 0059](0059-strict-frontend-boundary-and-escape-hatch-budget.md) and
  [ADR 0175](0175-the-frontend-boundary-does-not-stop-at-the-module-tree.md) (no modes, and the
  boundary covers all of an app's `src/`); respects
  [ADR 0122](0122-the-catalog-is-frozen-at-its-breadth-and-grows-in-legibility.md) (a profile
  names existing rules and adds none). Supersedes nothing.

---

## Context

ADR 0123 refused two things: widening this framework so that marketing websites can be built
on it, and admitting a second *kind* of Terp application for them. Its reasons were specific.
The domain has no authority seam, so two-layer enforcement collapses (§1); enforced uniformity
removes the capability a site is bought for (§2); and the audience justification inverts, because
the decisions a site needs are ones its author is the expert in (§3). None of that has changed.

It also stated a consequence more broadly than its reasons needed: "No change is made to this
framework, its capabilities, its rule catalog or its templates." And it named the evidence that
would reopen it: a real set of briefs, not a hypothetical one.

Two real briefs now exist.

1. **The Terp family's own public sites.** Brochure pages with their content in the repository,
   no accounts, no managed content, occasionally a form. They need fast static pages, the family's
   look through the design tokens, a security floor, and a deployment that is one step.
2. **A content library with a native mobile client and consumer accounts.** The content, its
   editors and approvers, the accounts and each reader's progress belong in an ordinary Terp app,
   which is the content-backend shape §5 already allows. A public website is a plausible later
   client of that app: anonymous, indexed by search engines and branded, none of which the Terp
   frontend supplies.

Neither brief is the evidence §2's revisit condition asks for. That condition is a batch of sites
so alike that only the palette, the logo and the copy differ, so that the pattern would be the
domain. These sites differ exactly where §2 says a site's value lies, so a site kind is still
refused.

What the briefs share is everything *around* the layout, and that is where the trouble was. The
first shape proposed for the content library was a backoffice sharing the database that an
existing sync already fills: two writers on one schema, half an audit trail, and tables the
backend cannot own (ADR 0090). That is what a site improvises when nothing says how it connects.
The other improvisations are as easy to predict and as harmful: a person's token baked into a
build, editor content inserted as raw HTML, a browser call that widens the API's CORS to a public
hostname, a secret in the static output, and a copy of the tokens that drifts the first time
someone edits it to fix a contrast failure locally.

So the line to reopen is the consequence, not the refusal. ADR 0111 decision 4 already says what
the framework owes where it does not ship the implementation: a definition of **what such a thing
must declare about itself**. A site needs a socket, and the family can ship a reference plug for
it, without a site ever becoming a kind of Terp application.

## Decision

### 1. ADR 0123's reasoning stands; §1's closing paragraph is amended openly

§1's reasoning holds: a site has no authority seam, so it would inherit only the build-time
half of two-layer enforcement, and that is why it is not a kind of Terp application. Its
closing paragraph said that what would transfer (a token system, a lint rule set, a
scaffolder) is "none of it this framework". That paragraph is amended: the Terp family now
ships those three things, from this repository and the spec, as build-time tooling for a
site. They carry no Terp guarantee to it, and nothing here says otherwise. §2 and §3 stand
unchanged.

A site is not a Terp application kind. No `site` value joins the layout manifest's `contract`
vocabulary, no page archetype is added for a public page, and the frontend primitives are not
split into a package for sites. No relaxed zone and no mode is added to an app's frontend: ADR
0059's "no modes" and ADR 0175's "the boundary covers all of `src/`" are reaffirmed, not
excepted. A public page never ships inside an app's single-page app, whose router is gated behind
login as a whole and whose every screen is held to one checked layout. A public page needs the
opposite on both counts.

### 2. A site is a client of one app's API, never of its database

A site that shows managed content reads it from the one Terp app that owns it, through that app's
API, at build time. That is the rule every other client follows: one contract and one identity
authority (ADR 0181 decision 1), and one owning history per table (ADR 0090). Nothing about a site
connects to the app's database.

The app stays the content backend §5 describes, unchanged: editors and approvers on the existing
role model, a trail on every change, media through the files capability, and a read of published
content for the site as one of its own module's endpoints. Business nouns such as a content type
or a publish workflow are that app's modules, not capabilities.

### 3. The socket: five things a site declares about itself

| Part | What the site declares | Where the fact lives | What it may never be |
|---|---|---|---|
| Content source | `repo` (content in the site's own tree) or `api` (published content from one Terp app) | the site manifest; for `api`, the base URL is a declared variable per environment, because it is an environment fact (ADR 0184 decision 2) | a database connection, or members-only content, which stays behind the app's API and is never built into static output |
| Authentication | none: what a public site shows is public, so the app serves its published content from a public, rate-limited read route (ADR 0148), and the build reads it anonymously | the app's own route declaration | any credential handed to a build: a person's token, a shared account, or a service principal, which is authorized exactly as a person with its role (ADR 0088 §4) and so cannot be held to published content |
| Rebuild trigger | `none` (rebuilt when it is deployed) or `webhook` (the app's publish event asks the deploy tool for a rebuild) | the site manifest | a rebuild that needs a new image |
| Rules profile | `site`: the subset of the Terp Standard's frontend rules a site is held to (decision 5) | the site manifest names it; the profile's words live in the spec | the application profile's uniformity rules |
| Deployment unit | a `web` unit built from the checkout; for an `api` source, also a `one-shot` build unit that runs inside the environment, where the API is reachable, and writes the site to a volume the `web` unit serves | `deployment.json` (ADR 0184) | a free image, an image build that fetches content or holds a secret, a build unit that receives the app's own environment, an `/api` proxy it did not declare, or a hostname in the API's CORS when its pages make no browser call |

Facts keep the owners ADR 0184 gave them. Units, volumes and the variable names a unit needs are
in `deployment.json`. Variables, whether each is secret and where each is required are in
`environment.schema.json`. Hostnames, TLS and CORS are environment facts, held by whatever records
environments. The **site manifest** is one file that holds only what no existing declaration can:
the content source, the rebuild trigger and the rules profile. Once a deploy
tool reads it as well as the site's own build, which wiring the rebuild trigger makes the case, it
is a declaration two programs read. Its schema then goes to the spec under ADR 0111 decision 5,
versioned and fixture-checked as ADR 0186 describes.

Three more facts belong to the socket, because a site cannot be safe without them:

- **No credential is ever handed to a build.** A site build runs the site's own third-party
  dependencies, so it must hold nothing worth stealing. Published content is public by
  definition, which is what lets the build read it anonymously; anything that is not public
  stays behind the app's API and is never built into a site.

- **Content arrives as data, never as markup.** Editor content is rendered from Markdown or a
  structured form. HTML from the API is never inserted into a page.
- **The contract is a pinned file.** A site that reads an app generates its client from that app's
  committed `openapi.json`, so a change to the shape the app serves is a diff the app's own gate
  can refuse before the site's next build discovers it. Pinning and checking that file is its own
  record, the API contract baseline (ADR 0194); the socket depends on it existing.
- **A site and the app's frontend share no source.** The app's frontend rules cover its own
  tree, so an import from `site/` into `frontend/` would bring unchecked code into the app; no
  import crosses between the two, and the site preset refuses one when it lands.

How a deploy tool picks the recipe that builds a site's `web` unit, whether by a field in
`deployment.json` or by inference from the profile, is not decided here. A field would be a change
to the deployment vocabulary, so it is taken with the spec, by the record that builds the recipe.

### 4. The family ships a reference plug: a site starter, outside the framework

The Terp family ships a site starter: a template of its own, separate from the app template, and
scaffolded by the `terp` CLI. A site made from it is **outside the framework** in every sense a
guarantee depends on. It imports nothing from `terp.*` or `@terpjs/react-core`. It has no
`ModuleSpec`, no archetype and no runtime control, and nothing in this platform's two-layer model
extends to it.

The starter is also only one plug. Any site that makes the five declarations above is as
first-class to the family's tooling as one made from the starter, which is what makes this a
socket rather than a second framework. The starter's build tool is chosen with the starter; the
socket does not depend on it.

### 5. A site is held to the `site` profile, and claims no application level

The `site` profile names the frontend catalog's security rules that mean the same thing on a
static page: no DOM HTML injection, no `eval` or `new Function`, no `javascript:` URL, no
`target="_blank"` without `rel="noopener"`, and the generated-client rule exactly as it stands,
applied to the site's page code. That rule refuses the raw egress primitives the spec's
`restricted-surface.json` lists (`fetch`, `XMLHttpRequest`, `WebSocket`, `EventSource` and
`navigator.sendBeacon`) and sanctions a generated client in their place, which decision 3 has a
site generate. A page that calls the app through that client passes it, so the rule does not
keep a page from calling the app. The build script that fetches published content is not page
code and is outside that rule. It names none
of the rules whose purpose is an app's uniformity: inline styling, stylesheet imports, token-styled
elements, the layout contract, router links and framework markers. The escape-hatch ratchet is the
site's own choice. The exact partition of the catalog's frontend entries is recorded in the spec,
with the profile.

What keeps a page from calling the app is the policy it is served with. For a site built from
[ADR 0198](0198-a-static-site-is-a-web-unit-the-framework-builds-from-a-recipe-it-owns.md)'s
recipe, that is the rendered content security policy's `connect-src 'self'` with no `/api` route
on the site's own origin (its decision 3): the browser refuses a script's connection to any
other origin, and the site's origin has no route to the app. A site that is not built from the
recipe has only the policy its own host sends: the site writes it, the starter ships one
(below), and no Terp check reads it.

The profile adds no rule and varies none; it names a subset of existing ones, so ADR 0122's
breadth freeze is untouched. Each rule in it classifies `runtime.applicability` as
`not-applicable` for this surface, with §1's rationale: there is no runtime to observe.

A site does **not** claim the spec's Level 2. That level builds on Level 1 and requires every
`static-portable` rule, and the profile deliberately leaves out several of them. A site's claim
is its own: its source is checked by the site preset against the `site` profile. What that
claim is called, and what it requires, is recorded in the spec with the profile, together with
the per-surface classification and corpus cases in the site's own source formats. The reference checker is a named preset
of `@terpjs/eslint-boundaries` that parses those formats and attributes its findings to the same
catalog ids.

A site's own threat model is §1's: do not accept spam through a form, do not ship a hostile
third-party script, do not break. The starter answers it with what a static host can carry: a
Content-Security-Policy in the posture of ADR 0104, no analytics or third-party script by
default, and the profile's rules in its CI.

### 6. The tokens are pinned, not copied (amends §4)

§4 copied the tokens into a site's tree rather than depending on a package, "because the platform
releases in lockstep with an application product that a website has no stake in." The reason
holds. The remedy does not need to be a copy. An **exact** version pin of `@terpjs/contract`
decouples a site from the lockstep just as completely, because the site's tokens move only when its
own diff moves the pin. And it keeps three things a copy loses:

- **Provenance.** The pin names the release whose contrast gate measured those values.
- **The manifest.** `tokens.manifest.json` publishes the five themes, the text and non-text pairs
  the gate measures and the bars it holds them to. A site that adds a brand colour can hold it to
  the same pairs instead of guessing which tokens must stay legible against which.
- **An upgrade path.** Taking a contrast fix is a one-line diff. A copy is a fork with no upstream,
  and it drifts the first time someone edits it to pass locally.

A site takes `tokens.css` and `tokens.manifest.json` from the package and nothing else, and its
lockfile pins the package's own dependencies with it; if that footprint matters to a site,
publishing the tokens as a package of their own is the starter's decision, taken on evidence. The
package's typed client is generated from the framework's own reference app, not from the app a
site reads, so a site never uses it (decision 3). The theme is one of the five named ones, set on
the document exactly as an app sets it. §4's second paragraph stands: the frontend primitives do
not travel.

## Consequences

- ADR 0123 gains a status line pointing here. Its text is otherwise not edited, so the reasoning
  this record keeps is read where it was written.
- The framework gains a site starter template, a site preset in `@terpjs/eslint-boundaries` and a
  guide topic, and the spec gains the `site` profile and its corpus. Capabilities gain nothing for
  sites: the content backend is an ordinary app, and its published read is one of its own routes,
  declared public with a reason and a rate limit.
- An agent asked for public pages in a Terp app has an answer before it improvises one: not in the
  single-page app, not in a relaxed zone, and not against the database, but a site reading the API
  through the socket. `AGENTS.md` says so in one sentence.
- A site that keeps the five declarations can live in its content app's repository, as a `site/`
  directory beside `frontend/` (two frontends are a shape ADR 0110 never flags), or in a
  repository of its own. The pinned contract makes a later move between the two cheap.

## How it will be held

Each part is its own change, in this order, and each is held by its own tests when it lands.

1. **The API contract baseline** (a framework record): a pinned `openapi.json`, a check that
   refuses a breaking change unless the baseline is moved on purpose, and the file published so
   another repository can pin a version of it.
2. **The `site` profile** (a spec release, before the framework pins it): the per-surface
   classification and corpus cases in the site's source formats.
3. **The site preset** in `@terpjs/eslint-boundaries`, run against that corpus by the existing
   parity tests.
4. **The starter template and its guide topic.** Done when the family's own public site is
   rebuilt from it and deploys, and a second site scaffolds without an edit to the starter.
5. **The deploy side**: a static `web` recipe, more than one `web` unit per app, and an on-demand
   rebuild. These land in the workbench and the runner, which record their own decisions.
