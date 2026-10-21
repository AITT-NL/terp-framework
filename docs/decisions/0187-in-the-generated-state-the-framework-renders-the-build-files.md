# 0187 — In the generated state the framework renders the build files, and a release is signed by a job that never runs the app

- **Status:** Proposed. Revised after four rounds of adversarial review (see *Debate*). Built in
  0.35.0, as decision 8's second pull request: the tables and the kind recipe, the generator
  (`terp.arch.deployment.generate`) with its golden samples, properties and import allowlist, the
  truth rule's compose unescaping, `terp jobs worker --forever`, the `--ignore-scripts`
  measurement, and the template's three build files replaced by the seed's render. The reader
  still refuses `generated`. Held by `tests/architecture/test_deployment_generator.py`,
  `test_deployment_truth.py`, `test_cli_jobs.py`, `test_prod_profile.py`,
  `test_template_build_inputs.py`, `test_compose_workbench.py` and `test_reference_app.py`. The
  two words and the rule ship in terp-spec 0.40.0, which is not published yet; see *How it was
  built*.
- **Date:** 2026-10-21
- **Relates:** amends [ADR 0062](0062-production-deployment-profile.md) decisions 1 to 4, on top
  of its 2026-10-21 amendment; amends [ADR 0184](0184-a-deployment-declares-its-units.md)
  decision 9 (`terp release` becomes three jobs; `terp promote` gains an envelope and an escape
  audit) and, for the new `generated` check only, decision 5's never-red list; is the record ADR
  0184 decision 4 promised for `"build": "generated"`, and settles three of its open items (the
  adoption command, the manifest's signature format, how `terp promote` gets its key). Builds on
  [ADR 0185](0185-a-release-declares-the-schema-window-it-accepts.md) (labels, per-release tag),
  [ADR 0110](0110-an-app-declares-which-parts-of-its-dev-topology-are-load-bearing.md),
  [ADR 0111](0111-flexibility-is-bounded-by-legibility-not-by-capability.md) (the degradation
  test), [ADR 0141](0141-the-gate-scans-every-deployable-not-only-the-mounted-one.md),
  [ADR 0092](0092-typed-route-params.md) (generate, commit, gate),
  [ADR 0063](0063-lockstep-release-and-publish-pipeline.md),
  [ADR 0124](0124-a-declared-variable-may-name-the-services-that-see-it.md),
  [ADR 0084](0084-runtime-applicability-classification.md),
  [ADR 0080](0080-terp-standard-rule-catalog-and-violation-corpus.md),
  [ADR 0082](0082-repo-split-readiness-spec-as-a-package.md),
  [ADR 0024](0024-health-endpoints-and-pool-config.md),
  [ADR 0104](0104-the-spa-document-carries-its-own-security-headers.md) and
  [ADR 0150](0150-mail-leaves-through-one-declared-relay.md). Supersedes nothing.

---

## Context

ADR 0184 put `generated` in the schema from its first release; every toolchain still refuses it
("this toolchain cannot honour generated; upgrade, or declare own"). This is the generator it waits
for.

In the `own` state, where every declared app sits today, the template owns `Dockerfile.prod`,
`frontend/Dockerfile.prod` and `docker-compose.prod.yml`, and every `copier update` merges them
three ways into whatever the app made of them. An app that grows a worker, a scheduler, a companion
or a files volume edits the template's profile and conflicts on every update after. Nothing
guarantees the files build, install the audited locks or keep secrets out. And the hardening that
shipped with ADR 0184 (lock-exact installs, layers, no cache mounts, a `.dockerignore` held path by
path to `.gitignore`, `terp verify --only locks`) reaches such an app only as a merge.

The constraints:

- **Consumers read committed files at fixed paths:** deploy-safety reads `docker-compose.prod.yml`,
  the profile and build-input tests read the Dockerfiles, `terp docker dev` and `terp smoke` need
  the profile, and Terp Studio's release build today builds both production Dockerfiles and refuses
  when either is missing.
- **The declaration is agent-editable**, and compose interpolates `${...}`. The schema's
  health-path pattern admits `$`, `'`, `(` and `;`.
- **Cutting a release runs the app:** its tests and conformance suite in the gate, the dev stack the
  suite needs, install-time code of its dependencies, its build backend and bundler configuration
  during the build. A change that reaches a release, an agent's or a locked typosquat's, runs there.
  Whatever holds the signing key, and whatever writes into the build context, must not run it.
- **Rollback must not depend on the framework version** a release was cut with.
- **A framework update is a change like any other**, made in a copy, checked, and published; a
  missed re-render must turn that copy red.
- **The manifest needs a signature format** (decision 6 settles on DSSE) and must record the Terp Standard
  release its declaration was validated against.

## Decision

**1. Three generated files; the template's own three are their render of the seed.**

| Path | Rendered when | From |
|---|---|---|
| `Dockerfile.prod` | a unit runs the backend image (no `kind`, role not `web`) | nothing in the declaration in this version: a constant of the framework release, with the base-image table's digests |
| `frontend/Dockerfile.prod` | a `web` unit | the same |
| `docker-compose.prod.yml` | always | the declaration, the project name, the datastore table and its kind recipes |

A generator-owned path the declaration renders nothing for must be absent. A tool that builds both
Dockerfiles unconditionally (Studio's release build today) cannot release a generated app without a
`web` unit until it builds only what the units need; until then `terp release` alone can.

**The Dockerfiles take no declaration input in this version.** The system-package table ships
empty, lifecycle-script exceptions wait for a measured need, a volume mounts only at `var/files`
(the mount point the image already makes), and the backend image carries no `HEALTHCHECK`: the
profile probes each `api` unit on its declared liveness path, and a unit that serves no request
has no check at all (decision 5).

**The template's files are the render of the seed** (`db`, `migrate`, `api`, `web`, `"build":
"generated"`), held byte for byte by a test, with the slug left as the template's placeholder. So
template and generator cannot drift, a hardening change is made once, and adopting `generated` in
a template-shaped app at the same template version changes no build file. Becoming that render
changes the template once, in these places, and an `own` app that edited the same lines meets them
as one merge:

- **Both Dockerfiles:** a header true in both states, and bases pinned by digest from the
  base-image table instead of by tag.
- **`Dockerfile.prod`:** "the same image backs the one-shot `migrate` job and the `api` server"
  becomes "every unit built from the checkout but the web tier". The image drops its
  `HEALTHCHECK`, which every unit on it inherited: a worker, a scheduler or a companion serves no
  HTTP, so each turned unhealthy and `docker compose up --wait`, which a deploy runs, failed
  every deployment of a profile that ran one (measured, *Consequences*). And it ships its
  bytecode: the dependencies are compiled in the dependency stage and the two source roots after
  they are copied, each in its own layer, with `python -m compileall --invalidation-mode
  checked-hash` (PEP 552), which records a hash of the source rather than an mtime, so the same
  lock compiles to the same bytes. The image's user cannot write the environment and
  `PYTHONDONTWRITEBYTECODE` stays, so before this every process start compiled the platform
  again: on a loaded host, importing the app took about 11.5 s where it took about 2 s compiled;
  on a quiet one, the platform's import is 6.2 s against 3.2 s (*How it was built*).
- **`frontend/Dockerfile.prod`:** `npm ci --ignore-scripts`, and `npm run build --ignore-scripts`
  under `RUN --network=none`. Measured before it was made (*Consequences*): nothing in the
  template's lock or the reference app's needs a lifecycle script.
- **The profile:** a declaration-neutral header pointing to `terp guide deployment` in place of the
  seed's topology and its override advice; per-service comments that state only what is true of
  their element; no `project_name` on the first line; the `api` healthcheck passing its path to a
  fixed probe as an argument; and `migrate` and `api` each listing `.app.env` then `.app.<id>.env`
  while `x-backend` keeps `.app.env`, so services an app added still inherit it.
  `test_prod_backend_forwards_app_declared_env` changes deliberately for those two lists; `web`
  keeps no environment file and its fixed healthcheck. The comments are ASCII, as every rendered
  byte is (decision 2), so the template's dashes and ellipsis become hyphens and dots.
- ADR 0185's tag, labels, release option and the backend's `heads` stage (decision 6) arrive
  through the generator when that ADR is built; they are its changes.

The header, identical in each file:

```
# Rendered by `terp deployment render` from deployment.json (ADR 0187). Where deployment.json
# says "build": "generated" this file is the generator's: change deployment.json and render
# again, never this file. Under "build": "own" it is the app's to change.
```

**Inputs, a closed list:** `deployment.json` through the typed reader; `[project].name` from
`pyproject.toml`, used verbatim and refused when compose or Docker would not accept it as a project
or repository name; whether `frontend/package-lock.json` exists, the one fact of the tree it needs
(a `web` unit is built from it, decision 5); and the framework release's tables in `terp-arch`,
passed in rather than read: the datastore table, a new
base-image table (the template pins the same digests, held by a test), a new system-package table
(empty), and a new framework-internal kind recipe per datastore kind (its data path, its
healthcheck, its own environment such as `POSTGRES_USER`, the `:?`-required `POSTGRES_PASSWORD` and
`POSTGRES_DB`, and the variable backend units reach it through). Not inputs: the locks (the
Dockerfiles copy them; `locks` checks them), `environment.schema.json` (each backend unit loads
`.app.env` and `.app.<id>.env`, both optional), companion roots (they ship inside the app wheel
because `[tool.hatch.build.targets.wheel]` lists them), the clock, the environment, git, the
network, the app's code.

**Environment files stay out of git and the image, checked by path.** The two ignore files stay the
template's. In the generated state the `generated` check asks only whether `.env`, `.app.env` and
`.app.<id>.env` for each unit that loads one are ignored by git and left out of the build context,
using git's own `check-ignore` and a matcher with Docker's own semantics (character classes,
negated classes, `**`, exceptions, parent exclusion). A pattern either cannot read is a finding,
never a crash.

**Two new words** (decision 8): `generator.systemPackages`, valid only beside `"build":
"generated"`, refused beside `own`, every name refused against the empty table with the allowed
list; and `volumes[].mount`, `{"path": "var/files", "units": [...]}`, a restatement the truth rule
checks in the `own` state (any path inside `var/`) and a rendered, required field in the
`generated` state (only `var/files`).

*Considered and rejected.*
- **Committing nothing.** Breaks every consumer, and no reviewer sees what runs.
- **Generating only the profile.** A generated app could then edit its Dockerfiles, and the build
  guarantee would mean nothing; taking them out of the merge is generating them, even as constants.
- **Keeping the template hand-written**, held to the generator structurally. Two authors of one
  text drift where the test does not read.
- **Comments copied from the template as fixed text.** Many are true only of the seed.
- **Normalising the project name** (`_` to `-`). The render would differ from the template for
  every slug the template already renders; refusing what compose and Docker refuse is enough.
- **Declaration inputs to the Dockerfiles now** (system packages from a dated archive, script
  exceptions, other mount paths, a declared image healthcheck). No exit test needs them, and each
  adds machinery and an escaping surface.
- **Per-Dockerfile ignore files, a `.gitignore` block, or holding the two ignore files to each other
  in an app.** The hardened files already carry the patterns; the first two add a second author,
  the third reddens edits that leak nothing.

**2. Plain Python emitters in `terp-arch`, byte-stable, one encoder per grammar.**

`terp.arch.deployment.generate` is a pure function from the reader's `Declaration`, the project
name, the lock's presence and the tables to a map of path to bytes, or to refusals in the
reader's finding shape; all files or none. It imports the standard library's text tools and the
reader's own modules only - the reader and the tables, which the caller loads - held by an import
allowlist test, and does no I/O. Its version is `terp-arch`'s, which ADR 0063 keeps lockstep.

**Byte-stable:** UTF-8, ASCII-only (`\uXXXX`, and `\UXXXXXXXX` above U+FFFF, inside quoted
scalars), LF, one final newline, no trailing whitespace, a fixed key order, units and volumes in
declaration order, sorted where order means nothing, no timestamp, path or version in a file.
Written and compared as bytes; the template's `.gitattributes` keeps `eol=lf`.

**The template's structure:** commands and healthcheck tests as flow sequences of double-quoted
strings; the backend image, `.app.env` and the four platform values in `x-backend`, merged with
`<<:` as today; `x-logging` by alias; per-unit lists written on the unit. The backend `build:` sits
on the `api` unit when one runs the image, else on the first backend unit.

**Escaping:**
- **Compose:** a command element, a health path and a mount path are always double-quoted with
  every `$` doubled, so compose never interpolates them. A unit or volume id (whose pattern excludes
  `$`, whitespace and YAML punctuation), and a scalar built only from ids, the project name and
  fixed text, may stand plain where YAML 1.1 and 1.2 both read it as a string and, when it starts
  with an id, that id does not start with a digit. A scalar that starts with the project name
  ends in fixed text (`-prod`) no YAML type has, so it stands as the template writes it whatever
  the name's first character. The emitter types every fragment as fixed text or a value and
  decides quoting on the finished scalar.
- **Dockerfile:** no declaration value in this version; when one comes, only inside an exec-form
  array and through a pattern that refuses a leading `-`.
- **The health path** is the argument of a fixed probe (`python -c "import sys, urllib.request;
  urllib.request.urlopen('http://127.0.0.1:8000' + sys.argv[1])" <path>`); the schema's leading
  `/` keeps it from moving the host.

**The `DATABASE_URL` seam stays** in `x-backend`:
`${DATABASE_URL:-postgresql+psycopg://app:${POSTGRES_PASSWORD}@<database id>:5432/app}`, so an
environment can point elsewhere without a commit; `${DATABASE_URL:?...}` and no `POSTGRES_PASSWORD`
under `externalDatabase`, and the same where no unit runs a database at all.

**The truth rule reads a profile as compose does:** `$$` is one `$`; `$name` and `${...}` are
interpolations that never equal a declared literal; any other `$` is literal. Today it compares raw
strings and would call a correct render untrue.

*Considered and rejected.*
- **Copier partials.** No offline render for the check, no typing of values, and copier would
  still merge the output.
- **Jinja in `terp-cli`.** One unfiltered `{{ }}` is an injection, behind the CLI's whole
  dependency set.
- **`yaml.safe_dump`.** Output moves with the PyYAML version and cannot carry the header.
- **Writing every service in full without the merge key.** A shape change every `own` app would
  merge for nothing.

**3. A check of its own refuses a copy that is not the render.**

`deployment_generated_files_match_their_render` is a `terp.arch` rule, static-bespoke,
`runtime.applicability: not-applicable` (the app never reads its build files; the deploy-boundary
controls are the signing job's render and the executor's escape audit). `terp verify --only
generated` runs it in every profile, category `build`, like `routes-drift`, with the scope the
three files, `deployment.json`, `pyproject.toml` (which pins `terp-arch`), `.gitignore`,
`.dockerignore` and the copier answers file; `terp check` runs it too. It is its own check, not
part of `deployment`, for the reason `locks` is: a stale render contradicts nothing the declaration
says.

In the generated state it is red when the declaration cannot be rendered (the generator's refusal,
word for word); when a generator-owned file differs from the render (a short diff, and the fix);
when a generator-owned path the render does not produce exists; when an environment file is not
ignored (decision 1); when the project name is one compose or Docker would refuse; and when `build`
and the template answer disagree. It is silent for an
undeclared, `own`, `unmanaged` or unreadable declaration, and for the agreement question when the
app has no answers file. It notes, never red, a profile `terp release` will refuse under ADR 0184
decision 9 (no migration step and not exactly one `api` unit).

**It amends ADR 0184's never-red list for this check only:** a shape the generator cannot render is
red under `--only generated` because the app chose a state that promises a render; it stays never
red under `--only deployment`. The refusal names `own` as the way out, so ADR 0111's degradation
test holds.

`terp deployment render` writes atomically or refuses with the generator's findings; `--check` runs
the rule. A person changes a generated file by changing `deployment.json`, the project name or the
framework version, then renders and commits both. The only escape is the whole app,
`terp deployment adopt --build own`; there is no per-file escape and no marker.

**`build` is the app's to choose**, so a guarantee that must hold lives elsewhere: a deploy tool's
environment policy, "accepts generated releases only", checked against the signed manifest's
`build`, with a change of state shown on the plan a person approves. `terp promote` offers it as
`--require-generated`. It is deploy policy, so ADR 0184 keeps it out of `deployment.json`.

*Considered and rejected.*
- **Rendering in `terp verify`.** A gate that writes hides the change from review.
- **Under `--only deployment`.** A non-truth refusal on a red list ADR 0184 closed on truth.
- **Rendering again in `terp promote` and every executor.** It ties rollback to the exact framework
  version; the independent render belongs where the version always matches, in `sign` (decision 6).

**4. The template stops rendering the files for a generated app; adoption flips one recorded
answer.**

- **`deploy_build`**, a copier question (`own` by default, `generated`), recorded in the answers
  file. No validator: copier does not expose the operation inside one, and validators run on
  recorded answers during updates. A fresh `generated` render is red until `terp deployment render`
  runs, which fails closed. The seed becomes `deployment.json.jinja` taking `build` from the answer;
  its `_exclude` entry still keeps an update from creating it (verified on copier 9.16).
- **`project_slug` gets no copier validator**, because copier runs validators on recorded answers
  during every update, and one would cut an app off from every template fix. A name compose or
  Docker would refuse is refused instead by `adopt` and by `--only generated`.
- **`_exclude`** gains one entry per generator-owned file under `deploy_build == 'generated'`, so an
  update neither renders nor merges them.
- **Dependabot's `docker` entry is removed for every app**: base digests move with framework
  releases, and the file says it is the app's to edit.
- **The upgrade report and recipe** list the generator-owned files and add `uv run terp deployment
  render` after the sync; the template's `AGENTS.md` says the same. A tool that runs agent commands
  from a closed list needs a profile for the render.
- **A framework update of a generated app** is `copier update`, the install, `terp deployment
  render` and the check, in the copy the update is made in; a missed render is red there.

**`terp deployment adopt`** (ADR 0184's open command name) writes and prints the diff; `--dry-run`
only prints.
- `--build own` on an undeclared app writes `deployment.json` from the resolved profile, pins table
  digests for datastores the app added, and refuses by name a service on an image neither built nor
  in the table (`unmanaged` is the way out).
- `--build generated` needs a readable, true, renderable declaration and scaffolding from a template
  version with the question. It sets `build` and the answer (nothing else in the answers file),
  renders, deletes generator paths the declaration does not produce, and prints the diff: empty for
  a template-shaped app at the same version.
- `--build own` on a generated app sets both back and changes no file.
- `--unmanaged "<reason>"` writes ADR 0184's opt-out.

The answer is written, not passed to copier: copier's update renders the old version with the
*recorded* answers, so with `generated` recorded the files read as the app's own and are left alone,
from the first update on. That needs no template source, network, git or clean tree. Reversed, the
old render has the template's files again and the kept files merge as any `own` app's do. The
round trip has been run on copier 9.16.

*Considered and rejected.*
- **`copier update --data deploy_build=generated`.** Its old render has the files and its new one
  does not, so copier deletes or conflicts what the generator is about to write.
- **The template reading `build` from `deployment.json`** through copier's external data. A newer
  copier, every update depending on the declaration parsing, and the same old-render problem.
- **A conditional Dependabot file**, or `_skip_if_exists` for the generated files.

**5. What the generator expresses, and what it refuses.**

It refuses what it cannot render faithfully and never what it would rather not. No backup, no
frontend, no API, three `api` units, `instances: "many"`, no scheduler and an unknown role with a
command all render; safety and completeness stay ADR 0184's deploy-boundary check and the deploy
tool's.

| Unit | Image | Command if none declared | Health | Restart | Dependants wait for |
|---|---|---|---|---|---|
| `kind` | table digest | the image's | the recipe's | `unless-stopped` | `service_healthy` |
| `api` | backend | the image's (uvicorn, port 8000) | its `livenessPath`, probed | `unless-stopped` | `service_healthy` |
| `web` | frontend | the image's; none may be declared | the template's, fixed | `unless-stopped` | `service_healthy` |
| `worker` | backend | `terp jobs worker --forever` | none | `unless-stopped`, `init` | `service_started` |
| `scheduler` | backend | `terp jobs scheduler` | none | `unless-stopped`, `init` | `service_started` |
| `one-shot` | backend | the migration step | none (it exits) | `"no"` | `service_completed_successfully` |
| other role | backend | required | none | `unless-stopped`, `init` | `service_started` |

**Health is never a check that cannot fail, and never a disabled one.** A deploy waits with
`docker compose up -d --wait`, and Compose (2.40, measured) refuses a container that turns
unhealthy and a service whose check is disabled ("has no healthcheck configured"), and waits for
a service with no check until it runs. So a unit that serves no request has no check, in the
profile or in the image, and is ready once it runs; that is the truth about it until ADR 0024's
heartbeat gives it a liveness of its own (decision 9).

- **Images:** `<project>-backend-prod` and `<project>-frontend-prod`, with ADR 0185's `:?`-required
  tag once that is built. They are the hardened ones, constant in this version.
- **The migration step** is the one-shot without a command (`terp migrate upgrade --app-root
  /srv/app`, plus ADR 0185's release option later). A one-shot declaring `terp migrate upgrade` is
  refused ("drop `command`: the generator owns the migration step"), as is a second one-shot
  without a command.
- **The web tier** proxies to the one `api` it depends on, or the only one; `API_UPSTREAM` is
  rendered only when that id is not `api`. It publishes `${WEB_PORT:-23100}:8080` and loads no
  environment file.
- **Environment:** `.app.env` and the four platform values from `x-backend`; `.app.env` then
  `.app.<id>.env` listed on each backend unit. A file a variable names (`SMTP_CA_FILE`, say) is the
  environment's to mount; the generator renders none.
- **Volumes:** a `kind` unit's data in `<id>-data` at its recipe's path; a declared volume at
  `/srv/var/files` on the units its `mount` names.
- **Never rendered:** `instances`, `size`/`sizes`, `env`, `migrations`, `stateful`, `backup`. A size
  is the smallest a unit runs at; the environment chooses one, and an executor applies it.
- **Logging:** the template's json-file driver, 10 MB by three files, on every service.

**Refused, each with its own message:** a `compose.file` other than `docker-compose.prod.yml`, or
any override; `externalDatabase` beside a `database` unit; a `database` or `store` unit without
`kind`; two `database` units or two stores of one kind; the migration-step cases above; a role with
no default and no command; a `web` unit without `frontend/` and its lock, with a command, or with no
single `api` to proxy to; two `web` units; an `api` unit without both health paths; a `dependsOn`
cycle, or one naming a unit the declaration does not have (a generated profile runs only declared
units); a `kind` under a role other than its table entry's, or a kind this release has no recipe
for; a volume without `mount`, a mount path other than `var/files`, a mount on a unit not on the
backend image, or a volume id equal to a `kind` unit's `<id>-data`; any system package; a unit id
that is not a lowercase compose name; and (the reader) a `generator` block beside `own`. What the
generator refuses, the app can build in the `own` state.

*Considered and rejected.*
- **A Dockerfile fragment or "run this too" hook.** Arbitrary build code inside a vouched-for build.
- **Rendering a shell string** (a worker loop). The loop moves into `terp jobs worker --forever`.
- **Refusing an app with no `api` unit.** With no probe in the image and none on a unit that
  serves no request, the render is faithful; refusing it would be a topology rule.
- **Disabling the image's probe on each unit that serves no request**, as this record first
  said. Compose then refuses to wait on that unit at all, so every deploy of a profile with a
  worker failed as surely as with the inherited probe.
- **A probe that always passes** (`exit 0`, or a process check that cannot fail while the
  container runs). It would claim a liveness nobody measured.
- **Rendering sizes as limits, or inferring start order.** A limit would cap production at its
  minimum; inferred order is a second, hidden source.

**6. `terp release` is three jobs: build from a pristine tree, gate without credentials, sign
without running the app.**

ADR 0184 decision 9's exact SHA, fresh bases, ADR 0185 labels and no shared cache or tag stay. What
changes is who can touch what: no job that runs the app outside a build container holds a
credential, or writes into what is built.

**Hosts.** Each job runs on a fresh host or VM that is discarded after it, and `build` and `sign`
never run on a host where the gate, or any app code outside a build container, has run. Where a
deployment cannot separate them (one operator's machine running all three), the guarantee becomes
"the host is trusted", and the manifest records that the jobs were not separated. `build` runs from
the operator's toolchain image, as `sign` does, and never installs the app's environment on its
host. Build containers get no ambient identity: no metadata endpoint or other credential the
registry or the signer trusts is reachable from them, and the build job's own identity cannot sign.

**`terp release build`** builds from a pristine context of the SHA (BuildKit's git context, or a
`git archive` of the SHA). The app's code runs only inside BuildKit's build containers, which hold
no credential and no secret mount. It uses a builder created for the job and removed after it,
`--pull`, no cache import or export, and pushes under `<repository>:<tag>` with a credential scoped
to the release. ADR 0185's heads label is made in two passes: a `heads` stage, built from the
runtime stage and left out of the shipped image, runs `terp migrate heads` under `RUN
--network=none`; `build` reads its output, refuses it unless it is JSON of the expected shape
(package label to revision) within a size cap, and passes it as the label's build argument to the
second pass, which changes only the image's configuration. An `own` app whose Dockerfile has no
`heads` stage is released without the label, which ADR 0185 classifies restore-based; it is never
refused at the second pass. `npm run build` also runs under `RUN
--network=none`. BuildKit's own metadata output carries the pushed digests straight to `sign`. It
refuses, from data, an undeclared or `unmanaged` app, a tree holding `.terp-dist/`, and a lock
naming a path source.

**`terp release gate`** checks the SHA out and runs `terp verify --profile release` with npm
scripts off, then reads the schedule catalog (`terp inspect jobs`) from the pushed image pulled by
digest, with a pull credential scoped to this release's repositories, and run with `--network
none`, read-only, as its non-root user. It holds no push credential and no key, and nothing it
writes reaches an image. Its assurance document and the schedules go to `sign` as its word.

**`terp release sign`** is the operator's own toolchain: an image the framework's release pipeline
builds and hash-locks, at its newest version. It reads the SHA's tree and history from git and the
images from the registry as data, and runs nothing of the app.

1. It repeats `build`'s refusals, and takes the release tag from the driving tool directly (or
   derives it from the commit and the inputs), never from another job.
2. It validates the declaration with its own reader, which accepts any spec release up to its own
   with the same `schemaVersion`, and recomputes `inputs` from the tree, parsing `uv.lock` as data
   (or running uv with `--no-config --offline --no-python-downloads`).
3. In the generated state it renders the generator's files with the generator of the version the
   SHA pins: `terp-arch==<pin>` from a fixed index, checked against wheel hashes the signer image
   carries for every release from a supported floor up, run in a subprocess that cannot reach the
   signer. If the framework's release workflow publishes PEP 740 attestations for `terp-arch`,
   `sign` verifies the wheel's attestation against that workflow instead and the hash list goes. A
   pin below the floor is refused. A committed file that differs is refused.
4. It checks each digest from `build`'s metadata in the registry, and the labels.
5. In a sandbox that cannot reach the signer and returns data, it reads the backend image. Each file
   under `/srv/app` and `/srv/control_plane`, and each file the app wheel's `RECORD` lists (but its
   `.dist-info`), must equal the tree's, and each tree file the build context admits under those
   roots must be present. The one exception is the bytecode the build compiles there: each
   `__pycache__` file must be the checked-hash compile of a tree file, whose source hash its
   header carries, and the sandbox compiles that file with the image's own interpreter and
   compares the bytes. A wheel that maps files to other paths (`force-include`) is refused as a
   shape `sign` cannot compare, not read as tampering. The installed distributions must equal the
   lock's runtime set plus the app. It computes the SBOM (the backend's from its filesystem, the
   web image's from `frontend/package-lock.json`, which `npm ci` installs exactly), scans it for
   known vulnerabilities, and runs the secret scan over the history reachable from the SHA, all
   data. The web bundle cannot be compared with the tree; it rests on `build`'s isolation.
6. It signs.

**The manifest** is one JSON object, `"schemaVersion": 1`, serialised with sorted keys, no
whitespace, UTF-8 and no floats. Its sections say who vouches for what:

- **`inputs`**, recomputed by `sign` from the tree: `commit` (SHA, tree hash); `releaseTag`;
  `toolchain` (the signer's version, and the `terp-cli` and `terp-arch` versions the SHA pins);
  `spec` (the Terp Standard release the app pins, through its `terp-arch` mirror, which the
  signer's reader accepts, and that schema's SHA-256); `build`;
  `generator` (in the generated state: the version that rendered, the project name, each owned
  file's SHA-256); `declaration` and `profiles` (path, SHA-256 and content, base file then
  overrides); `baseImages`; `datastores`; `locks` (path and SHA-256); `buildArgs` (`TERP_VERSION`,
  `SOURCE_DATE_EPOCH`); `platform`; and `fetches`, derived statically (the base images'
  registries, the sources `uv.lock` records, the hosts in `package-lock.json`, the index the build
  backend comes from).
- **`outputs`**, checked by `sign`: per image its repository, manifest digest, image id,
  installed-package list digest, SBOM digest, scan and secret-scan results; per profile service the
  release will run, its image by digest; per unit, its image digest.
- **`collected`**, other jobs' word: the schedule catalog and the gate's assurance document (the
  gate's), the migration heads per unit and the build's provenance (the build job's), and the
  operator's statement of whether the jobs ran on separate hosts. The heads
  label can rule a restore-free rollback out; only the target's own `terp migrate check`, run from
  its signed image, rules one in (ADR 0185 decision 6).

**DSSE.** `payloadType` `application/vnd.terp.release-manifest.v1+json`, the payload's bytes in
base64, signatures over DSSE's pre-authentication encoding, `keyid` the hex SHA-256 of the public
key's DER form, verified before parsing; Ed25519 and ECDSA P-256. `sign` holds no key: `--signer
<argv>` is the production path; `--sign-key <file>` refuses unless `--test-key` is given. Who signs
and where the key lives stay outside this ADR. `cryptography` becomes an optional extra of
`terp-cli`; without it `sign` and `promote` refuse to run, never skipping a verification.

**Reproducible in what can be compared:** two cold builds of one commit with one tag give
byte-identical `inputs` and identical installed lists. Identical image digests are measured, not
promised. Compiling bytecode changes neither: it adds `__pycache__` files and installs nothing,
and checked-hash bytecode takes no time or mtime from the build.

**`terp promote` changes in five ways, and no others.** It accepts only that envelope and verifies
it against `--public-key <file>` (repeatable) before reading. It accepts any `spec` release up to
its own with the same declaration `schemaVersion`, reads the declaration with its own reader against
the manifest's own `datastores` record rather than its own table (so a datastore version a newer
table retired still rolls back), and refuses only a newer spec release. With `--require-generated` it refuses a manifest whose `build` is not
`generated`. In the generated state it audits the carried profile without rendering it: over the
parsed scalars and keys, never the text, every `$` is half of a `$$` or opens one of the
generator's fixed interpolations, a closed list of variable and place the framework publishes and
only extends (`terp.arch.deployment.generator.fixed_interpolations`, applied by
`escape_findings`); the nested `DATABASE_URL` default is parsed exactly; any YAML tag is refused. It runs
compose with an allowlisted environment, never its own.

*Considered and rejected.*
- **Gate, build and sign in one job**, or **build after the gate in its worktree.** The gate runs
  the app and can write into the build context; either way the signer would vouch for code nobody
  reviewed.
- **`sign` at the version the SHA pins.** The app would choose its verifier, and a fixed `sign`
  would reach an app only when it upgraded.
- **Signing the SBOM and package list another job produced.** `sign` reads the same facts as data.
- **Refusing every `spec` release `promote` does not carry.** Rollback across a spec-pin move would
  need the old CLI again.
- **JWS or a canonical-JSON signature.** DSSE signs bytes and is the one format an executor reads.

**7. Amendments.**

- **ADR 0062.** Its 2026-10-21 amendment stands in both states. Decision 1: bases pinned by digest
  from the table in both states, the bytecode compiled at build time, and no `HEALTHCHECK` in the
  backend image; the template's backend file is the seed's render and, in this version, the
  generated file is that same constant. Decision 2: `npm ci --ignore-scripts` and a
  build without hooks in both states, once measured. Decision 3: the template's profile is the
  seed's render with decision 1's changes; a generated profile is the declaration's render, so "the
  same topology as the dev workbench" no longer binds it, while `ENVIRONMENT=production`, the
  required secrets, no seed, restart policies and healthchecks are generator invariants. Decision
  4: the build-time half gains the template equality, the golden files and their properties.
  Decision 5 is unchanged.
- **ADR 0184.** Decision 9's `terp release` is decision 6's three jobs, and `terp promote` gains
  decision 6's five changes; decision 5's never-red list does not bind `--only generated`.

In the `own` state the declaration only describes, and copier merges as today. In the generated
state the profile is the declaration's render, so the truth rule holds by construction, and it
keeps running for its app-side half (health paths served, migration labels owned).

**8. Six pull requests, each leaving main green, held by golden files.**

1. **The Standard:** `generator.systemPackages`, `volumes[].mount`, their fixtures, and the catalog
   entry, riding ADR 0184's first spec release if it has not shipped.
2. **The generator and the template as its render:** the three tables and the recipes, the
   generator with its goldens, properties and import allowlist, the truth rule's compose
   unescaping, `terp jobs worker --forever`, the `--ignore-scripts` measurement, and the template
   replaced by the seed's render with exactly decision 1's changes. If the measurement finds a
   needed script, the template keeps scripts on and an exception word follows on its own (it
   found none). The reader still refuses `generated`.
3. **The wiring:** both spec pins and the mirror; the reader accepting `generated`; the rule and
   `--only generated`; `terp deployment render`; then the spec's reference SHA. `generated` is never
   accepted without its drift check.
4. **The template and adoption:** the question, the `.jinja` seed, the
   `_exclude` entries, Dependabot, the upgrade recipe, `AGENTS.md`, and `adopt`; template acceptance
   runs the copier round trip both ways and refuses scaffolding that predates the question; the
   reference app gains a generated lane.
5. **Release and promote:** the three jobs, the signer image in the release pipeline, the manifest,
   DSSE, and promote's changes, with throwaway keys and a job-local registry. Tests prove that
   `sign` runs no app code (it signs a release whose app fails on import) and refuses an image
   whose app layer differs from the tree.
6. **The lanes:** two cold builds compared; the shipped set against the lock; a generated reference
   app moved up one minor and rolled back by promoting the previous release (from the second
   framework release carrying the generator).

**Golden samples**, each a `deployment.json`, a project name, optional tables and the exact
expected files: `seed` (expected files are the template's own); `grown` (the reference shape:
worker, scheduler, companion, files volume, a size table that renders nothing); `no-frontend`;
`no-api` (a migration step and a worker); `no-api-no-migration` (renders, with the check's note
that `terp release` will refuse it); `external-database`; `hostile-values` (`$`, `${SECRET_KEY}`,
`$$`, `$!`, quotes, backslashes, shell metacharacters, non-ASCII and above U+FFFF in commands; `$`
and `'` in health paths; ids `no`, `true`, `1e3`, `0o17`); `store` (an injected test table);
`renamed` (no template names, `api` not first); `no-database` and `datastore-only` (no seam, no
backend image); and one refusal sample per refusal. Over all of
them: byte-identical renders across processes and hash seeds; the truth rule, deploy-safety and
`promote`'s escape audit pass; the production-profile and build-input invariants hold; every `FROM`
is a table digest; plain scalars read back as strings under YAML 1.1 and 1.2. A Docker lane runs
`docker compose config` over `hostile-values` and gets every value back literally.

**9. Open.**

- **Python build-time code** (the app's build backend, resolved at build time; dependencies with no
  wheel) runs inside `build`'s containers, as in the template. A locked build backend and a
  wheels-only rule are a later change to both states.
- **`collected` facts** stay other jobs' word until they can be read without running the app.
- **The fixed-interpolation list** grows with ADR 0185's tag. Executors must carry the new list
  before an app may pin the release that extends it: a release-train item. The signer image is the
  same kind of item for every declared app, `own` included: its reader must know the app's spec
  release, and (until PEP 740 attestations replace the list) it carries the wheel hash of each
  `terp-arch` it may render with, so it is updated before any app can release on a newer framework
  version. The order is executors first, then the signer, then the app's pin.
- **The ignore check needs git.** In a tree with no git work tree it notes rather than judges.
- **System packages, script exceptions, other mount paths** wait for a measured need; the first
  package also needs a pinned source two cold builds read alike.
- **Worker and scheduler health** waits for ADR 0024's heartbeat. Until then such a unit has no
  check and is ready once it runs, which is what `up --wait` can wait for.
- **One platform per release; bit-for-bit images** stay a measurement.
- **Signing keys, the environment policy, and which key an environment trusts** are the deploy
  tool's.
- **The deploy-safety audit over a resolved plan** is a separate request.

## Consequences

- A generated app meets a framework update as a re-render, never a merge conflict, and grows by
  declaring.
- The template's build files are written once, by the generator; adopting `generated` in a
  template-shaped app changes no build file. Making the template the render is itself one merge for
  `own` apps that edited the listed lines.
- No job that holds a credential or a key runs the app outside a build container; `sign` checks
  what ships from data, and the manifest says what it could not check.
- Promotion and rollback do not depend on the framework or spec version a release was cut with.
- Every declaration value reaches compose as a literal.
- The vocabulary grows by two words and the Standard by one rule: one spec release, one framework
  release and a reference-SHA move.
- What the generator cannot express sends an app to `own`, never to a failed deploy.
- **No lifecycle script runs in the web image, by measurement.** On 2026-10-21 a fresh template
  render and the reference app render were each installed (`npm install`, the published
  `@terpjs` 0.34 packages) and their web image built twice from a cold builder, once with the
  template's install and build as they were and once with `npm ci --ignore-scripts` and
  `RUN --network=none npm run build --ignore-scripts`. Both locks hold 251 packages; one,
  `fsevents`, declares an install script, and it is macOS-only and never installed on Linux.
  Neither app declares a pre- or post-script. Both builds succeeded both ways, and each pair of
  bundles was byte for byte the same (six files, compared by SHA-256). So the template turned
  scripts off with no exception word; an app whose lock does need one keeps its frontend
  Dockerfile as its own under `own`.
- **A deploy's `up --wait` passes, by measurement.** On Compose 2.40.3 a container whose image
  check probes a server it does not run turns unhealthy and `up -d --wait` exits 1; a service
  with `healthcheck: {disable: true}`, with or without an image check, makes it exit 1 with
  "has no healthcheck configured"; a service with no check in the image or the profile is
  waited for until it runs, and the command exits 0. The reference app, whose production
  profile is the `grown` render, built from this tree (wheels and render staged as CI's
  reference variant stages them) came up with `up -d --wait` exiting 0 in 61 s: db, api and web
  healthy, the worker, the scheduler and the companion running, the migration step exited, the
  entrypoint answering. Before, every such deploy failed.
- **The backend image ships checked-hash bytecode, by measurement.** Two cold builds of the
  reference app's dependency stage gave the same 1355 `.pyc` files byte for byte from the same
  sources, and the image installs the same 57 distributions with and without compiling. Timing
  the platform's import (the CLI, the control plane and three capabilities) five times in one
  image on one host: median 3.2 s with the shipped checked-hash bytecode, 3.4 s unchecked-hash,
  2.9 s timestamp-based, 6.2 s with none. Checked-hash keeps nearly all of the gain and is the
  only one of them whose bytes do not depend on when a file was written. A package the wheel
  installs beside the two source roots (a companion's) is not compiled in this version.

## Debate

Four rounds of adversarial review changed this record; the fourth found nothing new of weight.

**Round one.**
- The signing key left the job that runs the app: release split into jobs, and `sign` runs no app
  code.
- The executor and promote no longer render again; that tied rollback to a framework version.
  `promote` audits escaping, and the independent render moved to `sign`.
- `.app.env` stayed in `x-backend`: moving it would have silently stripped it from every service an
  `own` app added (shown by a three-way merge).
- The template-equals-render claim was made true: `build:` on `api`, neutral comments, `web` without
  an environment file, every template change listed.
- An environment policy, not the app's choice, decides whether only generated releases run.
- The ignore check asks about concrete files only.
- The Dockerfiles take no declaration input in this version; apt rendering is gone.
- Smaller: no copy-time validator; a check of its own, static-bespoke, with the never-red amendment
  stated; compose's own unescaping; `\U` escapes and a two-resolver check; four more refusals;
  static `fetches`; the scan and the `cryptography` refusal; Studio's two-Dockerfile limit named;
  Dependabot's `docker` entry removed; six pull requests.
- Kept against the review: an app with no `api` unit renders.

**Round two.**
- The build moved before the gate, from a pristine tree, with app code only in build containers;
  the gate holds no credential; digests go from `build` to `sign` directly; `sign` compares the
  image's app files with the tree, and states that the web bundle rests on the build's isolation.
- `promote` accepts any spec release up to its own; refusing unknown ones had brought the rollback
  coupling back.
- `sign` is the operator's own hash-locked image; the SHA's pin is used only for the render, from
  pinned hashes, in a subprocess, above a floor; uv and the layer readers cannot reach the signer.
- Smaller: `web`'s healthcheck fixed as the template's; the kind recipe carries the datastore's own
  environment; the heads label rules rollback out and the target's own check rules it in; the
  secret scan moved into `sign`; the release tag and the step-one refusals taken by `sign` itself;
  the escape audit over parsed values with tags refused; git's own `check-ignore` and a Docker
  matcher that reports what it cannot read; the no-api-no-migration case noted and sampled; the
  project name used verbatim; silence without an answers file.

**Round three.**
- The host separation the three jobs rest on is stated: fresh, discarded hosts, `build` and `sign`
  never where app code ran, and a recorded "trusted host" where a deployment cannot separate them;
  `build` runs from the operator's toolchain image and never installs the app's environment.
- The image comparison is one-directional plus presence, so a tracked file the context excludes is
  not a false refusal; a wheel that remaps paths is refused as uncomparable.
- `promote` reads a carried declaration against the manifest's own datastores, so a retired
  datastore version still rolls back.
- Smaller: the heads stage and the bundle build run without network, the label's two-pass mechanism
  and the build containers' lack of ambient identity are stated; `sign` names its reader and the
  signer train item covers `own` apps; PEP 740 attestations may replace the hash list; the secret
  scan covers history; no copier validator on the slug, which `adopt` and `--only generated` refuse
  instead, so no update is blocked; the check's scope restored; the gate's pull credential scoped.

**Round four** found nothing new of blocker or serious severity; three minors were taken: `spec`
records the release the app pins, the heads output is shape- and size-checked before it becomes a
label, and an `own` app without a `heads` stage releases unlabelled rather than being refused.

## How it was built

Decision 8's second pull request, in 0.35.0.

- **The tables** live in `terp.arch.deployment.tables`: `base-images.json` (the four bases the
  Dockerfiles name, each by digest with the tag it was read from, sources recorded in
  `BASE_IMAGE_SOURCES`), `system-packages.json` (`{"packages": {}}`), and the `postgres` recipe.
  Each table is refused outright in any other shape.
- **The generator** is `terp.arch.deployment.generate`. The template's three files are its
  render of the seed, written from it and held byte for byte; a copier render of the template
  with its default answers equals the generator's render of that render's own declaration and
  project name, file for file. Its Dockerfiles take no declaration value: every sample renders
  the template's.
- **The golden samples** are `tests/architecture/generator_goldens/`: `grown`, `no-frontend`,
  `no-api`, `no-api-no-migration`, `external-database`, `hostile-values`, `store`, `renamed`,
  `no-database` and `datastore-only`, each a declaration, its sample record and the exact
  profile, and 30 refusal samples, one per refusal. `seed`'s expected files are the template's
  own. Over every sample: the same bytes in processes with hash seeds 0, 1, 4242 and random;
  every plain scalar a string under PyYAML (YAML 1.1) and the 1.2 core schema; every command,
  liveness path and mount back as declared after compose's unescaping; the truth rule,
  deploy-safety and the escape audit silent and no YAML tag; ADR 0062's invariants; ASCII, LF,
  one final newline. The Docker lane ran `docker compose config` (Compose 2.40) over
  `hostile-values` and got every value back literally, with the environment's `HOME` and
  `SECRET_KEY` set and never substituted; and `up -d --wait` over the reference app's `grown`
  render, built for real, which exited 0 (*Consequences*). A test holds what made it pass:
  no rendered service disables a check, and the backend image carries none.
- **The reference app** carries the template change as an `own` app would: its production
  profile is now the `grown` sample's render, held equal by a test, so its worker runs
  `terp jobs worker --forever` in both profiles and its worker, scheduler and companion no
  longer inherit the backend image's HTTP healthcheck, which had reported each of them
  unhealthy and failed every `up --wait` of that profile.
- **Not yet:** the reader accepts neither `generated` nor the two words (the pinned spec
  release does not carry them), so a sample is read as `own` without them through the reader,
  then as the generator's typed model. Decision 8's third pull request moves the pins and the
  mirror, and replaces that step with the reader.
