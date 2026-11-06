# `backend/safe_methods_are_read_only`

**A handler reachable via a safe HTTP method must not mutate**

> Generated from the catalog by `tools/generate_rule_docs.py` — do not
> edit by hand; the parity test holds this page to
> `packages/backend/arch/src/terp/arch/catalog/backend/safe_methods_are_read_only.json`.

## Why this rule exists

The deny-by-default guard derives the required role tier from the HTTP method: a safe method (GET / HEAD / OPTIONS) is authorized against the policy's read requirement, a mutating one against the write requirement. So a handler reachable through a safe method that calls a mutating service method performs a write a read-tier caller cleared — a privilege-tier escape (a viewer triggering an editor/admin write via a read request). This holds for a mixed-method route too: the safe-method invocation runs at the read tier, so a handler that always mutates is flagged (split it, or branch on the method behind a mutating route). Both decorator and imperative route registration are checked. Put the write behind a mutating method so it is authorized at the write tier. The runtime half marks a safe-method request read-only, so the write chokepoint refuses the write.

## How Terp realises this

Mutating BaseService calls (create/update/delete/_save/_remove) in safe-method handlers are flagged; create_app binds safe-method requests read-only (build_read_only_request_binder).

## If you really need an exception

Add a justified marker on (or immediately above) the line, and record it
in your app's escape-hatch budget:

```
# arch-allow-safe-methods-are-read-only: <reason>
```

An unjustified marker is itself a violation, and marker counts must
exactly match the checked-in budget (which can only shrink).

## Enforcement

- Checked while the app runs? Yes — the framework also enforces this while the app runs (fail closed).
- `build-time`: `terp.arch` — `check_safe_methods_are_read_only`
- `runtime`: `terp.core` — `build_read_only_request_binder`
- `black-box`: `@terpjs/conformance` — `standard: safe methods observably mutate nothing`
