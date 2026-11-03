# 0194 — An app's API contract is a committed file, and a change that breaks a client is named before it ships

- **Status:** Proposed (awaiting review). Built in 0.35.1: `terp verify --only api-contract`
  with its classification of every difference, the `api-client` check generating from a tracked
  contract instead of rewriting it, `terp openapi` naming what changed when it overwrites one,
  the template no longer ignoring `openapi.json`, and `terp release` carrying the contract in
  the signed manifest. Held by `tests/architecture/test_api_contract.py`, with the profiles
  and the published manifest in `test_cli_verify.py` and the template's ignore rules in
  `test_template_build_inputs.py`.
- **Date:** 2026-11-03. 0182 and 0183 are reserved for other records; 0184 to 0191 are taken,
  0192 is claimed by a proposal under review, and 0193 is the site socket.
- **Relates:** follows [ADR 0139](0139-who-can-reach-what-is-pinned-not-merely-reportable.md)
  (the shape of a pinned baseline: opt-in, drift is red, every line reported in the vocabulary
  of the change, and the writer is never a `--fix`); builds on
  [ADR 0041](0041-frontend-contract-openapi-export-seam.md) (the typed client is generated
  from the backend's OpenAPI) and [ADR 0181](0181-terp-supplies-the-inside-of-a-deployable.md)
  decision 1 (one deployable, one contract); serves
  [ADR 0193](0193-a-public-site-is-a-client-of-an-app-and-the-framework-defines-its-socket.md)
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
exists, and the first commit then carries it. An app that does not want the check lists the
file in its own `.gitignore` again, and the check says it is skipped.

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

The pin is exact. An additive change is red too until the file records it, because the
committed file is the artifact other repositories pin (decision 5), and a contract that lags
what the app serves is a contract that lies. The classification is advice to the reviewer:
the control is the exact pin, so a line the check labels wrongly can mislabel a change but
never let one through.

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
references. Everything else that differs is reported without the breaking label: an error
response, a schema renamed with its shape unchanged, a union with more than one object member,
or text that changes no shape at all (a description, a summary, a tag, an operation id).

### 4. The writer is `terp openapi`, never a `--fix`

Regenerating is how a change is accepted, and it happens in the same change so a reviewer sees
the diff, exactly as ADR 0139 has it. When `terp openapi` overwrites a contract that differs, it
prints the classified lines before it says what it wrote, so the person regenerating reads the
breaking ones too. `api-client` no longer exports over a tracked contract: it generates the
typed client from the committed file, because a gate check never writes a tracked file (a
driver that holds checks to being read-only fails otherwise), and because the reviewed contract
is the one the app's own frontend should be typed against. An untracked contract is exported
as before.

### 5. The signed release carries the contract

`terp release` records the committed `openapi.json` in the manifest's `inputs` as a carried file
(path, SHA-256 and content) when the app has one, so every release names the exact contract it
serves, under the same signature as its images. A client in another repository pins a release
and reads its contract from there, and a workbench that publishes releases publishes the
contract with them. `terp promote` reads nothing new; it checks the carried file's SHA-256 when
one is present, as it does for every other carried file.

## Consequences

- An app adopts with one commit. After that, a change to its API arrives as a named line in a
  red gate and a diff in the pull request that caused it, which is the only moment anyone has
  the context to judge it.
- The production posture is unchanged: the schema endpoints stay hidden, and the contract
  travels as a file, never as an endpoint.
- An app rendered before this release keeps its gate green. `copier update` drops the ignore
  entry; its next gate run writes the file, and the app commits it to adopt or ignores it again
  to opt out.
- A breaking change is accepted by regenerating, as a widening of authority is in ADR 0139.
  Keeping an old shape beside a new one until every client has moved is the app's choice, and
  nothing here versions an API for it.

## Open

- **A classified diff between two committed contracts.** Once the regenerated file is
  committed, the gate is green and a reviewer sees a JSON diff. Printing the classified lines
  between the contract on the target branch and the one in the change would need the target's
  history in CI, and is a later addition.
- **Publishing the contract beside a release** in the workbench's own interface is the
  workbench's change.
