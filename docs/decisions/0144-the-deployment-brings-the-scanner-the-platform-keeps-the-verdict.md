# 0144 — The deployment brings the scanner, the platform keeps the verdict

- **Status:** Accepted and implemented. `File.scan_state` is a column,
  `register_file_scanner` is the seam, and `FileService.open_stream` refuses to hand out
  the bytes of a rejected file. Held by `tests/architecture/test_files.py`.
- **Date:** 2026-09-18
- **Relates:** [ADR 0056](0056-files-capability.md) (the capability),
  [ADR 0068](0068-files-content-type-allowlist.md) (the type allowlist this is not a
  substitute for), [ADR 0076](0076-webhook-secret-sealing-jwt-rotation-audit-append-only-and-upload-sniffing.md)
  (magic-byte sniffing, likewise), [ADR 0057](0057-files-storage-profiles-and-references.md) (the
  registry shape this seam copies), [ADR 0029](0029-object-level-ownership-authorization.md)
  (`OwnedMixin`, which is why the asynchronous shape is absent)

---

## Context

A stored file is attacker-supplied bytes that somebody will later be handed back. The
capability already refuses two things it can decide from the upload alone: a media type
outside the deployment's allowlist (ADR 0068) and bytes whose signature contradicts their
declared type (ADR 0076). Neither is malware detection, and the distance between them is
worth saying out loud, because the pair reads like coverage: a signature check proves a
PDF is shaped like a PDF, which is exactly what a malicious PDF also is.

What was missing was not a scanner. **A platform cannot ship a scanner** — which engine a
deployment runs, whether it holds a licence for one, and what it costs per upload are
deployment questions, and a capability that answered them would be forked by the first
consumer that needed a different answer. What a platform can own is the *state*: a column
that records what was decided, a seam the decision arrives through, and a gate that reads
it. Without those, a consumer that wants scanning has to fork the capability or wrap every
call site, and a call site is exactly where this control must not live.

## Decision

**`register_file_scanner(scanner)` is the seam**, shaped like the storage registry beside
it: one composition-root line, a later registration replacing the earlier one. The scanner
runs inside `FileService.store`, after the bytes are in the backend and before the
metadata row is created, and it is handed a `ScanSubject` — the filename, media type, size
and digest, plus a callable that **opens the stored blob**.

Three details of that are decisions rather than mechanics:

- **It sees the stored bytes, not the request stream.** The scanner must judge what a
  download would actually hand out. The upload stream has also been consumed by the
  digesting copy by that point, so there is nothing else honest to give it.
- **It gets an opener, not the bytes.** A scanner needing only a header can stop early.
  This path has taken real care never to hold an upload in memory whole, and handing one
  over as a `bytes` would undo that on the way to a security control.
- **It is given a plain subject, not the `File` row.** At scan time there is no row — its
  `scan_state` is what the verdict decides — and handing a scanner a half-built ORM object
  invites it to write to one.

**`scan_state` holds one of three values.** `clean` and `rejected` come from a scanner.
`not_scanned` is what a deployment that wired none stores, and what the migration
backfills onto every existing row — *not* `clean`, which is the one value that would make
the column lie, in the direction that lets bytes out.

**A deployment that wires no scanner is unchanged.** There is no safe default available
here: a file cannot be `clean` without something having looked at it, so gating downloads
on a verdict nothing will ever produce would make every already-stored file unreachable at
upgrade — the kind of secure that gets reverted rather than configured.

**Rejected bytes are quarantined, not deleted.** The row is created and the blob stays
where it is, flagged and unservable. Deleting the evidence is the wrong reflex for a
security control: the operator needs to know what arrived, from whom and when, and the
uploader is told by `scan_state` on the response rather than by a discarded error. It also
keeps the gate honest — a state no reachable path can produce is a comment, not a control,
and a download gate that can never fire is untestable by construction.

**The gate lives in the service read chokepoint, not on the download route.** `open_stream`
is what the route, the buffered `load`, and the serve-through `load_for` all pass through.
Written on the route, `load_for` would have gone on handing out precisely the bytes the
scanner rejected, through another module's already-authorized row, and nothing would have
said so.

**An unrecognised verdict fails closed.** A scanner returning `"ok"` raises rather than
being coerced: coerced to `clean` the mis-wiring is invisible forever after, and written
to the row verbatim it sits outside the vocabulary and reads as servable. The upload that
hit it is where a mis-wired composition root is cheapest to find.

## What is deliberately not here, and why it is not a local decision

**There is no asynchronous scanning, and no way to re-mark a file after the fact.** Both
mean writing a verdict onto a row that already exists, from something that is not its
owner — a cross-owner maintenance write. The platform has no supported route for one.
`OwnedMixin` authorizes every write to an existing row against the request actor
(ADR 0029), a background worker has none, and `terp guide ownership` states the position
plainly: *"Genuine cross-owner maintenance — NO SUPPORTED ROUTE TODAY."*

A capability shipping it anyway would have had to pick one of two bad options: write
outside the audited chokepoint, or bind the actor context to the row's owner and record
them as the author of a verdict they did not produce. A security-relevant state change is
the last place in the system to falsify an audit record or skip one.

So the scanner here is synchronous, and the asynchronous case stays a **platform** gap
rather than becoming a capability-shaped workaround. Naming it is the useful part: the fix
belongs wherever cross-owner maintenance authority is eventually designed, and this is now
a second concrete caller for it.

## Consequences

**A migration, so this is consumer-visible.** One additive, backfilled, indexed column.
The index is not decoration: the question this column answers is a listing one — *which
stored files were never scanned* — which is exactly what an operator asks on the day they
finally wire a scanner.

**Wiring a scanner does not retroactively scan.** Files stored before it keep
`not_scanned` and keep being served. That is the deliberate cost of not bricking an
existing deployment, and the index is how those rows are found.

**`FileRead` gains `scan_state`** — additive, and the opposite kind of field from
`storage_key`, which that DTO exists to withhold. A caller refused a download is owed the
reason; a client that cannot read the state can only discover it by attempting the
transfer. `FileUpdate` does not gain it: a verdict a client could patch is not a verdict.
