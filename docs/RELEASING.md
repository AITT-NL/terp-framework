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
| `terp-core` | `terp-cap-access`, `terp-cap-audit`, `terp-cap-auth`, `terp-cap-eventbus`, `terp-cap-files`, `terp-cap-groups`, `terp-cap-identity`, `terp-cap-jobs-celery`, `terp-cap-oidc`, `terp-cap-outbox`, `terp-cap-realtime`, `terp-cap-redis`, `terp-cap-scheduler-apscheduler`, `terp-cap-scheduler-celery-beat`, `terp-cap-sync`, `terp-cap-tenancy`, `terp-cap-users`, `terp-cap-webhooks` |
| `terp-arch` | |
| `terp-cli` | |
| `terp-migrations` | |

A pending publisher becomes the project on first publish. **All projects must exist
before the first tag**: the lockstep `==` pins mean a partially published release is
uninstallable until every sibling is on the index (`skip-existing: true` makes a
re-run complete the remainder).

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

`terp-spec` / `@terp/spec` are **not** published from this repository — the framework
consumes them as git-tag pins from AITT-NL/terp-spec (ADR 0082); registry publishing of
the spec is deliberately out of scope until third-party checker consumption needs it.

### GitHub — the `release` environment

Create an environment named `release` (Settings → Environments). Both publish jobs run
in it; the PyPI trusted publishers above bind to it. Configure **Deployment branches and
tags** as **Selected branches and tags**, allowing only the default branch (`main`) and
release tags (`v*`). Require reviewers: a tag release and a manual per-package publish
both cross a registry trust boundary and should have an explicit approval gate. Disable
administrator bypass. Prefer an independent organization-member reviewer with
self-review prevention; GitHub does not accept an external collaborator for that role.

### npm — the `@terp` scope

1. Ensure the npm account owns the `@terp` organization/scope.
2. Create a granular automation token with publish rights for `@terpjs/contract`,
   `@terpjs/eslint-boundaries`, `@terpjs/react-core`, `@terpjs/conformance`.
3. Store it as the `NPM_TOKEN` secret on the `release` environment.

`npm publish --provenance` requires each `package.json`'s `repository.url` to match
this repository — they point at `git+https://github.com/AITT-NL/terp-framework.git`.

### GHCR — nothing to configure

`publish-images` authenticates with the workflow's `GITHUB_TOKEN` (`packages: write`).
It publishes the **example app's** production images
(`ghcr.io/aitt-nl/terp-example-backend`, `…-frontend`); client projects build their own
images from the published packages. Ensure organization settings allow Actions to
create packages.

## Cutting a release

1. Confirm every manifest carries the release version and `CHANGELOG.md` records it —
   `uv run pytest tests/architecture/test_release_versions.py` proves the lockstep.
2. Confirm CI is green on `main` at the release commit.
3. Tag and push (do **not** pre-create a GitHub Release in the UI — the workflow
   creates it after all three publishes succeed):

   ```bash
   git tag v0.1.0
   git push origin v0.1.0
   ```

4. Watch the `release` workflow: `verify` (tag ↔ version + the full gate, both stacks)
   fans out to `publish-pypi` + `publish-npm` + `publish-images`, then
   `github-release` attaches the conformance scorecards.
5. Verify installability from a clean project: `uv add terp-core terp-cli` and
   `npm install @terpjs/react-core` resolve at the new version.

### If a publish job fails partway

Fix the cause (usually a missing trusted publisher or scope permission) and re-run the
failed jobs from the same tag run: the PyPI upload (`skip-existing`), the npm loop
(version-exists check), and the GitHub Release step are all idempotent, so a re-run
publishes only what is still missing.

## Version bumps

Bump **every** backend `pyproject.toml`, every frontend `package.json`, the template
pins, and `CHANGELOG.md` in one commit — the gate enforces the lockstep. Then tag
`v<new-version>`.
