# `backend/offset_queries_declare_ordering`

**An offset-paginated query must declare an explicit ordering**

> Generated from the catalog by `tools/generate_rule_docs.py` — do not
> edit by hand; the parity test holds this page to
> `packages/backend/arch/src/terp/arch/catalog/backend/offset_queries_declare_ordering.json`.

## Why this rule exists

Row order without an explicit ordering clause is undefined, so paging a query by a numeric offset over an unordered result can silently skip or repeat rows between pages. A query that skips a number of rows must also declare a deterministic ordering so the page sequence is stable and every row is seen exactly once.

## How Terp realises this

A function that calls .offset(...) but no .order_by(...) is flagged at the offset call; add an explicit ordering, or page through the framework's ordered pagination helper.

## If you really need an exception

Add a justified marker on (or immediately above) the line, and record it
in your app's escape-hatch budget:

```
# arch-allow-offset-queries-declare-ordering: <reason>
```

An unjustified marker is itself a violation, and marker counts must
exactly match the checked-in budget (which can only shrink).

## Enforcement

- Checked while the app runs? No — this is a property of the written source only; the build-time check is the control, by recorded decision.
- `build-time`: `terp.arch` — `check_offset_queries_declare_ordering`
