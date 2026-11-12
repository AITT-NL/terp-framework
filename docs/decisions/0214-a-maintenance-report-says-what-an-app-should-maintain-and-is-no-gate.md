# 0214 — A maintenance report says what an app should maintain, and is no gate

- **Status:** Proposed on 2026-11-12. The owner asked for it on 2026-11-12, as the framework
  half of a design for maintenance signals that depend on no code host, and delegated the
  open questions review raised (item 7's default among them) to its author the same day.
- **Date:** 2026-11-12.
- **Relates:** [ADR 0187](0187-in-the-generated-state-the-framework-renders-the-build-files.md)
  (`sign` scans each image's SBOM against OSV; a framework release moves the base digests),
  [ADR 0200](0200-a-release-is-signed-only-over-a-green-release-profile.md) (the dependency
  audits are part of the release profile), [ADR 0033](0033-generic-enforcement-in-ci.md)
  (the audits are delegated, and need a network), [ADR 0110](0110-an-app-declares-which-parts-of-its-dev-topology-are-load-bearing.md)
  (an upgrade never turns a gate red for something the app never wired),
  [ADR 0059](0059-strict-frontend-boundary-and-escape-hatch-budget.md) (no severity dial) and
  [ADR 0117](0117-the-egress-capability-the-rule-was-already-naming.md) (outbound calls go through `terp-cap-egress`).

## Decision

`terp maintenance` reports what an app should maintain: a newer platform, scaffolding
rendered from an older template, a locked package that matches a published advisory, and a
base image whose tag has moved, where the app pins its own. It changes nothing and is not a
gate. Its caller schedules it. It asks the app's own package index and npm registry, OSV for
advisories, and the image registries; it asks no code host. It asks OSV through the client
`terp release sign` uses, so a report and a signed manifest cannot disagree about where they
asked.

## Context

The checks that answer "what should this app maintain" all exist, and each runs only when
someone acts:

- `terp upgrade --check` answers whether a newer `terp-*` is out, for the Python half only,
  when someone runs it.
- The gate's audit lane (`dependency-audit-python`, `dependency-audit-npm`) runs `pip-audit`
  and `npm audit` when a full or release gate runs, which is when someone pushes.
- `sign` asks OSV about every package of every image, once, and records the answer in the
  signed manifest.

An app nobody touches is never asked again. An advisory published the day after a release
goes unseen until the next push, and nothing ever asks it of the release that is running.
The template's only updater on a clock is Dependabot, which works on one code host only. An
app hosted anywhere else gets none, and a control that depends on where the code is hosted
disappears the day the code moves.

The question is also not a gate's question. A gate decides whether a change may land, and
the same commit must get the same answer tomorrow. An advisory published overnight changes
nothing about the commit, so a gate that turned red on it would refuse work that was green
yesterday for a reason no one in the change introduced (the reasoning of ADR 0110).

## What changes

1. **The command.** `terp maintenance [--format text|json] [--tree DIR | --commit SHA |
   --release DIR] [--osv URL] [--send-private-names]`, on four targets:
   - **the app in the current directory**, the default: every check below. The platform half
     reads the environment the command runs in (the installed `terp-*` set, `uv pip list`), so
     the command runs in the app, `uv run --frozen terp maintenance`; it takes no other root.
     `--frozen` because a plain `uv run` re-locks a stale `uv.lock` before it runs anything,
     which a scheduled check must never do;
   - **`--commit SHA`**: a commit of the repository in the current directory, read the way
     `terp release sign` reads one (every file of the commit through git plumbing, written to
     a scratch directory of its own, never the working tree) and planned the way a release is.
     Known vulnerabilities only. This is how a scheduler audits what an environment runs: the
     commit its release was built from, with nothing staged in the checkout;
   - **`--tree DIR`**: the same for another checkout on disk;
   - **`--release DIR`**: a signed bundle from `terp release sign`. Each image's SBOM is read,
     after its SHA-256 is checked against the one the manifest records, and asked again, of
     the database the manifest says `sign` asked unless `--osv` names another. Each finding
     says whether any of its advisories is new since the release was signed.
2. **The findings.** Five kinds, in this order:
   - `platform-behind`: the newest `terp-*` from `uv pip list --outdated` (the answer
     `terp upgrade --check` gives) and the newest `@terpjs/*` from `npm view`, run in each
     workspace so its `.npmrc` applies. Neither makes Terp an HTTP client of a package index,
     for the reasons `version.py` records: each tool already resolves against the app's own
     configuration.
   - `template-behind`: copier's `_commit` against the platform the app runs, the comparison
     `terp upgrade --check` already prints.
   - `known-vulnerability`: one finding per package, installed version and lock (or image).
     The locks are `uv.lock` and every npm lock the release plan builds a web image from
     (`terp.cli.release._plan.planned_images`), the set `dependency-audit-npm` reads. Each
     finding lists one advisory per flaw: OSV answers one flaw under each database's id (a
     GHSA, a PYSEC), and ids that alias each other or share an alias are one flaw. Each
     advisory carries its summary, aliases and the severity its source gives
     (`database_specific.severity`). The finding carries the lowest version above the
     installed one that fixes every advisory that has a fix. That version is chosen among the
     advisories' own `fixed` events by reading each advisory's ranges for the package as
     OSV's schema evaluates them: events in version order whatever order they are listed in,
     `last_affected`, `limit`, and the listed versions. A fix on one release line is never
     offered while another advisory still covers it. Versions compare in their ecosystem's
     order: PEP 440's for PyPI (as `packaging` keys it, development and post-releases
     included), semver's for npm. The finding also says which advisories have no fix, or
     that no single release clears them all.
   - `base-image-behind`: only under `"build": "own"`. A `FROM` pinned by digest with its tag
     on the comment line above (`# python:3.14-slim`), the convention the template's
     Dockerfiles already follow, in every Dockerfile the release plan builds from. The digest
     is compared with the one the tag names now, read through the client `sign` reads
     registries with. Under `"generated"` a framework release moves the bases (ADR 0187), and
     `platform-behind` already says when that is due.
   - `source-unavailable`: a source that could not be asked.
3. **The document.** `--format json` prints `terp_maintenance: 1`: `checked_at`, `terp_cli`,
   the `target` (`kind`, `path`, `release`, `commit`), `sources` (each with `reachable` and a
   `detail`), `not_checked` and `findings`. Every finding carries every key (`kind`,
   `subject`, `ecosystem`, `location`, `installed`, `latest`, `fixed_in`, `advisories`,
   `new_since_release`, `remedy`). An unknown value is `null` and no advisory is `[]`, so a
   reader never has to tell a missing key from an unknown value.
4. **Silence is never green.** A source that could not be asked is recorded twice: as an
   unreachable source and as a `source-unavailable` finding. When the database does not
   answer, or answers a batch and then not for one of its advisories, no package is reported
   at all, because a partial answer would read as a whole one. A check that could not be made
   for another reason is named in `not_checked`, once, starting with the kind it concerns:
   - a manifest with no lock beside it (`pyproject.toml` without `uv.lock`, a web image's
     `package.json` without `package-lock.json`);
   - packages from an index that is not public, which were not sent (item 7);
   - an environment without `terp-cap-egress`, where the database was not asked at all;
   - scaffolding rendered from a ref that is not a release tag, or no answers file at all;
   - a pinned `FROM` with no tag line, or a release plan that could not be read.

   A report is clean only when both `findings` and `not_checked` are empty.
5. **It is not a gate.** It exits 0 whatever it finds and 2 only when it could not report: no
   app in the current directory, a `--tree` or `--commit` that holds neither a lock nor a
   manifest, a SHA that is not an exact commit of the repository, a lock or a bundle that
   cannot be read or is not in the shape its writer writes. Each refusal names its cause.
   A scheduler alerts on 2 and stores the document on 0.
6. **One route to the vulnerability database.** The OSV client moves out of `sign`'s sandbox
   into `terp.cli.release._osv`, and both callers use it:
   - `/v1/querybatch` in batches of 500, then `/v1/vulns/<id>` once per advisory.
   - Requests go through `terp-cap-egress`, which allows only the database's host, HTTPS
     only (plain HTTP to the loopback alone), with a timeout and a bounded read. The declared
     client itself moves to `terp.cli.release._common`, shared with the index fetch.
   - `--osv` names a mirror, as it already did for `sign`.
   - A package with more advisories than one answer holds is now asked again with its
     continuation token. Before this change `sign` dropped the rest of such a list.
   - An answer in a shape OSV does not write is refused by name, never read as "no
     advisory": `null` or anything else that is not an object, a `vulns` that is not a list,
     an entry without a non-empty string `id`. This closes a fail-open in `sign`: before, it
     read a result of `[]`, `""`, `0` or `{"vulns": {}}` as a clean package and recorded
     `"7"` or `""` as an advisory id, so a signed manifest could say "no vulnerability"
     about an answer nobody could read.
7. **What leaves the machine.** By default, only the name and version of each package a lock
   takes from a public registry: PyPI (`pypi.org`), npm (`registry.npmjs.org`,
   `registry.yarnpkg.com`). A package from any other index, or an npm entry the lock leaves
   unresolved, may carry a name that is the app's own, and it is not sent: the report counts
   those packages and names their hosts in `not_checked`. Two ways send them, each a
   person's choice: `--osv` naming a mirror (it is theirs, and receives every name), or
   `--send-private-names`. A package taken from a path, a git repository or any URL that is
   no registry's tarball is never sent, and neither is the project itself. `--release` sends
   exactly the package URLs `sign` sent, to the database it sent them to, so nothing leaves
   that had not left already.
8. **Severity is data.** Nothing in the framework branches on an advisory's severity; a
   person or a scheduler may sort by it.
9. **The app's side.**
   - The template's development group gains `terp-cap-egress`, the one way the command asks
     the database. Without it nothing is asked, and `not_checked` names the `uv add` line
     that adds it.
   - `terp guide maintenance` says what each finding asks and how to schedule the command.
   - The generated `AGENTS.md` names the command and lists the topic.
10. **`terp upgrade` moves with it.** Its parser and dispatch leave the CLI's entry module
    for `terp.cli.maintenance`; what it does is unchanged. The release plan gains
    `planned_images`, which `web_npm_locks` now reads too, so the report reads the
    Dockerfiles and the locks a release reads.

## What this does not do

- **It applies no fix.** It does not merge, open a change or deploy. Each remedy names the
  command a person or an agent runs, and the gate decides whether that change lands.
  Adopting every new release automatically is how a compromised package reaches
  production.
- **It does not schedule itself.** Cron, any CI on a timer, or the tool that manages the app
  schedules it. A tool that manages several apps stores each document and shows the
  findings.
- **The gate's audit lane does not change.** `pip-audit` and `npm audit` still decide the
  `dependency-audit` lane. Moving that lane onto the same OSV client would mean the gate,
  the report and `sign` could never disagree. It is its own decision, because it changes
  what a gate refuses.
- **The template is still fetched from its repository by `copier update`.** Shipping it
  inside the `terp-cli` wheel was considered and left for its own decision: copier's update
  is a three-way merge that needs the template at the version the app was rendered from as
  well as at the new one, and a wheel carries only one.
- **There is no offline database.** `--osv` points at a mirror that answers OSV's API. OSV
  also publishes each ecosystem's whole database as a zip. The report already evaluates an
  advisory's ranges, but reading a zip as a database (finding a package's advisories in it,
  keeping it current) is not built. That waits for an app that cannot reach any mirror.
- **The document's schema is not in terp-spec yet.** More than one program reads it (a
  person, and the tool that manages the app), which is the test for a contract that belongs
  in terp-spec. Its JSON Schema goes to terp-spec with the next contracts release. Until
  then this ADR and the tests define it, as `terp verify`'s envelope is defined today.

## Alternatives considered

- **A code host's alerts and update bot as the control.** They work only on that host, and
  the control would disappear the day the code moved. The template keeps Dependabot as an
  extra layer for apps hosted there, and nothing here reads it.
- **A lane in `terp verify`.** That would make it a gate, and a newly published advisory
  would turn yesterday's green commit red. The gate already has its audit lane.
- **`pip-audit` and `npm audit` in the report.** That would mean two tools and two databases,
  plus a third at signing. `pip-audit` reads PyPI's advisory feed, which is synced from OSV.
  `npm audit` uploads the whole lock to npm's bulk endpoint on every run and has no mirror
  option. One route was chosen.
- **OSV-Scanner as a pinned binary.** That would be one more tool to ship, pin and update,
  when the framework already had an OSV client behind its egress capability.
- **An HTTP client of PyPI and npm for "latest".** Rejected for the reasons `version.py`
  records: uv and npm already resolve against the app's own index, mirror, credentials and
  proxy.
- **Sending every registry package by name.** Most private indexes mirror the public one,
  so it would give an app behind one a full report without a flag. But a name on a private
  index can be the app's own, or its client's, and secure by default means it stays unless a
  person says otherwise. The report says what it held back and how to send it.

## Consequences

- An app gets one command that a scheduler runs on any host, and a document whose shape is
  fixed by this ADR.
- `sign` and the report ask OSV through one client: `sign` no longer drops an advisory list
  longer than one page, and no longer records an answer it cannot read as a clean package.
- Every generated app installs `terp-cap-egress` in its development group.
- Tests:
  - `tests/architecture/test_cli_maintenance.py` covers the document, what a lock, a manifest
    left unlocked and a bundle yield, the four targets (a commit read from a real repository,
    never its working tree), the exit codes, what may leave, and a real process run.
  - `test_cli_maintenance_advisories.py` covers the version orders (PEP 440's, checked against
    `packaging`, and semver's), range evaluation, the fix offered, the grouping of aliases,
    the partial answer refused, and the egress client missing.
  - `test_cli_maintenance_sources.py` covers the platform halves, with `npm` as a real
    program on `PATH`, the scaffolding comparison, and the base images, read from the
    Dockerfiles a real declared app's release plan builds from.
  - `test_release_osv.py` covers the shared client against a real HTTP server on the
    loopback, through the declared egress client, and every malformed answer it refuses.
