"""terp.arch — the Terp enforcement harness, shipped as a versioned dependency.

The bespoke secure-by-default fitness rules (design §5.10): each is the
**build-time layer** that pairs with a fail-closed runtime control in
``terp.core`` (or a capability). Clients *run* these rules against their own
``app/`` but cannot edit them — the harness travels as a package.

Typical use in a client repo::

    from terp.arch import assert_app_clean

    def test_architecture() -> None:
        assert_app_clean("app")

Generic layering/boundary checks are delegated to Tach/import-linter and
dependency hygiene to deptry/pip-audit (design §8); only the domain-specific
rules are hand-rolled here. Secure-by-default opt-outs are governed: a justified
``# arch-allow-<rule>: <reason>`` comment suppresses a single violation, and
:func:`check_escape_hatch_budget` ratchets the marker counts against a checked-in
budget so opt-outs stay visible, greppable, and can only shrink.
"""

from __future__ import annotations

from terp.arch.rules import (
    GUIDE_TOPIC_BY_RULE,
    ArchViolation,
    assert_app_clean,
    check_app,
    check_base_query_not_overridden,
    check_canonical_module_shape,
    check_escape_hatch_budget,
    check_events_reference_catalog,
    check_input_schemas_exclude_managed_columns,
    check_input_str_fields_have_max_length,
    check_jobs_reference_catalog,
    check_list_routes_paginate,
    check_modules_declare_policy,
    check_mutations_emit_audit,
    check_mutations_require_write_role,
    check_no_adhoc_background_runtime,
    check_no_adhoc_config_decrypt,
    check_no_adhoc_logging_config,
    check_no_adhoc_middleware,
    check_no_adhoc_permission_literals,
    check_no_destructive_migrations,
    check_no_dynamic_sql,
    check_no_hardcoded_credentials,
    check_no_raw_outbound_http,
    check_policy_refs_resolve,
    check_no_app_instantiation,
    check_no_cross_module_imports,
    check_no_internal_imports,
    check_no_manual_actor_stamping,
    check_no_manual_ownership_checks,
    check_no_raw_app_routes,
    check_no_raw_file_references,
    check_no_manual_scope_filtering,
    check_no_raw_connection_access,
    check_no_raw_session_construction,
    check_no_unique_columns_on_soft_delete_models,
    check_public_modules_are_read_only,
    check_reads_use_base_query,
    check_response_model_not_table_model,
    check_routes_declare_response_model,
    check_safe_methods_are_read_only,
    check_schemas_exclude_sensitive_fields,
    check_session_imported_from_sqlmodel,
    check_table_models_use_base_table,
    check_no_manual_table_schema,
    check_tables_have_migrations,
    check_tenant_scoped_models_use_scoped_service,
    guide_topic_for,
    ungoverned_marker_violations,
)

__all__ = [
    "ArchViolation",
    "GUIDE_TOPIC_BY_RULE",
    "assert_app_clean",
    "check_app",
    "check_base_query_not_overridden",
    "check_canonical_module_shape",
    "check_escape_hatch_budget",
    "check_events_reference_catalog",
    "check_input_schemas_exclude_managed_columns",
    "check_input_str_fields_have_max_length",
    "check_jobs_reference_catalog",
    "check_list_routes_paginate",
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
    "check_no_hardcoded_credentials",
    "check_no_raw_outbound_http",
    "check_no_cross_module_imports",
    "check_no_internal_imports",
    "check_no_manual_actor_stamping",
    "check_no_manual_ownership_checks",
    "check_no_raw_app_routes",
    "check_no_raw_file_references",
    "check_no_manual_scope_filtering",
    "check_no_raw_connection_access",
    "check_no_raw_session_construction",
    "check_no_unique_columns_on_soft_delete_models",
    "check_policy_refs_resolve",
    "check_public_modules_are_read_only",
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
