# `backend/deployment_generated_files_match_their_render`

**A generated app's build files are exactly what its generator renders**

> Generated from the catalog by `tools/generate_rule_docs.py` — do not
> edit by hand; the parity test holds this page to
> `packages/backend/arch/src/terp/arch/catalog/backend/deployment_generated_files_match_their_render.json`.

## Why this rule exists

Where a deployment declaration says its build files are generated, they are the generator's and not the app's: a person or an agent changes them by changing the declaration, the project's name or the framework release the app pins, and renders again, so a review always sees the declaration that explains the change. Every file the stack's generator owns must therefore be, byte for byte, what that generator renders from the declaration, the project's name and the release's own tables, and a path the generator owns that the declaration renders nothing for must be absent, because a stale build file is a build nobody declared. The check is red, in the generated state only, when the declaration asks for what the generator cannot render faithfully - naming the generator's refusal, and the own state as the way out, because the app chose the one state that promises a render; when a generator-owned file differs from the render, with the difference and the fix; when a generator-owned path the render does not produce exists; when the project's name is one the container tooling refuses as a project or image name; when an environment file a generated unit loads is not kept out of version control and out of the build context; and when the build the app's template recorded for it disagrees with the declaration's. It is silent for an undeclared app, the own state, the opted-out state and a declaration that cannot be read, which is the readable rule's to report, and for the template question when the app records no template answers. A topology the release step will refuse is noted, never red. The check never writes into the tree: rendering is a command of its own whose output is reviewed and committed, because a gate that wrote would hide the change from the review it exists for.

## How Terp realises this

terp verify --only generated runs it in every profile, category build, as routes-drift is run, and terp check runs it too (ADR 0187). It is a check of its own rather than part of terp verify --only deployment, for the reason terp verify --only locks is: a stale render contradicts nothing the declaration says. The generator is terp.arch.deployment.generate, a pure function of the typed declaration, [project].name from pyproject.toml used verbatim, and the framework release's tables in terp-arch (the datastore table, the base-image table, the system-package table and a recipe per datastore kind); it owns Dockerfile.prod when a unit runs the backend image, frontend/Dockerfile.prod when a web unit is declared, and docker-compose.prod.yml always, and terp deployment render writes what it renders. The compose project name is <name>-prod and the image repositories <name>-backend-prod and <name>-frontend-prod. The environment files are .env, .app.env and .app.<id>.env for each backend unit, asked of git check-ignore and of a matcher with Docker's .dockerignore semantics; in a tree that lies in no git work tree, which every corpus case does, the git half notes rather than judges. The template answer is deploy_build in the copier answers file (.copier-answers.yml). The topology terp release refuses is one with no migration step and not exactly one api unit. The only escape is the whole app, terp deployment adopt --build own. A corpus case cannot carry the reference generator's bytes, which move with every framework release's base-image digests, so the compliant cases are the states the rule is silent in and every violation is red whatever the render is.

## If you really need an exception

This rule's subject is a checked-in declaration that cannot carry an
inline marker, so there is no marker to add. The declaration itself
states the exception:

Declare build own: the build files are then the app's own, maintained by hand, and the check is off for them. There is no per-file escape and no marker, because a build file that is half the generator's and half the app's carries neither guarantee. Opting the whole declaration out with unmanaged and a reason turns the check off as well.

## Enforcement

- Checked while the app runs? No — this is a property of the written source only; the build-time check is the control, by recorded decision.
- `build-time`: `terp.arch` — `check_deployment_generated_files_match_their_render`
