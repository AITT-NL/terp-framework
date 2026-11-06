# `backend/no_exception_text_in_responses`

**An error response never carries a caught exception's own text**

> Generated from the catalog by `tools/generate_rule_docs.py` — do not
> edit by hand; the parity test holds this page to
> `packages/backend/arch/src/terp/arch/catalog/backend/no_exception_text_in_responses.json`.

## Why this rule exists

Interpolating a caught exception into the message a client receives publishes whatever that exception happens to say. A database driver names the table, the column and often the failing statement; a filesystem error names an absolute path and therefore the deployment layout; a parser names the offending byte offset in a document the client did not send; a connection error names an internal hostname and port. None of that is chosen, reviewed or versioned - it is a library's diagnostic string, written for an operator reading a log, forwarded verbatim to whoever made the request. The sibling rule that keeps declared fields out of a serialized response cannot see this, because an error path builds its message on the spot rather than from a declared schema, so the one place an application improvises text for a client is also the one place nothing was checking. The compliant shape is that the response carries a message the application wrote and the log carries the exception.

## How Terp realises this

Inside `except ... as exc:`, raising an error whose message derives from the caught exception - `str(exc)`, `repr(exc)`, `f"...{exc}"`, `exc.args`, `"..." % exc`, `traceback.format_exc()` - is refused, in the error's positional message and in its `detail=` / `message=` keywords alike. Raise a written message and chain the cause (`raise NotFoundError("Order not found") from exc`): `from exc` keeps the traceback, and `log_context=` is the sanctioned place for the exception's own text, because terp.core never serialises it to the client.

## If you really need an exception

Add a justified marker on (or immediately above) the line, and record it
in your app's escape-hatch budget:

```
# arch-allow-no-exception-text-in-responses: <reason>
```

An unjustified marker is itself a violation, and marker counts must
exactly match the checked-in budget (which can only shrink).

## What the check is not required to catch

A check precise enough to have no false positives has limits. This
rule's limits are recorded as data (its corpus's `RESIDUALS.json`), so
where detection ends is a statement rather than a guess:

- an error built into a local name and raised on a later statement (`err = ValidationFailedError(str(exc))` then `raise err`) is not required to be connected to the handler that bound the exception
- a helper called from the handler that takes the caught exception and returns a message string is not required to be followed across the call
- exception text a handler persists instead of raising (`row.failure_reason = str(exc)`, on a column a read DTO later exposes) is not required to be followed to the response that eventually serves it: a write and a subsequent request separate the two, so no static check connects them

**These are not exemptions.** The rule governs those forms exactly as it
governs any other — a checker is simply not required to find them, so
review is the control there. The list only shrinks: closing one means
adding the corpus case that contracts it.

## Enforcement

- Checked while the app runs? No — this is a property of the written source only; the build-time check is the control, by recorded decision.
- `build-time`: `terp.arch` — `check_no_exception_text_in_responses`
