"""The Terp secure-by-default fitness rules (design §5.10), shipped as a dependency.

Each rule is a pure function that scans a client app's source tree and returns a
list of :class:`ArchViolation`. They are the **build-time layer** of Terp's
two-layer enforcement: a rule whose invariant the running system can observe
pairs with a fail-closed runtime control in ``terp.core`` (or a capability),
and which rules those are is recorded per rule in the Terp Standard catalog
(``runtime.applicability``, ADR 0084) -- a source-form rule is build-time-only
by recorded decision, with its rationale in its catalog entry. Clients *run*
these rules against their own ``app/`` but cannot edit them -- the harness
travels as a versioned package.

Run them all with :func:`assert_app_clean`::

    from terp.arch import assert_app_clean

    def test_architecture() -> None:
        assert_app_clean("app")          # the app package on sys.path

The rules are deliberately precise (not heuristic) so a green run is meaningful
and a red run names an exact file/line and a fixable reason.

This package is the **facade**: the rules live in themed modules (``imports`` /
``authz`` / ``http`` / ``persistence`` / ``events`` / ``traits`` / ``budget``)
over the shared ``_support`` machinery, and are gathered into :data:`_ALL_RULES`
and the :func:`check_app` / :func:`assert_app_clean` orchestrators here. The
public surface (and the ``terp.arch.rules`` import path) is unchanged.
"""

from __future__ import annotations

import pathlib
from collections.abc import Callable

from terp.arch.rules._support import (
    ArchViolation,
    _apply_suppressions,
    _scan_allow_markers,
)
from terp.arch.rules.authz import (
    check_modules_declare_policy,
    check_mutations_require_write_role,
    check_no_adhoc_permission_literals,
    check_policy_refs_resolve,
    check_public_modules_are_read_only,
)
from terp.arch.rules.budget import check_escape_hatch_budget
from terp.arch.rules.datetimes import check_no_naive_datetime
from terp.arch.rules.events import check_events_reference_catalog
from terp.arch.rules.http import (
    check_list_routes_paginate,
    check_no_adhoc_logging_config,
    check_no_adhoc_middleware,
    check_no_app_instantiation,
    check_no_dependency_overrides,
    check_no_raw_app_routes,
    check_response_model_not_table_model,
    check_routes_declare_response_model,
    check_safe_methods_are_read_only,
)
from terp.arch.rules.imports import (
    check_no_adhoc_background_runtime,
    check_no_cross_module_imports,
    check_no_internal_imports,
    check_no_raw_outbound_http,
    check_session_imported_from_sqlmodel,
)
from terp.arch.rules.migrations import check_no_destructive_migrations
from terp.arch.rules.jobs import check_jobs_reference_catalog
from terp.arch.rules.occ import (
    check_no_manual_version_assignment,
    check_update_schemas_inherit_base_update_schema,
)
from terp.arch.rules.persistence import (
    check_input_schemas_exclude_managed_columns,
    check_input_str_fields_have_max_length,
    check_mutations_emit_audit,
    check_no_manual_table_schema,
    check_no_dynamic_sql,
    check_no_raw_connection_access,
    check_no_raw_session_construction,
    check_no_unique_columns_on_soft_delete_models,
    check_schemas_exclude_sensitive_fields,
    check_table_models_use_base_table,
    check_tables_have_migrations,
)
from terp.arch.rules.secrets import (
    check_no_adhoc_config_decrypt,
    check_no_hardcoded_credentials,
)
from terp.arch.rules.structure import check_canonical_module_shape
from terp.arch.rules.traits import (
    check_base_query_not_overridden,
    check_no_manual_actor_stamping,
    check_no_manual_ownership_checks,
    check_no_manual_scope_filtering,
    check_no_raw_file_references,
    check_reads_use_base_query,
    check_tenant_scoped_models_use_scoped_service,
)

# Every rule's fix recipe: the ``terp guide`` topic that teaches the compliant
# pattern the rule enforces. Keyed by the bare rule name (no ``check_`` prefix) so
# a violation can carry its own remedy ("fix recipe: terp guide <topic>") instead
# of relying on the author remembering to look one up. Completeness (every rule in
# :data:`_ALL_RULES` has a topic, and every topic is a real ``terp guide`` topic)
# is locked by ``test_arch_harness`` / ``test_docs_parity`` meta-tests.
GUIDE_TOPIC_BY_RULE: dict[str, str] = {
    "no_internal_imports": "module",
    "no_cross_module_imports": "module",
    "no_raw_outbound_http": "capability",
    "no_adhoc_background_runtime": "jobs",
    "modules_declare_policy": "policy",
    "mutations_require_write_role": "policy",
    "public_modules_are_read_only": "policy",
    "no_adhoc_permission_literals": "policy",
    "policy_refs_resolve": "policy",
    "routes_declare_response_model": "module",
    "response_model_not_table_model": "module",
    "schemas_exclude_sensitive_fields": "module",
    "list_routes_paginate": "service",
    "safe_methods_are_read_only": "module",
    "no_raw_session_construction": "service",
    "no_raw_connection_access": "service",
    "no_dynamic_sql": "service",
    "no_naive_datetime": "service",
    "mutations_emit_audit": "service",
    "events_reference_catalog": "events",
    "jobs_reference_catalog": "jobs",
    "no_adhoc_config_decrypt": "capability",
    "no_hardcoded_credentials": "capability",
    "input_str_fields_have_max_length": "module",
    "input_schemas_exclude_managed_columns": "module",
    "tenant_scoped_models_use_scoped_service": "tenancy",
    "base_query_not_overridden": "service",
    "reads_use_base_query": "service",
    "no_manual_scope_filtering": "tenancy",
    "no_manual_actor_stamping": "service",
    "no_manual_ownership_checks": "ownership",
    "no_manual_version_assignment": "service",
    "update_schemas_inherit_base_update_schema": "module",
    "no_raw_file_references": "files",
    "table_models_use_base_table": "module",
    "tables_have_migrations": "migrations",
    "no_manual_table_schema": "migrations",
    "no_destructive_migrations": "migrations",
    "no_unique_columns_on_soft_delete_models": "module",
    "canonical_module_shape": "module",
    "session_imported_from_sqlmodel": "service",
    "no_app_instantiation": "capability",
    "no_raw_app_routes": "capability",
    "no_dependency_overrides": "capability",
    "no_adhoc_middleware": "capability",
    "no_adhoc_logging_config": "capability",
    "escape_hatch_budget": "rules",
    "ungoverned_escape_hatch": "rules",
}


def guide_topic_for(rule: str) -> str:
    """The ``terp guide`` topic teaching the fix for *rule* (``rules`` if unmapped).

    The unmapped fallback is deliberate: a violation renderer must never crash on a
    rule the mapping missed — the completeness meta-test catches the gap at build
    time, and ``rules`` (the generated every-rule topic) is always a safe pointer.
    """
    return GUIDE_TOPIC_BY_RULE.get(rule, "rules")


_ALL_RULES: tuple[Callable[..., list[ArchViolation]], ...] = (
    check_no_internal_imports,
    check_no_cross_module_imports,
    check_no_raw_outbound_http,
    check_no_adhoc_background_runtime,
    check_modules_declare_policy,
    check_mutations_require_write_role,
    check_public_modules_are_read_only,
    check_no_adhoc_permission_literals,
    check_policy_refs_resolve,
    check_routes_declare_response_model,
    check_response_model_not_table_model,
    check_schemas_exclude_sensitive_fields,
    check_list_routes_paginate,
    check_safe_methods_are_read_only,
    check_no_raw_session_construction,
    check_no_raw_connection_access,
    check_no_dynamic_sql,
    check_no_naive_datetime,
    check_mutations_emit_audit,
    check_events_reference_catalog,
    check_jobs_reference_catalog,
    check_no_adhoc_config_decrypt,
    check_no_hardcoded_credentials,
    check_input_str_fields_have_max_length,
    check_input_schemas_exclude_managed_columns,
    check_tenant_scoped_models_use_scoped_service,
    check_base_query_not_overridden,
    check_reads_use_base_query,
    check_no_manual_scope_filtering,
    check_no_manual_actor_stamping,
    check_no_manual_ownership_checks,
    check_no_manual_version_assignment,
    check_update_schemas_inherit_base_update_schema,
    check_no_raw_file_references,
    check_table_models_use_base_table,
    check_tables_have_migrations,
    check_no_manual_table_schema,
    check_no_destructive_migrations,
    check_no_unique_columns_on_soft_delete_models,
    check_canonical_module_shape,
    check_session_imported_from_sqlmodel,
    check_no_app_instantiation,
    check_no_raw_app_routes,
    check_no_dependency_overrides,
    check_no_adhoc_middleware,
    check_no_adhoc_logging_config,
)


def check_app(
    app_root: str | pathlib.Path,
    *,
    package: str = "app",
    budget_path: str | pathlib.Path | None = None,
) -> list[ArchViolation]:
    """Run every rule against *app_root* and return all effective violations, sorted.

    A justified ``# arch-allow-<rule>: <reason>`` comment on a violation's line
    suppresses it (an unjustified one is reported, never silently honoured). Pass
    *budget_path* to also enforce the escape-hatch budget ratchet over those
    markers (design §8).
    """
    root = pathlib.Path(app_root)
    if not root.is_dir():
        raise NotADirectoryError(f"app root not found: {root}")
    raw: list[ArchViolation] = []
    for rule in _ALL_RULES:
        raw.extend(rule(root, package=package))
    violations = _apply_suppressions(raw, _scan_allow_markers(root))
    if budget_path is not None:
        violations.extend(check_escape_hatch_budget(root, budget_path=budget_path, package=package))
    return sorted(violations, key=lambda violation: (violation.path, violation.line, violation.rule))


def assert_app_clean(
    app_root: str | pathlib.Path,
    *,
    package: str = "app",
    budget_path: str | pathlib.Path | None = None,
) -> None:
    """Raise ``AssertionError`` listing every architecture violation in *app_root*.

    Governed opt-out: if the app uses any ``# arch-allow-*`` marker but no
    *budget_path* is supplied, this fails closed — an opt-out must be governed by a
    checked-in escape-hatch budget, never used silently.
    """
    root = pathlib.Path(app_root)
    if budget_path is None and _scan_allow_markers(root):
        raise AssertionError(
            "terp.arch found '# arch-allow-*' opt-out marker(s) but no budget_path was "
            "supplied; govern opt-outs with a checked-in escape-hatch budget — call "
            "assert_app_clean(app, budget_path='escape-hatch-budget.json')"
        )
    violations = check_app(root, package=package, budget_path=budget_path)
    if violations:
        listing = "\n".join(
            f"  - {violation}  (fix recipe: terp guide {violation.rule})"
            for violation in violations
        )
        raise AssertionError(
            f"terp.arch found {len(violations)} architecture violation(s):\n{listing}"
        )


def ungoverned_marker_violations(
    app_root: str | pathlib.Path, *, package: str = "app"
) -> list[ArchViolation]:
    """The fail-closed ungoverned-opt-out condition, as structured violations.

    :func:`assert_app_clean` refuses (with a plain ``AssertionError``) to honour any
    ``# arch-allow-*`` marker when no escape-hatch budget governs it. This is the
    same condition projected as :class:`ArchViolation` values (rule
    ``ungoverned_escape_hatch``, one per marker line), so a structured renderer
    (``terp check --format json``) reports it in-band instead of crashing.
    """
    root = pathlib.Path(app_root)
    violations = [
        ArchViolation(
            rule="ungoverned_escape_hatch",
            path=path,
            line=line,
            message=(
                "'# arch-allow-*' opt-out marker is not governed by an escape-hatch "
                "budget; pass --budget escape-hatch-budget.json (a checked-in ratchet) "
                "or remove the marker"
            ),
        )
        for path, per_line in _scan_allow_markers(root).items()
        for line in sorted(per_line)
    ]
    return sorted(violations, key=lambda violation: (violation.path, violation.line))


__all__ = [
    "ArchViolation",
    "GUIDE_TOPIC_BY_RULE",
    "assert_app_clean",
    "check_app",
    "check_canonical_module_shape",
    "check_escape_hatch_budget",
    "check_events_reference_catalog",
    "check_list_routes_paginate",
    "check_input_str_fields_have_max_length",
    "check_jobs_reference_catalog",
    "check_modules_declare_policy",
    "check_mutations_emit_audit",
    "check_mutations_require_write_role",
    "check_no_adhoc_background_runtime",
    "check_no_adhoc_config_decrypt",
    "check_no_adhoc_logging_config",
    "check_no_adhoc_middleware",
    "check_no_adhoc_permission_literals",
    "check_no_app_instantiation",
    "check_no_destructive_migrations",
    "check_no_dynamic_sql",
    "check_no_cross_module_imports",
    "check_no_hardcoded_credentials",
    "check_no_internal_imports",
    "check_no_manual_actor_stamping",
    "check_no_manual_ownership_checks",
    "check_no_manual_version_assignment",
    "check_update_schemas_inherit_base_update_schema",
    "check_no_naive_datetime",
    "check_no_dependency_overrides",
    "check_no_raw_app_routes",
    "check_no_raw_file_references",
    "check_no_manual_scope_filtering",
    "check_no_raw_connection_access",
    "check_no_raw_outbound_http",
    "check_no_raw_session_construction",
    "check_no_unique_columns_on_soft_delete_models",
    "check_policy_refs_resolve",
    "check_reads_use_base_query",
    "check_response_model_not_table_model",
    "check_routes_declare_response_model",
    "check_safe_methods_are_read_only",
    "check_schemas_exclude_sensitive_fields",
    "check_session_imported_from_sqlmodel",
    "check_table_models_use_base_table",
    "check_no_manual_table_schema",
    "check_tables_have_migrations",
    "check_tenant_scoped_models_use_scoped_service",
    "guide_topic_for",
    "ungoverned_marker_violations",
]
