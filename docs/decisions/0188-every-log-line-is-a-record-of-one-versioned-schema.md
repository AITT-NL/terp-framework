# 0188 — Every log line is a record of one versioned schema

- **Status:** Accepted and implemented in 0.35.0. Every line terp-core writes is a
  `terp-log/1` record; the JSON Schema ships in terp-core as `log-record.schema.json`
  (`terp.core.log_record_schema()`, `terp.core.LOG_SCHEMA`). The access line, the guard's
  decision, the error records, uvicorn's loggers and the process hooks are built. Held by
  `tests/architecture/test_structured_logs.py` (each record and each control, in process) and
  `tests/architecture/test_structured_logs_served.py` (every line a production uvicorn process
  writes, validated against the schema). Decision 7 records that the schema belongs in the Terp
  Standard as a vocabulary; moving it there is a terp-spec change this record does not make.
- **Date:** 2026-10-22. 0182 and 0183 are reserved for other records; 0184 to 0187 are taken.
- **Relates:** amends [ADR 0005](0005-security-middleware-and-structured-logging.md) (the record
  shape, and its claim of PII redaction, corrected) and
  [ADR 0006](0006-cross-cutting-controls-and-opinionation-policy.md) (the same claim); extends
  [ADR 0025](0025-medium-input-and-observability-hardening.md) (the `extra=` fields keep their
  place), [ADR 0075](0075-login-timing-proxy-identity-and-request-id-hardening.md) (the request
  id's shape, now a schema pattern) and [ADR 0148](0148-a-route-declares-its-own-posture-not-its-neighbours.md)
  (the route policy the guard reports); applies
  [ADR 0111](0111-flexibility-is-bounded-by-legibility-not-by-capability.md) decision 5 to the
  log in decision 7, as the proposed ADR 0186 does for the workbench declaration.
  Decision 6's open item, personal data, is decided by
  [ADR 0190](0190-a-field-declares-itself-personal.md). Supersedes nothing.

---

## Context

A Terp app's log has a reader the framework never sees: a deploy runner or a workbench that
reads a container's output to say what went wrong, a log store that indexes it, an operator with
`jq`. Such a reader holds the lines of one release beside another's, because apps adopt
framework releases one at a time. What it could rely on before this record was that some lines
were one JSON object with a top-level string `level`. That was all, and it was not even every
line. A production process, served the way the template's image serves it, wrote:

1. **The app's own records** as JSON with `level`, `logger`, `request_id` and `message`, and no
   timestamp. A line could not be placed in time without the container runtime's own prefix.
2. **uvicorn's lines** as plain text. uvicorn's command line configures its loggers, with
   handlers that do not propagate, *before* it imports the app; `configure_logging` covered the
   root logger only, and the production command passes no log configuration. So "Started server
   process", the shutdown lines and every access line bypassed the formatter and the redaction.
   The access line named the raw path, ids and any query-string token included.
3. **Tracebacks nothing caught** as plain blocks: a `BootError` at composition, a settings
   refusal at import, an exception that ended a thread. The settings refusal also repeated the
   configuration it refused: pydantic's error quoted its input truncated in the middle, so the
   tail of `DATABASE_URL`, password included, reached the boot log.
4. **The guard's decisions** not at all. A 403 said nothing about which rule refused it.
5. **An `AppError`'s `log_context`** nowhere. The error envelope promised that the raw reason
   goes "into `log_context` (logged, never serialised)", and no code read the field. An
   `AppError` was logged in zero places.
6. **An unexpected exception** twice: once by the framework's 500 handler, and again by uvicorn
   as "Exception in ASGI application", because Starlette's outermost middleware re-raises the
   exception to the server after the handler has answered. Two tracebacks, the second without
   the request id.

And the redaction did less than it said. ADR 0005, ADR 0006, the logging module, and the
`no_adhoc_logging_config` rule's docstring and finding all said "PII redaction"; the filter has
only ever recognised secrets. Within secrets there was a hole in the commonest shape of all:
for `Authorization: Bearer <token>` in free text the pattern took the scheme word as the value,
so `Bearer` was redacted and the token after it was written. Exception text, an exception passed
as a log argument and a traceback were not scrubbed at all.

## Decision

**1. One record shape, versioned, additive.** Every line is one JSON object with six required
keys: `time` (UTC, RFC 3339, millisecond precision, ending in `Z`), `schema` (the string
`"terp-log/1"`), `level`, `logger`, `request_id` (`-` outside a request) and `message`. The
four keys every line already had keep their names and meanings. A line about a framework event
adds `event` and that event's typed fields: `http`, `actor`, `tenant`, `guard`, `error`,
`context`. The app's own `extra=` fields stay under `extra`, where they cannot collide with the
schema's keys. Version 1 grows only by addition: a release may add an optional key or an `event`
value, never removes a key, renames one, changes what one means or its type. A change that would
is version 2, under a new `schema` value. So every object in the schema leaves
`additionalProperties` open, and a reader takes what it knows and ignores the rest; the emitter
is held tighter than that by the suite, which refuses a key the schema does not declare.

The schema is JSON Schema draft 2020-12, shipped in terp-core beside the module that writes the
lines, so a reader can load it from the installed framework rather than copy it. Its patterns end
in `(?![\s\S])` rather than `$`, so a validator whose `$` also matches before a trailing newline
(Python's) cannot let one through, as in the deployment declaration.

**2. One access line per request.** A pure-ASGI middleware just inside the request-id middleware
writes `event: "http.access"` on logger `terp.access`, at INFO, once the response has gone: the
method, the matched route's **template** (`/api/v1/notes/{note_id}`; absent when nothing
matched), the status (500 when an exception escaped every handler, 499 when the client left
before any response started), `duration_ms` and the request id. It sits inside the request-id
middleware so it carries the id, and outside everything else so it sees every status the stack
answers with, a rate-limit refusal included.

The **actor** is the authenticated principal's id, and the **tenant** the tenant of that
authenticated request; both come from the guard, which is where the authenticated principal is
in hand, and both are absent when there is none. Each is held to the UUID shape, so whatever a
principal provider put in a principal, a token cannot reach the line through these fields. The
kernel cannot import the tenancy capability, so the capability registers its reader through
`register_log_tenant_reader`, the logging analogue of `register_job_tenant_context`.

uvicorn's own access line is retired (decision 4): the framework's is the careful copy.

**3. The guard records the rule that decided, for every allow and every deny, on the access
line.** `guard` carries the outcome, the decision's reason slug (the same `decide()` returns:
`allowed`, `rank`, `grant`, `unauthenticated`, ...), the **rule** (the requirement that applied,
`role:editor` or `permission:invoices.send`, or `authenticated`, `public`, `no_policy`,
`registered_role` where the decision came before a requirement was selected), whose policy it
was (`module` or `route`), the read/write tier and the module. Riding the access line is what
keeps this from flooding a production log: every decision is in it, at INFO, for no extra line.
A connection without an access line (a WebSocket) gets its own `guard.decision` record: a deny
at INFO, an allow at DEBUG. Recording never changes a decision: a failure to record is a
`log.failure` record, and the guard allows or denies as it would have.

**4. uvicorn's loggers and the interpreter's own printers go through the same handler.**
`create_app` configures logging first, before any boot check can refuse, and re-points
`uvicorn`, `uvicorn.error`, `uvicorn.access` and `uvicorn.asgi` at the root handler: their
handlers removed, propagation on, the access logger raised to WARNING. uvicorn's copy of an
exception the framework has already written (decision 5) is dropped by a filter on
`uvicorn.error`. Outside local development `create_app` also replaces the interpreter's default
printers, so an uncaught exception, one that ends a thread, an unraisable one and a warning each
become a record (`error.uncaught`, or logger `py.warnings`). It replaces only a hook still at the
interpreter's default: one somebody else installed (a test runner's, an APM agent's) is theirs.
Local development keeps them: there, a test runner owns those hooks. The hooks are a per-app
runtime seam (`reset_logging_runtime`), so a test that composes a production app leaves the
process as it found it.

A settings refusal happens while `terp.core` is still importing, before any composition root
runs. `Settings` now hides its input in errors, and the import routes the refusal through the
same handler before it propagates, so the most common boot failure is a record that does not
print the configuration.

**5. Each error is written once.** The envelope's exception handlers are the one place:
an `AppError` as one `error.app` record on logger `terp.errors` with its code, its status and its
`log_context` in `context`, redacted; an unexpected exception as one `error.unhandled` record
with its traceback, still on logger `terp.core`, where it always was. A client's error (4xx) is
INFO, beside its access line; a server's (5xx) is ERROR, an `AppError` of that kind with its
traceback. The unexpected exception's record binds the request id again, because its handler
runs outside the request-id middleware, which has already reset it; that is what lets a reader
join the error to its access line. The exception is marked as written, and the server's copy is
dropped (decision 4).

**6. Redaction is of secrets, and a failure inside logging never escapes.** The filter redacts a
credential-like key (`password`, `token`, `secret`, `api_key`, `cookie`, `authorization`) in any
`extra=` field and in `context`, and credential-shaped text: an `Authorization` value (the scheme
word kept, the credential gone), a bare `Bearer` value, a cookie header's value, a URL's
password, a `password=` / `client_secret:` / `api_key=` pair. It reads the message, its
arguments once rendered (an exception passed as an argument has text only then), the traceback
and the stack. Personal data has no shape to recognise, so it is withheld only where a field
declares it: that is [ADR 0190](0190-a-field-declares-itself-personal.md)'s decision, made
after this one. The framework's own typed fields
(`http`, `guard`, `actor`, `tenant`, `error`) are built from declarations and typed values and
are not re-scanned; `context`, which carries what an app handed over, is.

A record that cannot be redacted is withheld, message and extras and traceback, and says so; one
that cannot be rendered becomes a `log.failure` record; a write the stream refuses is retried
once in the record's shape and then dropped, instead of printing `--- Logging error ---`. The
access line and the guard's note catch their own failures for the same reason: logging never
breaks a response.

**7. The schema belongs in the Terp Standard as a vocabulary.** The log is a contract read by
programs other than its writer, which is the test ADR 0111 decision 5 sets, and the one the
proposed ADR 0186 applies to the workbench declaration. It is a vocabulary, not a catalog rule:
what every reader must agree on is how a line reads, not a check of an app's source. Moving it takes: terp-spec adding
`log-record.schema.json` with `log-record.fixtures.json` (valid records with what a reader
resolves from them, invalid ones with the field each refusal is about, and lines that are not
one JSON object), listed among the vocabularies no rule realises; a terp-spec release; the file
in terp-core becoming a byte-for-byte mirror of it under a test that compares the mirror and the
fixtures with the pinned spec, and until that pin moves asserts the pinned spec ships neither;
and every reader running the fixtures. The `schema` value `terp-log/1` stays what it is, because
readers key on it; the `$id` moves to the spec's convention. Until then terp-core owns the file.

## Consequences

- A reader of a production container's output gets one JSON object per line, every line, from
  uvicorn's first line to its last, each with a time and the schema it follows. A reader that
  keyed on `level` keeps working; the new keys are additions.
- Every request has exactly one access line, and every guarded request names the rule that
  decided it. A 403 says which permission it was.
- `log_context` is finally what the envelope always said it was: logged, never serialised.
- An unexpected exception is one record with the request id, not two tracebacks.
- An app that logged each request itself now has two lines per request; it drops its own.
- The access line costs about as much as the uvicorn access line it replaces plus a little:
  measured in process on a loaded development machine, the record alone is about 35 to 75
  microseconds against 26 to 50 for uvicorn's, the middleware itself under a microsecond. A
  request that does any work at all takes milliseconds.
- `cache`, `idempotency`, `throttling` and `leases` import `Lock` by name, as the
  `no_adhoc_background_runtime` rule asks; the module that sets the thread hook
  (`terp.core._log_capture`) is the one remaining finding of that rule in core's unscanned
  record.

## Not covered

- **A supervisor process.** Under `--reload` or `--workers`, uvicorn's parent process never
  imports the app, so its few lines ("Started reloader process", "Started parent process") stay
  uvicorn's. Production runs one process per container, which is what the template's image does.
- **An app object passed to `uvicorn.run` from Python.** uvicorn then configures its loggers
  *after* the app was composed and re-installs its own handlers; pass `log_config=None`.
- **A reserved `extra=` key.** `logger.info(..., extra={"message": ...})` raises `KeyError` in
  the standard library before any handler is reached. It is the same in every environment and
  fails the first test that runs the line.
- **A missing app module.** uvicorn's "Error loading ASGI app" is written before anything of the
  app has been imported.
- **Personal data.** Decision 6 redacts secrets; a field declared `Personal` is withheld
  as [ADR 0190](0190-a-field-declares-itself-personal.md) decides, and an undeclared value is
  not recognised.
