# 0184 — A deployment declares its units, and terp verify reads them

- **Status:** Proposed (awaiting review). The framework's half of decisions 1 to 6 and 8 is
  built in 0.35.0: the template seed for a fresh render only, `apps/example`'s and the
  reference app's declarations, the checked mirror of the schema, the typed reader in
  `terp.arch.deployment`, the two `terp.arch` rules the Terp Standard catalogues for it
  (`deployment_declaration_is_readable`, `deployment_declaration_tells_the_truth`),
  `terp verify --only deployment` with its app part, the closed datastore table and the
  profiles' digest pins. Held by `tests/architecture/test_deployment_declaration.py`,
  `test_deployment_truth.py`, `test_deployment_app.py`, `test_deployment_schema_mirror.py`
  and `test_deployment_fixtures.py`. Decision 7's deploy-boundary check and decision 9's
  commands are not built.
- **Date:** 2026-10-13 (drafted); brought into this repository with its implementation on
  2026-10-21. 0182 and 0183 are reserved for other records.
- **Relates:** amends [ADR 0110](0110-an-app-declares-which-parts-of-its-dev-topology-are-load-bearing.md)
  decision 5 (dev stays dev, now held from both files) and, for this file only, decision 3's
  never-red list (an unknown key is refused here) and
  [ADR 0111](0111-flexibility-is-bounded-by-legibility-not-by-capability.md) decisions 5 and 6
  (the first deploy vocabulary in the spec, and layer 2 given a file); designs
  [ADR 0134](0134-the-lifecycle-has-one-driver-and-a-workbench-is-not-it.md) decision 4
  (`terp release`, `terp promote`); closes
  [ADR 0181](0181-terp-supplies-the-inside-of-a-deployable.md) decision 4 item 4 (the
  deploy-unit vocabulary); builds on
  [ADR 0062](0062-production-deployment-profile.md) (the production profile this describes, and
  the renderers it still defers), [ADR 0027](0027-packaged-migrations-per-package-histories.md)
  (the per-package migration labels a unit claims),
  [ADR 0124](0124-a-declared-variable-may-name-the-services-that-see-it.md) and
  [ADR 0180](0180-a-value-is-required-where-the-app-runs-that-way.md) (the variable facts that
  stay in the environment manifest), [ADR 0047](0047-scheduler-seam-and-schedule-catalog.md)
  (schedules stay in the catalog), [ADR 0177](0177-egress-is-refused-at-the-socket-not-only-at-the-import.md)
  (egress stays in its policy), [ADR 0106](0106-the-verify-profile-is-open-at-the-app-end.md)
  (the profile the check joins), [ADR 0103](0103-the-ideology-one-pattern-enforced-escapable-by-proof.md)
  (the escape's shape), [ADR 0082](0082-repo-split-readiness-spec-as-a-package.md) and
  [ADR 0086](0086-publish-the-terp-standard-to-pypi-and-npm.md) (the spec as a published package),
  [ADR 0141](0141-the-gate-scans-every-deployable-not-only-the-mounted-one.md) (a second
  deployable in one repository); and
  [ADR 0185](0185-a-release-declares-the-schema-window-it-accepts.md) (the per-release tag
  `terp promote` sets and the rollback classification it runs; whether a rollback is restore-free
  is owned there, never declared here). Supersedes nothing.

---

## Context

A tool that deploys a Terp app has to answer a small set of questions about it: which units
exist, which one serves the API, how to tell each is healthy, which unit owns which migration
histories, what holds state and how it is backed up, and what a rollback is. ADR 0111 named the
unit, its health check, where migrations run and what a rollback is as layer 2 of a deployment,
legibility, "truth-checked, never gating",
and said layer 2 exists. "Every stateful resource names a backup" is a layer-1 invariant
there, not a layer-2 fact; this declaration gives it a field (decision 7).
For a single deployable rendered from the template it exists only by convention: the template's
production profile is `db`, `migrate`, `api` and `web`, and a test holds the template and the
example to exactly that set. A
tool that assumes those four names is guessing, and the guess fails silently the first day an
app adds a worker, a scheduler, a shared store or a second deployable. ADR 0110's context said
the same about the development loop, and the fix there was a declaration with a truth check.

Nothing in the tree can carry the answer today:

- `workbench.json` refuses a declaration whose `compose.file` names a deployment profile, and that
  refusal is the decision rather than a note under it.
- `environment.schema.json` describes variables, one at a time, with their secrecy, their
  `services` (ADR 0124) and their `requiredIn` (ADR 0180). It has no place for a unit.
- The production profile states images, commands and wiring, and cannot state a health path the
  app serves, a migration owner, a backup policy or a rollback.
- `terp inspect` emits a view and returns, with no verdict, so it cannot validate
  anything.

The design already exists. PLATFORM_REACH R4 (`docs/internal/PLATFORM_REACH.md` at
`db40d288`, folded into ADR 0181 since) put `deployment.json` at the project root, defined
in `terp-spec`, truth-checked by `terp verify --only deployment`, never gating, with an
`unmanaged` escape and four rules inherited from ADR 0110. Its runtime applicability is
`not-applicable`, because a declaration is source and the runtime never reads it. When
R4 was folded into ADR 0181 as decision 4 item 4, the record kept units, images, health paths,
migration ownership and rollback, and lost R4's per-unit `stateful` and `backup` fields. The
open-items list proposes folding the item into ADR 0111 decision 5. It gets its own record
here instead, because it is more than a vocabulary: a file, a check with a boundary, an app-owned
seed, a release train and two commands.

Those two commands are ADR 0134's debt. Cutting an exact-SHA artifact set and deploying an
existing set without rebuilding it "exist only inside a workbench", and decision 4 names them
`terp release` and `terp promote` so the gap is a decision.
They are still "named, not designed", and the CLI has no release, promote, deploy, build
or eject command. A
release command needs to know which units to build and which migrations each owns, so it needs
this declaration first.

One word needs care. In `workbench.json`, `"unmanaged": true` with a reason means a tool cannot
drive this app, and the tool says so. A deploy tool that
wanted its own "managed or unmanaged" switch, meaning "builds from its own Dockerfile", would give
the same word a second meaning in the next file over. How an app's images are built is a
different question from whether a tool can drive it, so it gets a different field.

## Decision

**1. `deployment.json` at the project root is the deploy declaration.** One JSON object with a
`schemaVersion`. It describes the app's deployment profile, never its development loop, and
nothing in it is read by the running app. The template seeds it once, describing its own
production profile, and only into a fresh render: `copier copy` writes it, `copier update` never
does. `_skip_if_exists` alone would not hold that, because it only stops copier overwriting a file
that exists; an update still creates one that is absent, which is how a seeded file the
template-owned half depends on reaches existing apps.
So the template also lists the seed in `_exclude` under a condition on copier's
`_copier_operation` that is true for an update, and a template test renders an update of an app
that has no `deployment.json` and finds none afterwards. An existing app therefore stays
undeclared through every framework update, its check stays a no-op (ADR 0110 decision 7), and it
is declared only by a deliberate step: it writes the file itself, or runs an adoption step that
writes it from the real profile and shows the diff. Once the file exists the app owns it: it goes
in copier's `_skip_if_exists` and in
`_APP_OWNED_SCAFFOLD_FILES`,
which `test_the_app_owned_scaffold_list_matches_copier` keeps equal.
`apps/example` gets one in the same change, so the check has a real subject on its first day, as
`workbench.json` did.

The seed is exactly the template's profile, `db`, `migrate`, `api` and `web`:

```json
{
  "schemaVersion": 1,
  "build": "own",
  "compose": { "file": "docker-compose.prod.yml" },
  "units": [
    { "id": "db", "role": "database", "kind": "postgres", "version": "17",
      "stateful": true, "backup": { "every": "P1D", "keep": "P30D" } },
    { "id": "migrate", "role": "one-shot", "dependsOn": ["db"] },
    { "id": "api", "role": "api", "healthPath": "/health/ready", "livenessPath": "/health/live",
      "dependsOn": ["db", "migrate"] },
    { "id": "web", "role": "web", "dependsOn": ["api"] }
  ]
}
```

It has no `volumes` entry: the profile's one named volume, `db-data`, is mounted only by `db`, so `db`'s backup policy covers it (decision 2). The seed claims no
`migrations`, because the template ships no app module; every installed history is still brought
to head (decision 9).

`apps/example`'s declaration has the same units and differs in one place. The example ships four
modules with their own histories (`journals`, `notes`, `projects` and `tasks`, under
`apps/example/app/modules/`), and an app module's label is its module name, so its `api` unit
claims them: `"migrations": ["journals", "notes", "projects", "tasks"]`. That gives the label
rule an app-module label to check on its first day. The capability histories the example installs
stay unclaimed, and are still brought to head.

There is no `terp:` version key. The app's exact pins already are the version, and a second statement of it would
be one more pin to drift.

**2. It is a partial description of units, and every fact has one owner.** A sketch:

```json
{
  "schemaVersion": 1,
  "build": "own",
  "compose": { "file": "docker-compose.prod.yml" },
  "units": [
    { "id": "db", "role": "database", "kind": "postgres", "version": "17",
      "stateful": true, "backup": { "every": "P1D", "keep": "P30D" } },
    { "id": "api", "role": "api", "healthPath": "/health/ready", "livenessPath": "/health/live",
      "migrations": ["app", "audit"], "env": ["SOME_API_BASE_URL"],
      "instances": "one", "size": "small", "dependsOn": ["db"] },
    { "id": "worker", "role": "worker", "command": ["terp", "jobs", "worker"], "dependsOn": ["db"] },
    { "id": "web", "role": "web", "dependsOn": ["api"] }
  ],
  "volumes": [ { "id": "files", "backup": { "every": "P1D", "keep": "P30D" } } ],
  "sizes": { "small": { "cpu": 0.5, "memoryMiB": 512 } },
  "rollback": { "strategy": "redeploy-previous-release" }
}
```

A profile that runs no database service at all says so beside the units, not as one:
`"externalDatabase": { "backup": "client" }`. The template's documented way to get there is an
external `DATABASE_URL` plus an override file that removes `db`, so `compose` may name
that override too: `"compose": { "file": "docker-compose.prod.yml", "overrides":
["docker-compose.external-db.yml"] }`. The check reads the base file and its overrides, in order,
as one resolved profile, merged the way `docker compose -f <file> -f <override>` merges them, and
every rule below applies to that resolved profile.

What each part answers, and what it deliberately does not:

| Part | Answers | Not here |
|---|---|---|
| `units[].id` | the profile service this unit is | anything about services it does not name |
| `role` | what a tool may look the unit up as | an approved list of roles |
| `kind`, `version` | a database or shared store taken from the framework's datastore table | a free image reference: there is no `image` key |
| no `kind` | the unit is built from the checkout, through its profile service | a registry, a tag, a build host |
| `command` | an argv list, never a shell string, restating the profile service's `command`, which owns it | a command the profile does not run |
| `healthPath`, `livenessPath` | how to tell the unit is ready and alive | |
| `migrations` | the histories the unit owns, by package label (ADR 0027), recorded per unit in the release manifest | which histories an upgrade applies: every installed package is brought to head (decision 9), so a label no unit claims, or one two units claim, changes nothing |
| `env` | the variable names the unit needs passed | the variable's type, secrecy, `services` or `requiredIn` |
| `dependsOn` | start order, restating the profile service's `depends_on`, which owns it | an order the profile does not use |
| `instances` | whether the unit may run more than one copy (`one` or `many`) | how many copies an environment runs |
| `size`, `sizes` | named sizes and the smallest one each unit runs at | which size an environment uses |
| `stateful`, `backup` | that the unit or a named volume of the profile holds state, and its backup policy: what (given by where the policy sits), how often, how long kept. A stateful unit's policy covers the named volumes only declared stateful units mount (the seed's `db-data`), so those are never declared again; `volumes` is for named volumes no declared stateful unit owns, such as a files volume | where backups go, their credentials and their encryption |
| `externalDatabase` | that the app's database is one this deployment does not run, with `{"backup": "client"}`: its owner backs it up. It names no profile service, so rule 2's profile match does not reach it, and `"client"` is valid only here | its connection, which is an environment fact |
| `rollback` | what a rollback is: `strategy` is closed, and `redeploy-previous-release`, `terp promote` of an earlier release manifest (decision 9), is the one value schemaVersion 1 knows | whether a rollback is restore-free: 0185 decision 6 classifies that by the target image's own `terp migrate check`, so no declaration can claim a window the target's code does not accept |
| `build` | `own` or `generated` (decision 4) | |

The roles share `workbench.json`'s words where they mean the same thing (`web`, `api`,
`one-shot`, `database`, `worker`) and add `scheduler` and `store`, a broker or shared store. R4's sketch said `datastore`; one word
per thing across both files is worth more than keeping the sketch's spelling. Exact key spellings
are fixed by the spec's schema, not by this sketch.

Facts with another owner stay there. Where the declaration restates one (a unit's `command`,
`dependsOn` and `env`, a volume), the owner wins and rule 2 (decision 5) turns a disagreement red:

- **The profile** owns each service's command, start order, image and volumes. The declaration
  may restate `command` and `dependsOn` so a reader need not parse Compose, and a restated value
  that differs from the profile is a lie, not a second opinion.
- **Variables**, their secret marks, `services` and `requiredIn` stay in
  `environment.schema.json` (ADRs 0124 and 0180). A unit's `env` is a claim about the profile and
  is checked against it. A name *passes* to a unit when it is in that service's `environment:`
  block, or when the service loads through `env_file` the rendered file that
  `environment.schema.json` routes the name to: `.app.env` for a declaration with no `services`,
  `.app.<unit>.env` for one whose `services` include the unit, by the same `rendered_files`
  rule the renderer uses. An app variable
  reaches the template's services only that second way, so a name the manifest
  does not declare, or scopes to other services, is a name the profile does not pass.
- **Jobs and schedules** stay in the control-plane catalogs. A schedule with
  no `scheduler` unit is never red: the default trigger is an external cron, and
  an absent service is never red (ADR 0110 decision 3). Making sure every schedule has a trigger
  is the deploy tool's job, and the list it needs travels in the release manifest (decision 9),
  because the catalog is code and a tool that never imports the app cannot read it.
- **Egress hosts** stay in `EgressPolicy`, with a per-environment value arriving through a variable the manifest declares.
- **Environment facts** never enter `deployment.json`: domains, TLS mode, CORS origins
  (platform-owned), an
  external database's connection, the `ENVIRONMENT` value, seed or data policy, log retention,
  the backup destination and a reference to its credentials, the image digest allowlist, and the
  size and instance count per environment. They belong to whatever records environments. The
  backup credentials themselves are held where the deploy tool keeps secrets, never in this file
  or in a committed record. This ADR moves nothing out of
  the profile: it keeps its hard-coded `ENVIRONMENT: production` and today's log cap until a later record says otherwise.
- **Development topology and reload classes** stay in `workbench.json` (decision 6).

**3. No free image, and no path outside the checkout.** A unit is either built from the checkout
or named by `kind` and `version` from a closed datastore table that each framework release
publishes, one digest per entry. The template's `postgres:17-alpine` by tag becomes `kind: postgres`,
`version: 17` with a digest the framework release states, and the template and `apps/example`
pin that digest in their profiles in the same change. An `image` key is an unknown key and is
refused, so a declaration cannot name a registry.

The declaration's words are not the only place an image is named, so the profile is held to
them as well. Under rule 2 (decision 5), a `kind` unit whose profile service's image is not the
table's digest for that kind and version (a tag, a foreign registry, another digest) is red; a
unit without `kind` is red unless its profile service runs an
image some profile service builds from the checkout, by its own `build:` or by the `image` name
of a service that has one (the template's `migrate` reuses the `api` build that way). Undeclared
services stay outside the check, and `terp release` holds them instead (decision 9).

*The checkout* is the root of the git work tree that contains the project root, or the project
root itself when it lies in no work tree. A path the declaration leads a reader to (the profile
file, a build context, a Dockerfile) is resolved against it, following symlinks, and refused if
it lands outside. A deployable in a subdirectory, the shape ADR 0141 allows, may build from the
repository root: `apps/example` does, with `context: ../..`, and that passes, because it
resolves to the work-tree root. Strings carry a length cap and refuse control characters.

The table states which digests this framework version accepts; whether a particular environment
accepts them is the deploying tool's per-environment allowlist, outside this file (decision 2,
environment facts), because the pin
that selects the framework version is itself in an agent-editable `pyproject.toml`. The framework's
part of signing is the check: `terp promote` verifies a release manifest's signature against a key
it is given (decision 9). Who signs a release, which key that is and where the release is stored
are outside this ADR; nothing in the framework's part changes with that answer.

**4. Four states, and `unmanaged` keeps its one meaning.**

| State | The file | `terp verify --only deployment` | A deploy tool |
|---|---|---|---|
| Undeclared | absent | passes, no-op (ADR 0110 decision 7) | may decline to drive the app, and says so in one sentence |
| Own | `"build": "own"` | runs | drives units built from the committed profile and Dockerfiles, with no build guarantee |
| Generated | `"build": "generated"` | runs | drives units whose build files a framework generator renders |
| Unmanaged | `{"unmanaged": true, "reason": "..."}` | off; a missing reason is red | does not drive the app and shows the reason |

`unmanaged` means exactly what it means in `workbench.json` and in R4 rule 3: a tool cannot drive
this, and says so honestly. An escape without a reason is
a hole, not an escape (ADR 0110 decision 4). How the images are built is `build`, a separate field.
So every file sits in exactly one state: `build` is required whenever `units` is present, and it
never appears beside `unmanaged`. A file with units and no `build`, or with `unmanaged` and
`build` together, is refused as unreadable (decision 5), never guessed into a state.

`generated` is in the schema from its first release, so the four states are fixed once. A
toolchain with no generator refuses the value the way it refuses a `schemaVersion` it cannot read: "this toolchain cannot
honour `generated`; upgrade, or declare `own`". The generator itself, and the switch of
build-file ownership from the template to it, is a later framework ADR that amends ADR 0062. Its
generated files stay committed and drift from them is refused, the way `terp routes --check`
refuses a stale route table, so every consumer that reads the committed profile keeps working.

**5. `terp verify --only deployment` is a truth-about-self check, never a topology gate.** It
joins the standard profile (ADR 0106). Its scope errs toward triggering, as `workbench`'s does, and covers every input a
rule reads: `deployment.json`; `environment.schema.json`; `workbench.json`, which names the
development file decision 6 refuses; `pyproject.toml` and `uv.lock`, which decide the installed
migration labels; `**/*.py`, which decides the routes served; and every YAML file, because the
declared `compose.file` and its overrides may sit anywhere and bear any name (decision 6).
It is red for exactly R4 rules 1 and 2, with rule 2's truth check
applied to every fact the declaration restates from the profile, plus a file this toolchain
cannot read:

- **Cannot be read:** invalid JSON; a value the schema refuses (a wrong type, a control character, or a string over its length cap, decision 3); an unknown key (the reason `envschema` refuses one: a misspelt `stateful`
  would otherwise be a policy that silently does nothing), except a `$`-prefixed annotation key,
  which carries no behaviour and is exempt as it is there; a key for deploy policy (who
  may publish, how many approvals a deploy needs, who may reach a deployed app, which gate policy
  applies), refused with its own message, "`<key>` is deploy policy: it belongs to the deploying
  tool's environment policy, not to this file", because anyone who can commit to the app could
  lower a policy kept here; the schema names those keys so every reader gives that message; a
  `schemaVersion` this toolchain does not know; a closed-vocabulary value it cannot honour; `backup: "client"`
  anywhere but `externalDatabase`, because a unit or volume the deployment runs is backed up by
  the deployment; a unit `size` that is not a key of `sizes`, because a size that points nowhere
  states nothing; a path outside the checkout; `unmanaged` without a reason; `units` without
`build`, or `unmanaged` together with `build` (decision 4); a `compose.file` or
  an override that is the development compose file (decision 6). Refusing an unknown key departs from ADR
  0110 decision 3, whose never-red list includes "a key some other tool invented";
  for `deployment.json` this amends that list, for the misspelt-`stateful` reason, and
  `workbench.json` keeps it.
- **Rule 1's boundary:** a field the schema marks as resolved by role, declared under a role the
  vocabulary does not know, because that field has no reader (ADR 0110 decision 3).
- **Rule 2, from files:** a declared unit that is not a service in the profile it names; a
  declared volume that is not a named volume in that profile, because its backup policy would
  back up nothing; an `env` name that profile never passes to that unit (decision 2); a declared
  `command` that is not the profile service's `command` in list form, or a `dependsOn` that is
  not the profile service's `depends_on` restricted to declared units; a unit image that breaks
  decision 3 (a `kind` unit not on the table's digest, a unit without `kind` that the checkout
  does not build); `externalDatabase` beside a resolved profile that still runs a database
  service (a declared `database` unit, or a service on a database digest of the datastore
  table), because the database is then one the deployment runs, with the message "the profile
  still runs a database service; name the override that removes it in `compose.overrides`, or
  drop `externalDatabase`".
- **Rule 2, from the app:** a `migrations` label that no installed package and no app module owns; a `healthPath` or
  `livenessPath` the app does not serve. These two need the app's installed environment, and the
  path check imports the app, so they skip with a named note when no app is importable, as
  `authz-surface` already does.

Never red: an undeclared service; no frontend; three APIs; a role nobody has heard of that
carries nothing resolved by role; a stateful unit with no backup; a schedule with no scheduler;
`instances: "many"` (the runtime controls for shared stores and a shared realtime broker stay
where they are); `externalDatabase` with a resolved profile that runs no database service,
including the template's base file plus an override that removes `db`; the seed's shape, a
stateful `db` unit with a backup and no `volumes` entry for the `db-data` it alone mounts; an
installed migration label no unit claims, or one two units claim (decision 9); a build
context that leaves the project root but stays inside the work tree (`apps/example`'s
`../..`); a profile file of any name that is not the development one; any topology nobody
predicted. A missing backup is a safety property, ADR 0111 layer 1, and it is enforced against
the resolved plan at the deploy boundary, not by a layer-2 check (decision 7).

"Never gating" means three things, and only these: absence passes, `unmanaged` passes, and no
rule asks whether a topology is approved. It does not mean a lying declaration passes: that is
red, as it is for `workbench.json`. A tool that must not execute the app's code reads the file as
data against the published schema and needs nothing else; the two app-side cross-checks belong to
the app's own gate.

**6. Dev stays dev, and now the boundary is held from both sides.** This amends ADR 0110 decision
5 without reversing it. `workbench.json` still refuses a deployment profile, by its `.prod.`
infix rule. `deployment.json`
refuses the mirror case, and only the actual overlap: a `compose.file` or an override that
resolves to the file
`workbench.json` names, or, in an app with no `workbench.json`, to the template's development
file `docker-compose.yml` at the project root. It requires no infix, so a profile named
`compose.production.yml` or `deploy/compose.yml` can be declared; the file name of a deploy
profile is not a gate. Between the two refusals the files can never describe the same compose
file. They overlap in concept and stay separate files, as R4's
compatibility note says:
development is retryable and deployment is not. The reload classes that drive the development
loop (hot, restart, env, recreate and the rest) belong to a later `workbench.json`
`schemaVersion` and never to this file; across releases only a unit's `migrations` matter.

ADR 0110 decision 5's "topology stays ungated"
holds unchanged for the deployment profile: this check reads it and asks only whether the
declaration tells the truth about it.

**7. This amends ADR 0111 in two places, and supersedes nothing.** Decision 5: `deployment.json`
is the first deployment vocabulary in the spec, and it is the vocabulary ADR 0181 decision 4 item
4 asked for, with R4's `stateful` and `backup` restored. Decision 6: layer 2 now has a file and a
check, and "absence means a workbench cannot drive the deploy and says so"
stays true word for word. Layer 1 gains one invariant that is decidable for *declared*
resources: with a declared `stateful` and `backup`, "every declared stateful resource names a
backup" can be stated over the artifact an app checks in, which ADR 0111 said it could not be.
The declaration is partial (rule 1), so a stateful resource left undeclared would
escape it by silence. The deploy-boundary check therefore does not start from the declaration:
it derives the stateful resources from the resolved plan (every service running a datastore
table digest or declared with a `kind`; every named volume some service mounts; and every
writable bind mount and anonymous volume, on any service) and refuses any that is undeclared or
names no backup, unless an escape a person approved covers it. A named volume
mounted only by declared stateful units counts as declared and backed up by their policy
(decision 2), so the seed's `db` with its `db-data` passes with one policy, and no live database
directory is copied as a second, file-level backup; a named volume any other service mounts must
be in `volumes` with its own policy. A named volume no service mounts holds nothing the
deployment writes and is not a stateful resource, so the external-database shape, which keeps the
base file's `db-data`
after its override removes `db`, passes. A writable bind mount (`./data:/srv/data`) or an
anonymous volume has no entry the declaration can give a backup, because `volumes` names named
volumes only, so it is always refused unless an approved escape covers it; the fix is a named
volume declared in `volumes`. A read-only bind mount is configuration, not state, and passes. Where that check runs stays where
ADR 0111 put it, against the resolved plan at the deploy boundary, in the tool that drives the
deploy. Layer 3 is untouched.

**8. The words live in `terp-spec`, the framework keeps a checked mirror, and a release train
follows.** The schema, `deployment-declaration.schema.json`, lives at the spec root beside
`layout-declaration.schema.json`, which already refuses unknown keys. Hostile fixtures live beside it, so every reader
runs the same ones: an `image` key, control characters, an over-long string, an unknown
`schemaVersion`, `units` without `build`, `unmanaged` together with `build`, a `command` written
as a shell string, and an argv `command` whose elements carry
shell metacharacters, which a reader passes as data and never to a shell. The path escapes, a
`..` that leaves the checkout and a symlink that does, ship as data describing a tree, and each
reader's test builds that tree on disk, because a wheel or an npm tarball carries no symlink.
Profile fixtures for decision 3 sit beside them: a `kind` unit whose profile image is a tag
without a digest, one on a foreign registry, and a profile service `terp release` must refuse.
Plan fixtures for decision 7's deploy-boundary check sit there too: a writable bind mount and an
anonymous volume, each refused; a read-only bind mount, which passes; and the base file with an
override that removes `db`, whose unmounted `db-data` passes.

`terp-spec` is only a development dependency of the framework, so neither the harness nor the
CLI can load the spec at run time. `terp-arch`, where the reader and both rules live,
therefore ships a byte-for-byte copy of the schema, and a framework test holds the copy equal
to the pinned spec release from the release that first carries it. None compares a copy against a spec schema yet, but both halves have
a precedent: `test_assurance_lanes_mirror_the_pinned_spec_vocabulary` holds a CLI mirror to the
pinned spec's schema, and
`test_the_apps_ship_the_same_bootstrap` asserts a byte-identical copy. The reader also gets a
vocabulary parity test against the mirror, like
`test_the_layout_declaration_vocabulary_matches_the_spec_schema`.
A runtime dependency on `terp-spec` was the alternative; the mirror keeps the app's exact
`terp-arch` pin as the one statement of which words its check reads. The reader applies the
mirror rather than restating it, through a validator for exactly the keywords the schema uses,
which refuses a schema that uses any other: a later schema cannot be read as if a constraint it
adds were not there.

Every change to the words then crosses three pins, in this order: a `terp-spec` release; a
framework release that bumps the Python and npm spec pins together and ships the mirror,
reader and check; then `terp-spec` moves its `REFERENCE_SHA` to that framework commit. That
follows the spec's own push order. `REFERENCE_SHA` names `03065436`
today, one commit before v0.29.0 while the framework is at 0.34.0, so
the first trip starts by bringing it current. Each tool that reads the file adopts the new words
after the framework release, with its own parity test; a tool that validates a checkout as data
pins its own validator, and which schema releases it accepts is its own skew policy, refusing by
default. Readers that drive a deploy refuse an
unknown `schemaVersion` and an unknown key; a new role word is information. To keep the train
short, the first schema release carries everything decided here (`stateful`, `backup`,
`volumes`, `sizes`, `build`, `kind`), and the next `workbench.json` words ride the same spec
release when they are ready.

**9. `terp release` cuts an exact-SHA artifact set, and `terp promote` deploys it without
rebuilding.** These are ADR 0134 decision 4's two commands, adopted under its names and its
meaning. No `terp build` and no `terp deploy` are added. `terp eject` is not added either: apps
already commit their build files, so the path that is needed is adoption, and the only "eject"
left is the reverse of a generated adoption, back to `own`. `terp inspect` stays a view.

- `terp release` checks out an exact SHA into a detached worktree, runs the gate in that worktree
  and builds every unit without a `kind` from the same tree, so nothing can write between the
  check and the build. Release builds pull fresh bases and never share a cache or a tag with a
  development build. An image carries no label for 0185: a rollback is classified by the target
  image's own `terp migrate check` (0185 decision 6).
- The release manifest is versioned and records the inputs as well as the outputs: the commit
  SHA and its tree hash; the `terp-cli` version, and the generator's in `generated` mode; the
  digest of every base image; the hash of each lock file; the build arguments; the content of
  `deployment.json` and of each profile file it names, the base file and its overrides in order,
  with a digest of each, so the profile a deploy runs is under the signature and an executor
  needs no checkout and no repository; the per-release tag of 0185 decision 6
  (`TERP_RELEASE_TAG`), under which the release's images are named; the schedule catalog, each schedule's name, cron and catalog job, read from the app's
  `ControlPlane` inside the gate worktree, so a deploy tool that
  never imports the app can trigger every schedule; and, per unit, the image digest. The
  histories a unit owns are in the declaration the manifest carries.
  It records a digest for every profile service the release will run, declared or not, and
  `terp release` refuses a profile service whose image is neither built from the checkout nor a
  datastore table digest. That is a property of a driven release, not a rule of `terp verify`:
  an app that needs another image still deploys it by its own means, or declares `unmanaged`.
- `terp promote` takes a release manifest and deploys exactly those digests, running the profile
  files the manifest carries, never a profile read from a checkout. It never rebuilds.
  Before it pulls or starts anything, it verifies the manifest's signature against the public key
  it is given, and refuses a manifest whose signature is missing or does not verify against that
  key, and an image whose digest is not the one the signed manifest records. It has no
  unsigned mode. The signature covers the manifest, so every digest, the per-release tag and the
  profile and declaration it carries are covered too; which key it is given, and who holds the signing key, stay outside this ADR
  (decision 3).
  Once the `kind` units are healthy, and before it starts any other unit, it brings every
  installed package to head with `terp migrate upgrade`, which has no per-label form and this ADR
  adds none. A
  `kind` unit is healthy when its profile service's `healthcheck` passes, as the template's `db`
  declares one, and
  `terp release` refuses a `kind` unit whose profile service has none, because a unit with no
  health test can never be shown ready.
- The *migration step* is the profile service, declared as a unit or not, whose `command` in argv
  form begins `terp`, `migrate`, `upgrade`, as the template's `migrate` does. `role: "one-shot"` does
  not identify it, because a seed or an import is a one-shot too. `terp release` refuses a profile
  with more than one, and one that passes `--revision` or `--sql`, because that step would not
  bring every package to head. With one, `terp promote` runs that service once, starts nothing
  that depends on it before it has completed, and runs no upgrade of its own. With none, the
  decision 2 sketch, `terp promote` runs `terp migrate upgrade` once in the image of the `api`
  unit, with that unit's environment and the image's working directory, where the default `./app`
  app root resolves; `terp release`
  refuses a profile with no migration step and other than exactly one `api` unit, because there
  is then no one image to run it in. Either way the upgrade runs exactly once per promotion.
- `terp promote` sets the manifest's per-release tag in `TERP_RELEASE_TAG`, which the profile's
  image names read and require (0185 decision 6). The tag names images only: the migration step
  takes no release option, and the record rows the upgrade writes name their run by its own
  code heads (0185 decision 2), so a step run in any of the ways above writes the same rows.
- This departs from R4, whose one new capability was a per-unit one-shot running "exactly the
  histories a unit owns". It
  keeps R4's migrate-then-serve order and drops the narrowing, because `terp migrate upgrade` has
  no per-label form and a declaration is partial: an upgrade narrowed to claimed labels would
  leave every unclaimed history pending, and the boot guard would then refuse the API. A unit's
  `migrations` therefore never narrows the upgrade; it records which histories the unit owns, in
  the declaration the manifest carries, so a label no unit claims is still brought to head and
  the API's boot guard (`PendingMigrationsError`) stays the runtime control.
  Restoring R4's narrowing would take a per-label upgrade, which is a later ADR amending ADR 0027.
- After the upgrade, `terp promote` starts the other units and waits on each declared health
  path. Given an earlier manifest, a rollback, it runs 0185 decision 6's
  classification before it starts anything, and starts the target's images by their tag with
  `--no-build --pull never`. It starts the target only when the classification
  is restore-free, or when the database has been restored so that the target's own `terp migrate
  check` passes on it; otherwise it refuses, says the rollback is restore-based, and names the
  restore 0185 decision 7 describes. The reference executor is the single-host Compose profile; a deploy tool may
  be another executor of the same contract.
- Both refuse an undeclared or `unmanaged` app with one sentence that names the reason, and the
  app still deploys by its own means. That is ADR 0111's degradation test: the tool loses the
  feature and says so, and the app loses nothing.
- A promotion is immutable in its images only. Configuration comes from the environment each time.
  A rollback across a migration is a restore until the schema window of 0185 exists.

## Consequences

- A tool can find an app's units, their health and their migration owners without assuming the
  template's four names, and an app that differs says so in a file its own gate checks.
- The deploy profile is still free. Nothing here asks what a unit is for, and the check reads the
  profile only to compare it with the declaration.
- An app has a third declaration beside `workbench.json` and `environment.schema.json`. The
  ownership list in decision 2 is what keeps three files from saying the same thing three ways.
  A field proposed later has to name its one owner first.
- A deploy tool may refuse to drive an app that has no declaration, or one that sets `unmanaged`.
  That refusal is the tool's, made in the tool's own words; the framework check never blocks on
  it. Both rules hold together only because this ADR says so plainly.
- Every vocabulary change now costs a spec release, a framework release and a `REFERENCE_SHA`
  bump before any tool can use it. That latency is real and is counted in the work, not
  discovered during it.
- Renderers for other platforms (Helm, Terraform, a PaaS manifest) stay deferred, as ADR 0062
  decision 5 and R4 left them. This declaration is what
  makes one possible later.
- `staging` gets no new meaning here. Today it receives neither the production guardrails nor the
  seed refusal. A tool that wants to run a
  seeded copy of the production image as `staging` needs a framework ADR that first says what
  `staging` guarantees, with `requiredIn` kept in step. Seed policy is never a field of this file.

## How it was built

The framework's half of decisions 1 to 6 and 8 was built in 0.35.0, and building it settled
what the decisions had left open about the check's shape.

- **Two rules, catalogued by the Terp Standard.** The check is `terp.arch`'s, as two rules over
  the project root: `deployment_declaration_is_readable` (static-portable: the file against
  the schema, in exactly one state, agreeing with itself and with the datastore table, and
  leading a reader only inside the checkout, the declared units' build contexts and build
  files included) and `deployment_declaration_tells_the_truth` (static-bespoke: rule 1's
  boundary and rule 2 from the files, against the resolved profile). Both are
  `runtime.applicability: not-applicable`. `terp check` runs them, handed the parent of the app
  root it scans; a companion root is never held to them. `terp verify --only deployment` runs
  both and adds rule 2 from the app, which needs the composed app and so lives in the CLI.
  A missing profile file and an unreadable one are the truth rule's to report; a reader stops
  at the first, so the truth rule says nothing about a file that cannot be read.
- **No marker; the escape is the declaration's.** A JSON file cannot carry an
  `# arch-allow-*` marker, so neither rule has one, no budget may name them, and the catalog
  states their way out in a field of its own, `escape`: `{"unmanaged": true, "reason":
  "..."}`.
- **The by-role marks.** The schema lists `healthPath` and `livenessPath` as the fields read
  by role: where a health path is reached is the role's, so under a role the vocabulary does
  not know they have no reader. The app part judges health paths only for the `api` role,
  whose paths the app itself answers; a `web` tier answers its own.
- **The datastore table** is `datastore-table.json` in `terp-arch`, in the format the
  standard's corpus uses for the table a case resolves against: kind, role (`database` or
  `store`) and, per version, one image by digest alone. It carries PostgreSQL 17, the one
  version the template runs; it carries no Redis, because the template runs none. A `kind`
  unit must run exactly the table's image, with no tag beside the digest, because a tag can
  say a version the digest is not. The template's, `apps/example`'s and the reference app's
  production profiles pin it.
- **Every pattern ends at the end of the input.** The schema anchors each pattern with
  `(?![\s\S])` rather than `$`, because Python's `$` also matches before a final newline
  and would let `"api\n"` through a pattern that refuses control characters.
- **Notes, never red.** Beside its findings the app part reports what the app's own
  declarations say it uses and the deploy declaration leaves unstated: a files volume with
  no backup policy, a companion root no unit runs, a datastore kind no unit declares.

## Where this stands

Proposed. The framework's half of decisions 1 to 6 and 8 is built (above). What waits:

1. The terp-spec release that carries `deployment-declaration.schema.json`, its fixtures and
   the two catalog entries. Until it is published and pinned, the two rules are listed in
   `_AWAITING_SPEC_RELEASE`, which a framework release requires to be empty, and the mirror's
   test asserts the pinned spec carries no schema yet. The pin bump moves the Python and npm
   spec pins together, and the spec's `REFERENCE_SHA` then moves to the framework commit
   that implements them, bringing it current from `03065436`.
2. `terp release` and `terp promote` with the release manifest (decision 9), with a fixture
   for each shape of the migration step, the schedule catalog in the manifest, and a manifest
   signed with throwaway keys refused in each way decision 9 names.
3. The deploy-boundary check of decision 7, in the tool that drives the deploy.
4. The generator ADR that amends ADR 0062 and makes `generated` usable, with the adoption step
   and its reverse.

Still open, each for its own record: how an upgrade that moves a digest is shown to whoever
keeps an environment's allowlist; the adoption step's command name; the release manifest's
signature format and how `terp promote` is given its key; and what `staging` guarantees.
Whether a rollback is restore-free is ADR 0185's.
