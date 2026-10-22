# 0186 — A declaration vocabulary lives in the spec, and a reader says what it does with a version it does not know

- **Status:** Proposed (awaiting review). Built in 0.35.0: the checked mirror of the Terp
  Standard's `workbench-declaration.schema.json` in `terp.arch.workbench`, the gate's checker
  reading every list from it and applying it, `terp ports` resolving a role the way the
  vocabulary says, the deployment reader's read of the development file held to decision 4,
  and `terp workbench adopt`. Held by `tests/architecture/test_workbench_schema_mirror.py`,
  `test_workbench_declaration.py`, `test_workbench_adopt.py`, `test_cli_ports.py` and
  `test_deployment_declaration.py`. The vocabulary ships in terp-spec 0.40.0, which is not
  published yet.
- **Date:** 2026-10-21. 0182 and 0183 are reserved for other records.
- **Relates:** carries out [ADR 0111](0111-flexibility-is-bounded-by-legibility-not-by-capability.md)
  decision 5 (declaration vocabularies belong in the spec) for `workbench.json`; amends
  [ADR 0110](0110-an-app-declares-which-parts-of-its-dev-topology-are-load-bearing.md)
  decisions 1 and 3 (the `env` block now has its workbench reader; a declared variable name is
  refused when the commands a workbench runs read it for themselves) and decision 6 (a later
  version reaches an app through adoption, never through an upgrade overwriting the file);
  extends [ADR 0184](0184-a-deployment-declares-its-units.md) (the deployment declaration was the
  first vocabulary in the spec; its readers already refuse an unknown version, and decision 4
  here records why); builds on [ADR 0107](0107-the-dev-server-names-who-may-frame-it.md) (the
  framing seam), [ADR 0082](0082-repo-split-readiness-spec-as-a-package.md) and
  [ADR 0086](0086-publish-the-terp-standard-to-pypi-and-npm.md) (the spec as a published
  package). Supersedes nothing.

---

## Context

`workbench.json` is read by two programs: the checker in the app's own gate
(`terp verify --only workbench`, and `terp ports`, which publishes the port variables it names)
and a workbench, which starts, observes and repairs the app's development loop from it. ADR 0111
decision 5 said a contract read by two programs needs one owner, and that its owner is the spec.
`deployment.json` went there first, in ADR 0184. `workbench.json`, the older file, stayed defined
in this repository's CLI, and the workbench kept its own copy of the same words. They drifted in
four places, every one of them silent:

1. **Command slots.** A workbench read and ran `containerLogs` and `recreate` from the `commands`
   block. The checker's `COMMAND_SLOTS` never knew them, and an unknown slot is information here,
   so a `containerLogs` of the wrong type passed the gate and was then run, or not, by the tool.
2. **The `env` block.** The checker held `env.sourceRoot` and `env.frameAncestors` to the compose
   file: the variables through which the checkout's path and the preview's framing grant reach the
   containers. The workbench never read the block; it set the template's two names whatever the
   file said. An app that renamed a seam passed its gate, and then hot reload or the framing grant
   silently did not arrive, which is the class of failure ADR 0110 exists to make visible,
   arriving through ADR 0110's own file.
3. **A role with two entries.** The workbench resolved a role's `hostPortEnv` by the first entry
   that carries one; `terp ports` by the last. An app with two services in one role had its port
   published under a name the workbench never set.
4. **The version.** The checker and `terp ports` refused a declaration they could not read,
   including one from a later `schemaVersion`. The workbench read the same file as if it were
   absent and fell back to the template's conventions, so an app that had renamed a variable and
   then broken its JSON got the old name set and a stack started on a guess.

A fifth fact came out of reconciling the second. A workbench puts every variable name the file
declares into the environment of the commands it runs, and those commands hold its access to the
container engine. A file that names `PATH` as its source-root seam makes the checkout -- a folder an
agent writes -- the place the engine's client is looked up; `DOCKER_CONFIG` makes it the place the
client reads its configuration and plugins from. Where an agent writes the checkout and the
workbench holds the engine, the file's author must not get that say.

And three axes of version skew had never been named together: the version of the framework an app
pins, which is the version of its own gate; the framework release a workbench was built against,
which is the version of every vocabulary it carries; and each declaration's own `schemaVersion`.
Nothing said what an older reader does with a newer file. Without an answer, the first `schemaVersion`
after 1 would be read differently by every reader in the field.

Finally: the template seeds `workbench.json` once and the app owns it (`_skip_if_exists`, ADR 0110
decision 6). That is right, and it means a later version of the vocabulary never reaches an app
that already has the file. Every existing project would keep the version it was rendered with.

## Decision

**1. The vocabulary is the Terp Standard's, and this repository carries a checked mirror.**
terp-spec's `workbench-declaration.schema.json`, with `workbench-declaration.fixtures.json`, fixes
the words. `terp-arch` ships the schema byte for byte in `terp.arch.workbench`, beside the
deployment declaration's mirror and for the same reason: terp-spec is only a development dependency,
and two packages read the file (the CLI's checker, and the deployment reader, which needs the
development compose file), of which terp-arch cannot import the other. A test compares the mirror,
and the fixtures this suite carries beside it, with the pinned spec from the release that first
ships them (`SPEC_RELEASE`, 0.40.0), and until that release is pinned asserts the pinned spec ships
neither, so no skip can outlive the window. `terp.cli.workbench` reads every list from the mirror
(the versions, the command slots, the roles, the fields resolved by role, the reserved variable
names, the deployment-profile markers) and applies the schema itself, through the same small
validator the deployment declaration is read with; a test refuses a list restated in its source.

**It is a vocabulary, not a catalog rule.** Holding the file to the compose file it names is this
stack's check of its own development loop, which another stack need not have in this shape; what
every reader must agree on is how the file itself reads, and the spec's fixtures fix that: valid
documents with what a reader resolves from them, invalid ones with the field the refusal is about,
and texts that are not one JSON document. Both readers run every fixture. The spec lists by name the
vocabularies no rule realises, each of which must ship fixtures, so its rule that normative data
joins only when something realises it still holds. Being a vocabulary also keeps it off the
certification path: no catalog entry changed, so `REFERENCE_SHA` did not have to move.

**2. Version 1 is what both readers read, and what changes is named.** Three states (absent,
declared, `{"unmanaged": true, "reason": "..."}`), open objects (a service the file does not name, a
role nobody has heard of and a key the vocabulary lacks are never refused, as ADR 0110 decision 3
says), and nine command slots: `start`, `stop`, `status`, `containerLogs`, `rebuild`, `recreate`,
`resetData`, `destroy`, `migrate`, any of which means a `start` is declared. What a file both
readers accepted can now be refused for is a value they used to coerce or skip in silence: a field
of the wrong type, a blank command, a control character, a string past its cap, a lower-case
variable name. Every pattern ends in `(?![\s\S])`, as in the deployment declaration. A role's field
resolves to the first entry of that role that carries it, in every reader.

**3. Which side each drift was wrong on.**

- *The slots*: this repository. Both slots are sound -- `containerLogs` only reads, and `recreate`
  is the repair for a saved setting that has not arrived, which a restart is not -- and a workbench
  had run them for a long time. A slot belongs in the vocabulary before a reader runs it, and the
  two arrived in the wrong order; they are in the vocabulary now, and the checker reads its list
  from there.
- *The `env` block*: the workbench. ADR 0110 decision 1 names the seam variables as part of what an
  app declares, decision 3 checks them, and the workbench already read `hostPortEnv` the same way.
  The block was right and its reader was missing; the workbench now sets the declared names.
- *The role with two entries*: `terp ports`, which now takes the first, as the vocabulary says.
- *The version*: the workbench (decision 4).

The declared names are guarded in the vocabulary, not only in a tool: a `hostPortEnv` or seam whose
name starts with a prefix the container toolchain, the dynamic loader or the per-user configuration
convention owns (`BUILDKIT_`, `BUILDX_`, `COMPOSE_`, `DOCKER_`, `DYLD_`, `LD_`, `XDG_`), or that the
process environment reads for itself (`PATH`, `HOME`, the proxy and certificate variables,
`TMPDIR`, `GODEBUG`), is refused by the gate and by every reader. The schema also asks a reader
never to let a declared name replace a variable its own process passes to the commands it runs,
which a workbench enforces against its own environment.

**4. What a reader does with a version it does not know.** One rule, three answers, decided by
what the reader does with the file:

- **Refuse** where the declaration drives something that runs or deploys. The reader says the file
  is from a version it does not read and that the remedy is to update the reader, and it acts on
  nothing in the file. It never falls back to what it would assume for an absent file: **an
  unreadable declaration is not an absent one**, and the defaults are for absence only.
- **Degrade** only where nothing runs on the result: a reader that displays what it can and acts on
  none of it.
- **Ignore** the version only for a field the vocabulary keeps under its name in every version,
  read by a reader whose use of it can only narrow a refusal.

That is safe because of how a vocabulary may change. A later version may add fields; **it never
gives a field a new meaning under the same name**, and **any key that changes what a reader does
arrives with a new `schemaVersion`**. The second half is what makes the open objects of version 1
safe to read: within a known version an unknown key carries nothing by construction, so ignoring it
loses nothing, and a key that would carry something forces an older reader to refuse rather than
ignore it. And versions roll out **readers first, writers last**: the spec release that defines a
version ships first, then a framework release whose mirror and readers read it beside every earlier
version, then the workbench's pin, and only then does the template write it or `terp workbench
adopt` offer it. A reader never drops a version an app may still carry.

Per declaration and reader, today:

| Declaration | Reader | A newer version or an unknown field | Why |
|---|---|---|---|
| `workbench.json` | the app's gate: `terp verify --only workbench`, `terp ports` (the app's pin) | refuse: the toolchain is behind | decides which port variables are published and whether the gate is green |
| `workbench.json` | the deployment reader's lookup of the development compose file | ignore the version, read `compose.file` | a field every version keeps; the read only narrows a refusal |
| `workbench.json` | a workbench (its own framework release) | refuse: no start, observation or repair from the file, and the reason on screen | drives what runs, with the container engine |
| `deployment.json` | the app's gate (`terp.arch.deployment`) | refuse (already: `SUPPORTED_VERSIONS`, ADR 0184) | deploys |
| `deployment.json` | a deploy tool's reader | refuse (already: the schema-version refusal of its strict reader) | deploys |
| `layout-contract.json` | lint and the running shell (the app's pin) | refuse an unknown key; the file has no version and its dialect is closed | the shell composes from it, fail closed at compose time |
| `layout-contract.json` | a workbench's layout editor | reads the vocabulary from the app's own installed framework, says when it fell back to its own copy, and refuses a key outside what it read | it writes a file the app's pin must accept |
| `environment.schema.json` | the app's gate (`terp verify --only env-seams`) | refuse an unknown field; no version, closed dialect | the gate is where the edit happens |
| `environment.schema.json` | a workbench's deploy reader | degrades: drops a field it does not know | recorded, not endorsed (below) |

The last row is the one exception, and it is written down rather than fixed here. A workbench's
environment reader drops a property field it does not know. For the fields that only describe a
variable that loses nothing; for `default` and `services` it is the gap `terp.cli.envschema`
already records against that reader. The rule this decision adds is that a new field which changes
custody or visibility reaches that reader before any app may write it -- readers first -- and the
workbench's parity test pins exactly which fields it drops, so a new one fails there instead of
travelling silently. Moving the environment dialect into the spec, as this decision does for the
development loop, is the remedy, and it is a later record.

The three axes then read as one: the app's pin is the version of its gate's readers, a workbench's
framework release is the version of every vocabulary it carries, and a declaration's
`schemaVersion` says which of them it needs. A workbench behind an app refuses, visibly, and is
updated; an app behind a workbench is read in its own version.

**5. A version reaches an app by adoption, and adoption is the app's own act.**
`terp workbench adopt [--schema N] [--write | --check]` carries an existing declaration forward.
It refuses a version the vocabulary does not define, reads the file the way the gate does and
stops at anything it cannot read, derives from the compose file what the declaration must agree
with -- the variable each declared service's host port actually arrives through -- and refuses a
fact it cannot represent: a declared service the compose file no longer defines, a fixed host
port, two variables for one service, a seam the compose file never reads, and a name the
vocabulary refuses. It shows the diff and writes only with `--write`, keeping the key order and
everything the compose file cannot settle (roles, readiness paths, the commands block, keys the
vocabulary lacks). An absent file stays absent and an opted-out one stays opted out. `--check`
writes nothing and fails exactly when adoption has something to write, for an app's own CI to opt
into; it is not part of `terp verify`, because the day a later version ships every app would turn
red over a file it has not adopted (ADR 0110 decision 7).

**What `--schema 2` writes today: nothing.** No release of the vocabulary defines version 2, so it
is refused by name with the versions this toolchain does define, and nothing is written. The blocks
a version 2 is expected to carry -- which source trees reach which service, which environment files
reach which services, and what a change costs to apply -- are not designed in the vocabulary yet,
and inventing them here would be a second copy of the words, the defect decision 1 ends. The command
exists now so that version 2 ships with its adoption path rather than after it: the release whose
vocabulary defines 2 teaches `adopt` to write it, in the same change that mirrors it. One constraint
is already fixed by decision 4: a version-2 block that means something other than version 1's `env`
seams cannot be called `env`.

## Consequences

- Both readers of `workbench.json` read the same words from one file and run the same fixtures. A
  slot, a role or a seam added to one and not the other now fails a parity test instead of
  travelling silently.
- An app that names a seam variable the commands read for themselves goes red at its gate, with the
  reason. No shipped declaration does; the template, `apps/example` and the reference app all read
  cleanly, and the test that says so runs on each of them.
- A declaration the gate used to accept by coercing a value is refused with the field and what it
  allows. The template has never written such a file.
- A workbench behind an app's framework now refuses the app's declaration instead of guessing its
  topology: the cost of lag is a visible stop and an update, never a misread.
- The deployment declaration and this one share their role words where a word means the same thing,
  and a test holds the development declaration's roles to the deployment declaration's.

## How it was built

`terp.arch.workbench` loads the mirror once, checks it against the validator's keyword subset (a
schema keyword the validator does not apply fails loudly at import), and exposes the lists and
`problems()`. `terp.cli.workbench.read()` applies it after two refusals it words itself (an opted-out
file without a reason, and a version the toolchain does not read, whose remedy is to upgrade), then
the three refusals the schema names and cannot state; the compose-file audit is unchanged and the
deployment-profile refusal moved into the read, where `terp ports` honours it too. The mirror test
reads every fixture through `read()`; `terp workbench adopt` lives in `terp.cli.workbench_adopt` and
writes through the CLI's one output seam.

## Where this stands

- Built in this repository as listed in the status. terp-spec 0.40.0 carries the vocabulary and is
  unreleased; the mirror test switches to comparing bytes when the pin moves there, together with
  the deployment declaration's.
- A workbench's half -- the vendored copy, its parity test, the refusal of an unreadable or later
  declaration, the declared seam names and the guard on them -- is that workbench's own change.
- Version 2 of the vocabulary is not designed. Adoption into it, and the template writing it, wait
  for that design and follow decision 4's order.
- The environment declaration's deploy reader still drops unknown fields (decision 4's exception),
  and its dialect is not in the spec.
