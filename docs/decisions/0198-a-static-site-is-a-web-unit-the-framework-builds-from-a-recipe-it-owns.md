# 0198 — A static site is a web unit the framework builds from a recipe it owns

- **Status:** Proposed (awaiting review). Nothing is built yet: the Terp Standard's schema
  word, the generator's second web build and Studio's builder follow as changes of their own,
  in the order decision 7 gives.
- **Date:** 2026-11-04. 0182 and 0183 are reserved for other records, 0184 to 0193 are taken,
  and 0194 to 0197 are the series this extends.
- **Relates:** applies [ADR 0197](0197-a-public-site-is-a-client-of-an-app-and-the-framework-defines-its-socket.md)
  (a site is a separate client and deploys as a unit of the app's deployment); extends
  [ADR 0187](0187-in-the-generated-state-the-framework-renders-the-build-files.md) (in the
  generated state the framework renders the build files) and
  [ADR 0184](0184-a-deployment-declares-its-units.md) (the deployment declares its units);
  keeps [ADR 0062](0062-production-deployment-profile.md)'s SPA image as it is. Studio's ADR 0094
  (a hostname record for every further web unit) is the deploy half.

---

## Context

ADR 0197 settled what a public site is: a separate client that reads published content from
one app's API at build time and deploys as a `web` unit of that app's deployment. It left the
build to this record.

In the generated state the framework renders the build files (ADR 0187), and it renders one
web tier: the SPA, built from `frontend/` (ADR 0062). A second `web` unit is refused ("the
generator renders one web tier"). So a site deploys today only under `"build": "own"`, where
the app writes and owns every build file, which is the state the generated one exists to spare
it. "No custom Dockerfiles" needs the platform to supply the site's build.

The owner decided how a unit selects it (question 6 of the plan this series came from): a
declared field, not inference from a name (ADR 0110), with a closed set of recipes and absence
meaning today's SPA. A review of that decision added four conditions: the word is read only
beside `"build": "generated"`, because under `own` it would be a second owner of how a unit is
built and a deploy tool honouring it would build from a file outside the checkout; a recipe
takes no parameters, because a base image, command or header option reopens what ADR 0187
decision 1 rejected; a rebuild that runs as a one-shot gets none of the app's environment; and
the volume such a rebuild writes is marked derived, so ADR 0184 does not demand a backup for it.

## Decision

### 1. One word in the generator block: `generator.recipes`

`generator.recipes` maps a `web` unit's id to a recipe name. This version knows one recipe,
`static-site`. It lives in the `generator` block because only a generator reads it, and that
block is already refused beside `own` (ADR 0187), so no reader can honour a recipe for a unit
whose build files the app owns. It is keyed by unit id because a recipe is about one unit.

A key that names no declared unit, a unit whose role is not `web`, or a recipe outside the set
is refused by the readable rule, naming the field and the values it allows. The review asked
for the word in `roleResolvedFields`; that list holds unit fields, and this is not one, so the
same resolution is this coherence check: under any role but `web` a recipe has no reader.

A recipe has a name and nothing else. Everything it needs is fixed by the name, so two apps
that declare `static-site` get the same build.

### 2. The `static-site` recipe builds `site/` the way the SPA image builds `frontend/`

The generator renders `site/Dockerfile.prod`, a path it owns, held byte for byte by
`deployment_generated_files_match_their_render`:

- **Stage 1** (the table's `node` base) installs exactly what `site/package-lock.json`
  records, with `npm ci --ignore-scripts`, and runs `npm run build --ignore-scripts` with
  `--network=none`, into `site/dist/`. It takes no build argument, no secret and none of the
  app's environment. A site whose lock needs a lifecycle script stays `own`, as an SPA does.
- **Stage 2** (the table's unprivileged `nginx` base) serves `site/dist/` as `nginx`.

The directory is the recipe's, not a parameter: a site's source is `site/`, beside `frontend/`.
A site that builds from content the app publishes rebuilds as a one-shot (item D3 of the
plan), which is where the environment and derived-volume conditions apply. A site built at
image time has no content source to read, so its image build stays hermetic.

### 3. The server configuration is rendered too

The SPA image copies the app's own `frontend/nginx.conf`, which the template seeds with the
document security headers. For a site the generator renders the server configuration as well,
into the image, with:

- the template SPA's document headers, its content security policy included: a built site
  calls no API from the browser, so `connect-src 'self'` holds for it as it does for the SPA;
- `try_files $uri $uri/index.html =404`: a site has real pages, so there is no SPA fallback;
- no `/api` location: a site reads published content when it is built (ADR 0197) and never
  proxies the app;
- long-lived, immutable caching for content-hashed assets, and none for HTML;
- a health path that nginx answers itself, which the profile probes.

A site that needs other headers, such as a third-party script, is `own`. This decision is the
one this record most wants reviewed: it is stricter than the SPA, whose server config is the
app's file, and it is stricter on purpose. A public site is what a stranger loads first, and a
recipe whose headers the app could edit would be a recipe with a parameter.

### 4. One SPA and one site, each on its own port

The generator renders a second `web` unit when exactly one web unit is the SPA and the other
names `static-site`. Two SPAs, two sites, or a site without `site/package-lock.json` are
refused, each naming `own` as the way out. The SPA keeps `WEB_PORT`. A further web unit is
published on a variable of its own, derived from its id (upper-cased, with `-` and `.` as `_`,
then `_PORT`), and a derived name that collides with another variable the profile reads is
refused. Studio reads which variable each web unit publishes from the profile (its ADR 0094),
so it needs no convention of its own.

### 5. An app that declares no recipe renders exactly what it renders today

With no `generator.recipes` the render is byte for byte the current one, held by the golden
samples. The reference app and the template declare none.

### 6. The Terp Standard carries the word

`generator.recipes` joins the deployment-declaration schema: an object whose keys match the unit
id pattern and whose values are the closed set, with fixtures that name the field and the
allowed values for each refusal, and corpus cases for the readable rule. It ships in the
standard's next release.

### 7. Order

1. terp-spec: the word, its fixtures and corpus, in the next release.
2. terp-framework: the mirror of the schema moves to that release. The mirror's existing
   window allows this: while the pinned release is older, the mirror may differ from the
   published schema (`test_deployment_schema_mirror`). Then the reader's coherence check, the
   generator's second web build and its golden samples, and the profile's port variable. The
   pin bump to the release closes the window.
3. terp-studio: the builder builds every generator-owned web Dockerfile in the checkout,
   instead of two fixed ones, after the framework release it pins.

## Consequences

- An app ships a public site under `"build": "generated"` with no Dockerfile of its own and no
  server config of its own, and every site built from the recipe has the same posture.
- The generator owns one more file, and only for an app that declares the recipe.
- A site that needs a lifecycle script, another header, or a build step outside npm stays
  `own`, as an SPA in that position does today.
- The managed-content rebuild (D3) and a server-rendered site (D5) are not decided here.

## Two-layer enforcement

- **Build time:** the readable rule refuses an incoherent recipe; the render rule holds
  `site/Dockerfile.prod` byte for byte; the golden samples hold the render, including the
  unchanged render without the word.
- **Runtime:** the image serves the rendered headers and has no route to the app, and the deploy
  waits on the health path the profile probes.
