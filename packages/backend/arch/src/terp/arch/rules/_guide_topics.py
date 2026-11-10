"""Every rule's fix recipe: the ``terp guide`` topic that teaches its compliant pattern.

Kept beside the registry (:mod:`terp.arch.rules`), which gathers the rules themselves: this
is the map from a rule to the guide topic a violation points at.
"""

from __future__ import annotations

# Every rule's fix recipe: the ``terp guide`` topic that teaches the compliant
# pattern the rule enforces. Keyed by the bare rule name (no ``check_`` prefix) so
# a violation can carry its own remedy ("fix recipe: terp guide <topic>") instead
# of relying on the author remembering to look one up. Completeness (every rule in
# :data:`_ALL_RULES` has a topic, and every topic is a real ``terp guide`` topic)
# is locked by ``test_arch_harness`` / ``test_docs_parity`` meta-tests.
GUIDE_TOPIC_BY_RULE: dict[str, str] = {
    "deployment_declaration_is_readable": "deployment",
    "deployment_declaration_tells_the_truth": "deployment",
    "deployment_generated_files_match_their_render": "deployment",
    "no_internal_imports": "module",
    "no_cross_module_imports": "dependencies",
    "cross_module_imports_use_public_surface": "dependencies",
    "module_dependency_graph_is_acyclic": "dependencies",
    "no_raw_outbound_http": "capability",
    "no_adhoc_background_runtime": "jobs",
    "modules_declare_policy": "policy",
    "mutations_require_write_role": "policy",
    "public_modules_are_read_only": "policy",
    "no_adhoc_permission_literals": "policy",
    "policy_refs_resolve": "policy",
    "grantable_modules_are_named": "permissions",
    "platform_modules_refuse_module_roles": "permissions",
    "module_role_writes_go_through_the_capability": "permissions",
    "routes_declare_response_model": "module",
    "response_model_not_table_model": "module",
    "schemas_exclude_sensitive_fields": "module",
    "list_routes_paginate": "service",
    "path_id_params_are_uuid": "module",
    "safe_methods_are_read_only": "module",
    "declared_read_only_routes_do_not_write": "module",
    "no_raw_session_construction": "service",
    "no_raw_connection_access": "service",
    "no_dynamic_sql": "service",
    "offset_queries_declare_ordering": "service",
    "declared_read_controls_are_forwarded": "service",
    "forwarded_filters_are_declared": "service",
    "frozen_values_hold_no_mutable_collection": "module",
    "no_naive_datetime": "service",
    "errors_use_the_typed_envelope": "service",
    "no_exception_text_in_responses": "service",
    "datetime_columns_are_timezone_aware": "module",
    "request_timestamps_carry_their_offset": "module",
    "no_oversized_python_files": "module",
    "no_eval_or_exec": "capability",
    "no_star_imports": "module",
    "no_blocking_sleep": "jobs",
    "no_print": "service",
    "no_todo_fixme": "module",
    "no_mutable_default_args": "service",
    "no_empty_tests": "rules",
    "mutations_emit_audit": "service",
    "events_reference_catalog": "events",
    "emitted_events_are_declared": "events",
    "jobs_reference_catalog": "jobs",
    "operations_reference_catalog": "operations",
    "routes_declare_operation": "operations",
    "no_adhoc_config_decrypt": "capability",
    "no_hardcoded_credentials": "capability",
    "input_str_fields_have_max_length": "module",
    "input_schemas_exclude_managed_columns": "module",
    "schemas_avoid_positional_tuples": "module",
    "tenant_scoped_models_use_scoped_service": "tenancy",
    "base_query_not_overridden": "service",
    "reads_use_base_query": "service",
    "no_manual_scope_filtering": "tenancy",
    "no_manual_actor_stamping": "service",
    "no_manual_ownership_checks": "ownership",
    "no_manual_lease_columns": "leases",
    "no_manual_version_assignment": "service",
    "update_schemas_inherit_base_update_schema": "module",
    "no_raw_file_references": "files",
    "permission_gated_reads_disclose": "access",
    "references_declare_delete_behaviour": "references",
    "personal_fields_are_declared": "personal-data",
    "table_models_use_base_table": "module",
    "tables_have_migrations": "migrations",
    "no_manual_table_schema": "migrations",
    "no_destructive_migrations": "migrations",
    "not_null_columns_are_backfilled": "migrations",
    "alembic_downgrades_not_empty": "migrations",
    "migration_history_is_intact": "migrations",
    "table_ownership_is_not_split": "migrations",
    "expand_revisions_only_expand": "migrations",
    "no_unique_columns_on_soft_delete_models": "module",
    "canonical_module_shape": "module",
    "modules_ship_tests": "testing",
    "session_imported_from_sqlmodel": "service",
    "no_app_instantiation": "capability",
    "no_raw_app_routes": "capability",
    "module_list_is_unconditional": "capability",
    "no_dependency_overrides": "capability",
    "no_adhoc_middleware": "capability",
    "no_adhoc_logging_config": "capability",
    "escape_hatch_budget": "rules",
    "ungoverned_escape_hatch": "rules",
}


def guide_topic_for(rule: str) -> str:
    """The ``terp guide`` topic teaching the fix for *rule* (``rules`` if unmapped).

    The unmapped fallback is deliberate: a violation renderer must never crash on a
    rule the mapping missed â€” the completeness meta-test catches the gap at build
    time, and ``rules`` (the generated every-rule topic) is always a safe pointer.
    """
    return GUIDE_TOPIC_BY_RULE.get(rule, "rules")


__all__ = ["GUIDE_TOPIC_BY_RULE", "guide_topic_for"]
