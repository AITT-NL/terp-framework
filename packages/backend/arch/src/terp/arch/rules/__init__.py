"""The Terp secure-by-default fitness rules (design Â§5.10), shipped as a dependency.

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

import enum
import pathlib
from collections.abc import Callable, Iterable
from dataclasses import dataclass

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
from terp.arch.rules.datetimes import (
    check_datetime_columns_are_timezone_aware,
    check_no_naive_datetime,
)
from terp.arch.rules.errors import (
    check_errors_use_the_typed_envelope,
    check_no_exception_text_in_responses,
)
from terp.arch.rules.hygiene import (
    check_no_blocking_sleep,
    check_no_empty_tests,
    check_no_eval_or_exec,
    check_no_mutable_default_args,
    check_no_print,
    check_no_star_imports,
    check_no_todo_fixme,
)
from terp.arch.rules.size import check_no_oversized_python_files
from terp.arch.rules.events import (
    check_emitted_events_are_declared,
    check_events_reference_catalog,
)
from terp.arch.rules.http import (
    check_declared_read_only_routes_do_not_write,
    check_list_routes_paginate,
    check_no_adhoc_logging_config,
    check_no_adhoc_middleware,
    check_no_app_instantiation,
    check_no_dependency_overrides,
    check_no_raw_app_routes,
    check_path_id_params_are_uuid,
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
from terp.arch.rules.module_roles import (
    check_grantable_modules_are_named,
    check_module_role_writes_go_through_the_capability,
    check_platform_modules_refuse_module_roles,
)
from terp.arch.rules.migrations import (
    check_alembic_downgrades_not_empty,
    check_migration_history_is_intact,
    check_not_null_columns_are_backfilled,
    check_table_ownership_is_not_split,
    check_no_destructive_migrations,
)
from terp.arch.rules.jobs import check_jobs_reference_catalog
from terp.arch.rules.operations import (
    check_operations_reference_catalog,
    check_routes_declare_operation,
)
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
    check_forwarded_filters_are_declared,
    check_declared_read_controls_are_forwarded,
    check_frozen_values_hold_no_mutable_collection,
    check_offset_queries_declare_ordering,
    check_no_unique_columns_on_soft_delete_models,
    check_schemas_avoid_positional_tuples,
    check_schemas_exclude_sensitive_fields,
    check_table_models_use_base_table,
    check_tables_have_migrations,
)
from terp.arch.rules.references import (
    check_references_declare_delete_behaviour,
)
from terp.arch.rules.dependencies import (
    check_cross_module_imports_use_public_surface,
    check_module_dependency_graph_is_acyclic,
)
from terp.arch.rules.secrets import (
    check_no_adhoc_config_decrypt,
    check_no_hardcoded_credentials,
)
from terp.arch.rules.structure import (
    check_canonical_module_shape,
    check_modules_ship_tests,
)
from terp.arch.rules.traits import (
    check_base_query_not_overridden,
    check_no_manual_actor_stamping,
    check_no_manual_lease_columns,
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
    "references_declare_delete_behaviour": "references",
    "table_models_use_base_table": "module",
    "tables_have_migrations": "migrations",
    "no_manual_table_schema": "migrations",
    "no_destructive_migrations": "migrations",
    "not_null_columns_are_backfilled": "migrations",
    "alembic_downgrades_not_empty": "migrations",
    "migration_history_is_intact": "migrations",
    "table_ownership_is_not_split": "migrations",
    "no_unique_columns_on_soft_delete_models": "module",
    "canonical_module_shape": "module",
    "modules_ship_tests": "testing",
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
    rule the mapping missed â€” the completeness meta-test catches the gap at build
    time, and ``rules`` (the generated every-rule topic) is always a safe pointer.
    """
    return GUIDE_TOPIC_BY_RULE.get(rule, "rules")


class RootKind(enum.Enum):
    """What a scanned root *is*, which is what decides the rules it is held to.

    ``APP`` is a Terp application package — the thing ``create_app`` mounts, with
    modules, routers, a policy, tables and migrations. Every rule applies to it.

    ``COMPANION`` is a second deployable that ships from the same repository and is
    **not** mounted by ``create_app``: a worker, a publisher, a CLI, a sidecar. It is
    ordinary Python that reaches real credentials, real databases and the real
    network, so the rules about the *code* apply to it in full — and the rules that
    are properties of being a mounted application (a route's response model, a
    module's policy, a table's migration) do not, because there is nothing for them
    to be a property of.

    A root that serves the platform's own HTTP surface is an ``APP``, however it is
    deployed. The kind describes what the code is, not how many processes run it.
    """

    APP = "app"
    COMPANION = "companion"


#: Every root kind — the applicability of a rule whose invariant holds for any
#: Python that ships.
EVERY_ROOT: frozenset[RootKind] = frozenset(RootKind)

#: Application roots only — the applicability of a rule whose invariant is a
#: property of being a mounted Terp application.
APP_ROOT_ONLY: frozenset[RootKind] = frozenset({RootKind.APP})


@dataclass(frozen=True)
class ScanRoot:
    """One directory the harness walks, with the package name and kind it is walked as.

    ``ScanRoot("engine", package="engine", kind=RootKind.COMPANION)`` is the whole
    configuration a second deployable needs; :func:`check_app` and
    :func:`assert_app_clean` take any number of these beside the app root and share
    one escape-hatch budget across them, so a sibling package is a line rather than a
    bespoke test module.

    A bare path passed to those functions is an ``APP`` root taking the call's
    ``package=``, which is what every existing call site means and why it keeps
    meaning it.
    """

    path: pathlib.Path
    package: str = "app"
    kind: RootKind = RootKind.APP

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", pathlib.Path(self.path))


#: Which root kinds each rule is evaluated over, keyed by the bare rule name (no
#: ``check_`` prefix) — the same key space as :data:`GUIDE_TOPIC_BY_RULE`, locked by
#: the same kind of completeness meta-test, so a new rule cannot arrive unclassified.
#:
#: The line is not "security rules travel and the rest do not", and it is not
#: negative-versus-positive phrasing either. It is this: **a rule applies to every
#: root when its invariant holds for any Python that ships, and to app roots only
#: when its invariant is a property of being a mounted Terp application** — of a
#: module, a route, a response, a table, a migration, an event, a job, or the guarded
#: session. A worker has no route whose response model could be wrong; it very much
#: has a hardcoded credential, an f-string SQL statement, a raw HTTP client and a
#: frozen value object holding a list.
#:
#: Two neighbouring rules show the line rather than describe it.
#: ``no_manual_table_schema`` asks a declaration not to hand-write a schema
#: qualifier, which is safe advice for any SQLModel table anywhere, so it travels;
#: ``table_models_use_base_table`` asks a declaration to inherit ``BaseTable``, which
#: a package outside the platform cannot do, so it does not.
RULE_ROOT_KINDS: dict[str, frozenset[RootKind]] = {
    # --- the invariant holds for any Python that ships -----------------------
    "no_internal_imports": EVERY_ROOT,
    "no_raw_outbound_http": EVERY_ROOT,
    "no_dynamic_sql": EVERY_ROOT,
    "no_hardcoded_credentials": EVERY_ROOT,
    "no_manual_table_schema": EVERY_ROOT,
    "no_adhoc_config_decrypt": EVERY_ROOT,
    "no_eval_or_exec": EVERY_ROOT,
    "no_star_imports": EVERY_ROOT,
    "no_blocking_sleep": EVERY_ROOT,
    "no_print": EVERY_ROOT,
    "no_todo_fixme": EVERY_ROOT,
    "no_mutable_default_args": EVERY_ROOT,
    "no_naive_datetime": EVERY_ROOT,
    "no_oversized_python_files": EVERY_ROOT,
    "no_empty_tests": EVERY_ROOT,
    "frozen_values_hold_no_mutable_collection": EVERY_ROOT,
    # --- the invariant is a property of being a mounted Terp application -----
    "no_cross_module_imports": APP_ROOT_ONLY,
    "cross_module_imports_use_public_surface": APP_ROOT_ONLY,
    "module_dependency_graph_is_acyclic": APP_ROOT_ONLY,
    "no_adhoc_background_runtime": APP_ROOT_ONLY,
    "modules_declare_policy": APP_ROOT_ONLY,
    "mutations_require_write_role": APP_ROOT_ONLY,
    "public_modules_are_read_only": APP_ROOT_ONLY,
    "no_adhoc_permission_literals": APP_ROOT_ONLY,
    "policy_refs_resolve": APP_ROOT_ONLY,
    "grantable_modules_are_named": APP_ROOT_ONLY,
    "platform_modules_refuse_module_roles": APP_ROOT_ONLY,
    "module_role_writes_go_through_the_capability": APP_ROOT_ONLY,
    "routes_declare_response_model": APP_ROOT_ONLY,
    "response_model_not_table_model": APP_ROOT_ONLY,
    "schemas_exclude_sensitive_fields": APP_ROOT_ONLY,
    "list_routes_paginate": APP_ROOT_ONLY,
    "path_id_params_are_uuid": APP_ROOT_ONLY,
    "safe_methods_are_read_only": APP_ROOT_ONLY,
    "declared_read_only_routes_do_not_write": APP_ROOT_ONLY,
    "no_raw_session_construction": APP_ROOT_ONLY,
    "no_raw_connection_access": APP_ROOT_ONLY,
    "offset_queries_declare_ordering": APP_ROOT_ONLY,
    "forwarded_filters_are_declared": APP_ROOT_ONLY,
    "declared_read_controls_are_forwarded": APP_ROOT_ONLY,
    "datetime_columns_are_timezone_aware": APP_ROOT_ONLY,
    "errors_use_the_typed_envelope": APP_ROOT_ONLY,
    "no_exception_text_in_responses": APP_ROOT_ONLY,
    "mutations_emit_audit": APP_ROOT_ONLY,
    "events_reference_catalog": APP_ROOT_ONLY,
    "emitted_events_are_declared": APP_ROOT_ONLY,
    "jobs_reference_catalog": APP_ROOT_ONLY,
    "operations_reference_catalog": APP_ROOT_ONLY,
    "routes_declare_operation": APP_ROOT_ONLY,
    "input_str_fields_have_max_length": APP_ROOT_ONLY,
    "input_schemas_exclude_managed_columns": APP_ROOT_ONLY,
    "schemas_avoid_positional_tuples": APP_ROOT_ONLY,
    "tenant_scoped_models_use_scoped_service": APP_ROOT_ONLY,
    "base_query_not_overridden": APP_ROOT_ONLY,
    "reads_use_base_query": APP_ROOT_ONLY,
    "no_manual_scope_filtering": APP_ROOT_ONLY,
    "no_manual_actor_stamping": APP_ROOT_ONLY,
    "no_manual_ownership_checks": APP_ROOT_ONLY,
    "no_manual_lease_columns": APP_ROOT_ONLY,
    "no_manual_version_assignment": APP_ROOT_ONLY,
    "update_schemas_inherit_base_update_schema": APP_ROOT_ONLY,
    "no_raw_file_references": APP_ROOT_ONLY,
    "references_declare_delete_behaviour": APP_ROOT_ONLY,
    "table_models_use_base_table": APP_ROOT_ONLY,
    "tables_have_migrations": APP_ROOT_ONLY,
    "no_destructive_migrations": APP_ROOT_ONLY,
    "not_null_columns_are_backfilled": APP_ROOT_ONLY,
    "alembic_downgrades_not_empty": APP_ROOT_ONLY,
    "migration_history_is_intact": APP_ROOT_ONLY,
    "table_ownership_is_not_split": APP_ROOT_ONLY,
    "no_unique_columns_on_soft_delete_models": APP_ROOT_ONLY,
    "canonical_module_shape": APP_ROOT_ONLY,
    "modules_ship_tests": APP_ROOT_ONLY,
    "session_imported_from_sqlmodel": APP_ROOT_ONLY,
    "no_app_instantiation": APP_ROOT_ONLY,
    "no_raw_app_routes": APP_ROOT_ONLY,
    "no_dependency_overrides": APP_ROOT_ONLY,
    "no_adhoc_middleware": APP_ROOT_ONLY,
    "no_adhoc_logging_config": APP_ROOT_ONLY,
    # The escape-hatch governance half is about the markers rather than the code, so
    # it is evaluated over every root the call scans.
    "escape_hatch_budget": EVERY_ROOT,
    "ungoverned_escape_hatch": EVERY_ROOT,
}


def root_kinds_for(rule: str) -> frozenset[RootKind]:
    """The root kinds *rule* is evaluated over (:data:`EVERY_ROOT` if unmapped).

    The unmapped fallback runs the rule **everywhere**, and the polarity is the
    decision rather than a detail. This seam exists because four rules were believed
    to be running over code they never reached (ADR 0136), so the failure this
    default has to refuse is silent under-enforcement. A rule that runs where it does
    not belong produces a false positive with a file and a line on it, which somebody
    fixes in an afternoon; a rule that quietly stops running produces a green gate
    that proves nothing, which is what took a security review to find. The
    completeness meta-test makes the fallback unreachable in this repository; it is
    here for a consumer holding a newer harness than its pinned classification.
    """
    return RULE_ROOT_KINDS.get(rule, EVERY_ROOT)


def _scan_roots(
    roots: Iterable[str | pathlib.Path | ScanRoot], *, package: str
) -> tuple[ScanRoot, ...]:
    """Normalise a call's roots to :class:`ScanRoot` values, in the order given.

    A bare path becomes an ``APP`` root on the call's *package*, which is what
    ``check_app("app")`` has always meant.
    """
    return tuple(
        root if isinstance(root, ScanRoot) else ScanRoot(pathlib.Path(root), package=package)
        for root in roots
    )


_ALL_RULES: tuple[Callable[..., list[ArchViolation]], ...] = (
    check_no_internal_imports,
    check_no_cross_module_imports,
    check_cross_module_imports_use_public_surface,
    check_module_dependency_graph_is_acyclic,
    check_no_raw_outbound_http,
    check_no_adhoc_background_runtime,
    check_modules_declare_policy,
    check_mutations_require_write_role,
    check_public_modules_are_read_only,
    check_no_adhoc_permission_literals,
    check_policy_refs_resolve,
    check_grantable_modules_are_named,
    check_platform_modules_refuse_module_roles,
    check_module_role_writes_go_through_the_capability,
    check_routes_declare_response_model,
    check_response_model_not_table_model,
    check_schemas_exclude_sensitive_fields,
    check_list_routes_paginate,
    check_path_id_params_are_uuid,
    check_safe_methods_are_read_only,
    check_declared_read_only_routes_do_not_write,
    check_no_raw_session_construction,
    check_no_raw_connection_access,
    check_no_dynamic_sql,
    check_offset_queries_declare_ordering,
    check_forwarded_filters_are_declared,
    check_declared_read_controls_are_forwarded,
    check_frozen_values_hold_no_mutable_collection,
    check_no_naive_datetime,
    check_datetime_columns_are_timezone_aware,
    check_errors_use_the_typed_envelope,
    check_no_exception_text_in_responses,
    check_no_oversized_python_files,
    check_no_eval_or_exec,
    check_no_star_imports,
    check_no_blocking_sleep,
    check_no_print,
    check_no_todo_fixme,
    check_no_mutable_default_args,
    check_no_empty_tests,
    check_mutations_emit_audit,
    check_events_reference_catalog,
    check_emitted_events_are_declared,
    check_jobs_reference_catalog,
    check_operations_reference_catalog,
    check_routes_declare_operation,
    check_no_adhoc_config_decrypt,
    check_no_hardcoded_credentials,
    check_input_str_fields_have_max_length,
    check_input_schemas_exclude_managed_columns,
    check_schemas_avoid_positional_tuples,
    check_tenant_scoped_models_use_scoped_service,
    check_base_query_not_overridden,
    check_reads_use_base_query,
    check_no_manual_scope_filtering,
    check_no_manual_actor_stamping,
    check_no_manual_ownership_checks,
    check_no_manual_lease_columns,
    check_no_manual_version_assignment,
    check_update_schemas_inherit_base_update_schema,
    check_no_raw_file_references,
    check_table_models_use_base_table,
    check_tables_have_migrations,
    check_no_manual_table_schema,
    check_no_destructive_migrations,
    check_not_null_columns_are_backfilled,
    check_alembic_downgrades_not_empty,
    check_migration_history_is_intact,
    check_table_ownership_is_not_split,
    check_no_unique_columns_on_soft_delete_models,
    check_references_declare_delete_behaviour,
    check_canonical_module_shape,
    check_modules_ship_tests,
    check_session_imported_from_sqlmodel,
    check_no_app_instantiation,
    check_no_raw_app_routes,
    check_no_dependency_overrides,
    check_no_adhoc_middleware,
    check_no_adhoc_logging_config,
)


def check_app(
    app_root: str | pathlib.Path | ScanRoot,
    *more_roots: str | pathlib.Path | ScanRoot,
    package: str = "app",
    budget_path: str | pathlib.Path | None = None,
) -> list[ArchViolation]:
    """Run every applicable rule against each scanned root and return the violations.

    One root is the ordinary case and needs no ceremony: ``check_app("app")`` scans
    the app package with every rule, exactly as it always has. Pass further roots —
    as :class:`ScanRoot` values when they are not app packages — to hold a second
    deployable in the same repository to the same harness::

        check_app(
            "app",
            ScanRoot("engine", package="engine", kind=RootKind.COMPANION),
            budget_path="escape-hatch-budget.json",
        )

    Each root is scanned with the rules :func:`root_kinds_for` says apply to its
    kind, and suppressions are resolved per root (a marker governs the file it sits
    in). The escape-hatch budget is **shared**: one checked-in ratchet counts the
    markers of every scanned root together, because one repository's opt-outs are one
    number to argue about, and a per-root budget would let an exception move rather
    than be justified.
    """
    roots = _scan_roots((app_root, *more_roots), package=package)
    for root in roots:
        if not root.path.is_dir():
            raise NotADirectoryError(f"{root.kind.value} root not found: {root.path}")
    violations: list[ArchViolation] = []
    for root in roots:
        raw: list[ArchViolation] = []
        for rule in _ALL_RULES:
            if root.kind not in root_kinds_for(rule.__name__.removeprefix("check_")):
                continue
            raw.extend(rule(root.path, package=root.package))
        violations.extend(_apply_suppressions(raw, _scan_allow_markers(root.path)))
    if budget_path is not None:
        violations.extend(check_escape_hatch_budget(*roots, budget_path=budget_path, package=package))
    return sorted(violations, key=lambda violation: (violation.path, violation.line, violation.rule))


def assert_app_clean(
    app_root: str | pathlib.Path | ScanRoot,
    *more_roots: str | pathlib.Path | ScanRoot,
    package: str = "app",
    budget_path: str | pathlib.Path | None = None,
) -> None:
    """Raise ``AssertionError`` listing every architecture violation in the scanned roots.

    Takes the same roots as :func:`check_app` — one app package by default, plus any
    number of further :class:`ScanRoot` values for the repository's other deployables.

    Governed opt-out: if any scanned root uses an ``# arch-allow-*`` marker but no
    *budget_path* is supplied, this fails closed — an opt-out must be governed by a
    checked-in escape-hatch budget, never used silently.
    """
    roots = _scan_roots((app_root, *more_roots), package=package)
    if budget_path is None and any(_scan_allow_markers(root.path) for root in roots):
        raise AssertionError(
            "terp.arch found '# arch-allow-*' opt-out marker(s) but no budget_path was "
            "supplied; govern opt-outs with a checked-in escape-hatch budget — call "
            "assert_app_clean(app, budget_path='escape-hatch-budget.json')"
        )
    violations = check_app(*roots, package=package, budget_path=budget_path)
    if violations:
        listing = "\n".join(
            f"  - {violation}  (fix recipe: terp guide {violation.rule})"
            for violation in violations
        )
        raise AssertionError(
            f"terp.arch found {len(violations)} architecture violation(s):\n{listing}"
        )


def ungoverned_marker_violations(
    app_root: str | pathlib.Path | ScanRoot,
    *more_roots: str | pathlib.Path | ScanRoot,
    package: str = "app",
) -> list[ArchViolation]:
    """The fail-closed ungoverned-opt-out condition, as structured violations.

    :func:`assert_app_clean` refuses (with a plain ``AssertionError``) to honour any
    ``# arch-allow-*`` marker when no escape-hatch budget governs it. This is the
    same condition projected as :class:`ArchViolation` values (rule
    ``ungoverned_escape_hatch``, one per marker line), so a structured renderer
    (``terp check --format json``) reports it in-band instead of crashing. Every
    scanned root contributes its markers, for the same reason the budget is shared.
    """
    roots = _scan_roots((app_root, *more_roots), package=package)
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
        for root in roots
        for path, per_line in _scan_allow_markers(root.path).items()
        for line in sorted(per_line)
    ]
    return sorted(violations, key=lambda violation: (violation.path, violation.line))


__all__ = [
    "APP_ROOT_ONLY",
    "EVERY_ROOT",
    "ArchViolation",
    "GUIDE_TOPIC_BY_RULE",
    "RULE_ROOT_KINDS",
    "RootKind",
    "ScanRoot",
    "assert_app_clean",
    "check_alembic_downgrades_not_empty",
    "check_migration_history_is_intact",
    "check_table_ownership_is_not_split",
    "check_app",
    "check_canonical_module_shape",
    "check_modules_ship_tests",
    "check_escape_hatch_budget",
    "check_events_reference_catalog",
    "check_emitted_events_are_declared",
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
    "check_not_null_columns_are_backfilled",
    "check_no_dynamic_sql",
    "check_no_cross_module_imports",
    "check_no_hardcoded_credentials",
    "check_no_internal_imports",
    "check_no_manual_actor_stamping",
    "check_no_manual_lease_columns",
    "check_no_manual_ownership_checks",
    "check_no_manual_version_assignment",
    "check_schemas_avoid_positional_tuples",
    "check_update_schemas_inherit_base_update_schema",
    "check_no_naive_datetime",
    "check_errors_use_the_typed_envelope",
    "check_no_exception_text_in_responses",
    "check_datetime_columns_are_timezone_aware",
    "check_no_oversized_python_files",
    "check_no_blocking_sleep",
    "check_no_empty_tests",
    "check_no_eval_or_exec",
    "check_no_mutable_default_args",
    "check_no_print",
    "check_no_star_imports",
    "check_no_todo_fixme",
    "check_no_dependency_overrides",
    "check_no_raw_app_routes",
    "check_no_raw_file_references",
    "check_no_manual_scope_filtering",
    "check_no_raw_connection_access",
    "check_no_raw_outbound_http",
    "check_no_raw_session_construction",
    "check_no_unique_columns_on_soft_delete_models",
    "check_references_declare_delete_behaviour",
    "check_offset_queries_declare_ordering",
    "check_operations_reference_catalog",
    "check_routes_declare_operation",
    "check_forwarded_filters_are_declared",
    "check_declared_read_controls_are_forwarded",
    "check_frozen_values_hold_no_mutable_collection",
    "check_path_id_params_are_uuid",
    "check_policy_refs_resolve",
    "check_reads_use_base_query",
    "check_response_model_not_table_model",
    "check_routes_declare_response_model",
    "check_declared_read_only_routes_do_not_write",
    "check_safe_methods_are_read_only",
    "check_schemas_exclude_sensitive_fields",
    "check_session_imported_from_sqlmodel",
    "check_table_models_use_base_table",
    "check_no_manual_table_schema",
    "check_tables_have_migrations",
    "check_tenant_scoped_models_use_scoped_service",
    "guide_topic_for",
    "root_kinds_for",
    "ungoverned_marker_violations",
]

