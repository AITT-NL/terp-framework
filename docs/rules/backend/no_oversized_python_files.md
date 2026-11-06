# `backend/no_oversized_python_files`

**No source file grows past the line-count cap**

> Generated from the catalog by `tools/generate_rule_docs.py` — do not
> edit by hand; the parity test holds this page to
> `packages/backend/arch/src/terp/arch/catalog/backend/no_oversized_python_files.json`.

## Why this rule exists

A file that keeps growing stops being reviewable: it hides more than one responsibility, is harder to reason about in one sitting, and is exactly what an automated author tends to produce when it appends to an existing file instead of factoring the work into a new one. Capping the line count of every hand-authored source file forces the cohesive-file discipline the rest of the layout assumes — a responsibility that outgrows its file is split into its own file, not piled onto the current one. Generated and machine-owned trees (dependency caches, database migration history, the test suite) are out of scope: their size is not an authoring decision the cap should second-guess.

## How Terp realises this

Every scanned *.py file must stay at or under 500 physical lines; generated/vendored caches, the migration history and the test tree are excluded from the scan. Split a file that grows past the cap into smaller, cohesive modules (extract helpers or sub-services into their own files).

## If you really need an exception

Add a justified marker on (or immediately above) the line, and record it
in your app's escape-hatch budget:

```
# arch-allow-no-oversized-python-files: <reason>
```

An unjustified marker is itself a violation, and marker counts must
exactly match the checked-in budget (which can only shrink).

## Enforcement

- Checked while the app runs? No — this is a property of the written source only; the build-time check is the control, by recorded decision.
- `build-time`: `terp.arch` — `check_no_oversized_python_files`
