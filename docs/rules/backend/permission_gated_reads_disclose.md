# `backend/permission_gated_reads_disclose`

**A read gated by a named permission records that the data was disclosed**

> Generated from the catalog by `tools/generate_rule_docs.py` — do not
> edit by hand; the parity test holds this page to
> `packages/backend/arch/src/terp/arch/catalog/backend/permission_gated_reads_disclose.json`.

## Why this rule exists

An audit trail emitted from the write chokepoint is unbypassable and, for the same reason, mutation-only: it answers who changed what and never who looked. For the data an application guards most closely — a credential reference, a salary, a case file, a customer list — reading is the whole of the harm, and a principal holding the grant can enumerate every row and leave nothing behind. Not every read warrants a record; one per read of everything buries the entry somebody will eventually need. The discriminator is already written in the source by the author: a route that carries a named-permission requirement is one where a role tier was judged unable to express the decision, which is the application saying this data is sensitive. Such a route, on a safe method, must record the disclosure before it answers — so the record is the precondition of the disclosure rather than a report on it, and a failing trail fails the request instead of quietly losing the entry. A mutating route behind the same grant is out of scope: the write chokepoint already records it, and a second record would blur what a disclosure means.

## How Terp realises this

The reference implementation supplies the disclosure emitter (terp.core.emit_disclosure, ADR 0118): it opens its own session because a read has no unit of work to ride and the request session is write-guarded during a safe method, and it emits before the data is returned. ADR 0149 adds the obligation to call it.

## If you really need an exception

Add a justified marker on (or immediately above) the line, and record it
in your app's escape-hatch budget:

```
# arch-allow-permission-gated-reads-disclose: <reason>
```

An unjustified marker is itself a violation, and marker counts must
exactly match the checked-in budget (which can only shrink).

## Enforcement

- Checked while the app runs? Not yet — a runtime control is planned; the gap is explicit and tracked.
- `build-time`: `terp.arch` — `check_permission_gated_reads_disclose`
