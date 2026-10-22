# 0185 — A release declares the schema window it accepts

- **Status:** Proposed (awaiting review). Revised after one adversarial review (see *Review*).
  Nothing is built.
- **Date:** 2026-10-13 (drafted); brought into this repository on 2026-10-21; revised on
  2026-10-22. 0182 and 0183 are reserved for other records.
- **Relates:** [ADR 0027](0027-packaged-migrations-per-package-histories.md) (amended: each
  revision carries a mark, the migration run records it, and the boot guard reads a database
  that is *ahead* of the code as well as one that is behind),
  [ADR 0062](0062-production-deployment-profile.md) (amended: the profile's images take a
  per-release tag, the `migrate` one-shot accepts a database ahead inside the window, and the
  deployment guide gains a rollback section),
  [ADR 0072](0072-database-additivity-review.md) (an offline script writes no record yet, so a
  release applied from one rolls back by restore),
  [ADR 0024](0024-health-endpoints-and-pool-config.md) (unchanged: the health a release
  running behind the window reports),
  [ADR 0070](0070-per-module-schema-layout.md) (the record lives beside the version tables),
  [ADR 0071](0071-runtime-role-privilege-split.md) (extended: the runtime role holds the record
  on the version tables' grants, and its PostgreSQL lane pins the refusal to write it),
  [ADR 0063](0063-lockstep-release-and-publish-pipeline.md) (the one version the record
  carries), [ADR 0084](0084-runtime-applicability-classification.md) (the new rule's runtime
  classification), [ADR 0133](0133-a-reference-declares-what-a-delete-of-its-target-does.md)
  (which referential actions an expand revision may add),
  [ADR 0111](0111-flexibility-is-bounded-by-legibility-not-by-capability.md) (layer 2 names
  "what a rollback is"), [ADR 0134](0134-the-lifecycle-has-one-driver-and-a-workbench-is-not-it.md)
  (`terp release` and `terp promote`, which set the tag and run the classification),
  [ADR 0184](0184-a-deployment-declares-its-units.md) (the deployment declaration, whose
  rollback wording rests on this decision) and
  [ADR 0187](0187-in-the-generated-state-the-framework-renders-the-build-files.md) (the
  generator that renders the tag).

---

## Context

A Terp app in production cannot be rolled back across a migration without restoring its
database, and the reason is a guard doing exactly what it was built to do.

The template arms the boot guard in production only. `assert_migrations_current`
first refuses a database holding a revision the code does not define, and only then checks
whether any package is behind its head. "Does not
define" is a plain lookup: any applied revision missing from the code's history counts as
orphaned. Histories are linear per package, each behind its own version table, so
there is no second branch in which a newer revision could be explained. The `migrate` one-shot
runs the same orphan preflight before it upgrades, and the
production profile starts `api` only after that one-shot succeeds.

So when release N has applied one new revision and release N-1 is started again, N-1's
`migrate` fails on its preflight, and if it were skipped, N-1's `api` would refuse at boot. The
guard cannot tell two different situations apart: *a newer release ran revisions I do not
know*, and *my own history was rewritten after it was applied*. Both arrive as an unknown
revision. Refusing is right for the second, and it is what makes every rollback across a
migration a restore today: the database goes back to the backup taken before the upgrade,
and every write made since is lost.

Nothing else in the tree closes that gap:

- The deployment guide covers upgrade and backup and has no rollback.
- ADR 0111 names "what a rollback is" as part of what a deployment declares,
  and the deploy-unit sketch in PLATFORM_REACH R4 (`docs/internal/PLATFORM_REACH.md` at
  `db40d288`) writes
  `"rollback": { "strategy": "redeploy-previous-image", "migrations": "expand-contract" }`.
  Nothing makes that claim checkable.
- The guides teach expand/contract, but not consistently. Moving a model puts the drop "in a
  LATER release". The
  `not_null_columns_are_backfilled` rule guide says "across two releases" and then "in a LATER
  revision". The
  migrations topic says "back-fill it in the same release, tighten it in a LATER revision", which permits the
  contract step in the same release as the expand step.
- A test cannot stand in for the control. Tests run against a fresh scratch database with the guard
  unarmed outside production, so the previous release's suite can pass while its production
  boot refuses.

## Decision

1. **A revision says whether it is expand-only, and a revision that says nothing is not.**
   Each revision file may declare `expand_only = True` at module level. Absent or `False`, the
   revision is a contract revision, which is the fail-closed reading. Expand-only means the
   previous release's code keeps working on the schema after it. The operations that may
   appear in such a revision are a closed list:

   - `create_table`, with foreign keys only from the new table, together with the new table's
     own primary key, constraints and indexes, unique ones included, and `bulk_insert` into it:
     seeding a table the same revision creates;
   - `add_column` that is nullable, carries a `server_default` or is generated (`Computed`),
     and whose `Column` declares no `unique`, no check and no foreign key but the one below;
   - `create_index` that is not unique.

   A `batch_alter_table` block is judged by the operations it records, and one created with
   `recreate="always"` is off the list.

   A foreign key on the list depends on where it sits (ADR 0133). One from a table the same
   revision creates has `CASCADE` or `SET NULL`: a cascade there deletes only rows the previous
   release never reads. One on an `add_column` to an existing table has `SET NULL`, and its
   column is nullable: a `CASCADE` there would let a delete the previous release makes remove
   rows of a table it reads and never expected to lose, which is silent data loss. Neither ever
   points at a `SoftDeleteMixin` target, where ADR 0133 refuses both actions. `RESTRICT` or
   `NO ACTION` onto an existing table refuses a delete the previous release makes, which is the
   failure a rollback must not meet.

   Everything else is off the list: any drop, any rename, a type change, tightening a column to
   `NOT NULL` or removing its default, and, on a table that already exists, a unique or check
   constraint, a unique index or a primary key change. So is `execute`, whatever it sends, and
   every other data write to a table that already exists (`bulk_insert`, a statement sent
   through `op.get_bind()`): the expand release already handles rows it has not filled
   (decision 4), so a back-fill there is never load-bearing, and it would hold a lock while the
   previous release still serves; it runs as a job. So is a merge revision: two branches that each add an unreleased revision re-parent
   one onto the other instead. A table the same revision creates holds no rows the previous
   release relies on, so what it declares about itself is on the list.

   The list is necessary, not sufficient. A revision whose every operation is on it can still
   add a restriction the previous release cannot enforce, and a rollback brings back the
   previous release's behaviour, so the restriction stops applying while it runs. Two of Terp's
   own revisions have that shape: the files capability's `NOT NULL` scan state with a default,
   which decides whether a stored file may be downloaded, and identity's token-version epoch with
   a default, which revokes tokens. A rollback across either would serve files the newer release
   quarantined and accept tokens it revoked. So `terp migrate make` always writes
   `expand_only = False`, and where every operation it generated is on the list it adds the
   comment `# every operation is on the expand list; set True once the previous release may run
   without what this adds`. The author raises the mark, and the rule below holds a raised mark
   to the list. Restore-free rollback is a choice an author makes, never a default an agent
   inherits.

   | Layer | Control |
   |---|---|
   | Build-time | A new terp-spec rule, `backend/expand_revisions_only_expand`, checked by `terp.arch`: a revision marked `expand_only = True` that contains an operation off the list, reading each `Column` it adds and each batch block's `recreate`, is refused. No opt-out marker: a revision that needs one is a contract revision, and saying so costs only restore-free rollback for its release. A `no_destructive_migrations` marker never excuses an operation in an expand-only revision. |
   | Runtime, fail-closed | Three checks, through the Terp-owned `env.py`, which wraps each revision's `upgrade()` so the checks know where a step starts and ends (Alembic signals only the end). Each operation of an expand-only revision is classified as Alembic dispatches it (`Operations.invoke`), and one off the list raises before it runs; a batch block whose recorded operations are all admitted is admitted, with the statements its flush emits, reflection included. Any other statement the revision sends is refused before it runs online and before it is written offline; `op.get_bind()` bypasses the dispatch in both modes, and in `--sql` mode it returns a mock connection that writes straight into the script (measured on Alembic 1.18.5). Alembic's version-table statements, the record's inserts and the run's own catalogue reads fall outside `upgrade()` and are not judged. Online, at each step's `on_version_apply`, inside the step's transaction after its version update, the run also reads the database's own catalogue and raises when an expand-only step left anything the list does not admit, which is how a batch flush that rebuilt its table is judged; it reads with the guard's catalogue queries, widened to every schema and to triggers, policies and enum types, and the first step does not count the record's own creation. A raise rolls back what the package's upgrade has not committed, its record rows included; a package already upgraded earlier in the same `migrate` stays, as on any failure today. DDL an `autocommit_block` ran is not rolled back, because Alembic commits the transaction before the block unconditionally: it is judged after the fact, and the pre-migrate backup recovers it. Offline, a refusal exits non-zero naming the operation or statement, and the output is not a release script. The checks run in the process of the revision they judge, so they catch mistakes, not a hostile revision; the backup before every `migrate` is the defence against that. The rule's `runtime.applicability` is `required` (ADR 0084). |

2. **The migration run records every revision it applies, and which run applied it, where
   older code can read it.** `terp migrate upgrade` writes one row per applied revision into
   `public.terp_migration_window`, schema-qualified under either layout: the package label, the
   revision, its parent, `expand` or `contract`, `applied_by`, `applied_terp`, `seq` and the
   time. `applied_by` is the SHA-256 of the canonical JSON of the run's own code heads per
   package, the heads `terp migrate heads` lists; `applied_terp` is the run's lockstep Terp
   version (ADR 0063); `seq` rises with every insert. The run takes no option and reads no
   variable for any of them: what identifies a run is its own code, which nobody can forget to
   pass or reuse from a stale environment. The primary key is `(label, revision)`, and a
   revision applied again replaces its row.

   terp-migrations creates the table itself, as Alembic creates the version tables, outside
   every package history. A row is written at `on_version_apply`, in the same transaction as
   the version-table update for that revision. `downgrade` deletes the rows of the revisions it
   reverses. `stamp` writes none, and deletes the package's rows for revisions above the one it
   stamps, so a stamped database never opens a window and a revision applied again after a
   recovery stamp meets no stale row. The table only ever gains columns, and a guard that
   cannot read its shape treats the database as outside the window rather than failing on it.
   Offline `--sql` writes no row in this decision: a release applied from a script leaves
   revisions the record does not hold, the guard refuses to walk them, and the release rolls
   back by restore. That fails closed; inserts in the script are a later change.

   The record is in the database, not in a manifest a deploy tool passes. Older code cannot
   read a newer release's revision files, and the database is the one thing both releases
   share. The guard's answer must not depend on who starts the release: a deploy tool,
   `terp promote` and an operator starting a previous image by hand all meet the same record.
   And it cannot drift from the schema it describes: it changes in the same transaction, and a
   backup carries it with the schema. A dump that drops it makes older code refuse, which is
   the safe failure.

   It adds no trust boundary. `terp migrate grant-runtime` gives it exactly the version tables'
   grants: the runtime role reads it, as the boot guard must, and writes it only where it can
   already write the version tables, which is the flat layout, where ADR 0071 leaves `public`
   writable; under `per-module`, `public` is read-only for it. ADR 0071's PostgreSQL lane,
   which makes a runtime-role `DELETE FROM alembic_version_*` raise `insufficient_privilege`,
   gains the same refusal for an `INSERT`, `UPDATE` and `DELETE` on the record. And
   `assert_migrations_reverse_cleanly` leaves the record out of its residue check, as it leaves
   out the version tables: without that one condition, every app that runs the template's
   reverse-cleanly test would report the record as what a downgrade to base left behind.

3. **The guard admits a database one migration run ahead, through the record.** For each
   package the code defines, `assert_migrations_current` reads the applied revision:

   - equal to the code head: current, as today;
   - an ancestor of the code head: `PendingMigrationsError`, as today;
   - unknown to the code: walk it back through the record, revision to recorded parent, until
     a revision the code knows is reached. The walk must cross only recorded revisions and end
     exactly at the code head; one that meets an unrecorded revision, ends on an older ancestor
     or never ends raises `OrphanedRevisionsError` as today.

   Two rules then judge the record's rows in every package the code does not retire, whether it
   defines the package or not, and a row that fails either raises `OrphanedRevisionsError`:

   - every row the newest run (the newest `applied_by`, by `seq`) wrote for a revision this code
     does not define is `expand` and carries the guard's own Terp version as `applied_terp`;
   - the *horizon* is the newest row written by any run that applied a revision this code
     defines, and every row above it is the newest run's. Rows at or below it were written no
     later than the last run that applied this code's history, which has run beside them since,
     so they are ignored, as today. Where no revision the code defines has a row (its history
     predates the record), every row is above the horizon.

   The newest `applied_by` names the last run that applied anything, so the window is one run
   deep in every package and the guard enforces it itself. Two expanding releases in a row leave
   rows of two runs above the horizon, and the release before both is refused, even where the
   older of them only installed a history the target does not define. A release that applied
   nothing wrote no row and adds no depth. After a deploy that migrated and then failed, the
   failed release's run is the newest applier whether or not it was ever switched to, so its
   predecessor is judged with no input about which release was running. A run on another Terp
   version is never crossed: its capability histories and record format were never tested
   against this guard. A first deploy that applies N-1's history and N's in one run is judged
   the same way, because N's new histories are still that run's rows for revisions N-1 does not
   define.

   **A release that removes a package retires it**, because only the code can tell a package it
   removed from one a newer release installed. The app lists every label it removed, a module or
   an uninstalled capability, as a literal `RETIRED_MIGRATIONS` tuple in
   `<app root>/modules/__init__.py`, read with `ast` and never imported; `pyproject.toml` would be
   simpler to edit, but the runtime image does not carry it, and every image carries the app
   root. Terp keeps the same list for capability histories it retired itself. The guard, the
   `migrate` preflight and the check ignore a retired package's rows; its tables stay the app's,
   as today. They refuse a retired label the code still defines, so the app's own upgrade test
   refuses it before a release is built, and a package that comes back takes a new label. An
   undefined, unretired package whose rows the rules above refuse is named in the refusal: "the
   database holds revisions of `<label>`, which this code does not define: if this release
   removed it, retire it in this release; if a newer release installed it, this rollback is
   restore-based".

   When the guard admits a window it logs one warning at boot naming each package and the
   revisions the code runs behind. There is no switch back to the strict refusal: the guard, the
   `migrate` preflight and `terp migrate check` read the window alike, and a switch honoured by
   one and not the others would let them disagree.

   This narrows the guard by decision; it does not weaken it. A rewritten or deleted history is
   still refused, because a rewritten revision was never recorded as an expand step whose
   parent is the code's head. The framework's PostgreSQL lane gains the proof: the example app
   at N-1, with the guard armed as in production, boots on a database upgraded to an
   expand-only N; refuses one with a contract revision, one whose record is missing, one two
   expanding releases ahead, one where the older of those two only installed a new module whose
   first revision is a contract revision, and one a fresh environment's first deploy of N
   migrated in a single run with such a module; and its `migrate` one-shot exits 0 without
   running DDL.

4. **Rollback is promised one release deep, and a rollback never migrates.** The promise is that
   release N-1 runs on the database release N left, when every revision N applied is
   expand-only. A rollback runs no downgrade and applies no revision. It does not need the
   target's `migrate` one-shot, and where a profile still runs it (the template's `api` waits on
   it) the one-shot shares the guard's check as its preflight, finds nothing to apply for a
   package ahead inside the window, and exits 0 without DDL. Under the per-module layout the
   database's `search_path` becomes the union of its current setting and the code's labels,
   `public` last, written only when a label is missing and never dropping a schema: a rollback
   leaves the newer release's schema on the path and writes nothing, and a restore into a clean
   database, which carries no database-level setting, is repaired by the next `migrate`, pending
   or not. Letting it run keeps the profile's `db → migrate → api` order and gives the guard's
   refusal before `api` starts on a database outside the window. Rolling forward to N finds N's
   heads and applies nothing.

   While the previous release runs, its inserts leave N's new columns at NULL or their default
   and N's new tables without rows, and its updates change rows N wrote without touching what N
   added. A revision applies once, so nothing N ran fills that in again. Until the contract
   release, N therefore keeps writing the old shape the previous release reads, and treats the
   old shape as the truth for anything the previous release writes: a value N derives from old
   columns is computed on read, or is a generated column, which the database keeps current for
   the previous release's writes too but costs a rewrite of the table to add (the lock notes
   below). A value N copied into a new column when it wrote the row would be stale once the
   previous release updates that row, and a job that fills NULLs on the roll forward would skip
   it. N's code handles a new column's NULL until the contract release tightens it, and the
   contract revision back-fills first. The PostgreSQL-lane proof of decision 3 covers the round
   trip: N writing; N-1 reading what N wrote, inserting, and updating a row N wrote; then N
   reading both correctly.

   Every release after a rollback descends from N's migration history. A fix cut from N-1, a
   revert of N's code for example, keeps N's revision files and the model fields and tables
   they create, and reverts behaviour only. Keeping the files alone is not enough: the app's own
   test gate upgrades a scratch database to head and requires autogenerate to find no drift, so a release
   that keeps N's revisions but reverts N's models fails it, and the next `terp migrate make`
   would generate drops of N's columns. Removing them is a later contract release. A release
   that drops N's revision files is admitted only while it adds no revision of its own. The
   first revision it adds hangs off N-1's head, where the walk of decision 3 ends on an older
   ancestor, so the `migrate` preflight refuses before any DDL: the deploy is refused, and the
   fix is to cut the release from N. The deployment guide's rollback section and the
   migrations guide both state the rule, and the guard's message for this case names it: the
   database holds expand revisions this release's history dropped. The PostgreSQL-lane proof
   includes such a revert release, which passes `test_migrations_match_models` and boots on N's
   database.

5. **Contract steps go into a later release's history.** A revision without the mark is a
   contract revision, and the release that ships one is rolled back by restore. So the step
   that drops, renames or tightens goes into a later release than the one that expanded, once
   nothing in the release before it still needs the old shape. The guides change with this:
   the migrations topic's NOT NULL recipe becomes "tighten it in a later release", and the rule
   guide's "in a LATER revision" becomes "in a LATER release", in line with the move-a-model
   recipe that already says so. A release that mixes expand and contract revisions is legal; it
   is classified restore-based (decision 6), which is the cost of mixing them.

6. **A release's images keep their own tag, and a rollback is classified by the target's own
   check.**

   The profile stops overwriting the image a release ran. Today the backend image has one
   untagged name, `{{ project_slug }}-backend-prod`, and the frontend another, so `up --build`
   replaces the image the previous release ran and there is nothing left to start again. Both
   names take a per-release tag from `TERP_RELEASE_TAG`:

   ```yaml
   image: "<project>-backend-prod:${TERP_RELEASE_TAG:?TERP_RELEASE_TAG is required, one new image tag per release}"
   ```

   and the same on `<project>-frontend-prod`. The message is fixed text, so the escape audit
   matches the scalar exactly.

   - **Required.** It is `:?`-required, as `SECRET_KEY` and `POSTGRES_PASSWORD` are (ADR 0062
     decision 3). Unset, every compose command on the profile refuses with that message, `up`,
     `run` (the first administrator's bootstrap), `down`, `logs` and `config` alike, instead of
     falling back to a fixed tag the next `up --build` would overwrite. The deployment guide's
     upgrade step, the CLI guide's deploy and bootstrap commands, and every lane that runs
     compose on the profile set it in the same release.
   - **Its value** is a Docker tag, `[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}`, new for each release.
     `terp release` refuses another, and the manifest records it as `inputs.releaseTag`; for a
     hand deploy the guide suggests `git rev-parse --short=12 HEAD`. `:?` cannot catch a stale
     value. A reused tag moves the old name onto the current release's images, so a hand
     rollback by that tag starts the current release again, whose check passes, and looks like
     a rollback; the rollback section says so. A tool that retags by digest is immune, and the
     classification reads no tag.
   - **Platform-owned.** It names images only; the migration run never reads it (decision 2).
     The environment manifest's reader refuses an app that declares it, as it refuses
     `SECRET_KEY` (`PLATFORM_OWNED_NAMES`), so no value an app ships chooses which image a
     deploy starts. A tool that mirrors that list adds the name after the framework release
     that does, never before, or a manifest declaring it would pass the gate and fail in the
     tool.
   - **Audited.** The escape audit's fixed-interpolation list gains this scalar at the `image`
     of any service, which is where the merge key puts `x-backend`'s, with the project name's
     pattern. Executors carry the extended list before an app pins the release that renders it
     (ADR 0187 decision 9); until they do, they refuse every such release.
   - **A rollback starts what is on the host.** The target starts with its own tag and
     `up -d --wait --no-build --pull never`. The backend unit carries `build:`, so without
     `--no-build` an image pruned from the host would be built again from the current checkout
     under the old tag, and without `--pull never` a bare name would be looked for in a public
     registry. A tool that pulls by digest tags each image `<project>-backend-prod:<tag>` or
     `<project>-frontend-prod:<tag>` before it starts it.

   **Rule zero: a rollback that crosses no migration is restore-free**, whatever Terp version
   either release runs and whether either carries this decision. Its test is the target's own
   check, run from the target's image against the live database: the migration step's own
   command with `upgrade` replaced by `check` (the template's `terp migrate check --app-root
   /srv/app`; with no step, `terp migrate check` in the `api` unit's image and working
   directory), in the step's environment, so it judges exactly the histories the step would.
   It passes with every package at exactly the target's head, which every Terp version's
   strict guard proves, and a target on this decision also holds the record's rows to decision
   3's two rules. A framework update released on its own, applying no revision, therefore rolls
   back for free.

   One case needs a fact the target's check cannot give. A target that predates this decision
   never looks at a history it does not define, so its check also passes where a newer release
   installed one, a new module or capability with foreign keys onto the target's tables. Rolling
   back to such a target, a tool also compares every version table with a reading it took before
   the first migration step that followed the target, and classifies the rollback restore-based
   where it has no such reading or they differ. `terp promote` owns the reading: it reads every
   version table before the migration step and keeps the reading for an undo in the same
   invocation, so the undo of a deploy whose migration step applied nothing starts the previous
   release without a restore. A separate rollback invocation to such a target has no reading and
   is restore-based; the record holding no row does not stand in for one, because a release in
   between that also predates this decision installs a history without writing a row. A target
   on this decision needs no reading where the releases since it carry the decision too: its
   guard then judges such a history through the record (decision 3).

   **Every other rollback is classified by the same check.** It exits 0 only when the database
   is at the target's heads or inside its window (decision 3), so exit 0 is restore-free and
   anything else is restore-based, decided before the rollback is offered. The check is
   read-only: it opens an engine and calls `assert_migrations_current`. Because the guard
   enforces the depth, the guard and the classification cannot disagree, and a tool needs no
   image label, no reader of the record and no knowledge of which release was running. A tool
   may still rule restore-free out without starting the target: a `contract` row by the newest
   applier rules out every target that does not define that revision.

   The PostgreSQL lane of decision 3 gains the cases: two consecutive expand-only releases, N-1
   and N; the check from N-1's image passes on N's database and the check from N-2's image
   refuses it; and a rollback over a release that applied no revision is restore-free, to a
   target on either side of this decision (the older one through `terp promote`'s reading).

7. **Until a rollback target carries the window, a rollback across a migration is
   restore-based, and the guide says so.** The deployment guide gains a rollback section:
   without a restore-free classification, roll back by restoring the backup taken before the
   upgrade and starting the previous images, which loses every write made since that backup.
   With one, start the previous images by their tag on the same database (decision 6) and run
   nothing else. The section also states decision 4's rule that every release after a rollback
   keeps N's revision files and the model fields and tables they create, reverts behaviour
   only, and leaves their removal to a later contract release; the migrations guide states the
   same rule. The upgrade step gains "back up the database before running `migrate`", because
   today it asks for no backup and a restore-based rollback needs one taken before each
   upgrade.

## Consequences

- **ADR 0027 is amended in three places.** Decision 1: histories stay linear and per package;
  each revision now carries a mark, and the migration run keeps one record outside every
  history. Decision 3: the runtime control also judges a database *ahead* of the code, and
  admits it only inside the recorded window, and a release that removes a package retires it. The operational guidance on a `NOT NULL`
  add-column gains "tighten in a later release".
- **ADR 0062 is amended in three places.** Decision 3's `db → migrate → api` order stays, with
  a `migrate` that exits 0 on a database ahead inside the window, and the profile's backend and
  frontend images take the `:?`-required `TERP_RELEASE_TAG`. Decision 4's two-layer guard keeps
  its shape with the window inside it, and its build-time half,
  `tests/architecture/test_prod_profile.py`, asserts the tag on both image names, beside its
  required-secrets test. Decision 5's `docs/DEPLOYMENT.md` gains the rollback section, the tag
  in the upgrade step and a backup before every upgrade's `migrate`.
- **ADR 0071 is extended, not amended.** Its grants are unchanged: the record lives in `public`
  and takes the version tables' grants in either layout. Its PostgreSQL lane adds the refusal of a
  runtime-role write to `terp_migration_window` under `per-module`.
- **ADR 0072 decision 2's offline script writes no record yet**, so a DBA-applied release rolls
  back by restore; it still refuses to render an expand-only revision that sends anything off
  the list.
- **terp-spec gains one catalog entry** (`backend/expand_revisions_only_expand`, with corpus
  cases), and the runtime rationale of `migration_history_is_intact`, which describes the orphan
  check as refusing any revision the code no longer defines, is reworded to the narrowed check.
- **Authors make one more choice per revision.** `make` leaves it at contract and says where
  raising it is allowed. A release with a contract revision costs a restore to roll back, and
  that cost is visible before the release ships, not discovered during an incident.
- **Terp's own capability revisions carry marks too**, under the same rule. A rollback across a
  Terp update that applied a revision stays restore-based until a later decision proves
  capability histories across Terp releases; one that applied none is free by rule zero. So an
  app that wants a restore-free rollback of an expand release does not take a Terp update in
  the same release.
- **Data written under the newer release stays** in its new columns and tables while the older
  release runs, unread by it; what the older release must see, the newer release also wrote in
  the old shape (decision 4). Restore-free rollback undoes code, never data.
- **Texts that change with it:** `assert_migrations_reverse_cleanly`'s residue filter and its
  docstring, which still calls `terp migrate downgrade` every Terp app's rollback plan; the
  migrations topic's NOT NULL recipe; and the migrations guide's notes, that an unreleased
  revision is re-parented rather than merged, that a release removing a package retires it,
  that a `create_index` without `CONCURRENTLY`, a
  volatile default and a generated column (PostgreSQL 17 stores it, so adding one rewrites the
  table) hold a lock while the previous release still serves, because migrate runs before `api`
  is recreated, so a large table computes a derived value on read, and that a new child table of a soft-deleted parent is a contract
  revision, because neither referential action is allowed onto it.
- **Health is untouched.** A release running behind the window reports liveness and readiness
  by ADR 0024's rules, and the window adds no readiness signal. Worker and shared-store
  signals are a separate amendment to ADR 0024, not part of this decision.
- **An app that does not adopt the version that carries this** keeps its guard and its `migrate`
  exactly as today, and its rollback across a migration stays a restore; a rollback that crosses
  none is restore-free by rule zero, with the version-table reading decision 6 asks of a tool.

## Where this stands

Proposed, not built. The first Terp release that carries it is the earliest version a
restore-free rollback across a migration can target; until an app has two consecutive releases
on such a version, its rollback across a migration is restore-based (decision 7), while rule
zero holds from the start. It needs acceptance before any rollback test, or any deployment
declaration's rollback field, relies on the window. ADR 0184's `rollback.strategy`, built in
0.35.0, says what a rollback is and claims nothing about whether one is restore-free, so it
does not wait on this decision.

What proves it, and the decisions each proof needs:

| Proof | Decisions |
|---|---|
| N-1, guard armed as in production, boots on a database N upgraded with expand-only revisions, batch-style ones included, and its migration step exits 0 with no DDL | 1, 2, 3, 4 |
| The rule refuses an off-list operation in an expand-only revision; the online run raises on one; `--sql` refuses to render one | 1 |
| N-1 refuses a contract row, a missing record and a database two runs ahead, also where the older run only installed a contract history N-1 does not define; the round trip, an update included; a revert release passes `test_migrations_match_models` and boots on N's database; N to N-1 restore-free and N to N-2 restore-based, by the target's own check; a runtime-role write to the record refused under `per-module` | 2, 3, 4, 6 |
| A fresh environment's first deploy of N, one run applying N-1's history, N's expand revisions and a module whose first revision is contract, is refused by N-1 | 3, 6 |
| A release that deletes a module whose rows are the newest run's contract rows boots when it retires the module and is refused, naming the retirement, when it does not; a retired label still defined is refused | 3 |
| A per-module database restored into a clean database is routed again by the next `migrate` | 4 |
| A contract step ships in a later release than its expand | 5 |
| Rows carry the applier's heads digest and Terp version, however the migration step is run, with no option | 2 |
| A rollback over a release that applied no revision is restore-free, to a target on either side of this decision | 6 (rule zero) |
| A profile without `TERP_RELEASE_TAG` refuses; with one per release, the previous release's images stay on the host and a rollback starts them without a build | 6 |

Open for implementation, not for this decision: whether `terp migrate make` or `terp.arch` can
also refuse a new revision whose parent is behind a recorded expand step before it ships;
offline record inserts; and the final spelling of the table and the mark.

## Review

Two rounds of adversarial review changed this record.

**Round one.**

- **Rule zero (the blocker).** The draft classified a rollback restore-based whenever the target
  carried no labels, predated this decision or ran another Terp version, even when no migration
  lay between, so the commonest rollback, code only, became a restore that loses every write
  since the deploy began. A rollback whose target's own check passes at exactly its heads is now
  restore-free, whatever the versions (decision 6). Revising it found one blind spot the review
  did not name: a target that predates this decision cannot see a history a newer release
  installed, so a tool rolling back to one also compares the version tables.
- **Depth from the run, not a tag.** Rows carried a release tag passed as an option, which a
  stale variable could reuse, an older migration command could leave out, and an undo after a
  failed deploy had to guess. Rows now carry the run's own heads digest, its Terp version and a
  sequence, and the guard admits only the newest run's rows, so it enforces one deep itself and
  there is no input to get wrong (decisions 2 and 3). The record gained a primary key, `stamp`
  clears what it moves past, and the table only gains columns.
- **`make` writes `False`.** Two of Terp's own revisions are on the expand list and still carry
  a restriction a rollback would drop; a default of `True` would hand that to every generated
  revision (decision 1).
- **The runtime check judges what ran.** A raw connection bypasses Alembic's dispatch, so the
  run also refuses statements outside an admitted operation and reads the catalogue each step
  left, and what an abort rolls back now excludes an `autocommit_block` (decision 1). The review
  held the dispatch complete offline because `get_bind()` returns `None` in `--sql` mode; on
  Alembic 1.18.5 it returns a mock connection that writes into the script, so the statement
  check covers offline too.
- **No data writes in an expand revision** except seeding a table it creates (decision 1): the
  classifier the draft leaned on is a denylist with no "cannot classify" outcome. This closes
  the draft's open item on `execute`.
- **Rows the older release updates.** The roll-forward rule covered inserts only; N now treats
  the old shape as the truth for what the older release writes, and the lane updates a row
  (decision 4).
- **Smaller:** the reverse-cleanly residue filter; a `migrate` with nothing pending skips the
  search-path DDL; the revert-release refusal arrives as a refused deploy; the merge and
  `Column` rules; the guide notes on locks and soft-deleted parents; the guard docstring that
  still names downgrade as the rollback plan.
- **Cut, because no proof needs them:** the `terp.version` and `terp.migrations.heads` image
  labels, a machine-readable `terp migrate heads` and ADR 0187's two-pass `heads` stage; the
  release option and its plumbing through the profile, `terp promote` and the generator;
  promote's reader of the record; the label-only rule-out; a guard that admitted what the
  classification refused. Offline record inserts are deferred, so a script-applied release
  rolls back by restore.
- **Kept against the review:** the runtime role's write to the record under the flat layout.
  Revoking it there adds no control, because that role can already write the version tables,
  which alone decide whether the check passes; adopting `per-module` is the control, as ADR 0071
  says. And the tag is reserved in the environment manifest's platform-owned names rather than
  the workbench vocabulary the review named: `.app.env` is the environment manifest's, and the
  workbench list governs only the variables a development tool sets.

**Round two** accepted the four places where this record departed from round one, and found
three more of weight:

- **One horizon for every row.** The first revision judged a history the code does not define
  only by the newest run's rows, so a contract history installed one release earlier, under a
  release that then added an expand column, was admitted two releases deep. Every row above the
  horizon, in any package, is now held to the newest run, and the walk's steps with it
  (decision 3).
- **Batch blocks.** A `batch_alter_table` flush runs outside Alembic's dispatch, so the statement
  check would have refused every batch-style expand revision, Terp's own among them. A block
  whose recorded operations are all admitted is admitted with its flush; a rebuild is judged by
  the catalogue, and `recreate="always"` is off the list (decision 1).
- **The search path only grows.** Skipping it when nothing is pending left a per-module app
  restored into a clean database unrouted; it is now the union of what is set and what the code
  needs, written whenever a label is missing (decision 4).
- **Smaller:** `terp promote` owns the version-table reading for an undo in the same invocation,
  and an empty record is not taken for one; the rollback check is the migration step's own
  command; the generated column's rewrite joins the lock notes; the reused-tag sentence; a tool
  mirroring the platform-owned names follows the framework; the checks' start signal and what
  they do not judge.

**Round three** found that the horizon hid the newest run's new histories when that run also
applied the target's own, as a fresh environment's first deploy does, and that refusing a
removed package stalled a plain removal a managed deploy cannot downgrade. The newest run's rows
for revisions the code does not define are now judged wherever they sit, which also covers the
walk's steps, and a release that removes a package retires it (decision 3).
