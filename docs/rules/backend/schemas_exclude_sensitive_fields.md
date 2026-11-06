# `backend/schemas_exclude_sensitive_fields`

**A read / response DTO never exposes a credential-shaped field**

> Generated from the catalog by `tools/generate_rule_docs.py` — do not
> edit by hand; the parity test holds this page to
> `packages/backend/arch/src/terp/arch/catalog/backend/schemas_exclude_sensitive_fields.json`.

## Why this rule exists

Routes serialize a response DTO out of the boundary, so a field whose name reads like a secret — a password, a password hash, or a *secret / *api_key / *token suffix — would leak the credential to every caller. A response DTO is a schema in the response role: a read/response base schema or any class wired as a route's declared response type (so an input DTO mistakenly reused as a response is caught), excluding the inputs that are only ever request bodies (a client supplies a password) and table models (a table may store the hash). Plain helper classes are not policed. This guards the gap response_model_not_table_model leaves: a hand-rolled read DTO that copies the stored hash. (Version counters are integers, not secrets.)

## How Terp realises this

BaseSchema / BaseUpdateSchema models and response_model= classes are scanned for password / hashed_password / *secret / *api_key / *token field names; request-body-only inputs and table=True models are excluded.

## If you really need an exception

Add a justified marker on (or immediately above) the line, and record it
in your app's escape-hatch budget:

```
# arch-allow-schemas-exclude-sensitive-fields: <reason>
```

An unjustified marker is itself a violation, and marker counts must
exactly match the checked-in budget (which can only shrink).

## Enforcement

- Checked while the app runs? Yes — the framework also enforces this while the app runs (fail closed).
- `build-time`: `terp.arch` — `check_schemas_exclude_sensitive_fields`
- `black-box`: `@terpjs/conformance` — `standard: responses never expose credential-shaped fields`
- `runtime`: `terp.core` — `validate_schemas_exclude_sensitive_fields`
