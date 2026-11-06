# `backend/declared_read_controls_are_forwarded`

**A declared filter or sort must be reachable from an endpoint that forwards it**

> Generated from the catalog by `tools/generate_rule_docs.py` — do not
> edit by hand; the parity test holds this page to
> `packages/backend/arch/src/terp/arch/catalog/backend/declared_read_controls_are_forwarded.json`.

## Why this rule exists

A read layer declares which fields a caller may narrow or order by, and an endpoint reaches those declarations by forwarding the caller's request into the read. A declaration no endpoint forwards is inert: the capability is described in the source, absent from the API, and silent about the difference. The failure is worse than an unimplemented feature because it presents as an implemented one — a client generated from the contract offers no way to sort, a screen built against it ships with every column's sorting disabled, and nothing in the read layer is wrong. Each declared filter and sort must therefore be reachable: a module that declares one and forwards none is rejected on the source, rather than discovered by a user who cannot order a list the code says is orderable.

## How Terp realises this

Judged per module and per control kind by PRESENCE, never by name: a module that declares a filter is required to forward a filters mapping somewhere within itself, and a module that declares a sort is required to forward a sort. The keyword is visible in the source even when the value handed to it is computed, which is what makes presence decidable where a per-name comparison is not — a mapping built elsewhere hides its names but not its existence, so requiring a specific declared name to appear at a call site would reject correct code. The pairing of one declaration to one endpoint is not statically knowable either, which is why the unit is the module that owns both.

## If you really need an exception

Add a justified marker on (or immediately above) the line, and record it
in your app's escape-hatch budget:

```
# arch-allow-declared-read-controls-are-forwarded: <reason>
```

An unjustified marker is itself a violation, and marker counts must
exactly match the checked-in budget (which can only shrink).

## Enforcement

- Checked while the app runs? No — this is a property of the written source only; the build-time check is the control, by recorded decision.
- `build-time`: `terp.arch` — `check_declared_read_controls_are_forwarded`
