# 0137 — A reset that disables a control is not public API

- **Status:** Accepted and implemented. `reset_scope_predicates` and
  `reset_object_authz_predicates` are private in their own modules and reachable only
  through `terp.core._internal.registry_resets`, where the `no_internal_imports` rule
  refuses a module import. Held by `tests/architecture/test_scope_predicate_registry.py`
  and `tests/architecture/test_object_authz.py`.
- **Date:** 2026-09-15
- **Relates:** [ADR 0017](0017-row-scope-is-a-non-droppable-registry.md) (the row-scope
  registry this protects), [ADR 0029](0029-object-level-write-authorization.md) (the
  object-authz registry), [ADR 0015](0015-the-audited-write-chokepoint.md)
  (`allow_session_writes`, the precedent this follows exactly)

## Context

Two registries hold authorization controls, and both are filled at **import** by
whichever capability owns the trait — the tenancy capability registers the tenant filter
the moment a model composes `TenantScopedMixin`. Neither is a per-app runtime seam, so
neither appears in `terp.core.runtime`'s registry (its own docstring names them as the
counter-example) and nothing resets them between apps.

A test that registers its own predicate still has to clean up, so a reset has to exist.
Both existed, in `terp.core.scoping` and `terp.core.object_authz`, public and in
`__all__`.

What that meant is that one line, at import time, in any module of any application:

```python
from terp.core.scoping import reset_scope_predicates
reset_scope_predicates()
```

removes the tenant filter and every other registered row predicate for the whole
process. No exception. Nothing in the log. Reads simply start returning rows they used
to hide. The object-authz twin is the same shape on the write side: every registered
per-row policy gone, and writes that were refused start succeeding.

Neither is reachable by accident in the sense of a typo, and neither is an attack — the
caller is the application's own author. The realistic path is duller and likelier: a
test-isolation pattern copied out of a suite into a conftest that ships, a capability
author calling it at import "to start clean", a fixture that migrates into module code
during a refactor. Every architecture rule passes afterwards, and the suite goes green,
because the app's own tests set up the tenant context they expect.

The framework already had the right answer for exactly this hazard and had applied it
once. `allow_session_writes` would let any module wave itself past the audited write
chokepoint, so it lives under `terp.core._internal`, where the `no_internal_imports`
rule refuses the import — the module docstring says so in as many words: *"so a module
cannot import `allow_session_writes` to wave itself past the guard."* The scope and
object-authz resets pose the same kind of hazard to the other two controls and had none
of the protection.

## Decision

**The two resets move behind `_internal`.** Each module keeps its implementation as a
private `_reset_*` and drops the public name from `__all__`;
`terp.core._internal.registry_resets` re-exports both under the spelling tests use. No
new rule was needed — `no_internal_imports` already covers anything under that package,
which is the point of putting them there rather than inventing a third mechanism.

**The secrets call-site reset stays public**, and the difference is worth stating
because it looks like the same thing. `reset_decrypt_call_site_runtime` is a registered
**per-app runtime seam**, held to the `reset_<name>_runtime` naming convention that
`test_runtime_seams.py` reads back as an expected set, and isolated generically by
`terp.core.testing`. More importantly its failure direction is the opposite: with no
registered call site every `decrypt_config` raises, so resetting it makes decryption
stop working rather than start working. Re-opening the chokepoint takes a second,
deliberate `register_decrypt_call_site` call that is plainly visible in a diff.

## Consequences

An application that was calling either reset — only this repository's own suite was —
updates one import line. The functions are unchanged; the spelling of where they live
is what moved.

The distinction this draws is the one to carry forward when a third registry appears:
**a reset whose effect is to make a control stop refusing belongs under `_internal`; a
reset whose effect is to make something fail closed does not.** The naming convention
(`reset_<name>_runtime`) already marks the second kind, and now the package boundary
marks the first.
