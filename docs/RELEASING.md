# Releasing Terp

Terp releases **in lockstep** (ADR 0063): one tag `v<version>` publishes every backend
distribution to PyPI, every frontend package to npm, and the production example images
to GHCR, then creates the GitHub Release. The pipeline is
[`.github/workflows/release.yml`](../.github/workflows/release.yml); the gate refuses a
drifted version at build time (`tests/architecture/test_release_versions.py`).

## One-time registry setup

### PyPI — trusted publishing (OIDC, no token)

The unprivileged `build-pypi` job builds **all** backend distributions and transfers
the resulting bytes as a short-lived workflow artifact. Only then does `publish-pypi`
enter the `release` environment, download those pre-built bytes, and upload them through
one trusted-publishing exchange. It never checks out the repository, installs
dependencies, invokes a build backend, or runs shell code while holding the OIDC token.
Every PyPI project must trust the same publisher identity. On
<https://pypi.org/manage/account/publishing/> add a (pending) publisher **per project
below**, each with:

- **Owner:** `AITT-NL` · **Repository:** `terp-framework`
- **Workflow:** `release.yml`
- **Environment:** `release`

Projects (one publisher each — the distribution names, not the repository name):

| Kernel & tooling | Capabilities |
|---|---|
| `terp-core` | `terp-cap-access`, `terp-cap-audit`, `terp-cap-auth`, `terp-cap-egress`, `terp-cap-eventbus`, `terp-cap-files`, `terp-cap-groups`, `terp-cap-identity`, `terp-cap-jobs-celery`, `terp-cap-leases`, `terp-cap-mail`, `terp-cap-mfa`, `terp-cap-oidc`, `terp-cap-outbox`, `terp-cap-realtime`, `terp-cap-redis`, `terp-cap-scheduler-apscheduler`, `terp-cap-scheduler-celery-beat`, `terp-cap-sync`, `terp-cap-tenancy`, `terp-cap-users`, `terp-cap-webhooks` |
| `terp-arch` | |
| `terp-cli` | |
| `terp-migrations` | |

A pending publisher becomes the project on first publish. **All projects must exist
before the first tag**: the lockstep `==` pins mean a partially published release is
uninstallable until every sibling is on the index (`skip-existing: true` makes a
re-run complete the remainder).

`verify` now asks the index that question before anything is uploaded
(`tools/check_pypi_projects.py`, push-only), so a distribution with no project
refuses the release in seconds and names the procedure below. It is a preflight, not
a fix: creating the project is still the manual sequence, and the check is deliberately
absent from the dispatch path because that path is how a project gets created. Before
it existed the answer arrived mid-upload — 0.19.0 published five distributions, then
stopped on `terp-cap-egress`, which was new.

#### Bootstrapping brand-new projects (per-package publish)

PyPI's *pending* publisher is keyed by `(owner, repository, workflow, environment)` and
that tuple must be **unique** — since every Terp project shares the exact same identity,
you can register a pending publisher for only **one** not-yet-existing project at a time.
So the very first publish of each project is done one at a time, through the manual
per-package entry point of the same workflow:

1. On <https://pypi.org/manage/account/publishing/>, register the pending publisher for a
   single project (the four fields above; **PyPI Project Name** = the distribution name,
   e.g. `terp-core`).
2. Run the release workflow manually against that project — either in the Actions UI
   (**release → Run workflow → branch `main` → `package`**) or from the CLI:

   ```bash
   gh workflow run release.yml -f package=packages/backend/core
   ```

   This runs the full gate, then builds **only** that distribution outside the privileged
   job and publishes its transferred artifact through the same trusted-publishing step
   (same `release` environment), so it is attested exactly like a tagged release. It
   creates the project and converts the pending publisher to an **active** one bound to
   the project. The workflow refuses a manual publish from any branch other than the
   repository's default branch.
3. Once the project exists, its active publisher no longer occupies the single pending
   slot — register the next project's pending publisher and repeat.

The dispatch publishes to PyPI only; it never publishes npm, pushes images, or creates a
GitHub Release (those legs stay tag-only). Use the same entry point later to **backfill**
a single distribution whose upload failed mid-release
(`gh workflow run release.yml -f package=packages/backend/capabilities/<name>`).

`terp-spec` / `@terpjs/spec` are **not** published from this repository — AITT-NL/terp-spec
publishes them to PyPI and npm from its own release workflow (ADR 0086). Since ADR 0203 the
rules live here: the backend catalog in `terp-arch`, the frontend catalog in
`@terpjs/eslint-boundaries`, their corpora beside those packages, and the runtime security
cases in `tests/runtime_security/`. **A rule lands in one pull request in this repository**,
with its catalog entry, its corpus cases and its regenerated rule page
(`python tools/generate_rule_docs.py`), and no spec release is involved.

What the framework still takes from terp-spec are the contracts more than one program reads:
the deployment, workbench and layout declarations, the check-report and findings formats, the
assurance profile and the conversation stream. Adopting a new contracts release means moving
**six** declarations together, which is what ADR 0082 asks: the two pins (`pyproject.toml`'s
dev group and `packages/frontend/eslint-boundaries/package.json`), the two constants that
name the check-report format the toolchain writes (`terp.arch.SPEC_VERSION` and the ESLint
adapter's `SPEC_VERSION` in `packages/frontend/eslint-boundaries/src/spec.js`), and the
`SPEC_RELEASE` of the two mirrored declarations (`terp.arch.deployment` and
`terp.arch.workbench`), which moves with the pin even when the release leaves their files as
they were; copy over any file it changed. Then re-lock `package-lock.json` (`uv.lock` is not
tracked) and keep `@terpjs/spec` at the root of it: re-locking can place the new release
under the workspace instead, and the readiness test reads the root entry.
`test_repo_split_readiness.py`, `test_check_json.py` and the two mirror tests fail the build
if any of them skew.

**An assurance lane may be realised here ahead of the release that declares it.** The lane
vocabulary is pinned in two places — the schema's enum and `ASSURANCE_LANES` here — and
`test_assurance_lanes_mirror_the_pinned_spec_vocabulary` holds them equal against the
installed release. A lane realised here first goes in `_AWAITING_SPEC_RELEASE` in
`tests/architecture/test_cli_verify.py`, and comes out when the pin reaches the release that
declares it; `test_no_lane_awaits_a_spec_release_it_already_had` fails on a name left behind.

**Check what the spec release actually ships, not what its changelog says it ships.** A
schema declared in the spec repository but missing from its packaging manifests installs as
an absence, and an absence is what a skip-guarded parity test reads as a pass — terp-spec
0.26.0 shipped exactly that way and needed 0.26.1 to carry the file it announced.

### GitHub — the `release` environment

Create an environment named `release` (Settings → Environments). Both publish jobs run
in it; the PyPI trusted publishers above bind to it. Configure **Deployment branches and
tags** as **Selected branches and tags**, allowing only the default branch (`main`) and
release tags (`v*`). Require reviewers: a tag release and a manual per-package publish
both cross a registry trust boundary and should have an explicit approval gate. Disable
administrator bypass. Prefer an independent organization-member reviewer with
self-review prevention; GitHub does not accept an external collaborator for that role.

### npm — the `@terpjs` scope, via trusted publishing (OIDC, no token)

1. Ensure the npm account owns the `@terpjs` organization/scope.
2. On <https://www.npmjs.com/> add a trusted publisher to each of `@terpjs/contract`,
   `@terpjs/eslint-boundaries`, `@terpjs/react-core` and `@terpjs/conformance`, with the
   same identity the PyPI publishers use: owner `AITT-NL`, repository `terp-framework`,
   workflow `release.yml`, environment `release`.

**No `NPM_TOKEN` secret.** `publish-npm` upgrades npm past 11.5.1 and exchanges the job's
`id-token` for a short-lived registry credential, exactly as `publish-pypi` does — so there
is no long-lived npm credential stored anywhere, and provenance is emitted automatically
rather than asked for. An earlier version of this runbook told the operator to create an
automation token and store it here; a secret nothing reads is worse than no secret, because
it looks like the thing granting the access.

Provenance still requires each `package.json`'s `repository.url` to match this repository —
they point at `git+https://github.com/AITT-NL/terp-framework.git`.

### GHCR — nothing to configure

`publish-images` authenticates with the workflow's `GITHUB_TOKEN` (`packages: write`).
It publishes the **example app's** production images
(`ghcr.io/aitt-nl/terp-example-backend`, `…-frontend`); client projects build their own
images from the published packages. Ensure organization settings allow Actions to
create packages.

## Cutting a release

1. Confirm every manifest carries the release version and `CHANGELOG.md` records it —
   `uv run pytest tests/architecture/test_release_versions.py` proves the lockstep.
   If the release adds a distribution, bootstrap its PyPI project first (above);
   `uv run python tools/check_pypi_projects.py` answers that locally, and `verify`
   refuses the tag if you skip it.
2. Confirm CI is green on `main` at the release commit — and if you check locally first,
   run the command the workflow runs, not an approximation of it:

   ```bash
   uv run coverage run -m pytest && uv run coverage report
   ```

   `pytest` alone is not the gate. Coverage is `fail_under = 100`, so a passing suite and a
   passing gate are different claims: 0.15.0's first tag failed on six uncovered statements
   with every test green. Nothing published (the publish jobs skip when `verify` fails, so
   the version was not burned), but the tag had to be moved and re-pushed.
3. Tag and push (do **not** pre-create a GitHub Release in the UI — the workflow
   creates it after all three publishes succeed):

   ```bash
   git tag v0.1.0
   git push origin v0.1.0
   ```

4. Watch the `release` workflow: `verify` (tag ↔ version + the full gate, both stacks)
   fans out to `build-pypi` and `publish-images`, and `publish-npm` runs **after**
   `publish-pypi` rather than beside it — the serialization is deliberate and the reason is
   below. Then `github-release` publishes the tag's authored notes.
   Both publish jobs enter the `release` environment, and the run parks **twice** — once
   before `publish-pypi` and again before `publish-npm`. Expect to approve two deployments
   for one release. GitHub shares an approval between jobs that enter a protected
   environment *together*, and `publish-npm` needs `publish-pypi`, so it enters later and
   counts as its own deployment. This runbook said "the approval is per run, not per job"
   until 0.15.0 released and it parked the second time; the sentence mattered because the
   warning below is that a version only one registry accepted can neither be completed nor
   withdrawn, and approving once then walking away lands in exactly that state.
5. Verify installability from a clean project: `uv add terp-core terp-cli` and
   `npm install @terpjs/react-core` resolve at the new version. Give npm a few minutes
   first: it accepts a publish and serves the version some minutes later (0.31.0 took about
   four), and until then the version 404s and `latest` still names the previous release. And
   ask it past your own cache, with `npm install --prefer-online`, or `npm view` answers from
   the copy it fetched before the publish, which reads exactly like a publish that failed.

### If a publish job fails partway

Fix the cause (usually a missing trusted publisher or scope permission) and re-run the
failed jobs from the same tag run: the PyPI upload (`skip-existing`), the npm loop
(version-exists check), and the GitHub Release step are all idempotent, so a re-run
publishes only what is still missing.

The two registry legs run in sequence, PyPI first, so a failure there leaves npm
untouched. That ordering is deliberate and load-bearing: both registries are immutable,
so a version only one of them accepted can neither be completed nor withdrawn — the
number is burned for every published artifact while still being pinnable (each
distribution in the table above, and each `@terpjs/*` package). PyPI goes
first because it is the leg that publishes a built artifact and can therefore fail on
one. (`terp-spec` 0.21.0 is the worked example of the alternative.)

## Version bumps

Bump **every** backend `pyproject.toml`, every frontend `package.json`, the template
pins, and `CHANGELOG.md` in one commit — the gate enforces the lockstep. Then tag
`v<new-version>`.
