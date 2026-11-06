# `backend/input_str_fields_have_max_length`

**Every string a client can supply caps its length**

> Generated from the catalog by `tools/generate_rule_docs.py` — do not
> edit by hand; the parity test holds this page to
> `packages/backend/arch/src/terp/arch/catalog/backend/input_str_fields_have_max_length.json`.

## Why this rule exists

A field is client-supplied when it lives on a table model, on a *Create / *Update schema, or on any class used as a request body (a route handler's body parameter, or a generated CRUD router's create/update schema) — so an input DTO named off-convention (LoginRequest, UserProvision) is capped too, not only the *Create / *Update ones. Plain strings, optional strings, and sequence containers of strings all count; an uncapped one is an unbounded-input (DoS / abuse) hole.

## How Terp realises this

str / str | None / list[str] fields declare max_length; build_crud_router create/update schemas are scanned too.

## If you really need an exception

Add a justified marker on (or immediately above) the line, and record it
in your app's escape-hatch budget:

```
# arch-allow-input-str-fields-have-max-length: <reason>
```

An unjustified marker is itself a violation, and marker counts must
exactly match the checked-in budget (which can only shrink).

## Enforcement

- Checked while the app runs? No — this is a property of the written source only; the build-time check is the control, by recorded decision.
- `build-time`: `terp.arch` — `check_input_str_fields_have_max_length`
