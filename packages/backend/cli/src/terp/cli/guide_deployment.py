"""The ``terp guide deployment`` topic: the deploy declaration, the generated state and a release."""

from __future__ import annotations

TOPIC = """\
The deploy declaration: deployment.json, and what `terp verify --only deployment` holds

WHAT IT IS (ADR 0184)

deployment.json at the project root tells a tool that deploys the app which units exist,
which one serves the API, how to tell each is healthy, which migration histories each
owns, what holds state and how it is backed up, and what a rollback is -- instead of the
tool assuming the template's four service names. It describes the PRODUCTION profile
(docker-compose.prod.yml, or whatever file it names) and never the development loop,
which workbench.json describes. Nothing in it is read by the running app.

The words are the Terp Standard's (deployment-declaration.schema.json in terp-spec,
mirrored byte for byte in terp-arch). The template writes the file once, at `copier
copy`, describing its own profile; `copier update` never creates or rewrites it. An app
rendered before it existed stays undeclared until it writes one itself, or has `uv run
terp deployment adopt --build own` write it from its production profile (MOVING
BETWEEN STATES, below).

    {
      "schemaVersion": 1,
      "build": "own",
      "compose": { "file": "docker-compose.prod.yml" },
      "units": [
        { "id": "db", "role": "database", "kind": "postgres", "version": "17",
          "stateful": true, "backup": { "every": "P1D", "keep": "P30D" } },
        { "id": "migrate", "role": "one-shot", "dependsOn": ["db"] },
        { "id": "api", "role": "api", "healthPath": "/health/ready",
          "livenessPath": "/health/live", "migrations": ["notes"],
          "dependsOn": ["db", "migrate"] },
        { "id": "worker", "role": "worker", "command": ["terp", "jobs", "worker", "--forever"],
          "env": ["SOME_API_BASE_URL"], "dependsOn": ["db"] },
        { "id": "web", "role": "web", "dependsOn": ["api"] }
      ],
      "volumes": [ { "id": "files-data", "backup": { "every": "P1D", "keep": "P30D" } } ],
      "rollback": { "strategy": "redeploy-previous-release" }
    }

FOUR STATES, EXACTLY ONE AT A TIME

  absent                          undeclared: every check passes, as before
  "build": "own"                  units built from the build files the app commits
  "build": "generated"            the framework renders Dockerfile.prod,
                                  frontend/Dockerfile.prod and docker-compose.prod.yml
                                  from this file (`terp deployment render`), and a
                                  committed copy that is not the render is refused.
                                  frontend/Dockerfile.prod only beside a web unit: an api
                                  unit with no web unit in front of it is the deployment's
                                  only way in and publishes ${API_PORT:-23200}:8000 (ADR
                                  0202) -- the shape an app rendered API-only (the
                                  template's `frontend: false`) has from the start
  {"unmanaged": true, "reason"}   no tool can drive this deploy; the checks are off and
                                  a tool shows the reason. Nothing may stand beside it.

Units without "build", or "unmanaged" beside "build", is refused -- never guessed.

IT IS PARTIAL, AND IT MUST BE TRUE

A service no unit names is not this file's business: add a worker, a cache, a scanner
or a second API to the profile and nothing here objects. A role nobody has heard of is
information. What the file DOES say must be true of the resolved profile -- the file
plus compose.overrides, merged the way `docker compose -f ... -f ...` merges them:

  - a unit is a service of the profile; a volume is a named volume a service mounts, and
    a restated "mount" names exactly the declared units whose services mount it there
    (its path relative to /srv, where the images run the app);
  - a restated "command" (an argument list, never a shell string) or "dependsOn" is the
    profile's own, the order restricted to declared units;
  - an "env" name reaches the unit's service: in its environment: block, or through the
    file environment.schema.json routes it to (.app.env; .app.<service>.env when the
    declaration names services) and the service loads with env_file:;
  - a unit with "kind" runs EXACTLY the image the datastore table publishes for that
    kind and version (postgres 17 today, by digest); every other unit runs an image the
    profile builds from the checkout. There is no "image" key: the file cannot name a
    registry;
  - "externalDatabase": {"backup": "client"} never stands beside a profile that still
    runs a database (name the override that removes `db` in compose.overrides);
  - "healthPath" and "livenessPath" are read BY ROLE, so they belong under a role the
    vocabulary knows (api, database, one-shot, scheduler, store, web, worker).

From the app (`terp verify --only deployment` only, because it needs the composed
app): a "migrations" label is one an installed package or app module owns, and an api
unit's health paths are routes the app serves. Where app.main:build cannot be imported
that part is skipped with a named note.

NEVER RED: no frontend, three APIs, a stateful unit with no backup, a schedule with no
scheduler unit, "instances": "many", an installed history no unit claims, a profile of
any file name other than the development one. A missing backup is a safety property for
the deploy boundary, not for this check.

REFUSED AS UNREADABLE: a key the vocabulary lacks at any level (a $-prefixed key is a
comment), a control character, a string over its cap, a version this toolchain does not
read, a size that is not a key of "sizes", "client" anywhere but externalDatabase, a
backup on a unit not declared stateful, two units or volumes with one id, a profile
path or build context that resolves outside the checkout (links followed), and the
development compose file named as the profile.

DEPLOY POLICY NEVER BELONGS HERE. Who may publish, how many approvals a deploy needs,
who may reach a deployed app and which gate policy applies are set per environment by
the deploying tool, where a commit cannot lower them. Such a key is refused with:
"<key> is deploy policy: it belongs to the deploying tool's environment policy, not to
this file". Domains, TLS, CORS, the backup destination, sizes per environment and the
digest allowlist are environment facts and stay out too.

WHERE IT IS CHECKED

  terp check                       the three terp.arch rules, from files alone:
                                   deployment_declaration_is_readable,
                                   deployment_declaration_tells_the_truth and
                                   deployment_generated_files_match_their_render
  terp verify --only deployment    the first two, plus the app part and notes on what
                                   the app uses that the file does not state (a files
                                   volume with no backup policy, a companion root no
                                   unit runs, a datastore kind no unit declares)
  terp verify --only generated     the third, with notes: what it did not judge, and a
                                   profile `terp release` will refuse

None of them has an `# arch-allow-*` marker -- a JSON file cannot carry one, and a marker
in a file the generator rewrites would be erased by the next render. The way out is the
declaration's own: {"unmanaged": true, "reason": "..."}, or, for the third, "build": "own".

THE GENERATED STATE (ADR 0187)

Under "build": "generated" the production build files are the framework's: the three, and
site/Dockerfile.prod as well when a web unit names the static-site recipe (A STATIC SITE,
below). Change deployment.json (or pyproject.toml's name, or the framework version), then:

  uv run terp deployment render          writes the render, every file or none, and
                                         removes a generator-owned file the declaration
                                         no longer renders; refuses, in the generator's
                                         own words, what it cannot render faithfully
  uv run terp deployment render --check  writes nothing; exit 1 when a committed file is
                                         not the render (the same rule as the gate's)

and commit the files with the declaration. The gate never writes. `terp verify --only
generated` is red when a committed file differs from the render (a short diff and the
fix), when a generator-owned path the render does not produce exists, when the generator
refuses the declaration, when [project].name is one compose or Docker refuses, when .env,
.app.env or a backend unit's .app.<id>.env would be committed (asked of git check-ignore)
or baked into an image (asked of a matcher with Docker's own .dockerignore semantics), and
when deploy_build in .copier-answers.yml disagrees. In a tree git finds no work tree in,
the git half is noted, not judged.

What the generator refuses, each with the field and what is allowed: another profile name
or an override; externalDatabase beside a database unit; a database or store without kind,
or two of a kind; a one-shot that declares `terp migrate upgrade` (drop the command: the
one-shot without one is the migration step) or a second step; a role with no command of
its own and none declared; a web unit with a command; a web unit naming no recipe (the SPA)
with no single api to proxy to, or without frontend/package-lock.json; a second SPA or a
second static site, and a static site without site/package-lock.json; two or more api units
with no SPA in front of them (which one callers reach would be a guess; a site proxies
nothing, so it fronts none); an api without both health paths; a start-order cycle
or a unit it names that is not declared; a volume without its mount, mounted anywhere but
var/files, on a unit not on the backend image, or on a unit that already mounts another
volume there (Compose would mount only the last of them, without a word); any system
package (the table is empty in this release); a unit id that is not a lower-case compose
name. Any of them: declare "build": "own" and keep the files yourself.

The generator's words: "generator": {"systemPackages": [...]} and "generator": {"recipes":
{...}}, valid only beside "build": "generated", and "mount": {"path": "var/files", "units":
[...]} on a volume, required under generated and a restatement the truth rule holds to the
profile under own.

A STATIC SITE (ADR 0198)

A public site is a web unit of the app's deployment (ADR 0197) whose image the framework
builds from a recipe it owns. Name it in the generator block, by the web unit's id:

  "units": [..., {"id": "site", "role": "web"}],
  "generator": {"recipes": {"site": "static-site"}}

static-site is the one recipe, a name with no parameters, so two apps that name it get the
same build. The readable rule refuses a key that names no web unit and a recipe outside the
set, each naming what is allowed. Its source is site/, beside frontend/, with a committed
site/package-lock.json, and the render gains site/Dockerfile.prod, held like the others:

  stage 1  `npm ci --ignore-scripts` over exactly the lock, then `npm run build
           --ignore-scripts` with no network into site/dist/: no build argument, no
           secret, none of the app's environment. Then a check looks through every
           document under dist/ (.html, .htm, .shtml, and as XML .xhtml, .svg, .xml, .rss,
           .atom, .kml, .xspf) for markup the policy below breaks in a browser, where the
           page breaks with nothing in any log, and refuses the build, naming the file,
           its first such tag and what to change: an inline script that runs, a <style>
           element, a style or on* attribute, a javascript: URL, a <base href>, an
           <object> or <embed>, a form that submits elsewhere, and a script, stylesheet,
           frame, image, media, icon, manifest or preload from another origin or a data:
           URL (an image may be one). It refuses what it cannot read too: an XML file's
           internal DTD subset, and a symbolic link under dist/. It is a finder, not a
           promise: it reads no CSS and nothing a script fetches, and the policy stays the
           control. Write each as a file the page loads (a JSON-LD data block runs as
           nothing and passes).
  stage 2  a non-root nginx with the recipe's own server configuration: the template SPA's
           security headers and content security policy (no 'unsafe-inline') on every
           file it serves, an asset as much as a page, real pages (a path, its index.html
           or the site's own 404.html; no SPA fallback), immutable caching under /assets/
           and no-cache elsewhere, /healthz, and no /api location.

So the site reads the app's published content when it is built, never from a browser: it
proxies nothing, and connect-src 'self' leaves a page no other origin to call. Its media are
its own files under dist/. Its nginx answers its health at /healthz, where the profile probes
it, so the site unit declares that healthPath or none: a deploy tool waits on the declared
path, and the readable rule refuses another. It is published on WEB_PORT_ and its unit id
upper-cased, with - and . as _ (unit site: ${WEB_PORT_SITE:-23101}:8080), beside the SPA's
WEB_PORT, and its image is <project>-site-prod, tagged per release like the other two. One
SPA and one site render together; a site alone is fine too, and the api then publishes
API_PORT as it does with no web unit. A site that needs another policy, a lifecycle script,
a form that posts or the app's environment is "build": "own".

MOVING BETWEEN STATES: terp deployment adopt (ADR 0187)

The state is two recorded facts that must agree: "build" in deployment.json, which the
gate reads, and deploy_build in .copier-answers.yml, the template question `copier
update` reads. Copier renders an update's OLD template version with the RECORDED
answers, so adoption writes the answer itself; never `copier update --data
deploy_build=...`, whose old render still has the files it would then delete. Each form
writes all its files or none and prints the diff; --dry-run only prints.

  uv run terp deployment adopt --build generated
      needs a readable, true, renderable deployment.json and scaffolding from a template
      version that asks deploy_build. Sets both facts, renders, removes a generator path
      the declaration does not produce. A template-shaped app at the template version it
      was rendered from changes NO build file: the template's are the seed's render.
      Refused, writing nothing: a declaration the generator cannot render (each refusal
      above), a project name compose or Docker refuses, an environment file git or the
      build context would carry, and an answers file that records no deploy_build --
      its template version's every update renders the build files over the generator's,
      so `copier update` first, which records deploy_build: own, then adopt.
  uv run terp deployment adopt --build own
      on a generated app: both facts back to own, and no file changes; the last render is
      the app's, and the next update merges into it as into any own app's. On an
      undeclared app: deployment.json written from docker-compose.prod.yml as it runs --
      a datastore by the table's kind (its image pinned to the table's digest in the same
      change), a service built from the checkout by what it does (web from frontend/,
      one-shot when it does not restart, worker and scheduler by `terp jobs`, api when it
      runs the image's own command, with the framework's health routes; otherwise its own
      name as the role), dependsOn restricted to declared units, and a volume a declared
      unit mounts with its mount where it is one path inside var/. A service on an image
      neither built here nor in the table is refused by name. A backup policy, env names,
      sizes and a rollback strategy are not in a profile: the notes name them.
  uv run terp deployment adopt --unmanaged "<reason>"
      ADR 0184's opt-out, and deploy_build: own, since the build files are the app's.

A copier answers file is optional: an app without one changes deployment.json only.

A FRAMEWORK UPDATE OF A GENERATED APP

`copier update`, then the install (`uv sync`, `npm --prefix frontend install`), then
`uv run terp deployment render`, committed together, in the copy the update is made in.
The template leaves the three files to the generator of the release just installed, so a
missed render is red there under `terp verify --only generated`. `uv run terp upgrade
--check` prints the render as its own step for an app whose deployment.json says
generated. A fresh `copier copy --data deploy_build=generated` has none of the three until
the first render, which needs frontend/package-lock.json (`npm --prefix frontend install`).

THE LOCKS A DECLARED APP IS BUILT FROM

A tool that drives the units builds the committed Dockerfiles, and the template's install
exactly the committed locks (`uv sync --locked --no-dev`, `npm ci`). So `terp verify --only
locks`, its own check and not part of this one, refuses an app with units declared whose
uv.lock, frontend/package-lock.json or a static site's site/package-lock.json is missing or
stale against its manifest, and names the fix: `uv lock`, `npm --prefix frontend install` or
`npm --prefix site install`, then commit the lock. uv and npm answer for their own locks,
offline (`uv lock --check`, `npm ci --dry-run`). An undeclared or unmanaged app is told the
same as a note. Its npm locks are the ones the release jobs read, and the release profile's
dependency-audit-npm audits each of them.

THE PRODUCTION PROFILE THE TEMPLATE SHIPS (ADR 0187)

The template's Dockerfile.prod, frontend/Dockerfile.prod and docker-compose.prod.yml are
the framework generator's render of the seed declaration (terp.arch.deployment.generate),
held byte for byte by a test, so a hardening change reaches them once. Each says so in
its header. Under "build": "own" they are the app's to change; under "build": "generated"
they are the render (THE GENERATED STATE, above). With the files capability on (use_files),
the seed also declares the files-data volume, mounted at var/files on api with a daily
backup policy, and the profile mounts it: the render of that seed, held the same way. The
backend image makes /srv/var/files owned by the user it runs as, and Docker gives an empty
named volume the owner of the directory it is mounted over, so that user can write it.

  start it, with its required secrets and a new per-release image tag set (compose
  stops on an unset one; the tag keeps the previous release's images beside this
  one's, so it can be started again):
    SECRET_KEY=... POSTGRES_PASSWORD=... TERP_RELEASE_TAG=$(git rev-parse --short=12 HEAD) \\
      docker compose -f docker-compose.prod.yml up -d --wait --build
  bootstrap the first administrator (`terp seed` refuses ENVIRONMENT=production), with
  the same variables set:
    docker compose -f docker-compose.prod.yml run --rm -e TERP_USER_PASSWORD api \\
      terp user create admin@your-domain.example --role admin
  start an earlier release again: set its TERP_RELEASE_TAG and run `up -d --wait
    --no-build`, so an image that is gone fails instead of being rebuilt from this
    checkout under the old tag
  a database this deployment does not run: set DATABASE_URL, which every backend unit
    reads before its default; to drop the bundled `db` service too, add an override
    that removes it, name it in compose.overrides and declare
    "externalDatabase": {"backup": "client"}

What each unit becomes: a datastore runs its table digest and its own healthcheck; an
api is probed on its livenessPath, passed to a fixed probe as an argument; a worker runs
`terp jobs worker --forever` (drain, wait --poll-seconds, drain again, until stopped)
and a scheduler `terp jobs scheduler`, each with init and a healthcheck on the heartbeat
its own loop writes (ADR 0191); the one-shot without a command is the migration step; the
web tier proxies to its api, and a static site serves its own files and proxies nothing.
The backend image carries no HEALTHCHECK. A unit that serves
no request and writes no heartbeat (a companion, a drain without --forever) has no check,
so `docker compose up --wait` (what a deploy runs) waits for it to run, where an inherited
HTTP probe turned it unhealthy and a disabled one made Compose refuse to wait.
The image ships its bytecode compiled (checked-hash, so the same lock compiles to the same
bytes). Every backend unit loads .app.env, then its own .app.<id>.env. Every value a
declaration gives (a command, a health path) is written double-quoted with each $
doubled, so compose passes it on as written.

THE HEARTBEAT CHECK (ADR 0191)

A unit whose command is `terp jobs worker ... --forever` or `terp jobs scheduler ...`,
declared or the role's default, is checked every 10 seconds with a fixed probe: python -c
<standard library only> worker|scheduler. It reads <tmp>/terp-<role>.heartbeat in the
container, prints {"heartbeat", "age_seconds", "stale_after_seconds"} as one JSON line, and
fails when the heartbeat is older than the bound the process wrote into it, or missing. So
a worker stuck in one job turns unhealthy once its bound has passed (60s with the default
lease), while a container that merely runs is not called healthy. A deploy tool reads the
same answer per unit, with no HTTP and no database: the container's health status, and the
last probe's output for the age (docker inspect, .State.Health.Log), or the probe run in
the container. Dependants of such a unit wait for service_healthy. Do not set TMPDIR
differently for the process and its healthcheck: both find the file through it.

READINESS (ADR 0191)

/health/ready answers 200 when the database answers SELECT 1 and every shared store a
require_shared_* made mandatory answers its ping(); 503 otherwise, naming each check. A
store is asked on a thread of its own within 2 seconds, never twice at once, so one that
stops answering turns readiness 503 instead of holding the probe. Workers, schedulers and
the outbox backlog are never part of it. Bound the Redis client's own commands too, or a
Redis that stops answering holds every request the rate limiter counts:
REDIS_URL=redis://host:6379/0?socket_timeout=2&socket_connect_timeout=2.

CUTTING A RELEASE AND PROMOTING IT (ADR 0187)

`terp release` is three jobs, each on a fresh host, so that no job that runs the app outside a
build container holds a credential or writes into what is built. Each takes the exact commit
(its full object name) and reads it from git's object store, never from a working copy:

  uv run terp release build --sha <sha> --tag <tag> --registry registry.example/team
    builds every image the profile builds from the commit's pristine tree, in a BuildKit
    builder made for the job and removed after it, with --pull and no cache, and pushes
    <registry>/<image>:<tag> with the credential your docker configuration holds for this
    release. It writes terp-release-build.json: BuildKit's own digests.
  uv run terp release gate --sha <sha> --build terp-release-build.json
    runs in a clean checkout of the commit: `terp verify --profile release` once, with npm's
    scripts off, recording every check's verdict and the release-assurance claim those same
    results compose (no check's output), then the schedule catalog, read by running the
    pushed image sealed (no network, read-only, its own non-root user). It holds no push
    credential and no key. It writes terp-release-gate.json, and exits 1 unless every check
    passed and the claim holds, naming each red check. Run it from the commit's own
    environment: sign reads the document only in the version the commit's pinned terp-cli
    writes (ADR 0200).
  terp release sign --sha <sha> --tag <tag> --registry ... --build ... --gate ... \\
      --hosts separated --signer '["your-kms-signer", "--key", "release"]' --public-key k.pub
    runs from the signer image, never the commit's own toolchain, and runs nothing of the
    app: it repeats the refusals, refuses a gate with a red check or a claim that does not
    hold (ADR 0200; a commit pinning terp-cli below 0.36.1 has a gate that records the claim
    alone, and is held to it), renders a generated app's files with the terp-arch the
    commit pins (fetched by hash, run in a process of its own) and, from a terp-arch that
    writes one, the resolved deployment the release runs, which it holds to its own copy of
    terp-spec's schema and checks before the manifest (then version 2) carries it at
    outputs.deployment, reads the backend image from
    the registry as data and holds it to the tree and the lock, describes each web image from
    the npm lock it installs, the package-lock.json its Dockerfile copies (when it names
    none, the one beside it or at the root of its build context, never a choice between two;
    a static site's is site/package-lock.json), scans for known
    vulnerabilities and for secrets in the history, and signs the manifest as a DSSE envelope
    (release.dsse.json). --sign-key <file> is refused without --test-key. Run the image with
    the checkout mounted read-only (/repo) and the engine's socket and its group
    (-v /var/run/docker.sock:/var/run/docker.sock --group-add <the socket's group>): the
    bytecode check starts the base image's interpreter, and the image runs as its own user.

Refused, by name, before anything is built or signed: an undeclared or unmanaged app, a
declaration that cannot be read or is untrue, a committed .terp-dist/ or submodule, a lock
naming a path, a web image whose npm lock cannot be named (its Dockerfile copies two, or one
the commit does not hold, or names none where two stand or none does), an
image neither built here nor a datastore table digest, a datastore with no healthcheck, more
than one migration step or one with --revision/--sql, no step and other than one api unit, a
built image that does not read TERP_RELEASE_TAG, and a build with more than a context and a
Dockerfile.

  terp promote release.dsse.json --public-key k.pub --project-dir /srv/deploy/app
    verifies the envelope before reading it, checks the manifest (a newer Terp Standard than
    its own is refused, its own must record the schema it holds, and an older one's
    declaration may use no word that release lacks; --require-generated refuses an own
    release; a generated profile is audited for every $), pulls each image by its signed
    digest and tags it by the name the
    profile gives it (<project>-backend-prod:<tag>, the frontend's, a site's), writes the
    carried profile, and runs compose with an
    allowlisted environment and TERP_RELEASE_TAG set: the datastores, a reading of every
    alembic_version_* table, the migration step exactly once, then the rest, every `up` with
    --no-build --pull never. If the deploy fails and the version tables are as they were,
    going back is restore-free: --undo-to <the running release's envelope> starts it again
    after its own `terp migrate check`. Otherwise going back is a restore. A rollback in an
    invocation of its own has no such reading, so it is refused unless --rollback --restored
    says the database was restored to the backup taken before the release that followed it.
    Over a release that applied no revision, going back is promoting the previous envelope
    again: its step finds every history at its own heads and applies nothing.
`terp release` and `terp promote` need terp-cli[release] (cryptography, packaging, the egress
capability); without it they refuse, and nothing is signed or verified halfway.
"""
