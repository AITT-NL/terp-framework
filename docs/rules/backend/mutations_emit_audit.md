# `backend/mutations_emit_audit`

**Modules never write to the session directly; mutations go through the audited chokepoint**

> Generated from the catalog by `tools/generate_rule_docs.py` — do not
> edit by hand; the parity test holds this page to
> `packages/backend/arch/src/terp/arch/catalog/backend/mutations_emit_audit.json`.

## Why this rule exists

Audit is auto-emitted from the single audited write chokepoint of the model's service, inside the write's transaction. A module that calls the session's persistence methods itself — or smuggles a write through a session-executed data-modification statement — bypasses that chokepoint and would persist a mutation with no audit trail. The receiver is recognised by the conventional session names and by any parameter annotated with the session type (so renaming the variable does not evade the rule). Routing every write through the service keeps the trail structural — a method call on the model's service is fine; a raw session write is not.

## How Terp realises this

BaseService.create/update/delete (_save/_remove) is the audited chokepoint; session.add/delete/merge/commit/flush, bulk_* helpers, and DML via session.execute/exec are refused, on conventional names and Session/SessionDep-annotated parameters alike.

## If you really need an exception

Add a justified marker on (or immediately above) the line, and record it
in your app's escape-hatch budget:

```
# arch-allow-mutations-emit-audit: <reason>
```

An unjustified marker is itself a violation, and marker counts must
exactly match the checked-in budget (which can only shrink).

## Enforcement

- Checked while the app runs? Yes — the framework also enforces this while the app runs (fail closed).
- `build-time`: `terp.arch` — `check_mutations_emit_audit`
- `runtime`: `terp.core` — `WriteGuardedSession`
