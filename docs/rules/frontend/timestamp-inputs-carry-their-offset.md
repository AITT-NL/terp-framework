# `frontend/timestamp-inputs-carry-their-offset`

**A date and time a form sends carries its UTC offset**

> Generated from the catalog by `tools/generate_rule_docs.py` — do not
> edit by hand; the parity test holds this page to
> `packages/frontend/eslint-boundaries/catalog/frontend/timestamp-inputs-carry-their-offset.json`.

## Why this rule exists

A browser's local date-and-time control hands the page a wall time with no UTC offset. That names no instant: ten in the morning is a different moment in every zone. Sent as it is, the API refuses it for a timestamp, and a server that read it as UTC instead would store a person in any other zone off by their offset. So a form never sends the control's own value: it shows the instant in a zone and sends what is picked as the instant it names, with that zone's offset.

## How Terp realises this

Any JSX `type` attribute whose value is `datetime-local` is refused, on `Input`, a raw `input` or a wrapper that passes it on, in any letter case (the browser reads the type case-insensitively), as a string, an expression or a plain template. The reference stack ships `DateTimeInput` from `@terpjs/react-core`: it shows an RFC 3339 instant as wall time in a zone, the browser's own or one it is given, and sends what is picked as an RFC 3339 instant with that zone's offset; a wall time the clocks skip moves past the gap, and one they repeat is the earlier. A calendar day (`type="date"`) and a time of day (`type="time"`) name no instant and are not this rule's concern. The runtime half is the server's: a BaseSchema refuses timestamp text without an offset with a 422 (ADR 0206). A field that truly holds a wall time with a named zone, read as text by the API, keeps the control with the marker and its reason.

## If you really need an exception

Add a justified marker on (or immediately above) the line, and record it
in your app's escape-hatch budget:

```
// terp-allow-timestamp-inputs-carry-their-offset: <reason>
```

An unjustified marker is itself a violation, and marker counts must
exactly match the checked-in budget (which can only shrink).

## What the check is not required to catch

A check precise enough to have no false positives has limits. This
rule's limits are recorded as data (its corpus's `RESIDUALS.json`), so
where detection ends is a statement rather than a guess:

- a type reached through a spread or a variable (`type={kind}`), and an input whose type is set through the DOM rather than in JSX, are not resolved to the local date-and-time control

**These are not exemptions.** The rule governs those forms exactly as it
governs any other — a checker is simply not required to find them, so
review is the control there. The list only shrinks: closing one means
adding the corpus case that contracts it.

## Enforcement

- Checked while the app runs? Yes — the framework also enforces this while the app runs (fail closed).
- `build-time`: `@terpjs/eslint-boundaries` — `BOUNDARY_SPEC.restrictLocalDateTimeInput`
- `runtime`: `terp.core` — `refuse_timestamp_text_without_offset`
