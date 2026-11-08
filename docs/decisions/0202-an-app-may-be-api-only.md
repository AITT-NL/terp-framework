# 0202 — An app may be API-only: the template asks, and every reader accepts the absence

- **Status:** Accepted; built in 0.36.1, the record and the implementation reviewed together.
- **Date:** 2026-11-05.
- **Relates:** [ADR 0110](0110-an-app-declares-which-parts-of-its-dev-topology-are-load-bearing.md)
  (no frontend is never red), [ADR 0184](0184-a-deployment-declares-its-units.md) and
  [ADR 0187](0187-in-the-generated-state-the-framework-renders-the-build-files.md) (the
  declaration and the generator this amends: an `api` unit nothing fronts now publishes a
  port), [ADR 0139](0139-the-release-gate-makes-one-assurance-claim.md) (the assurance
  claim a not-applicable check must not carry), the Terp direction record (an API-only
  choice on the template, Phase 4).

## Decision

The template asks one more question, `frontend`, answered yes by default. Answered no, it
renders an API-only app: no `frontend/` and no `conformance/`, no `web` service in either
Compose file, no `web` role in `workbench.json`, no `web` unit in `deployment.json`, and no
Node steps in the app's own CI. The `api` unit is then the deployment's only way in, so the
generator (and the template, held to its render) publishes it on `${API_PORT:-23200}:8000`
whenever a declaration has an `api` unit and no `web` unit, and `trusted_proxy_hops` stays
at the platform's 0 in production, because nothing in the profile proxies. A `terp verify`
check that runs `npm` in a workspace the app does not have reports *not applicable* and
passes, as `frontend-tests` and `api-client` already do; an assurance lane whose every
check was not applicable is `not-run`, never `passed`, and a lane with one check that ran
green composes from that check alone. The Studio wizard offers the choice. Nothing about
the kernel changes: an API-only app is the same app with no screens of its own.

## Context

Integration services, webhook receivers, workers, and an app whose clients are a native app
or a site built elsewhere (ADR 0197) are the same stack as an app with screens. The
deployment declaration accepts them (ADR 0110 and 0184 say "no frontend" is never red; the
generator has a `no-frontend` golden), but the template always renders a frontend, so every
such app starts by deleting one, and the pieces that assume it stay behind: the `web`
service, a workbench role naming a missing service, five `npm` checks that fail on an
absent `package.json`, and a release claim those checks sink. The `no-frontend` render
also had no way in at all: nothing published a port, because the `web` tier was the only
place one was written.

## Decisions

### 1. One question, taken at `copier copy`

`frontend` is a boolean beside the capability toggles, default yes; `layout` is asked only
when it is yes, because a layout is a frontend's shape. The answer is recorded like every
other and is for a new app: an app that later removes or adds a frontend does it by hand,
for the reason `deploy_build`'s comment gives (an update rendered with a flipped answer
still holds the files the old answer wrote). What the negative answer excludes is the two
Node workspaces whole, through `_exclude`, and what it leaves out of a rendered file is
written with the same `{% if frontend %}` conditional the toggles use.

### 2. An `api` unit nothing fronts publishes a port

The generator writes `ports: ["${API_PORT:-23200}:8000"]` on the `api` unit when the
declaration has no `web` unit, one range step past `WEB_PORT`'s 23100, and the executor's
closed list of interpolations (`fixed_interpolations`) admits exactly that scalar. Several
`api` units with nothing in front of them are refused, with the remedy named: which one
callers reach would otherwise be a guess. A declaration with a `web` unit is unchanged. An existing generated app without a `web` unit
takes the port with its next `terp deployment render`; `terp verify --only generated` is red
until then, which is the mechanism, not a defect. The template's production profile renders
the same lines, so the byte-for-byte hold between the two stands.

### 3. The proxy-hop count follows the profile

`trusted_proxy_hops` is `1` in production only for a profile with the `web` tier, whose
nginx is the one hop; an API-only profile declares nothing in front of the `api` unit, so
the platform's `0` holds everywhere, and the comment tells an operator who adds a proxy to
count it. The template's test of this premise reads the rendered answer, not the raw file.

**An API-only app expects a proxy in front of it in production** (added in 0.39.0; the owner
decided it on 2026-11-08). With a `web` tier, nginx stands between a client and the app and
times out a client that sends its request slowly. An API-only profile publishes uvicorn
itself, which does not, so a client that trickles its headers holds a connection for as long
as it likes. The profile is where production starts, not its edge: production puts a reverse
proxy, a load balancer or an ingress in front of the `api` unit, as it would to terminate TLS,
and counts it in `trusted_proxy_hops`. The template's README and its comment on
`trusted_proxy_hops` say so. Nothing refuses the bare profile, because nothing the framework
reads says what stands in front of a host.

### 4. A check is not applicable where its workspace does not exist

Every `npm` check of the framework's runs through one seam. That seam answers *not
applicable* (exit 0, with the note) when the workspace directory is missing and no manifest
anywhere in the app depends on the package that marks that workspace: `@terpjs/react-core`
for `frontend/`, `@terpjs/conformance` for `conformance/`. So `frontend-boundaries`,
`frontend-typecheck`, `frontend-build`, `dependency-audit-npm`, `conformance`,
`frontend-tests`, `routes-drift` and `api-client` all answer through it. A workspace kept
anywhere else is one these checks would never read, so the check is red and names where it
is: renaming a directory must not switch the security lint off. An app's own declared check
names its workspace itself, so for it a missing workspace is always red, never not applicable.
(The first build decided on the directory alone; a review found both holes, fixed in 0.39.0.)

A check's result records that it was not applicable, and the assurance document composes a
lane from the checks that ran: all not applicable is `not-run` with no checks named (the
schema's word for an unmet precondition, never a pass), some is a verdict on the rest. The
release gate records it too, so the claim it signs is the same (ADR 0200, version 3). The
required lanes are unchanged in shape; for an API-only app `terp-standard` and
`dependency-audit` carry the backend halves, and `blackbox-conformance` is `not-run`.

### 5. Studio offers it where the starting screen is chosen; its deploy path is the deployment record's

The new-app wizard shows "API only" beside the starting screens, not the capability toggles:
it answers the same question a layout answers, what the app starts with, and the render turns
it into the template's `frontend` answer and no layout at all. The proposal, prompt and chat
that describe a new app say it too, and the portal rule leaves it alone, since an app for
outsiders may have its screens elsewhere. The offering appears only where the template Studio
will render is known to ask the question; for a template source Studio cannot read, the
choice is withheld rather than assumed. Studio's deploy and preview code assumes a `web`
service and `WEB_PORT`; routing a hostname to a published `api` unit is a change to the
managed deployment, recorded there, not here, and until it lands Studio says so for such an
app instead of refusing for a reason that is not the cause.

## What does not change

`terp dev` already runs the API alone; `terp new module` already writes no frontend slot
where there is none; the development profile already publishes `api` on `API_PORT`. The
kernel, the control plane and the authority baseline are the same with or without screens.

## Two-layer enforcement

- **Runtime:** not applicable, and recorded as such: nothing here is observed by the
  running app. The shape is decided when the template renders and when the generator
  renders; a generated app is held to the render by the `generated` check, and an `own`
  build's profile is the app's own, as every shape is (ADR 0184 keeps "no frontend" off
  the red list, and this record adds no reader of `ports:`). A check that is not
  applicable says so in its output and in the JSON and assurance records.
- **Build time:** a fourth template-acceptance variant renders `frontend=false` and runs the
  backend gate and the production boot on it; the generator's `no-frontend` golden carries
  the port; the template's premise tests read the rendered answer; the assurance document's
  tests hold a not-applicable lane to `not-run`.

## Consequences

- An integration service or a webhook receiver scaffolds as what it is, with a profile that
  can be reached, and its gate and release claim are about what it has.
- The executor's closed list grows one scalar, which a framework release may do.
