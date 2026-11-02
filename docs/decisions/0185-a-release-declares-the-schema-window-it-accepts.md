# 0185 — A release declares the schema window it accepts

- **Status:** Proposed (awaiting review). Nothing is built.
- **Date:** 2026-10-13 (drafted); brought into this repository on 2026-10-21. 0182 and 0183
  are reserved for other records.
- **Relates:** [ADR 0027](0027-packaged-migrations-per-package-histories.md) (amended: each
  revision carries a mark, the migration run records it, and the boot guard reads a database
  that is *ahead* of the code as well as one that is behind),
  [ADR 0062](0062-production-deployment-profile.md) (amended: the production image carries its
  schema labels, the `migrate` one-shot accepts a database ahead inside the window, and the
  deployment guide gains a rollback section),
  [ADR 0072](0072-database-additivity-review.md) (offline SQL writes the record too),
  [ADR 0024](0024-health-endpoints-and-pool-config.md) (unchanged: the health a release
  running behind the window reports),
  [ADR 0070](0070-per-module-schema-layout.md) (the record lives beside the version tables),
  [ADR 0071](0071-runtime-role-privilege-split.md) (extended: the runtime role holds the record
  on the version tables' grants, and its PostgreSQL lane pins the refusal to write it),
  [ADR 0063](0063-lockstep-release-and-publish-pipeline.md) (the one version the image label
  carries), [ADR 0084](0084-runtime-applicability-classification.md) (the new rule's runtime
  classification), [ADR 0133](0133-a-reference-declares-what-a-delete-of-its-target-does.md)
  (which referential actions an expand revision may add),
  [ADR 0111](0111-flexibility-is-bounded-by-legibility-not-by-capability.md) (layer 2 names
  "what a rollback is"), [ADR 0134](0134-the-lifecycle-has-one-driver-and-a-workbench-is-not-it.md)
  (`terp release` and `terp promote`, which carry the labels and the classification once
  designed), [ADR 0184](0184-a-deployment-declares-its-units.md) (the deployment declaration,
  drafted alongside, whose rollback wording rests on this decision).

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
     own primary key, constraints and indexes, unique ones included;
   - `add_column` that is nullable or carries a `server_default`;
   - `create_index` that is not unique;
   - data writes (`bulk_insert`, and `execute` of an `INSERT` or `UPDATE`): a back-fill.

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
   constraint, a unique index or a primary key change; also a merge revision, and any `execute`
   the `no_destructive_migrations` classifier flags or cannot classify. A table the same
   revision creates holds no rows the previous release relies on, so what it declares about
   itself is on the list. The list is necessary, not sufficient. An author marks a revision
   `False` when the previous release would mishandle what it adds even though every operation is
   on the list, and must do so when the new schema carries an access restriction the previous
   release cannot enforce: a rollback brings back the previous release's behaviour, and a
   restriction it does not know would stop applying while it runs.

   `terp migrate make` writes the mark it can prove: `True` when every operation it generated
   is on the list, `False` otherwise. The author may lower it and may raise it only within the
   list.

   | Layer | Control |
   |---|---|
   | Build-time | A new terp-spec rule, `backend/expand_revisions_only_expand`, checked by `terp.arch`: a revision marked `expand_only = True` that contains an operation off the list is refused. No opt-out marker: a revision that needs one is a contract revision, and saying so costs only restore-free rollback for its release. A `no_destructive_migrations` marker never excuses an operation in an expand-only revision. |
   | Runtime, fail-closed | The migration run classifies each operation of an expand-only revision as it executes, through the Terp-owned `env.py`, and raises on one off the list, before its DDL runs. The run keeps today's one transaction per package upgrade, with no transaction per revision, so the abort rolls back that package's whole upgrade in this run, its record rows included; a package already upgraded earlier in the same `migrate` stays, as on any failure today. Offline `--sql` has no transaction to abort, so it refuses to render: it exits non-zero naming the operation, and the output is not a release script. The rule's `runtime.applicability` is `required` (ADR 0084). |

2. **The migration run records every revision's mark in the database, where older code can
   read it.** `terp migrate upgrade` writes one row per applied revision into
   `terp_migration_window`: package label, revision, parent revision, `expand` or `contract`,
   the release that applied it, and when it was applied. The release is the per-release tag of
   decision 6: `terp migrate upgrade` takes it as an option, and the profile's `migrate`
   one-shot passes the same environment variable its image name reads. A run given none writes
   its rows with no release, which decision 6 reads as restore-based. terp-migrations creates
   the table itself, the way Alembic creates the version tables, outside every package
   history, and it lives beside them in `public`
   under either schema layout.
   The row is written in the same transaction as the version-table update for that revision.
   `downgrade` deletes the rows of the revisions it reverses. `stamp` writes none, so a stamped
   database never opens a window. `terp migrate upgrade --sql` emits the inserts beside the
   version-table bookkeeping it already renders (ADR 0072 decision 2), with the release taken
   from the same option, so a script-applied database opens the same window as one migrated
   online.

   The record is in the database, not in a manifest a deploy tool passes, for four reasons.
   Older code cannot read a newer release's revision files, so the mark has to live outside
   the newer image; the database is the one thing both releases share. The guard's answer must
   not depend on who starts the release: a deploy tool, `terp promote` and an operator starting
   a previous image by hand all meet the same record, where a manifest would give a different
   answer to whoever did not pass it.
   The record cannot drift from the schema it describes: it changes in the same transaction,
   and a backup carries it with the schema. And it adds no trust boundary: whoever can write the
   record can already write the version tables, the owner role always and the runtime role only
   in the flat layout, where ADR 0071 leaves `public` writable; under `per-module`, `public` is
   read-only for the runtime role. `terp migrate
   grant-runtime` gives the record exactly the version tables' grants and nothing of its own:
   the runtime role reads it, as the boot guard must, and writes it only where it can already
   write the version tables. ADR 0071's PostgreSQL lane, which today makes a runtime-role
   `DELETE FROM alembic_version_*` raise `insufficient_privilege`, gains the same
   refusal for an `INSERT`, `UPDATE` and `DELETE` on `terp_migration_window`. The guide
   already requires dumping the whole database; a dump that drops
   the record makes older code refuse, which is the safe failure.

3. **The guard checks the window instead of refusing outright.** For each package the code
   defines, `assert_migrations_current` reads the applied revision:

   - equal to the code head: current, as today;
   - an ancestor of the code head: `PendingMigrationsError`, as today;
   - unknown to the code: walk it back through the record, revision to recorded parent, until
     a revision the code knows is reached. The database is inside the window only when every
     step is recorded, every step is `expand`, and the walk ends exactly at the code head.
     Anything else, an unrecorded revision, a `contract` step, a walk that ends on an older
     ancestor or never ends, raises `OrphanedRevisionsError` as today.

   A package label the record holds and the code does not define (a history a newer release
   added) is admitted only when every revision recorded for it is `expand`. When the guard
   admits a window it logs one warning at boot naming each package and the revisions the code
   runs behind, so a release running behind is never silent. There is no switch back to the
   strict refusal: the guard, the `migrate` preflight and `terp migrate check` read the window
   alike, and a switch honoured by one and not the others would let them disagree. Strict
   refusal is given up by this decision. An app that wants its own rollbacks restore-based
   lowers each mark `terp migrate make` writes on its own revisions to `False`; the windows of
   Terp's capability revisions, which carry Terp's marks, stay admitted by the guard, and a
   rollback across them is still classified restore-based where decision 6 says so.

   This narrows the guard by decision; it does not weaken it. A rewritten or deleted history is
   still refused, because a rewritten revision was never recorded as an expand step whose
   parent is the code's head. The framework's PostgreSQL lane gains the proof: the example app
   at N-1, with the guard armed as in production, boots on a database upgraded to an
   expand-only N; refuses on one with a contract revision; refuses when the record is missing;
   and its `migrate` one-shot exits 0 without running DDL.

4. **Rollback is promised one release deep, and a rollback never migrates.** The promise is
   that release N-1 runs on the database release N left, when every revision N applied is
   expand-only. A target further back is restore-based, even where the guard would admit it,
   because nothing has proven it. The depth is read from the record, not from a deploy tool's
   history: each row names the release that applied it (decision 2), so two expand-only
   releases in a row leave rows of two releases between N-2 and the database, and decision 6
   rules that rollback out. A release that applied no revision leaves no row and adds no depth:
   rolling back over it changes code on an unchanged schema, as every rollback without a
   migration does today. A rollback runs no downgrade and applies no revision. It
   does not need the target's `migrate` one-shot, and where a profile still runs it (the
   template's `api` waits on it) the one-shot migrates nothing: it shares the guard's check as
   its preflight, reports nothing to apply for a package ahead inside the window, and exits 0;
   it never downgrades. Letting it run, rather than starting `api` without it, keeps the
   profile's `db → migrate → api` order unchanged and gives the same refusal as the guard
   before `api` starts on a database outside the window. Rolling forward to N again finds the
   database at N's heads and applies nothing.

   Rows the previous release writes while it runs leave N's new columns at NULL or at their
   default and N's new tables without them, and a back-fill revision N ran is not run again,
   because a revision applies once. So an expand release's code must read correctly on rows
   the previous release wrote, and the previous release must read correctly on rows N wrote.
   So an expand release keeps writing the old shape the previous release reads, and also writes
   the new one, the way the move-a-model recipe writes to both tables while the old one still
   has readers. It
   reads the old shape, or it re-runs its back-fill as an idempotent step on every start of the
   release (a job, not a revision), so a roll forward fills what the rollback left. A new
   column's NULL is a value N's code handles until the contract release tightens it; the
   contract revision back-fills again first, and the expand list's rule that a new column is
   nullable or defaulted is what keeps those rows valid in the meantime. The PostgreSQL-lane
   proof of decision 3 covers the round trip: N writing, then N-1 reading what N wrote and
   writing, then N again reading what N-1 wrote.

   Every release after a rollback descends from N's migration history. A fix cut from N-1, a
   revert of N's code for example, keeps N's revision files and the model fields and tables
   they create, and reverts behaviour only. Keeping the files alone is not enough: the app's own
   test gate upgrades a scratch database to head and requires autogenerate to find no drift, so a release
   that keeps N's revisions but reverts N's models fails it, and the next `terp migrate make`
   would generate drops of N's columns. Removing them is a later contract release. A release
   that drops N's revision files is admitted only while it adds no revision of its own, and the
   first revision it adds hangs off N-1's head, where the walk of decision 3 ends on an older
   ancestor and the guard and the `migrate` preflight refuse. That refusal is fail-closed but
   arrives as a restore, so the deployment guide's rollback section and the migrations guide
   both state the rule, and the guard's message for this case names it: the database holds
   expand revisions this release's history dropped. The PostgreSQL-lane proof includes such a
   revert release, which passes `test_migrations_match_models` and boots on N's database.

5. **Contract steps go into a later release's history.** A revision without the mark is a
   contract revision, and the release that ships one is rolled back by restore. So the step
   that drops, renames or tightens goes into a later release than the one that expanded, once
   nothing in the release before it still needs the old shape. The guides change with this:
   the migrations topic's NOT NULL recipe becomes "tighten it in a later release", and the rule
   guide's "in a LATER revision" becomes "in a LATER release", in line with the move-a-model
   recipe that already says so. A release that mixes expand and contract revisions is legal; it
   is classified restore-based (decision 6), which is the cost of mixing them.

6. **A release image says which window it can read, and a rollback is classified before it is
   offered.** The production image carries two labels: `terp.version`, the lockstep Terp
   version it was built with (ADR 0063), and `terp.migrations.heads`, its head revision per
   package as JSON. `terp migrate heads` gains a machine-readable form to supply the second, and the template's `Dockerfile.prod` takes both as build arguments
   and writes them as labels. `terp release` supplies both when it builds the image (ADR 0134).
   The profile's own `build` passes none, so an image built by a plain `up --build` carries no
   labels and classifies restore-based; the guard's window still applies to it, but nothing
   offers it as restore-free.

   The profile also stops overwriting the image a release ran. Today the backend image has one
   untagged name, `{{ project_slug }}-backend-prod`, and the frontend
   another, so `up --build` replaces the image the previous release ran and there is
   nothing left to start again. Both names gain a per-release tag the profile reads from the
   environment, so a release's images stay on the host beside the next one's. The tag is
   `:?`-required in the production profile, the way `SECRET_KEY` and `POSTGRES_PASSWORD` are
   (ADR 0062 decision 3): with the variable unset, compose fails fast instead of falling back
   to a fixed tag that `up --build` would silently overwrite again. A plain `docker compose up`
   of the profile therefore needs the tag set, and the deployment guide's upgrade step says to
   choose a new one per release.

   A rollback from the running release to a target is restore-free only when all of these
   hold:

   - the target is the release immediately before the running one, read from the record:
     every row the walk from the applied revision back to the target's head crosses carries the
     running release's tag. A row with another release's tag or with none rules it out;
   - the target's `terp.version` carries this decision;
   - the target's `terp.version` equals the running release's, so no Terp upgrade lies
     between them;
   - `terp migrate check`, run from the target's own image against the live database, passes
     with the window. It is read-only today: it opens an engine and calls
     `assert_migrations_current`, so it
     becomes window-aware because it calls the guard of decision 3.

   Anything else is restore-based, and is classified that way before the rollback is offered:
   a target without labels, the first release an app cuts after adopting this decision (its
   predecessor cannot read the window), and any rollback across a Terp upgrade, whose
   capability histories and record format the older release was never tested against.

   The labels let a tool rule restore-free out without starting the target's image. The
   record's release column settles the first condition, and the `terp.version` labels the
   second and third. The `terp.migrations.heads`
   label is compared against the database: for each package, the walk of decision 3 from the
   applied revision back through `terp_migration_window` must reach the target's head through
   `expand` rows only, and a package whose walk crosses a `contract` row, an unrecorded
   revision, a row that names no release or one other than the running release, or never
   reaches that head rules the rollback restore-based. A label-only verdict can only rule restore-free out, never
   in: the labels cannot show what the target's own code accepts, so only `terp migrate check`
   from the target's image rules it in, because the window only exists in the target's own
   code.

   The classification is one terp-migrations function, so `terp promote` and any other deploy
   tool that calls it reach the same verdict. The PostgreSQL lane of decision 3 gains the case
   that makes the depth checkable: two consecutive expand-only releases, N-1 and N, each run with
   its own tag; N-2's guard admits the database, and the classification still rules a rollback
   from N to N-2 restore-based, because the walk crosses rows N-1 applied. The same lane rules a
   rollback from N to N-1 restore-free.

7. **Until a rollback target carries the window, rollback is restore-based, and the guide says
   so.** The deployment guide gains a rollback section: across a migration, without a
   restore-free classification, roll back by restoring the backup taken before the upgrade and
   starting the previous images, which loses every write made since that backup. With one, start
   the previous images on the same database and run nothing else. The section also states
   decision 4's rule that every release after a rollback keeps N's revision files and the model
   fields and tables they create, reverts behaviour only, and leaves their removal to a later
   contract release; the migrations guide states the same rule. The upgrade
   step gains "back up the database before running `migrate`", because today it asks for no
   backup and a restore-based rollback needs one
   taken before each upgrade.

## Consequences

- **ADR 0027 is amended in three places.** Decision 1: histories stay linear and per package;
  each revision now carries a mark, and the migration run keeps one record outside every
  history. Decision 3: the runtime control also judges a database *ahead* of the code, and
  admits it only inside the recorded window. The
  operational guidance on a `NOT NULL` add-column gains "tighten in a later release"
.
- **ADR 0062 is amended in four places.** Decision 1's image carries the two labels. Decision 3's
  `db → migrate → api` order stays, with a `migrate` that exits 0 on a database ahead inside the
  window, and the profile's backend and frontend images gain a `:?`-required per-release tag.
  Decision 4's two-layer guard keeps its shape with the window inside it, and its build-time
  half, `tests/architecture/test_prod_profile.py`, asserts the tag is `:?`-required on both
  image names in both profiles, beside its required-secrets test. Decision 5's `docs/DEPLOYMENT.md`
  gains the rollback section and a backup before every upgrade's `migrate`.
- **ADR 0071 is extended, not amended.** Its grants are unchanged: the record lives in `public`
  and takes the version tables' grants in either layout. Its PostgreSQL lane adds the refusal of a
  runtime-role write to `terp_migration_window` under `per-module`.
- **ADR 0072 decision 2's offline script writes the record**, so DBA-applied releases keep the
  same rollback as online ones.
- **terp-spec gains one catalog entry** (`backend/expand_revisions_only_expand`, with corpus
  cases), and the runtime rationale of `migration_history_is_intact`, which describes the orphan
  check as refusing any revision the code no longer defines, is reworded to the narrowed check.
- **Authors make one more choice per revision**, and `make` makes it for them where it can prove
  it. A release with a contract revision costs a restore to roll back, and that cost is visible
  before the release ships, not discovered during an incident.
- **Terp's own capability revisions carry marks too**, under the same rule. A rollback across a
  Terp upgrade stays restore-based until a later decision proves capability histories across
  Terp releases.
- **Data written under the newer release stays** in its new columns and tables while the older
  release runs, unread by it; what the older release must see, the newer release also wrote in
  the old shape (decision 4). Restore-free rollback undoes code, never data.
- **Health is untouched.** A release running behind the window reports liveness and readiness
  by ADR 0024's rules, and the window adds no readiness signal. Worker and shared-store
  signals are a separate amendment to ADR 0024, not part of this decision.
- **Nothing changes for an app that does not adopt the version that carries this.** Its guard,
  its `migrate` and its rollback (by restore) behave exactly as today.

## Where this stands

Proposed, not built. The first Terp release that carries it is the earliest `terp.version` a
restore-free rollback can target; until an app has two consecutive releases on such a version,
its rollback is restore-based (decision 7). It needs acceptance before any rollback test, or
any deployment declaration's rollback field, relies on it. ADR 0184's `rollback.strategy`,
built in 0.35.0, says what a rollback is and claims nothing about whether one is restore-free,
so it does not wait on this decision.

Open for implementation, not for this decision: the exact `execute` classification an expand
revision may carry (the spec entry's reference text settles it, starting from the
`no_destructive_migrations` classifier), whether `terp migrate make` or `terp.arch` can also
refuse a new revision whose parent is behind a recorded expand step before it ships, and the
final spelling of the table and its release column, the mark, the two labels and the
per-release tag.
