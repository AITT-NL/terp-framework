"""The `terp guide testing` topic."""

TOPIC = """\
Testing a Terp app (process-global runtime isolation)

EVERY WIRED MODULE OWES AT LEAST ONE TEST (`modules_ship_tests`). The canonical module
shape is five production files, so until this rule a module could mount routes, own a
table and declare a policy with no test of any kind -- and `terp scaffold` emitted
exactly those five, so untested was the shape the platform handed out, not a corner an
app had to cut. WHERE they go:
      tests/<module>/test_*.py        the scaffolded shape; `terp new module` writes it
      tests/test_<module>_*.py        a flat file per module; recognised, not taught
  Both satisfy the rule. The directory is what the scaffold emits, because a module
  accumulates test files and a directory holds them without anyone inventing a naming
  convention; the flat form is recognised because refusing it would fail an app whose
  modules ARE tested, whose only way out would be a marker reading "no tests" (ADR 0119).
  Tests live in the project's tests/ tree, NOT inside the module directory -- a test that
  drives the composed app has to live where the app fixtures are.
  A module that genuinely has none takes
  `# arch-allow-modules-ship-tests: <reason>`, which spends the app's escape-hatch
  budget -- a shrink-only ratchet, so the debt is counted and cannot grow quietly.
  The rule asks only that the tests EXIST and are attributable. Whether they are any
  good is `no_empty_tests` (a body that cannot fail is not a test) and your coverage gate.

COUNT THE QUERIES A LIST ROUTE RUNS. The gate says a great deal about what your code
cannot get structurally wrong and nothing about what it costs to run, and the shape that
bites is dull: an endpoint loads N rows and touches a relationship per row, so the count
is 1 + N. The response is fine on the twelve rows your fixture creates, nothing in the
code looks wrong, every test passes -- until the table has real data in it.

      from terp.core.testing import assert_max_queries

      def test_listing_invoices_does_not_scale_with_rows(client, session):
          with assert_max_queries(session, 2, only="FROM invoice"):
              client.get("/api/v1/invoices/")

  Statements, not seconds: the count is deterministic and small where a wall clock is
  neither, so this survives a slow runner and still fails the moment a loop starts
  talking to the database. `count_queries(session)` is the same thing without the
  assertion, for when you want to look. A failure prints every statement that ran,
  because "expected at most 2, got 14" without the fourteen is a puzzle -- and the
  fourteen are almost always one SELECT with a different id, which is the diagnosis.

  PICK THE LIMIT FROM WHAT THE ENDPOINT SHOULD DO, not from what it currently does. A
  bound recorded from present behaviour passes forever and asserts nothing. The number
  is a claim about the SHAPE of the query, and the claim is that adding a row to the
  fixture must not change it -- so write the test with several rows in the fixture, or
  it cannot tell the two apart.

PROVE THE SEED IS DETERMINISTIC. `terp seed` may run on every boot and a fresh
environment is seeded from nothing, so a seed owes two things: a second run on the same
database writes NOTHING, and two fresh databases it seeds hold the SAME data. Comparing
rows as stored cannot show the second, because a fresh run does not repeat what a write
generates: every id is a new uuid4, every timestamp is now, a password hash has a new
salt, and every owner, actor stamp and audit target carries some row's new id.
`seed_checksum` compares the BUSINESS columns instead, by one rule:
      left out   a table's own single-column primary key, and every DateTime column
      reduced    a PHC hash ($argon2id$v=19$m=..$<salt>$<digest>) to scheme and params
      resolved   a value that is some row's UUID key (a foreign key, a text reference,
                 a JSON payload) to that row's table and business columns
      kept       everything else, a Date included; rows are compared as a set
and `generated=True` keeps every column as stored, which is how "nothing was written"
is asked:

      from terp.core.testing import seed_checksum

      def test_the_seed_is_deterministic(terp_db_url):
          engine = create_engine(terp_db_url)
          SQLModel.metadata.create_all(engine)
          run_the_seed(engine)
          first, stored = seed_checksum(engine), seed_checksum(engine, generated=True)
          run_the_seed(engine)                       # the second run is a no-op
          assert seed_checksum(engine, generated=True) == stored
          SQLModel.metadata.drop_all(engine)
          SQLModel.metadata.create_all(engine)
          run_the_seed(engine)                       # and a fresh database agrees
          assert seed_checksum(engine) == first

  A seed that fails it reads the clock, a random value or whichever row comes back first.
  Write through the real services, look each row up by its natural key before creating
  it (UsersService.ensure_user does), and derive any id the seed must choose with uuid5.
  `terp_db_url` runs it on PostgreSQL too.

WHAT YOU MUST STILL DO YOURSELF. The platform UNDOES a runtime; it never INSTALLS the
one your test needs. That distinction is the whole of testing on Terp:
      * whole runtime -> compose the app in a fixture (see apps/example/tests/conftest.py,
        where db_engine + app_db are function-scoped and build() runs per test)
      * only the event bus -> the `terp_events` fixture, which installs a catalog
        (and dispatcher) for the duration of one test:
            terp_events(event_catalog, dispatcher=dispatch_in_process)
        Annotate it `InstallEvents` (exported from terp.core.testing) - it carries
        configure_events' real signature, so a wrong catalog is a type error.
      * only the DURABLE AUDIT SINK -> the `terp_audit` fixture (annotate it
        `InstallAudit`), because the default sink only LOGS:
            from terp.capabilities.audit import persist_audit
            terp_audit(AuditPolicy.default(), sink=persist_audit)
        Without it, `select(AuditEvent)` returns [] and an assertion about an empty
        result PASSES - the test reports that audit works and has established only
        that nothing was installed. If a durable-audit assertion is passing suspiciously
        quietly, the sink is the first thing to check.
      * asserting on what was written to a FAKE/bare session -> `terp_default_runtime`,
        which states the baseline instead of assuming it. Without it a composed app's
        durable audit sink quietly adds audit rows to the session under assertion.
Deleting a conftest that INSTALLS something is not part of adopting the plugin.

WHAT YOU GET FOR FREE. terp-core ships a pytest plugin (terp.core.testing, registered
under pytest11) whose autouse fixture SNAPSHOTS every runtime before a test and
RESTORES it after. No conftest.py line, no opt-in. Without it a suite goes
order-dependent: green together, red alone - the sharpest failure mode there is,
because the green is the wrong answer.

SIGNING TOKENS NEEDS NO KEY OF YOUR OWN. The same plugin's `terp_signing_key` fixture
(autouse, once per session) replaces the development SECRET_KEY with a random 64-character
one while the default is in place, and puts the default back afterwards. So a test that
calls create_access_token signs with a strong key and pyjwt does not warn. Never write a
key into a test file: it is a credential-shaped literal the secret scan flags. A key the
environment sets, or one a test sets with monkeypatch, is left as it is.

THE SIX SEAMS. create_app installs six process globals per app; in a test process they
outlive the app that installed them. Restored automatically -- but installed by you:

      seam         what create_app installs        who installs it in a test
      audit        audit policy + durable sink     compose the app, or `terp_audit`
      events       event catalog + dispatcher      compose the app, or `terp_events`
      jobs         job catalog + queue             compose the app
      scheduling   schedule catalog                compose the app
      passwords    password policy                 compose the app, else the default
      secrets      the decrypt call site           compose the app (a secrets capability)

STRICT MODE. Restoring is faithful, which is also its blind spot: a runtime installed
BEFORE the first test (a stray `import app.main` at collection time, a module-scope
create_app()) is part of the snapshot, so it is restored before every test and covers
every test equally - green together, red alone, with nothing having leaked. Strict mode
follows the snapshot with a RESET, so every test starts from the platform baseline and
a test that only ever passed on ambient state fails where it stands:
      [tool.pytest.ini_options]
      terp_strict_isolation = true          # or: pytest --terp-strict-isolation
New projects start with it on, and the framework runs its own suites that way. Switching
it on in an existing suite can turn a green red - that red is the finding, not the
regression: the test was reading a runtime it never installed. Install it explicitly;
never re-order the suite.

AND READ THE GREEN HONESTLY. Strict mode resets BEFORE fixtures run, so it can only see
installs that happen before the suite. An autouse fixture that installs a runtime for a
whole package is invisible to it - every test gets a bus it never asked for, and strict
mode agrees with you every time. So: a green strict run does NOT mean your installs are
precise, only that none of them happen before the suite. Ask the other half instead:
      uv run pytest --terp-report-runtime-installs
which reports, per seam, the tests that installed it. Read the SHAPE of the answer: one or
two ids under a seam is a test installing what it needs; every id in a package under one
seam is a fixture installing it for them. Then make that installer NAMED and non-autouse,
and let the tests that emit request it. The ones that then fail were the ones being carried.

To find ORM commits with changes outside a service or framework writer, run
      uv run pytest --terp-report-writes
The summary lists the test ID, mapped model and changed column names. It includes ORM
writes made by fixtures and framework services on plain SQLModel and request sessions.
It follows the outer session commit and discards rolled-back savepoints. Raw SQL and
bulk statements are outside its scope. When the ORM writes an unloaded column and its
prior value is unknown, the report includes the column even if the assignment was a no-op.
To refuse those commits during a test run, use
      uv run pytest --terp-validate-writes
For one test or fixture, request the terp_validate_writes fixture before opening the
writer session. A custom service method can call _save again after changing a row.
A framework writer accounts for its specific insert, changed fields or delete. Move
ordinary fixture writes through the service. Seed historical imports as migration data.
A refusal names the model and columns. Service and job owners roll the transaction
back. A caller that owns a plain session must roll it back before starting another unit.

TWO FIXTURES, ONE SEAM. A seam holds one runtime, so the last install wins - and pytest
decides "last" from the FIXTURE GRAPH, not from the order of your test's parameters. A tap
that installs a recording dispatcher after the catalog fixture must DEPEND on it:
      @pytest.fixture
      def emitted(events_runtime: None, terp_events: InstallEvents) -> list[object]:
          ...
Getting it the wrong way round is silent: the tap installs first, the catalog fixture
overwrites it, and the recorder simply records nothing.
"""
