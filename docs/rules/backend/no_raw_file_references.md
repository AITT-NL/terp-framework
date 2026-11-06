# `backend/no_raw_file_references`

**A table model's file-pointer column is a declared file reference, never a bare id column**

> Generated from the catalog by `tools/generate_rule_docs.py` — do not
> edit by hand; the parity test holds this page to
> `packages/backend/arch/src/terp/arch/catalog/backend/no_raw_file_references.json`.

## Why this rule exists

A stored pointer to a file object carries authorization semantics: the files capability serves delegated reads only through a declared reference, failing closed on an undeclared column. A bare id-typed file-pointer column on a table model is an undeclared reference: nothing ties the file's access to the referencing row, which is the classic object-level (BOLA) drift. Declare the column with the files capability's reference type so the pointer is greppable, verified at runtime, and served through the module's own already-authorized row — never hand-rolled. A non-table schema (a read DTO exposing the pointer) is fine and not policed; only the persisted column is.

## How Terp realises this

FileRef(...) from terp-cap-files declares the column; FileService.load_for fail-closes on an undeclared *file_id column (ADR 0057).

## If you really need an exception

Add a justified marker on (or immediately above) the line, and record it
in your app's escape-hatch budget:

```
# arch-allow-no-raw-file-references: <reason>
```

An unjustified marker is itself a violation, and marker counts must
exactly match the checked-in budget (which can only shrink).

## Enforcement

- Checked while the app runs? Yes — the framework also enforces this while the app runs (fail closed).
- `build-time`: `terp.arch` — `check_no_raw_file_references`
- `runtime`: `terp.capabilities.files` — `load_for`
