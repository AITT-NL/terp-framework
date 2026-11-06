# `backend/no_dynamic_sql`

**Raw SQL text in app modules must be a static literal, never dynamically built**

> Generated from the catalog by `tools/generate_rule_docs.py` — do not
> edit by hand; the parity test holds this page to
> `packages/backend/arch/src/terp/arch/catalog/backend/no_dynamic_sql.json`.

## Why this rule exists

A raw-SQL construct built dynamically — through interpolation, concatenation, format calls, or a variable — is not statically reviewable and is easy to turn into SQL injection. Keep SQL as a literal and pass data through bound parameters / the query builder's typed expressions instead. As a security rule this also scans test and migration files inside a module — they are importable code, so they are application surface too.

## How Terp realises this

text(...) / sqlalchemy.text(...) with an f-string, concatenation, .format, % formatting, or a variable is refused; SQLAlchemy bound parameters / ORM expressions are the compliant path.

## If you really need an exception

Add a justified marker on (or immediately above) the line, and record it
in your app's escape-hatch budget:

```
# arch-allow-no-dynamic-sql: <reason>
```

An unjustified marker is itself a violation, and marker counts must
exactly match the checked-in budget (which can only shrink).

## What the check is not required to catch

A check precise enough to have no false positives has limits. This
rule's limits are recorded as data (its corpus's `RESIDUALS.json`), so
where detection ends is a statement rather than a guess:

- SQL built as a string and handed to a raw DB-API cursor (`cursor.execute(f"SELECT ... FROM {table}")`) is not required to be caught: the check matches the reference stack's `text(...)` construct, and a package that does not model the schema it talks to never writes one. The shape is not ungoverned — the reference stack delegates it to a stock analyzer's SQL-string-construction rule, in the platform repository and in every generated project as a blocking step — but that lane is outside the catalog, so the limit is recorded here rather than implied
- an alias-renamed symbol import (`from sqlalchemy import text as sql_text`) is not required to be resolved to `text`

**These are not exemptions.** The rule governs those forms exactly as it
governs any other — a checker is simply not required to find them, so
review is the control there. The list only shrinks: closing one means
adding the corpus case that contracts it.

## Enforcement

- Checked while the app runs? No — this is a property of the written source only; the build-time check is the control, by recorded decision.
- `build-time`: `terp.arch` — `check_no_dynamic_sql`
