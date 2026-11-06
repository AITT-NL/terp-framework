# `backend/no_todo_fixme`

**No placeholder comments for deferred work**

> Generated from the catalog by `tools/generate_rule_docs.py` — do not
> edit by hand; the parity test holds this page to
> `packages/backend/arch/src/terp/arch/catalog/backend/no_todo_fixme.json`.

## Why this rule exists

A TODO, FIXME, HACK, or XXX comment marks unfinished work that ships anyway and is almost never revisited, so the gap it names silently becomes permanent. Finish the behaviour or delete the dead branch — do not leave a note promising a fix that will not come.

## How Terp realises this

The markers TODO, FIXME, HACK, and XXX are refused when they appear in a real comment token; matching ignores identical text inside strings or docstrings.

## If you really need an exception

Add a justified marker on (or immediately above) the line, and record it
in your app's escape-hatch budget:

```
# arch-allow-no-todo-fixme: <reason>
```

An unjustified marker is itself a violation, and marker counts must
exactly match the checked-in budget (which can only shrink).

## Enforcement

- Checked while the app runs? No — this is a property of the written source only; the build-time check is the control, by recorded decision.
- `build-time`: `terp.arch` — `check_no_todo_fixme`
