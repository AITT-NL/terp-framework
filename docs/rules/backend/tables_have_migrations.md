# `backend/tables_have_migrations`

**Every app module that defines a table model ships a packaged migration history**

> Generated from the catalog by `tools/generate_rule_docs.py` — do not
> edit by hand; the parity test holds this page to
> `packages/backend/arch/src/terp/arch/catalog/backend/tables_have_migrations.json`.

## Why this rule exists

A deployed Terp app builds its schema from packaged migrations, never from dev-time schema auto-creation — so a module that declares a table model but ships no migration revision would deploy with that table missing, and the first request would fail on a nonexistent table. This rule fails the build first, and the running system's migration guard refuses the same violation at boot (the two halves of the migration control). Generate and commit the module's migration revision.

## How Terp realises this

terp migrate make <name> generates the module's migrations/versions/ revision; assert_migrations_current is the production boot guard (it runs assert_no_missing_histories, so a table-owning package without any history refuses to boot), create_all the refused dev shortcut.

## If you really need an exception

Add a justified marker on (or immediately above) the line, and record it
in your app's escape-hatch budget:

```
# arch-allow-tables-have-migrations: <reason>
```

An unjustified marker is itself a violation, and marker counts must
exactly match the checked-in budget (which can only shrink).

## Enforcement

- Checked while the app runs? Yes — the framework also enforces this while the app runs (fail closed).
- `build-time`: `terp.arch` — `check_tables_have_migrations`
- `runtime`: `terp.migrations` — `assert_no_missing_histories`
