# 0200 — A release is signed only over a green release profile

- **Status:** Proposed (awaiting review). Built in 0.36.1: `terp release gate` writes a version 2
  document holding every check of the release profile beside the release-assurance claim, both
  from one run, and exits 1 unless both are green; `terp release sign` refuses a red check, a
  document that contradicts itself, and a gate document of another version than the one the
  commit's pinned `terp-cli` writes. Held by `tests/architecture/test_release_gate.py`,
  `test_release_verdict.py` and `test_release_cli.py`, and on an engine by the release lane.
- **Date:** 2026-11-04. 0182 and 0183 are reserved for other records, 0184 to 0198 are taken,
  and 0199 is another record's.
- **Relates:** amends [ADR 0187](0187-in-the-generated-state-the-framework-renders-the-build-files.md)
  decision 6 (what `terp release gate` writes, and what `sign` reads of it); settles
  [ADR 0194](0194-an-apps-api-contract-is-a-committed-file.md)'s open item *Signing over a red
  contract check* and amends its decision 5; applies
  [ADR 0106](0106-the-verify-profile-is-open-at-the-app-end.md) (an app's declared check runs in
  the release profile and composes no assurance lane); keeps
  [ADR 0122](0122-the-catalog-is-frozen-at-its-breadth-and-grows-in-legibility.md) decision 4
  (the claim, its lanes and their requirement levels are the Standard's and stay as they are)
  and [ADR 0110](0110-an-app-declares-which-parts-of-its-dev-topology-are-load-bearing.md)'s
  rule that upgrading the framework never turns an app's gate red for a feature it never wired.
  Supersedes nothing.

---

## Context

`terp release gate` runs `terp verify --profile release` in a checkout of the commit, and ADR
0187 decision 6 gives what it writes to `sign` as the gate's word. It ran it with `--format
assurance`, which writes the release-assurance claim: the run's checks composed into the Terp
Standard's evidence lanes, its `ok` following the required lanes alone. `sign` refused a gate
whose claim did not hold, and read nothing else of the run.

The required lanes compose six checks: `architecture`, `frontend-boundaries`,
`appsec-baseline`, the two dependency audits and `secret-scanning`. The release profile runs
twenty-six, and then the app's own declared checks, which compose no lane at all (ADR 0106
decision 2). So a release could be signed while the backend suite failed, while
`production-readiness` refused the production boot, while `deploy-safety` refused the
profile, while an app's own check was red, or while `api-contract` said the committed
`openapi.json` no longer matched the app, and the signed manifest then carried that contract
under the release's signature (ADR 0194, *Open*). `sign`'s own refusal said it "signs only a
release the gate passed", and ADR 0187 says the gate "runs `terp verify --profile release`":
both read as the whole profile, and the code held six checks of it.

The claim is right as a claim. It is the Standard's statement of evidence, its lanes and their
requirement levels are normative (ADR 0122 decision 4), and a red recommended lane informs its
reader without carrying it. It is the wrong place for a signer to stop, because a signature is
read as "this release passed its gate", and that is the release profile's verdict, not the
claim's.

Two facts bound the fix. The gate is the commit's own pinned `terp-cli`, while `sign` is the
operator's newest (ADR 0187 decision 6), and `sign` signs commits older than itself, whose gate
writes the claim and nothing more. And a check's output is the app's own text, printed by a run
of the app with its environment.

## Decision

### 1. The gate records every check of the release profile beside the claim, from one run

`terp release gate` runs `terp verify --profile release --format json` once, in the checkout
with npm's lifecycle scripts off, and records two verdicts of that one run:

- **the release profile's:** every check it ran, the platform's and the app's own, by id with
  whether it passed, and whether all of them did;
- **the release-assurance claim,** composed from those same results by the function `--format
  assurance` uses (`terp.cli.verify.assurance_document`), so it is that run's claim and never a
  second run's.

The gate document becomes version 2:

```json
{"terpReleaseGate": 2, "commit": "<sha>",
 "profile": {"name": "release", "ok": false, "checks": [
   {"id": "platform-install", "ok": true},
   {"id": "api-contract", "ok": false}]},
 "assurance": {"terp_assurance": 1, "ok": true, "lanes": ["..."]},
 "schedules": ["..."], "image": "<repository>@<digest>"}
```

A check is recorded by its id and its verdict, never by what it printed. That is the app's own
text from a run with the app's environment, which can hold whatever the app had in scope (an
assertion over a configuration value, a scanner's matched line), and the gate document travels
between hosts as an artifact. The gate refuses a run that wrote no such verdict: no `terp
verify` document, another profile, no checks, a check without an id or a boolean verdict, or an
`ok` its checks contradict.

The gate writes its document whatever it says, then exits 1 unless every check passed and the
claim holds, naming each red check; `terp verify --only <check>` in the checkout says why. The
manifest is unchanged: `collected` carries the claim, as it did.

### 2. `sign` signs only over a green release profile and a claim that holds

Reading a version 2 document, `sign` refuses, before it reads the registry, renders a file or
signs:

- a document whose verdict it cannot read: no release profile, no checks, or a check without
  an id or a boolean verdict;
- a document that contradicts itself: a profile recorded green that holds a red check, or one
  recorded red that holds none;
- any red check, each named, with the remedy: `terp verify --only <check>` in a checkout of the
  commit says why, and the release is gated again once it passes, or cut from the commit that
  fixes it;
- a claim that does not hold, as it did.

An app's own declared check counts as a platform check does. `terp verify` already counts it in
its exit code, so `sign` now reads the verdict an app's gate already gave.

`sign` cannot know which checks a commit's release profile has, because that is the commit's
pinned toolchain's and its app's to say, so it holds the document to itself. A gate that left a
check out of its document would be a gate that lied, which is the trust ADR 0187 decision 6
already places in the gate's word, and the reason the gate holds no credential and no key.

### 3. A gate document is read as the commit's own toolchain writes it

The gate is the commit's pinned `terp-cli`, so its document's version follows from the commit.
`sign` reads the `terp-cli` the commit's `uv.lock` pins, as it already does for the manifest's
`toolchain`, and compares it with 0.36.1, the first release whose gate writes version 2
(`terp.cli.release.gate.STRICT_SINCE`):

- **below 0.36.1** it accepts version 1 only, held to its claim alone, as before;
- **from 0.36.1 up** it accepts version 2 only, held to decision 2.

Refusing version 1 for a newer pin is what makes decision 2 a control rather than an option:
otherwise a document an older gate wrote, or one cut down to its claim, would be signed over the
claim alone. Refusing version 2 for an older pin keeps the reading true the other way, because
that document's profile is another toolchain's than the one the commit pins. Both refusals name
the versions and the remedy: run `uv run terp release gate` in the commit's checkout, and sign
what it writes.

The window is deliberate, and it closes with the pin. A commit pinning an older `terp-cli` has
no gate that could record more, and refusing its document would leave the newest signer, which
every release must use, unable to sign it at all. So its release is signed over its claim,
exactly as before, and moving its pin to 0.36.1 or later is what brings it under decision 2.

### 4. Considered and rejected

- **Widening the claim to follow every check.** Which lanes the claim composes and which are
  required is the Standard's, and a toolchain that widened it would restate a normative claim
  from the toolchain side: the reason an app's declared check composes no lane.
- **Making `api-contract` a required lane.** The same widening, made to close a signer's gap,
  and it would still leave every other check outside the lanes signed over.
- **Running the profile twice**, once for each format. Two runs can disagree, a flaky check
  green in one and red in the other, and the document would then carry the claim of a run it
  holds no verdict of.
- **Recording each check's output**, so that the operator need not look elsewhere. The output
  can carry a secret, and the operator has the checkout to run the check in.
- **Carrying the verdict in the manifest.** The manifest is a deploy tool's document, and the
  verdict is a fact `sign` judges rather than one it passes on: the signature is the statement
  that it held. The toolchain the manifest records says which reading signed it (see
  *Consequences*).
- **Refusing version 1 outright.** Every commit pinning a released `terp-cli` would become
  unsignable.

### 5. Amendments

- **ADR 0187 decision 6.** `terp release gate` runs `terp verify --profile release` and records
  every check's verdict beside its assurance document, from one run (decision 1). `sign` reads
  the gate document in the version the commit's pinned `terp-cli` writes (decision 3), and
  refuses a red check, a document that contradicts itself and a claim that does not hold
  (decision 2). `collected` carries the assurance document, as it did.
- **ADR 0194 decision 5** and its open item *Signing over a red contract check*: a commit that
  pins `terp-cli` 0.36.1 or later is signed only when its `api-contract` check passed in the
  gate, so the contract its manifest carries is the one its app served there.

## Consequences

- For a commit pinning `terp-cli` 0.36.1 or later, a release's signature says that every check
  of its release profile passed in the gate, beside the claim: the app's suite, the production
  boot, the deploy-safety audit, the contract, the conformance suite against a running stack,
  and the app's own declared checks.
- A release that `terp verify --profile release` reported red, and that `sign` signed while the
  claim held, is now refused. No check turns red that was green, so ADR 0110's rule holds: what
  changes is that `sign` reads a red the profile already reported. The one an operator is
  likeliest to meet is `conformance`, which drives the development stack; ADR 0187's gate runs
  that stack, and now has to.
- A manifest says which reading signed it. Its `inputs.toolchain` records the signer's version
  and the commit's `terp-cli` pin, and where both are 0.36.1 or later the release was signed
  over the whole profile: that signer reads no version 1 document for that pin.
- A tool that stands in for `terp verify` in the gate, such as a lane that does not run the
  app's suite, stands in for the verdict, every check by id, and the gate composes the claim
  from it.
- The gate document carries no output. The gate prints what each red check said to its own
  log, so why a check is red is read in the job that ran the gate, or from
  `terp verify --only <check>` in a checkout of the commit. The one exception is the secret
  scanner, whose output is the matched line itself: the log names the check and the command,
  and nothing it printed.

## Two-layer enforcement

- **Runtime, fail-closed:** `terp release gate` refuses a `terp verify` run that wrote no
  verdict of each check it ran, and exits 1 on a red profile or a claim that does not hold.
  `terp release sign`, before it reads the registry, renders or signs, refuses a version 2
  document with a red check, one that contradicts itself or holds no readable verdict, a claim
  that does not hold, a version 1 document from a commit pinning `terp-cli` 0.36.1 or later,
  and a version 2 document from an older pin.
- **Tests:** the gate writes version 2 from one run of the profile, its claim composed from the
  very checks it records and no check's output in it (`test_release_gate.py`); `sign` refuses a
  release whose claim holds while its `api-contract`, `backend-tests` or app check is red,
  naming them, signs one whose every check passed, signs a version 1 document from an older pin
  and refuses one from a pin at 0.36.1, refuses version 2 from an older pin, and refuses a
  document that records green over a red check (`test_release_verdict.py`); `terp release
  gate` exits 1 on a red profile whose claim holds (`test_release_cli.py`).

No `terp.arch` rule is added: this is the release jobs' own mechanics, with no authored pattern
to police.
