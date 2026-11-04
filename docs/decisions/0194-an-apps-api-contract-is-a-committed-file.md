# 0194 — An app's API contract is a committed file, and a change to its shape that breaks a client is named before it ships

- **Status:** Proposed (awaiting review). Built in 0.36.1: `terp verify --only api-contract`
  with its classification of every difference, the `api-client` check generating from a tracked
  contract instead of rewriting it, `terp openapi` naming what changed when it overwrites one,
  the template no longer ignoring `openapi.json`, and `terp release` carrying the contract in
  the signed manifest. Held by `tests/architecture/test_api_contract.py`, with the profiles
  and the published manifest in `test_cli_verify.py` and the template's ignore rules in
  `test_template_build_inputs.py`.
- **Date:** 2026-11-03. 0182 and 0183 are reserved for other records and 0184 to 0193 are taken;
  0194 to 0197 are this series.
- **Relates:** follows [ADR 0139](0139-who-can-reach-what-is-pinned-not-merely-reportable.md)
  (the shape of a pinned baseline: opt-in, drift is red, every line reported in the vocabulary
  of the change, and the writer is never a `--fix`); builds on
  [ADR 0041](0041-frontend-contract-openapi-export-seam.md) (the typed client is generated
  from the backend's OpenAPI) and [ADR 0181](0181-terp-supplies-the-inside-of-a-deployable.md)
  decision 1 (one deployable, one contract); serves
  [ADR 0197](0197-a-public-site-is-a-client-of-an-app-and-the-framework-defines-its-socket.md)
  (a site generates its client from its app's committed contract); extends the release manifest
  of [ADR 0184](0184-a-deployment-declares-its-units.md) decision 9 and
  [ADR 0187](0187-in-the-generated-state-the-framework-renders-the-build-files.md) decision 6;
  keeps [ADR 0110](0110-an-app-declares-which-parts-of-its-dev-topology-are-load-bearing.md)'s
  rule that upgrading the framework never turns an app's gate red for a feature it never wired.
  Supersedes nothing.

---

## Context

An app built on Terp is often reached by more than its own frontend: a native mobile client,
a public site built from another repository, a partner's integration. Each of them is compiled
against the shape of the app's API at one moment and then runs against whatever the app serves
afterwards. A native client is the hard case, because a version already installed on a phone
cannot be recalled.

Nothing records that shape where such a client could pin it. The production profile hides
`/openapi.json`, `/docs` and `/redoc` unless `expose_api_docs` is set, which is right: a public
schema is a map of the attack surface. The template ignores `/openapi.json` as a regenerated
artifact. The framework's own reference app commits its document, and its own test holds that
file equal to the live app, but a generated app gets neither the file nor the test.

So a change that removes an endpoint, renames a response field, narrows a type or adds a
required request field passes every gate an app has. The app's own frontend does not notice
either: its client is regenerated from a fresh export on every gate run, so it is retyped
against the new shape each time. The first program to learn of the break is a client in the
field.

## Decision

### 1. The contract is `openapi.json` at the project root, committed

The file is what `terp openapi` already writes: the live app's document with sorted keys, two
spaces of indentation and LF line endings, so a regenerated contract diffs cleanly. Tracking it
in git is adoption. The template stops ignoring it. A fresh render has no contract until the
first gate run writes one, because the template cannot know an app's surface before the app
exists, and the first commit then carries it, so for a generated app adoption is the default
rather than a step: the check's states are ADR 0139's, and only the starting state differs. An
app that does not want the check lists the file in its own `.gitignore` again, and the check
says it is skipped.

The contract is the API as `terp openapi` composes it, in the environment it runs in, which is
the development one by default. A route an app mounts only in some environments appears as
that composition has it, so a client must not take a route's presence in the file as a promise
that production serves it; exporting the production composition is an open item.

### 2. `terp verify --only api-contract` holds the committed file to the live app

The check is in `quick`, `full` and `release`, ordered before `api-client`. Its three states
are the ones ADR 0139 settled for the authority baseline:

- **Not tracked:** a pass that says so, naming the command that adopts it.
- **Tracked and equal** to the document the composed app exports: a pass.
- **Tracked and different:** red, with every difference on its own line in the vocabulary of
  the change, the breaking lines first, each naming its method and path:

  ```text
  BREAKING GET /api/v1/notes/{item_id}: response 200 field 'title' removed
  BREAKING POST /api/v1/notes/: request body field 'kind' is new and required
  GET /api/v1/tags/: new operation
  ```

"Not tracked" is git's own answer and nothing else: `git ls-files --error-unmatch` exiting 1
and naming the path. Where git cannot answer (it is not installed, the tree is not a work
tree, or it refuses a repository another user owns, as it does for a checkout mounted into a
container), the check is red with git's own words and the remedy, because reading that silence
as "not tracked" would skip the comparison over a committed contract and tell the reader to
commit a file that is committed. And a tracked contract is skipped only where there is no
`app/` package to compose, as `production-readiness` skips only where there is no
`control_plane/`. An app that is there and does not compose is red, naming the error, because
with a tracked contract `api-client` reads the file and no longer imports the app, and this
check is then what reaches it.

The pin is exact. An additive change is red too until the file records it, because the
committed file is the artifact other repositories pin (decision 5), and a contract that lags
what the app serves is a contract that lies. The classification is advice to the reviewer:
the control is the exact pin, so a line the check labels wrongly can mislabel a change but
never let one through. And because an agent decides whether to regenerate from these lines, a
difference the check cannot read is counted as breaking rather than left out (decision 3).

### 3. Breaking means a client built against the committed contract fails against the new one

The list is closed and written from the client's side.

| Where | Breaking | Not breaking |
|---|---|---|
| Operations | an operation removed (a path, or a method on a path) | a new operation |
| Parameters | a parameter removed, new and required, or newly required; its value set narrowed | a new optional parameter; a required one made optional; its value set widened |
| Request body | a body newly required, or removed; a media type removed; a field removed, new and required, or newly required; a field's value set narrowed | a new optional field; a required field made optional; a value set widened |
| Success responses | a success status removed; a media type removed; a field removed or no longer required; a field's value set widened | a new field; an optional field made required; a value set narrowed |

A **value set** is everything a schema admits: its JSON types, with `null` among them for a
nullable field and `integer` inside `number`; its `enum`; its `format`; and on the request side
its bounds (`maxLength`, `minLength`, `maximum`, `minimum`, `pattern`, `maxItems`, `minItems`).
A request is breaking when the new schema refuses something the old one accepted. A response is
breaking when the new schema may produce something the old one never did, which is why a new
`enum` value on a response is breaking: a strict decoder in a native client refuses the whole
response when it meets a value it was not built with.

`$ref`s are resolved within each document, and a recursive schema is compared once per pair of
references. Shapes are compared without their editorial keys (a description, a summary, a
title, a tag, an operation id) and without the order of lists whose order nothing reads, and a
property named like one of those keys is still a property.

A difference the list does not model is never silent and never counted as safe, wherever it
sits and whatever else changed. At every place the check compares (a schema node, a parameter,
a request body, a response, a media type, a path, an operation, the document), what no rule
there reads is compared on its own, every `$ref` in it resolved, and a difference in it is a
line that names the place, says to review it as breaking and counts as breaking, beside
whatever lines that place's rules or its fields produced. That covers a map's value schema, a
default (one written beside a `$ref` too), `additionalProperties`, `allOf`, a union of object
shapes, and whatever is behind a reference inside any of them; a response's headers, a
parameter's style, a media type's encoding; a path's own parameters or servers; an operation
that changed outside its parameters, body and responses (a callback, a deprecation); a
`security` or `securitySchemes` a document declares; and the document's `openapi` and `info`.
A component schema that changed where no compared operation reaches it (a vocabulary a client
is typed against, one only a new or a removed operation uses) is such a line of its own. An
error response that changed, a schema renamed with its shape unchanged (behind a reference the
rules follow or one they do not), and a change to `servers` or another reusable part are named
without the label. Text that changes no shape is one line, and only when nothing else changed.

**Who may call an operation is not in the contract.** Terp's composition declares no
`security`, no `securitySchemes` and no 401 or 403 response, so moving a route from public to
admin, or tightening the permission behind it, leaves `openapi.json` and this check unchanged,
although a client built against the old surface is then refused. The authority baseline pins
that surface (`authz-surface`, ADR 0139); the contract pins the shape of what is sent and
answered. The rules for `security` and `securitySchemes` are for a document that declares
them, which a Terp app's does not.

### 4. The writer is `terp openapi`, never a `--fix`

Regenerating is how a change is accepted, and it happens in the same change so a reviewer sees
the diff, exactly as ADR 0139 has it. When `terp openapi` overwrites a contract that differs, it
prints the classified lines before it says what it wrote, so the person regenerating reads the
breaking ones too. `api-client` no longer exports over a tracked contract: it generates the
typed client from the committed file, because a gate check never writes a tracked file (a
driver that holds checks to being read-only fails otherwise), and because the reviewed contract
is the one the app's own frontend should be typed against. An untracked contract is exported
as before. Where git cannot say whether the contract is tracked, `api-client` exports nothing
and is red, with the same words and remedy as the check.

### 5. The signed release carries the contract

`terp release` records the committed `openapi.json` in the manifest's `inputs` as a carried file
(path, SHA-256 and content) when the app has one, so every release carries the committed
contract under the same signature as its images.

The signature vouches for the file the commit holds, not for the app serving it. What holds the
file to the app is the `api-contract` check, in the gate every change passes before it merges.
`terp release gate` runs it too, in the release profile, but `sign` refuses only a gate whose
release-assurance claim does not hold (ADR 0187 decision 6), and that claim follows the spec's
required lanes, of which `api-contract` is none. So a commit whose contract lags its app can be
signed, and its manifest then carries the contract the commit records, not the API its images
serve.

The manifest is a deploy tool's document,
with base images, scans and profiles beside the contract; a client in another repository is
given the contract file of the release it pins, never the manifest, and a workbench that
publishes releases publishes that one file with them. `terp promote` reads nothing new; it checks the carried file's SHA-256 when
one is present, as it does for every other carried file.

## Consequences

- An app adopts with one commit. After that, a change to its API's shape arrives as a named
  line in a red gate and a diff in the pull request that caused it, which is the only moment
  anyone has the context to judge it. A change to who may call it arrives through the authority
  baseline instead, when the app has adopted that one.
- The production posture is unchanged: the schema endpoints stay hidden, and the contract
  travels as a file, never as an endpoint.
- An app rendered before this release keeps its gate green. `copier update` drops the ignore
  entry; its next gate run writes the file, and the app commits it to adopt or ignores it again
  to opt out.
- A breaking change is accepted by regenerating, as a widening of authority is in ADR 0139.
  Keeping an old shape beside a new one until every client has moved is the app's choice, and
  nothing here versions an API for it.

## Open

- **The production composition.** The file is exported from the development composition; a
  route mounted only in some environments appears as that composition has it. Exporting the
  production composition needs a build of the app under production settings, which today
  refuses to boot without them.
- **A classified diff between two committed contracts.** Once the regenerated file is
  committed, the gate is green and a reviewer sees a JSON diff. Printing the classified lines
  between the contract on the target branch and the one in the change would need the target's
  history in CI, and is a later addition.
- **Publishing the contract beside a release** in the workbench's own interface is the
  workbench's change.
- **Signing over a red contract check.** `sign` reads the gate's release-assurance claim and
  nothing else of its run, and `api-contract` composes no lane of it, so a release can carry a
  contract its app no longer serves. Refusing that needs the gate's document to record the
  check's verdict and `sign` to read it, which is a change to ADR 0187's gate, not a reading of
  it.
