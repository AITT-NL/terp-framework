"""The ``terp guide maintenance`` topic: what an app should maintain, and the report that says so."""

from __future__ import annotations

TOPIC = """\
Maintenance: the report that says what this app should maintain (ADR 0214)

WHAT IT IS

`uv run --frozen terp maintenance`, in the app, reports what this app should maintain, and
changes nothing:

  platform-behind      a newer terp-* (from the index this app installs from, read by uv)
                       or @terpjs/* (from the frontend's registry, read by npm view)
  template-behind      the scaffolding was rendered from an older template than the
                       platform the app runs (copier's _commit)
  known-vulnerability  a package in uv.lock or a web image's package-lock.json matches a
                       published advisory in OSV, with the lowest version that clears
                       every advisory that has a fix
  base-image-behind    under "build": "own" only: a pinned FROM, in any Dockerfile the
                       release builds from, whose tag (the `# image:tag` line above it)
                       names another digest now. Under "generated", a framework release
                       moves the bases (ADR 0187)
  source-unavailable   one of the above could not be asked. Never an empty report: a
                       database that did not answer has not said a package is clean

A check that could not be made for another reason is named in `not_checked`, once: a
manifest with no lock beside it, packages from a private index that were not sent (below),
terp-cap-egress missing, scaffolding rendered from a ref that is not a release tag, a pinned
FROM with no `# image:tag` line above it. A report is clean only when `findings` and
`not_checked` are both empty.

It is a report, not a gate. It exits 0 whatever it finds and 2 only when it could not
report at all (no app here, a --tree or --commit that holds no lock and no manifest, a SHA
that is not an exact commit, a lock or bundle it cannot read), so a newly published
advisory never turns yesterday's green gate red. The gate keeps its own audit lane
(dependency-audit-python, dependency-audit-npm).

    uv run --frozen terp maintenance                    # for a person
    uv run --frozen terp maintenance --format json      # the terp_maintenance document
    uv run --frozen terp maintenance --commit <sha>     # what a release built from <sha> holds
    uv run --frozen terp maintenance --tree <checkout>  # another checkout's locks
    uv run --frozen terp maintenance --release <bundle> # a signed release, re-asked

`--commit` reads the commit the way `terp release sign` does, never the working tree, and
writes nothing into the checkout: it is how a scheduler audits what an environment runs.

RUNNING IT ON A SCHEDULE

Nothing schedules it for you, and nothing in it needs a code host: run it from cron, from
any CI on a timer, or from the tool that manages the app. Unattended, run it through
`uv run --frozen`: plain `uv run` re-locks a uv.lock that has fallen behind pyproject.toml
before it runs anything, which would change the app while nobody watches, and the report
would then describe a lock nobody committed. A weekly line is enough to start with:

    17 6 * * 1  cd /srv/app && uv run --frozen terp maintenance --format json > maintenance.json

Read `findings` for what to do, `not_checked` for what could not be checked, and
`sources` for what was asked. Each finding carries every key (kind, subject, ecosystem,
location, installed, latest, fixed_in, advisories, new_since_release, remedy); an unknown
value is null.

FIXING WHAT IT FINDS

Every finding's `remedy` names the command. Make it a change like any other and run the
gate before it lands:

  platform-behind      `uv run terp upgrade --check` prints the recipe; read
                       `uv run terp guide changelog --since <your version>` first
  template-behind      `copier update`, reviewed as one change
  known-vulnerability  `uv lock --upgrade-package <name>`; for npm,
                       `npm --prefix frontend install <name>@<fixed>` when package.json
                       names it, `npm --prefix frontend update <name>` when another
                       package brings it in (or an `overrides` entry). `fixed_in` is the
                       lowest release that clears every advisory with a fix. A signed
                       release needs a new release, cut from the commit that moves it
  base-image-behind    pin the digest the tag names now, keep the `# image:tag` line

Nothing here merges or deploys a fix by itself, and nothing should: adopting the newest
release of everything automatically is how a compromised package reaches production.

WHAT LEAVES THIS MACHINE

By default, the names and versions of the packages your locks take from a PUBLIC registry
(pypi.org, registry.npmjs.org), sent to OSV (https://api.osv.dev) through terp-cap-egress:
HTTPS only, that host only, a timeout and a bounded read. A package from any other index
may be named after your app or your client, so it is NOT sent: `not_checked` counts those
packages and names their hosts. To check them too, point --osv at a mirror of OSV's API
inside your network (it receives every name), or pass --send-private-names if those names
may leave it. A package taken from a path, a git repository or any URL that is not a
registry tarball is never sent, nor is the project itself. --release re-asks only what
`terp release sign` already sent, of the database it sent it to.

Install terp-cap-egress in the dev group (the template does), or nothing is asked and
`not_checked` names the line that adds it. Version questions go to your own index and
registry, through uv and npm, with their configuration.

A WORD ON SEVERITY

Each advisory carries the severity its source gave it (database_specific.severity), as
data. Nothing in Terp branches on it: a scheduler may sort by it, a person decides.
"""
