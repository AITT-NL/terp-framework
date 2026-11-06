# `backend/table_ownership_is_not_split`

**The package whose models own a table is the package whose history creates it**

> Generated from the catalog by `tools/generate_rule_docs.py` — do not
> edit by hand; the parity test holds this page to
> `packages/backend/arch/src/terp/arch/catalog/backend/table_ownership_is_not_split.json`.

## Why this rule exists

Moving a model between packages splits table ownership from history ownership, and nothing visible happens: the losing package no longer owns the table so its scoped autogenerate cannot propose a drop, and the gaining package diffs against a database where the table already exists so it proposes no create. No DDL is emitted, every existing database keeps upgrading, and the build stays green. The damage lands later: the next ordinary schema change to that model is authored into the gaining package's independent history, which — absent a foreign key between the two packages — a fresh install may run before the history that creates the table, failing with 'no such table'. Only fresh installs break (a new environment, a new developer, a restore, a disaster-recovery rebuild), months after the causing commit, and the blame falls on an innocent add_column. A table is therefore created by exactly the package whose models declare it; moving a table between packages uses expand/contract (new table, copy the rows, retire the old one in a later release under a reviewed destructive-migration marker).

## How Terp realises this

For each migration tree, the tables its models own (the mapped classes under its import path) are compared against the tables that other trees' revision files literally create with create_table('<name>') inside upgrade(). A table owned by one package and created by another is a violation. A table owned but created by no package is not (that is the normal state before `terp migrate make` authors the revision), and neither is a table created under one name and later renamed (no literal create under the current name), so the check only fires on an exact, statically provable foreign creator. Enforced at authoring time (terp migrate make) and in the build-time drift guard (assert_migrations_match_models). The opt-out lives in the owning package's models module, for a move that has already shipped and whose expand/contract is planned for a later release.

## If you really need an exception

Add a justified marker on (or immediately above) the line, and record it
in your app's escape-hatch budget:

```
# arch-allow-table-ownership-is-not-split: <reason>
```

An unjustified marker is itself a violation, and marker counts must
exactly match the checked-in budget (which can only shrink).

## Enforcement

- Checked while the app runs? No — this is a property of the written source only; the build-time check is the control, by recorded decision.
- `build-time`: `terp.arch` — `check_table_ownership_is_not_split`
- `build-time`: `terp.migrations` — `assert_no_split_table_ownership`
