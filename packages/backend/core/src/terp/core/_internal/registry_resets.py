"""Test-only resets for the two import-time authorization registries (ADR 0137).

:func:`~terp.core.scoping.register_scope_predicate` and
:func:`~terp.core.object_authz.register_object_authz_predicate` are filled at **import**
by whichever capability owns the trait — the tenancy capability registers the tenant
filter the moment a model composes ``TenantScopedMixin`` — and are meant to stay filled
for the life of the process. They are not per-app runtime seams, so they are deliberately
absent from :mod:`terp.core.runtime`'s registry (its docstring names them as the
counter-example) and nothing resets them between apps.

A test that registers its own predicate still has to clean up after itself, so a reset
has to exist. What it must not be is *reachable from module code*. Both registries hold
controls whose failure mode is silence:

* clearing the scope predicates removes the tenant filter, so every scoped read starts
  returning rows from every tenant — no exception, no log line, just more rows;
* clearing the object-authz predicates removes every registered per-row write policy, so
  writes that were refused start succeeding.

One line at import time in any module would do either, and every architecture rule would
still pass. That is the same hazard ``allow_session_writes`` poses to the audited write
chokepoint, and it is answered the same way: the callable lives under ``terp.core._internal``,
where the ``no_internal_imports`` rule refuses to let a module reach it, and the test that
needs it imports it from here in as many words.

The kernel's own suite is the only caller.
"""

from __future__ import annotations

from terp.core.object_authz import _reset_object_authz_predicates
from terp.core.scoping import _reset_scope_predicates

#: Clear every registered row-scope predicate (soft-delete stays — it is inlined in
#: ``apply_row_scope``, not registered).
reset_scope_predicates = _reset_scope_predicates

#: Clear every registered object-authz predicate (the built-in owner check stays — it is
#: inlined in ``apply_object_authz``, not registered).
reset_object_authz_predicates = _reset_object_authz_predicates

__all__ = ["reset_object_authz_predicates", "reset_scope_predicates"]
