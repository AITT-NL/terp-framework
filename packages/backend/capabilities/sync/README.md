# terp-cap-sync

The bundled sync jobs commit their local records, mapping ledger, record logs and
successful run cursor in one database transaction. A failure raised by the sync
operation rolls that work back. After rollback, a separate audited transaction
records the failed attempt with its original actor, request and tenant context.
It does not recreate business rows or advance the resume cursor.

For a failed pull, `processed_count` describes attempted processing; local
`created_count` and `updated_count` are zero when the transaction rolled back.
For a push, a count already returned by the source remains recorded if local
finalization subsequently fails. A source that raises before returning has no
confirmed count; zero recorded updates does not establish that no external effect
occurred. External systems still require their own idempotency or destination
fencing because a local rollback cannot undo a remote write.

A custom job that catches a sync failure may choose to complete its surrounding
transaction. Its run still receives the failed outcome, without discarding those
committed local effects. The journal checks the original run's version and status
and preserves a reaper's or concurrent writer's verdict. A later failure outside
the sync operation itself remains the surrounding job's responsibility; this
journal does not describe arbitrary handler failures.

Direct calls outside a job retain the service's existing audited write units.
Use the bundled jobs when the entire local reconcile must commit or roll back
together.

Source custody uses a separate coordination connection for acquisition and
heartbeats on non-SQLite databases, so other workers can observe an active lease
and its expiry during a long job. The pool must provide distinct physical
connections; a shared connection cannot safely separate those transactions and
is refused. With `DatabaseLeaseStore` (or a store honoring the same transaction
contract), the final custody check joins the business transaction and holds its
database fence through commit. Release runs after commit or rollback and cannot
clear a successor's claim.

SQLite permits one writer at a time, so its custody operations remain in the
business transaction. A long write transaction therefore delays takeover until
that transaction finishes; lease TTL alone is not a bound on recovery while the
writer remains active. A new run is also uncommitted until the job finishes:
the reaper cannot see it during that transaction, and rollback removes it. A
failure raised by sync records the separate failed-attempt journal described
above; a process that disappears without running cleanup leaves no such new run.
