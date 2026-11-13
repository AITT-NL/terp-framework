# 0216 — The release manifest lists every migration history its image runs

- **Status:** Proposed on 2026-11-13. Built in 0.43.0: `terp release sign` writes
  `outputs.migrations`, and `terp.arch.revision_depends_on` reads a revision's `depends_on`.
  Held by `tests/architecture/test_release_migrations.py`, with the signed manifest in
  `test_release_sign.py`, the image's reading in `test_release_image.py` and
  `test_release_sandbox.py`, and the header in `test_revision_header.py`.
- **Date:** 2026-11-13.
- **Relates:** extends the release manifest of
  [ADR 0187](0187-in-the-generated-state-the-framework-renders-the-build-files.md) decision 6
  (its `outputs`, which `sign` checks); reads the per-package histories of
  [ADR 0027](0027-packaged-migrations-per-package-histories.md); builds on
  `destructive_operations` and `revision_header`, in `terp.arch` since 0.35.0. Supersedes
  nothing.

## Decision

`sign` records in the signed manifest every migration history `terp migrate upgrade` would
bring to head in the release's backend image: each revision, with the revisions it follows, and
each destructive step of its `upgrade()`. It reads them as data, never by importing anything,
and refuses a release whose histories it cannot list.

## Context

A deploy tool that has a person confirm a deploy's destructive steps before they run needs to
know which steps a release brings, and it trusts only what the release's signature covers. No
field of the manifest named a revision or an operation, so such a tool had nothing to show and
no deploy that migrates could be confirmed from the manifest alone.

The rule's half existed: `destructive_operations(source)` lists a revision's destructive steps,
and the steps it cannot see into as `opaque`, by the same reading the gate's
`no_destructive_migrations` uses, and `revision_header(source)` gives its id and parents. What
was missing is which revisions a release carries. The tree alone does not say: a capability's
history comes from the wheel the image installs, and the webhooks capability's
`8f1c4a2d9b3e_widen_webhook_secret_for_sealing`, a type change, is in no app's tree.

## What changes

1. **The field.** `outputs.migrations`, beside `outputs.images`, is an object keyed by history
   label, each `{"revisions": [{"id", "down"}], "operations": [{"revision", "ordinal", "kind",
   "operation"}]}`. `down` lists a revision's parents: none for a base, one, or several for a
   merge. `operations` holds every entry `destructive_operations` lists for the revision's
   `upgrade()`, excused by its marker or not and `opaque` ones included: a person confirms each,
   and an unexcused one already fails the gate. Revisions are sorted by id, each `down` sorted,
   and operations by revision then ordinal, all by code point, so one image and one tree give
   one byte string; the manifest goes through `canonical()` as before. A history whose
   `versions/` holds no revision yet is listed with both arrays empty, so a unit may name it.
   The field is additive: `schemaVersion` stays 1, and `terp promote` does not read it.
2. **Which histories.** The trees `terp.core.migrations.resolve_all_migration_trees` finds in
   the image, under the labels it gives them:
   - **a capability's**, for each line `label = import.path` or `label = import.path:attr` of a
     `[terp.migrations]` section in the `entry_points.txt` of a `*.dist-info` or `*.egg-info`
     directory anywhere in the image, as `importlib.metadata` finds them on any path entry. The
     distribution must sit directly in a `site-packages` or `dist-packages` directory, and its
     package at `<that directory>/<import path>/`;
   - **an app module's**, for each directory `modules/<name>/` of the app root whose name does
     not begin with `_`, read from the commit's tree, which the gate read. The root is the one
     the migration step passes, `--app-root /srv/app` (`MIGRATION_STEP`), and the tree's `app/`
     is what the image holds there.

   A history's revision files are the names Alembic loads from `<package>/migrations/versions/`,
   matched by its `_only_source_rev_file`, `(?!\.\#|__init__)(.*\.py)$`, with `sourceless` and
   `recursive_version_locations` off as `terp migrate` leaves them: `_b2_hotfix.py` is listed,
   `__init__x.py` is not.
3. **The image is read in the sandbox, and `sign` judges.** The sandbox's image task hands back,
   beside what it handed back before (unchanged), every path of the whole image that is no
   regular file, including each directory only the paths below it make, and the bytes of every
   `entry_points.txt` and of every file directly in a `migrations/versions/` directory below a
   `site-packages` or `dist-packages` directory. A hard link takes the bytes of the file it
   names; one to a file of a layer below whose bytes were not kept is refused rather than read
   as empty. The image is the one the migration step's service runs or, with no step, the one
   `api` unit's: the image whose upgrade brings every history to head.
4. **Each revision** is decoded as the interpreter decodes a module (PEP 263) and read with
   `revision_header`, `revision_depends_on` and `destructive_operations`, each from the source.
   `revision_depends_on` is new in `terp.arch`: it reads `depends_on` by `revision_header`'s
   rule, the one plain module-level assignment of a literal, and gives `None` where the file
   assigns none.
5. **What `sign` refuses**, each by name with what to change, every one at once:
   - a `[terp.migrations]` section outside such a distribution directory; a package not where
     its distribution put it (an editable install, a `.pth` path, a namespace spread over two
     directories), because `terp migrate upgrade` would bring to head a history no list holds;
   - any other directory in the image at `<any directory>/<import path>/`, because the
     interpreter imports whichever copy comes first on its path, and a copy under a
     `PYTHONPATH` entry would run in place of the one read;
   - a symbolic link where a reading would pass (a distribution, its `entry_points.txt`, a
     package or a directory on the way to it, the app's modules, a module, a `migrations/` or
     `versions/` directory, any entry of `versions/`), and anything else there that is neither a
     file nor a directory: the upgrade would read through it to code no list names;
   - an app module, or a revision file of one, that only the image or only the tree holds, or
     whose bytes differ: the list must be what the image runs, and what the image runs must be
     what the gate read;
   - a revision that is no source text the interpreter can decode, that does not parse, that
     nests deeper than the parser or the reading goes, or whose header cannot be read for
     certain; an id or a parent outside `^[0-9A-Za-z_]{1,64}$`; a parent named twice; a
     `depends_on` other than `None`, because Alembic then writes only the dependent revision to
     the version table, and a reader that follows `down` would count the other pending ever
     after;
   - a revision id given twice in one history, a parent that is no revision of it, a cycle;
   - two histories with one label, which would share `alembic_version_<label>`; a label outside
     `^[a-z0-9_]{1,47}$`, since that table's name holds 63 characters;
   - more than 64 histories, more than 4,096 revisions or operations in one history, or more
     than 16 parents of one revision: what a deploy's plan holds. No ordinal can pass that
     plan's 9,999 within 4,096 operations.

## What it does not do

- **It reads no argument list.** The owner decided on 2026-11-13 that the runner runs the
  migration step with an argument list of its own, `terp migrate upgrade --app-root /srv/app`,
  and no migration command an app wrote. So `sign` does not read a service's `command`,
  `entrypoint`, `working_dir` or the image's `CMD` to find the app root, nor a `PYTHONPATH`,
  nor the step's mounts. A copy of a capability's package that a path entry could reach is
  refused wherever it lies instead.
- **It sees no finder installed as the interpreter starts** (a `.pth` file's `import` line, a
  `sitecustomize`), which can map an import path anywhere, and no migration run by other means
  than `terp migrate`, an app calling Alembic itself or a script an argv only names.
- **It reads a header as `revision_header` reads it**: the plain top-level assignment. A header
  rebound in an `if`, by a walrus or from a function called at import is listed under the id
  that assignment gives. Holding a revision module to a plain shape, and the gate refusing the
  other forms, are not part of this change; neither are the changes to what
  `destructive_operations` reads as opaque that the same request names.
- **`canonical()` is unchanged.** It still refuses a float, and refuses no large integer and no
  deep nesting; nothing in the field is either.
- **There is no `terp migrate graph`** that prints the graph Alembic loads, for a deploy to hold
  the list to at boot.

## Consequences

- A release `sign` signed before can be refused now: a revision that sets `depends_on`, an id
  holding a character other than a letter, a digit or `_`, a module whose name holds an
  upper-case letter, a capability installed editable. The template, the example app, the
  reference app and this repository's capabilities have none of these.
- On this repository's capabilities the field holds three steps in all: the webhooks
  capability's type change, and the audit capability's two trigger statements, which are
  computed and so listed `opaque`. Every release that carries the audit capability lists those
  two for a person to confirm on the deploy that first applies that revision.
- The reading lives in `terp.cli.release._migrations` (where the histories are found) and
  `terp.cli.release._history` (one history's listing).
