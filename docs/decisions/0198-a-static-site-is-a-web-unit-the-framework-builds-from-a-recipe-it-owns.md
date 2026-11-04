# 0198 — A static site is a web unit the framework builds from a recipe it owns

- **Status:** Proposed (awaiting review). Decision 3, the part this record most wanted
  reviewed, was reviewed on 2026-11-04 and kept, with the build refusing what its policy would
  break. Nothing is built yet: the Terp Standard's schema word, the generator's second web
  build, the executors and the signer that accept its render, and Studio's builder follow as
  changes of their own, in the order decision 7 gives.
- **Date:** 2026-11-04. 0182 and 0183 are reserved for other records, 0184 to 0193 are taken,
  and 0194 to 0197 are the series this extends.
- **Relates:** applies [ADR 0197](0197-a-public-site-is-a-client-of-an-app-and-the-framework-defines-its-socket.md)
  (a site is a separate client and deploys as a unit of the app's deployment), and amends its
  *How it will be held*, item 5 (the deploy side lands in the workbench and the runner);
  amends [ADR 0187](0187-in-the-generated-state-the-framework-renders-the-build-files.md)
  decision 1 (three generated files, and one fact of the tree as input), decision 5 (a second
  `web` unit refused, the image names constant), decision 6 (a web image's SBOM read from the
  frontend lock) and decision 9 (the order a longer fixed list ships in), as decision 8 here
  records; extends [ADR 0184](0184-a-deployment-declares-its-units.md) (the deployment declares
  its units); keeps [ADR 0062](0062-production-deployment-profile.md)'s SPA image as it is.
  Studio's ADR 0094 (a hostname record for every further web unit) is the deploy half.

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

ADR 0197 (decision 3) and Studio's ADR 0094, both of 2026-11-03, left open how a `web` unit
selects the recipe that builds it. The owner decided it after both: a declared field, not
inference from a name (ADR 0110), with a closed set of recipes and absence meaning today's SPA.
A review of that decision added four conditions: the word is read only beside `"build":
"generated"`, because under `own` it would be a second owner of how a unit is built and a
deploy tool honouring it would build from a file outside the checkout; a recipe takes no
parameters, because a base image, command or header option reopens what ADR 0187 decision 1
rejected; a rebuild that runs as a one-shot gets none of the app's environment; and the volume
such a rebuild writes is marked derived, so ADR 0184 does not demand a backup for it.

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
  Then it refuses what decision 3's policy would break in a browser: an HTML file under
  `site/dist/` with an inline script (a `<script>` element without `src` whose type runs as
  script; a data block such as `application/ld+json` runs as nothing and passes), a `<style>`
  element, a `style` attribute or an event-handler attribute. The refusal names the file and
  the first such tag, so the image build fails rather than the pages.
- **Stage 2** (the table's unprivileged `nginx` base) serves `site/dist/` as `nginx`.

The directory is the recipe's, not a parameter: a site's source is `site/`, beside `frontend/`.
A site that builds from content the app publishes is rebuilt by a one-shot unit inside the
environment, which writes the site to a volume the `web` unit serves (ADR 0197 decision 3).
That managed-content rebuild is not decided here, and it is where the environment and
derived-volume conditions apply. A site built at image time has no content source to read, so
its image build stays hermetic.

### 3. The server configuration is rendered too

The SPA image copies the app's own `frontend/nginx.conf`, which the template seeds with the
document security headers. For a site the generator renders the server configuration as well,
into the image, with:

- the template SPA's document headers, its content security policy included;
- `try_files $uri $uri/index.html =404`: a site has real pages, so there is no SPA fallback;
- no `/api` location: a site reads published content when it is built (ADR 0197) and never
  proxies the app;
- long-lived, immutable caching for content-hashed assets, and none for HTML;
- the site's own `404.html` for a path with no file, when the build writes one;
- a health path that nginx answers itself, which the profile probes.

That configuration decides three things for every site built from the recipe:

- **No browser call to the app.** `connect-src 'self'` with no `/api` location is the control
  that holds it: the browser refuses a script's connection to any other origin, and the site's
  own origin has no route to the app. ADR 0197's generated-client rule does not hold it, because
  a page that calls the app through a generated client passes that rule.
- **No inline style or script.** The policy has no `'unsafe-inline'`, so the browser refuses a
  `<style>` element, a `style` attribute, an inline `<script>` and an event-handler attribute.
  The SPA needs no `'unsafe-inline'` for its styles: react-core adopts its stylesheet through
  `document.adoptedStyleSheets`, which the policy does not govern (the template's
  `frontend/nginx.conf` says so beside the header). A site imports nothing from react-core (ADR
  0197 decision 4), so a site built from the recipe ships no inline style or script: each is a
  file it serves.
- **No form that posts.** `form-action 'self'` refuses another origin as a form's target, and
  with no `/api` location nothing on the site's own origin takes a post, so a form on such a
  site has nowhere to post.

Reviewed on 2026-11-04 and kept. Each part was held against what a site built from published
content needs, and two consequences are now part of the recipe:

- **The media a page shows is the site's own.** `img-src 'self' data:` and `font-src 'self'`
  hold because the site's build copies the images and fonts its pages show into `site/dist/`.
  A link the app hands out for a file may be signed and expire, and a page built once outlives
  it, so a page that pointed at the app's storage would break later under any policy.
- **What the policy forbids is refused when the image is built.** A static-site generator may
  inline a small stylesheet, or a script that wakes a page's interactive parts, and the policy
  refuses both in the browser, where the failure is a page that renders wrong with nothing in
  any log. So stage 1 refuses such a build (decision 2), and the site starter configures its
  generator to write every style and script as a file. Allowing inline content by hash was
  the alternative; it makes the policy depend on each build's output, which is a parameter by
  another name.

A site that needs another policy, for a third-party script, an inline style or script, a form
that posts or a browser call to the app, is `own`. The policy is stricter than the SPA's,
whose server config is the app's own file, and stricter on purpose: a public site is what a
stranger loads first, and a recipe whose headers the app could edit would be a recipe with a
parameter.

### 4. One SPA and one site, each on its own port and its own image

The generator renders a second `web` unit when exactly one web unit is the SPA and the other
names `static-site`. Two SPAs, two sites, or a site without `site/package-lock.json` are
refused, each naming `own` as the way out. The site proxies nothing (decision 3), so the
refusal of a `web` unit with no single `api` to proxy to holds for the SPA alone.

The SPA keeps `WEB_PORT`. The site is published on a variable under a fixed prefix:
`WEB_PORT_`, then its unit id upper-cased with `-` and `.` as `_`, so unit `site` is on
`WEB_PORT_SITE` and unit `9site` on `WEB_PORT_9SITE`. The rule takes a prefix rather than
refusing a derived name that is not a variable name. A unit id may begin with a digit, and
compose refuses a variable that does: `docker compose config` refuses `${9SITE_PORT:-23101}` as
an "invalid interpolation format". Behind the prefix every unit id the generator accepts gives
a name compose reads, so no declaration is refused for the name the generator derives from it,
which is ADR 0187 decision 5's line: it refuses what it cannot render faithfully, never what it
would rather not. The prefix also keeps a derived name out of the namespaces the Terp Standard
reserves for the toolchain (`reservedEnvironmentPrefixes`), whose names Studio refuses to set:
a suffix would publish unit `docker-site` on `DOCKER_SITE_PORT`. And no variable the profile
reads begins with `WEB_PORT_`, so a derived name collides with none and needs no refusal of its
own. Studio reads which variable each web unit publishes from the profile (its ADR 0094), so it
needs no convention of its own.

For unit `site` the port is rendered as `${WEB_PORT_SITE:-23101}:8080`. 8080 is the web tier's
port, where the site's nginx listens as the SPA's does; 23101 is the port after the SPA's
default and, like that default, only decides what a first `up` takes. The site's image is
`<project>-site-prod`, tagged per release as the other two are (ADR 0185 decision 6):
`<project>-site-prod:${TERP_RELEASE_TAG:?TERP_RELEASE_TAG is required, one new image tag per release}`.
A project name the generator accepts for `<project>-frontend-prod` gives a valid, shorter
`<project>-site-prod`, so the project-name refusal needs no new case.

Neither scalar is on ADR 0187's fixed list of interpolations. `terp promote` audits a carried
profile against that list before it pulls or starts anything, the runner audits one against its
own copy of the list, and each refuses any other interpolation. The list gains two entries:

| Place | The exact scalar |
|---|---|
| `ports[]` | `${WEB_PORT_<UNIT>:-23101}:8080`, with `<UNIT>` a unit id in the derived form, `[A-Z0-9][A-Z0-9_]{0,62}` |
| `*.image` | `<project>-site-prod:${TERP_RELEASE_TAG:?TERP_RELEASE_TAG is required, one new image tag per release}`, with `<project>` read as the two existing image entries read it |

The release jobs find the site's image as they find the others, from the profile. Of the npm
locks they read only the frontend's today: the refusal of a lock that takes a package from a
path, the manifest's `locks` and `fetches.npm`, and the SBOM `sign` builds for every web image
from `frontend/package-lock.json`. Each of them reads `site/package-lock.json` for the site
image as it reads the frontend lock for the SPA's.

### 5. An app that declares no recipe renders exactly what it renders today

With no `generator.recipes` the render is byte for byte the current one, held by the golden
samples. The reference app and the template declare none.

### 6. The Terp Standard carries the word

`generator.recipes` joins the deployment-declaration schema: an object whose keys match the unit
id pattern and whose values are the closed set, with fixtures that name the field and the
allowed values for each refusal, and corpus cases for the readable rule. It ships in the
standard's next release.

### 7. Order

The render needs two entries the fixed list does not have (decision 4), so this is the order
ADR 0187 decision 9 sets for every extension of that list: executors first, then the signer,
then the app's pin.

1. **terp-spec:** the word, its fixtures and corpus, in the next release.
2. **terp-framework:** the mirror of the schema moves to that release. The mirror's existing
   window allows this: while the pinned release is older, the mirror may differ from the
   published schema (`test_deployment_schema_mirror`). Then the reader's coherence check, the
   generator's second web build and its golden samples, the profile's port variable, the two
   entries in `fixed_interpolations`, and the release jobs' reading of the site's lock. The pin
   bump to the release closes the window.
3. **The executors:** `terp promote` audits with the list of the `terp-arch` it runs with, so it
   accepts the two entries from that framework release on, and the runner's own copy of the list
   gains them. Until then each refuses a site's profile.
4. **The signer:** its image moves to that framework release. Its reader then knows the
   standard release with the word, it carries the hash of that `terp-arch` wheel, its render
   tells the pinned generator whether `site/package-lock.json` exists, and it reads the site's
   lock (decision 4).
5. **An app** pins that framework release only after steps 3 and 4.
6. **terp-studio:** the builder builds every generator-owned web Dockerfile in the checkout,
   instead of two fixed ones, after the framework release it pins. Until then an app that
   declares the recipe releases with `terp release` alone.

### 8. Amendments

- **ADR 0187 decision 1.** An app that declares the recipe has four generated files:
  `site/Dockerfile.prod` joins the three, rendered for the `web` unit that names `static-site`
  and, like the other two Dockerfiles, a constant of the framework release with the base-image
  table's digests that takes nothing from the declaration. `frontend/Dockerfile.prod` is
  rendered for the `web` unit that names no recipe. The generator's closed list of inputs gains
  one fact of the tree: whether `site/package-lock.json` exists.
- **ADR 0187 decision 5.** A second `web` unit renders when one of the two is the SPA and the
  other names `static-site` (decision 4); any other second `web` unit is still refused. The
  images are three, constant in this version: `<project>-backend-prod`,
  `<project>-frontend-prod` and `<project>-site-prod`. The SPA alone proxies `/api` and
  publishes `WEB_PORT`.
- **ADR 0187 decision 6.** `sign` builds the site image's SBOM from `site/package-lock.json`,
  and the manifest records that lock and the hosts it fetches from, as it does the frontend's.
- **ADR 0187 decision 9.** The fixed list grows again, by decision 4's two entries, in the order
  that item sets (decision 7).
- **ADR 0197, *How it will be held*, item 5,** puts the deploy side, a static `web` recipe,
  more than one `web` unit per app and an on-demand rebuild, in the workbench and the runner.
  The first two are this record's instead: a word in the standard and a render in the
  framework's generator, which the executors, the signer and Studio then follow (decision 7).
  The rebuild is not decided here.

## Consequences

- An app ships a public site under `"build": "generated"` with no Dockerfile of its own and no
  server config of its own, and every site built from the recipe has the same posture.
- That posture is strict: a site built from the recipe ships no inline style or script, makes no
  browser call to the app, and has no form that posts (decision 3). Its build copies the media
  its pages show, and refuses a page the policy would break, so the strictness costs a build
  error with a file name rather than a broken page.
- The generator owns one more file, and only for an app that declares the recipe.
- The fixed list of interpolations grows by two entries, so an app pins the framework release
  that renders a site only after the runner carries them and the signer image has moved to that
  release (decision 7).
- A site that needs a lifecycle script or a build step outside npm stays `own`, as an SPA in
  that position does today. So does a site that needs another policy, for a third-party script,
  an inline style or script, a form that posts or a browser call to the app, where an SPA edits
  its own `frontend/nginx.conf`.
- Two things are not decided here: the managed-content rebuild, a one-shot unit inside the
  environment that reads the app's published content and writes the site to the volume its
  `web` unit serves, and a site that a server renders on each request instead of one built into
  files.

## Two-layer enforcement

- **Build time:** the readable rule refuses an incoherent recipe; the render rule holds
  `site/Dockerfile.prod` byte for byte; the golden samples hold the render, including the
  unchanged render without the word, and each passes the executor's escape audit, so a render
  that wrote an interpolation the fixed list lacks would fail. The image build refuses a site
  whose HTML carries an inline script or style, naming the file.
- **Runtime:** the image serves the rendered headers and has no route to the app, the browser
  holds every page to that policy, and the deploy waits on the health path the profile probes.
  An executor deploys a site's profile only when every interpolation in it is on the fixed list.
