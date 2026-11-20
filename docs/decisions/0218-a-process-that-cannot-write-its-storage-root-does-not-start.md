# 0218 — A process that cannot write its storage root does not start

- **Status:** Proposed on 2026-11-20. Built in 0.43.0. Held by
  `tests/architecture/test_startup_storage.py` (the registry, the probe, the refusal and the
  warning), `apps/example/tests/test_files_api.py` (a late failure answers 502),
  `tests/architecture/test_prod_profile.py` and `test_production_boot.py` (the example's image
  and volume, and the lanes that store a real file), `test_cli_maintenance_sources.py` (the
  maintenance finding) and `test_scheduler_adapters.py` (Celery beat's schedule file).
- **Date:** 2026-11-20.
- **Relates:** the startup comparison of
  [ADR 0212](0212-an-app-compares-the-routes-it-serves-with-its-record-before-it-serves.md),
  which this runs beside and copies in shape (a refusal outside `ENVIRONMENT=local`, a warning
  in it). The files capability of [ADR 0056](0056-files-capability.md) and the storage profiles
  after it. The files volume of
  [ADR 0187](0187-in-the-generated-state-the-framework-renders-the-build-files.md) ("The files
  volume and the production boot"), which fixed the template in 0.35.0 and reached no app
  rendered before it. Amends the maintenance report of
  [ADR 0214](0214-a-maintenance-report-says-what-an-app-should-maintain-and-is-no-gate.md):
  its kinds gain `scaffolding-defect`, a defect in a render's files rather than a version
  behind (item 7). The deployment notes of
  [ADR 0184](0184-a-deployment-declares-its-units.md) stay notes. Supersedes nothing.

## Decision

A capability can register a boot check with `terp.core` when it is imported. `create_app`
runs every registered check after the ADR 0212 comparison. Outside `ENVIRONMENT=local` a
check that returns a sentence is a `BootError` and the process does not serve. In local it is
a warning. The files capability registers one: every storage profile is asked
`boot_problem()`, and the local filesystem adapter creates its root and writes and removes a
probe file there. If that fails, the sentence names the path, the cause, the user the process
runs as, and the remedy.

## Context

An app rendered from the 0.34 template answered HTTP 500 to every upload in production. The
files capability stores under `var/files`, relative to the working directory, which is `/srv`
in the production image. That image ran as a user that cannot write `/srv`, and its production
profile mounted no volume there. The first `mkdir` raised `PermissionError`, and the kernel's
catch-all turned it into `500 internal_error`. The deploy was healthy: health, login and
`/me` never touch the disk.

Template 0.35.0 fixed the template: the image makes `/srv/var/files` owned by the user it runs
as, and with `use_files` the profile mounts a `files-data` volume there. But that fix only
reaches an app through `copier update`, and nothing in the framework noticed the defect where
it remained:

- the deployment check gives a note, never a finding, and runs only when `deployment.json`
  exists. Copier never creates that file on an update, so an app rendered before 0.35 has none;
- conformance runs on the development stack, where the directory is writable;
- template acceptance wrote its probe with `pathlib`, so it never proved that the root the
  capability resolves is the mount; `prod-smoke` never stored a file;
- `terp maintenance` said only that the scaffolding was behind.

The framework's own `apps/example` had the same defect, and `prod-smoke` stayed green on it.

Whether a directory can be written by the user an image runs as, with the mounts a deploy
gives it, is true or false only in the process that serves. A check of the Dockerfile's text
cannot read a shell `RUN` line reliably and does not reach an app that never adopted
`deployment.json`. The process can just try.

## What changes

1. **A boot-check registry in the core.** `terp.core.boot_checks.register_boot_check(name, check)`. A
   check is a function that returns `None` or one sentence. The registry imports nothing above
   `terp.core`: a capability fills it at import, as the realtime capability fills
   `register_mandatory_store`. A second, different check under one name is refused, so two
   capabilities cannot replace each other's. A check that raises is a problem too, never a
   pass.
2. **`create_app` runs them, last.** Directly after the ADR 0212 comparison, so the same
   asymmetry holds: outside `ENVIRONMENT=local` a sentence is a `BootError`, which the
   uncaught-exception hook logs as `uncaught BootError: ...`, the line Terp Studio already reads
   on a deploy and in release verification. In local it is a warning that says the app refuses
   to start on this outside local. Outside local, a process whose checks passed logs `boot
   checks passed: <names>` at INFO, so a checked process reads differently from one where
   nothing was registered.
3. **Every storage backend can say why it cannot be used.** `StorageBackend.boot_problem()`
   returns `None` by default: a store behind a network adapter is not called at boot, so a slow
   or briefly unreachable provider never stops a process from starting. `LocalFilesystemStorage`
   creates its root, then writes and removes a temporary file in it. It does not use
   `os.access`, because permission bits do not tell the whole truth on a network filesystem,
   under ACLs, or on a read-only mount. The sentence names the root, the error, the uid the
   process runs as, and the remedy: make the directory writable by that user and mount a named
   volume there, and for an app rendered before 0.35, re-render (with `--data use_files=true`
   where the recorded answer is false, or the volume does not come) or add what the 0.35
   production profile has: the `RUN useradd` line's `mkdir` and `chown` in `Dockerfile.prod`,
   and the `files-data` volume on `api` in `docker-compose.prod.yml`, declared under its
   top-level `volumes`.
4. **Only an unwritable root refuses.** A root that can be written but lies on the same
   filesystem as `/` is, in a container, not on a mounted volume: its files go with the
   container at the next deploy. That is a warning outside local
   (`StorageBackend.boot_warning()`), never a refusal, because a host can keep its files on that
   disk on purpose.
5. **A late failure is typed.** An `OSError` from `put`, `open` or `delete` in the local
   adapter is a `FileStorageError` (502 `file_storage_failed`), with the operation, root, key and
   error in `log_context=` and never in the response. An unknown key stays a
   `FileNotFoundError` (404). When an upload fails and its cleanup fails too, the upload's own
   error is raised and the cleanup's is logged beside it.
6. **The framework's own lanes store a real file.** `apps/example` makes `/srv/var/files` its
   runtime user's and mounts a `files-data` volume there in its production profile, declared in
   its `deployment.json` with a backup policy. `prod-smoke` stores a file through the API, reads
   it back, reads it again from a new api container, and holds the start to the `boot checks
   passed` line. Template acceptance stores and reads through the capability's own backend,
   and shows that the same image refuses to start as a user that cannot write the volume.
7. **`terp maintenance` names this defect, under a kind of its own.** For an app that installs
   `terp-cap-files` and builds its own image, it reads the text of `Dockerfile.prod` and
   `docker-compose.prod.yml`. Either one in which no line but a comment names `var/files` is a
   `scaffolding-defect` finding with the subject `terp-cap-files`. When a file is missing, a
   release ref older than 0.35.0 decides. A `Dockerfile.prod` fixed by hand is not reported.
   One whose re-render dropped the line is, whatever its ref, so the finding is a defect in
   the render's files, not a version behind: its `location` is the file, its `fixed_in` is
   0.35.0, the template release whose production files first carried the fix, and its
   `installed` and `latest` are `null`. Its text headline reads
   `terp-cap-files in Dockerfile.prod: lacks what template 0.35.0 added`. Its remedy opens with
   what is wrong (a storage root the image's user cannot write, so uploads fail and the start
   is refused outside `ENVIRONMENT=local`; or no volume there) and the fix, then names what it
   read, the lines to add to the image and the profile, the re-render that brings them, and
   the one-time `chown` of a volume an older image created. It reads text, not ownership: any
   line that names the path counts, so a `VOLUME /srv/var/files`, which leaves the mount point
   owned by root, reads as fixed. Whether the root can be written is proven by the process
   itself (items 1 to 3), not by this report.

   It is not a `template-behind` finding. ADR 0214 defines that kind as the scaffolding's ref
   against the platform, and a reader of it shows the `installed` ref, which this finding does
   not have. What changes in the document is one kind: ADR 0214's list gains
   `scaffolding-defect`, after `template-behind`. Every finding keeps the same keys, and the
   format version stays `terp_maintenance: 1`, because the kind joins before that version is
   first released, in 0.43.0 with the report itself. The tool that manages the app shows a
   kind it does not know by its subject and the opening of its remedy, which is why that
   opening says what is wrong and what to do.
8. **Celery beat keeps its schedule file out of the app root.** Celery opens beat's schedule
   file under a relative default name in the working directory, `/srv` in the production image,
   which the runtime user cannot write. The template's production profile runs no beat and the
   framework's own scheduler keeps its state in the database, so no rendered app hits this
   today. An app that opts into `terp-cap-scheduler-celery-beat` and runs the documented
   command would. `CeleryBeatScheduler.install()` moves Celery's default into a directory made
   for that start by `tempfile.mkdtemp()`, under the temporary directory: a name nobody can
   guess, and access for the app's user alone. Beat reads the file with `shelve`, which
   unpickles it, so a fixed name in a temporary directory other users share would let one of
   them plant it first and have beat run it as the app's user. A path the app set itself is
   kept. The file is only beat's cache, and a new start does not find the last one's: the
   schedule ledger settles each tick, and `catch_up()` covers the gap (ADR 0191).

## What it costs

One `mkdir` and one small file written and removed per local storage profile, per process
start. Every process that composes the app probes: the api, a worker and a scheduler. That is
right, because a worker that reads stored files needs the same root.

## What it does not do

- **It does not probe a profile registered after `create_app`.** A composition root registers
  its storage profiles before it composes the app. One registered later is not asked, and the
  default it replaced was.
- **It does not call a network store at boot.** An S3 or Azure profile is asked nothing, so a
  missing bucket or a wrong credential still shows on the first request, as a 502.
- **It does not make the deployment note a finding.** The note still runs only with
  `deployment.json`, and the catalog entry's intent keeps backup a property of the resolved
  plan. Ownership, which the note never saw, is now held by the process.
- **It does not add a catalog rule.** The invariant is a property of the image, the user and
  the mounts, which no source form holds. The build-time half is the template's and the
  generator's own tests of the image text, and the lanes that store a real file.

## Consequences

- An app rendered before template 0.35 that uses the files capability refuses to start outside
  `ENVIRONMENT=local` once it moves to this release, until its image makes the directory
  writable. Terp Studio shows the refusal at release verification, before production. Before,
  the same app started and failed every upload.
- The sentence an operator sees names the fix. `terp maintenance` names it ahead of the
  upgrade.
- Every `create_app` in a process that imports the files capability creates each local
  storage profile's root if it is missing: for the default profile, `./var/files` relative to
  the working directory. In a checkout that is an empty, untracked directory.
- A volume an older image created is root-owned and refuses too. The one-time `chown` from the
  0.35.0 upgrade notes repairs it.
