"""Gate for ``terp.arch``: every rule fires on a violation and the example app is clean.

The harness is Terp's build-time enforcement layer (design Â§5.10). These tests
prove each rule (1) catches the breach it targets and (2) does **not** fire on
correct code â€” and that the real ``apps/example/app`` passes the whole suite,
so the harness dogfoods against a genuine secure-CRUD app.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from terp.arch import (
    assert_app_clean,
    check_app,
    check_base_query_not_overridden,
    check_canonical_module_shape,
    check_escape_hatch_budget,
    check_emitted_events_are_declared,
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
    check_no_app_instantiation,
    check_alembic_downgrades_not_empty,
    check_migration_history_is_intact,
    check_table_ownership_is_not_split,
    check_no_destructive_migrations,
    check_no_dynamic_sql,
    check_no_cross_module_imports,
    check_cross_module_imports_use_public_surface,
    check_module_dependency_graph_is_acyclic,
    check_no_hardcoded_credentials,
    check_no_internal_imports,
    check_no_manual_actor_stamping,
    check_no_manual_ownership_checks,
    check_no_manual_version_assignment,
    check_no_naive_datetime,
    check_datetime_columns_are_timezone_aware,
    check_no_oversized_python_files,
    check_no_blocking_sleep,
    check_no_empty_tests,
    check_no_eval_or_exec,
    check_no_mutable_default_args,
    check_no_print,
    check_no_star_imports,
    check_no_todo_fixme,
    check_no_dependency_overrides,
    check_no_raw_app_routes,
    check_no_raw_file_references,
    check_no_manual_scope_filtering,
    check_no_raw_connection_access,
    check_no_raw_outbound_http,
    check_no_raw_session_construction,
    check_offset_queries_declare_ordering,
    check_forwarded_filters_are_declared,
    check_path_id_params_are_uuid,
    check_policy_refs_resolve,
    check_public_modules_are_read_only,
    check_reads_use_base_query,
    check_response_model_not_table_model,
    check_routes_declare_response_model,
    check_safe_methods_are_read_only,
    check_schemas_exclude_sensitive_fields,
    check_session_imported_from_sqlmodel,
    check_no_manual_table_schema,
    check_no_unique_columns_on_soft_delete_models,
    check_table_models_use_base_table,
    check_tables_have_migrations,
    check_tenant_scoped_models_use_scoped_service,
    check_update_schemas_inherit_base_update_schema,
)

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_EXAMPLE_APP = _REPO_ROOT / "apps" / "example" / "app"
_EXAMPLE_BUDGET = _REPO_ROOT / "apps" / "example" / "escape-hatch-budget.json"

# A single guaranteed violation we can suppress: a module importing terp.core._internal.
_INTERNAL_IMPORT = "from terp.core._internal.engine import get_engine"


def _write(app_root: pathlib.Path, rel: str, source: str) -> None:
    path = app_root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")


def _rule_names(violations: list) -> set[str]:
    return {violation.rule for violation in violations}


def test_no_internal_imports(tmp_path: pathlib.Path) -> None:
    app = tmp_path / "app"
    _write(app, "modules/notes/service.py", "from terp.core._internal.engine import get_engine\n")
    assert _rule_names(check_no_internal_imports(app)) == {"no_internal_imports"}

    _write(app, "modules/notes/service.py", "from terp.core import BaseService\n")
    assert check_no_internal_imports(app) == []


def test_no_cross_module_imports(tmp_path: pathlib.Path) -> None:
    app = tmp_path / "app"
    _write(app, "modules/a/service.py", "from app.modules.b.models import Thing\n")
    assert _rule_names(check_no_cross_module_imports(app)) == {"no_cross_module_imports"}

    # A plain ``import app.modules.b...`` is the same coupling.
    _write(app, "modules/a/service.py", "import app.modules.b.models\n")
    assert _rule_names(check_no_cross_module_imports(app)) == {"no_cross_module_imports"}

    # A *relative* sibling import is the same coupling by another spelling.
    _write(app, "modules/a/service.py", "from ..b.service import TaskService\n")
    assert _rule_names(check_no_cross_module_imports(app)) == {"no_cross_module_imports"}

    # Importing the sibling as a package alias is also coupling.
    _write(app, "modules/a/service.py", "from .. import b\n")
    assert _rule_names(check_no_cross_module_imports(app)) == {"no_cross_module_imports"}

    _write(app, "modules/a/service.py", "from app.modules import b\n")
    assert _rule_names(check_no_cross_module_imports(app)) == {"no_cross_module_imports"}

    # Importing one's own module is fine â€” absolute or relative.
    _write(app, "modules/a/service.py", "from app.modules.a.models import Thing\n")
    assert check_no_cross_module_imports(app) == []

    _write(app, "modules/a/service.py", "from .models import Thing\n")
    assert check_no_cross_module_imports(app) == []


def _declare(app_root: pathlib.Path, name: str, requires: str) -> None:
    """Write *name*'s manifest declaring *requires* (a literal tuple source)."""
    _write(
        app_root,
        f"modules/{name}/module.py",
        f'module = ModuleSpec(name="{name}", requires={requires})\n',
    )


def test_no_cross_module_imports_allows_a_declared_edge(tmp_path: pathlib.Path) -> None:
    app = tmp_path / "app"
    _write(app, "modules/a/service.py", "from app.modules.b.service import Thing\n")
    _write(app, "modules/b/service.py", "from terp.core import BaseService\n")

    # Undeclared: refused.
    assert _rule_names(check_no_cross_module_imports(app)) == {"no_cross_module_imports"}

    # Declared in the DEPENDING module's manifest: allowed.
    _declare(app, "a", '("b",)')
    assert check_no_cross_module_imports(app) == []

    # The edge is one-way: b still may not import a.
    _write(app, "modules/b/service.py", "from app.modules.a.service import Other\n")
    assert _rule_names(check_no_cross_module_imports(app)) == {"no_cross_module_imports"}

    # A declaration a static reader cannot resolve grants nothing (fail closed).
    _write(app, "modules/b/service.py", "from terp.core import BaseService\n")
    _write(
        app,
        "modules/a/module.py",
        "module = ModuleSpec(name=\"a\", requires=_edges())\n",
    )
    assert _rule_names(check_no_cross_module_imports(app)) == {"no_cross_module_imports"}

    # Nor does a sequence whose elements are not all string literals: a reader that
    # cannot say WHICH siblings are declared must grant none of them.
    _write(
        app,
        "modules/a/module.py",
        "module = ModuleSpec(name=\"a\", requires=(\"b\", SOME_NAME))\n",
    )
    assert _rule_names(check_no_cross_module_imports(app)) == {"no_cross_module_imports"}


def test_cross_module_imports_use_public_surface(tmp_path: pathlib.Path) -> None:
    app = tmp_path / "app"
    _write(app, "modules/b/service.py", "from terp.core import BaseService\n")
    _declare(app, "a", '("b",)')

    # The edge grants the domain vocabulary.
    for surface in ("models", "schemas", "service", "events"):
        _write(app, "modules/a/service.py", f"from app.modules.b.{surface} import Thing\n")
        assert check_cross_module_imports_use_public_surface(app) == []

    # It does not grant the dependency's delivery surface or its internals.
    for surface in ("router", "_private"):
        _write(app, "modules/a/service.py", f"from app.modules.b.{surface} import Thing\n")
        assert _rule_names(check_cross_module_imports_use_public_surface(app)) == {
            "cross_module_imports_use_public_surface"
        }

    # Nor the bare package, whose shape nobody published.
    _write(app, "modules/a/service.py", "from app.modules import b\n")
    assert _rule_names(check_cross_module_imports_use_public_surface(app)) == {
        "cross_module_imports_use_public_surface"
    }

    # An UNdeclared import is the sibling rule's business, not this one's.
    _write(app, "modules/a/service.py", "from app.modules.c.router import Thing\n")
    assert check_cross_module_imports_use_public_surface(app) == []


def test_module_dependency_graph_is_acyclic(tmp_path: pathlib.Path) -> None:
    app = tmp_path / "app"
    _declare(app, "a", '("b",)')
    _declare(app, "b", '("c",)')
    _declare(app, "c", "()")
    assert check_module_dependency_graph_is_acyclic(app) == []

    # Close the loop: every participant is named, so the fix has somewhere to start.
    _declare(app, "c", '("a",)')
    violations = check_module_dependency_graph_is_acyclic(app)
    assert _rule_names(violations) == {"module_dependency_graph_is_acyclic"}
    assert {pathlib.Path(item.path).parent.name for item in violations} == {"a", "b", "c"}

    # A module that requires itself is the shortest cycle there is.
    _declare(app, "c", "()")
    _declare(app, "a", '("a",)')
    assert _rule_names(check_module_dependency_graph_is_acyclic(app)) == {
        "module_dependency_graph_is_acyclic"
    }

    # A capability named in requires is not a module edge.
    _declare(app, "a", '("audit", "b")')
    assert check_module_dependency_graph_is_acyclic(app) == []

    # Nor is a build artefact: __pycache__ is a directory under modules/ that holds
    # no Python source, so it never becomes a node a requires entry could match.
    (app / "modules" / "__pycache__").mkdir(parents=True, exist_ok=True)
    (app / "modules" / "__pycache__" / "module.cpython-313.pyc").write_bytes(b"\x00")
    _declare(app, "a", '("__pycache__", "b")')
    assert check_module_dependency_graph_is_acyclic(app) == []


def test_module_cycle_is_seen_through_real_imports_not_only_declarations(
    tmp_path: pathlib.Path,
) -> None:
    """A cycle closed by an import is reported before it becomes a boot-time traceback.

    While an edge is being written the manifest lags the code by a few minutes. If
    the check read only declarations, the author would learn about the cycle from a
    circular-import error at app startup — which names files, not the design mistake.
    """
    app = tmp_path / "app"
    _declare(app, "a", '("b",)')
    _declare(app, "b", '("c",)')
    _declare(app, "c", "()")
    assert check_module_dependency_graph_is_acyclic(app) == []

    # c reaches back to a in code only — nothing was added to any requires tuple.
    _write(app, "modules/c/service.py", "from app.modules.a.models import Thing\n")
    violations = check_module_dependency_graph_is_acyclic(app)
    assert _rule_names(violations) == {"module_dependency_graph_is_acyclic"}
    assert {pathlib.Path(item.path).parent.name for item in violations} == {"a", "b", "c"}

    # The message names the cycle AND a place to put the shared vocabulary.
    assert "a -> b -> c -> a" in violations[0].message
    assert "contracts" in violations[0].message

    # An import of one's own module is not an edge.
    _write(app, "modules/c/service.py", "from app.modules.c.models import Thing\n")
    assert check_module_dependency_graph_is_acyclic(app) == []


def test_no_raw_outbound_http(tmp_path: pathlib.Path) -> None:
    app = tmp_path / "app"
    for stmt in (
        "import httpx",
        "from httpx import AsyncClient",
        "import requests.sessions",
        "import urllib.request",
        "from urllib import request",
        "from urllib.request import urlopen",
        "import urllib3",
        "from aiohttp import ClientSession",
    ):
        _write(app, "modules/notes/service.py", f"{stmt}\n")
        assert _rule_names(check_no_raw_outbound_http(app)) == {"no_raw_outbound_http"}, stmt

    # The scan is scoped to app modules, and benign urllib helpers are not HTTP clients.
    _write(app, "shared/http.py", "import httpx\n")
    _write(app, "modules/notes/service.py", "from urllib import parse\nfrom terp.core import BaseService\n")
    assert check_no_raw_outbound_http(app) == []

    # Lower-level escape routes to the network are the same egress (G3).
    for stmt in ("import socket", "import http.client", "from http.client import HTTPSConnection", "from http import client"):
        _write(app, "modules/notes/service.py", f"{stmt}\n")
        assert _rule_names(check_no_raw_outbound_http(app)) == {"no_raw_outbound_http"}, stmt
    _write(app, "modules/notes/service.py", "from http import HTTPStatus\n")
    assert check_no_raw_outbound_http(app) == []

    # tests/ and migrations/ dirs inside a module are importable code: still scanned (G1).
    _write(app, "modules/notes/service.py", "from terp.core import BaseService\n")
    _write(app, "modules/notes/tests/helper.py", "import httpx\n")
    assert _rule_names(check_no_raw_outbound_http(app)) == {"no_raw_outbound_http"}
    _write(app, "modules/notes/tests/helper.py", "from terp.core import BaseService\n")
    _write(app, "modules/notes/migrations/versions/0001_x.py", "import requests\n")
    assert _rule_names(check_no_raw_outbound_http(app)) == {"no_raw_outbound_http"}



def test_modules_declare_policy(tmp_path: pathlib.Path) -> None:
    app = tmp_path / "app"
    _write(app, "modules/billing/module.py", "module = ModuleSpec(name='billing', router=router)\n")
    violations = check_modules_declare_policy(app)
    assert _rule_names(violations) == {"modules_declare_policy"}
    assert "Use Policy.default() for authenticated CRUD" in violations[0].message
    assert "only for an intentionally unauthenticated module" in violations[0].message

    _write(
        app,
        "modules/billing/module.py",
        "module = ModuleSpec(name='billing', router=router, policy=Policy.default())\n",
    )
    assert check_modules_declare_policy(app) == []


def test_no_adhoc_permission_literals(tmp_path: pathlib.Path) -> None:
    app = tmp_path / "app"
    _write(
        app,
        "modules/billing/module.py",
        "module = ModuleSpec(name='billing', policy=Policy(read='billing.read'))\n",
    )
    assert _rule_names(check_no_adhoc_permission_literals(app)) == {
        "no_adhoc_permission_literals"
    }

    _write(
        app,
        "modules/billing/router.py",
        "@router.post('/export', dependencies=[Depends(require_permission('billing.export'))])\n"
        "def export() -> None:\n    return None\n",
    )
    assert _rule_names(check_no_adhoc_permission_literals(app)) == {
        "no_adhoc_permission_literals"
    }

    _write(
        app,
        "modules/billing/module.py",
        "from control_plane import permissions as perms\n"
        "module = ModuleSpec(name='billing', policy=Policy(read=perms.BILLING_READ))\n",
    )
    _write(
        app,
        "modules/billing/router.py",
        "from control_plane import permissions as perms\n"
        "@router.post('/export', dependencies=[Depends(require_permission(perms.BILLING_EXPORT))])\n"
        "def export() -> None:\n    return None\n",
    )
    assert check_no_adhoc_permission_literals(app) == []


def test_policy_refs_resolve(tmp_path: pathlib.Path) -> None:
    app = tmp_path / "app"

    # Referencing the registry without a control_plane/permissions.py at all fails.
    _write(
        app,
        "modules/billing/module.py",
        "from control_plane import permissions as perms\n"
        "module = ModuleSpec(name='billing', policy=Policy(read=perms.BILLING_READ))\n",
    )
    assert _rule_names(check_policy_refs_resolve(app)) == {"policy_refs_resolve"}

    # An undeclared authority name is a violation â€” module alias spelling.
    _write(
        tmp_path,
        "control_plane/permissions.py",
        "from terp.core import EDITOR, Permission\n"
        "BILLING_EXPORT = Permission('billing.export', min_role=EDITOR)\n",
    )
    assert _rule_names(check_policy_refs_resolve(app)) == {"policy_refs_resolve"}

    # ...and the from-import spelling, in a require_permission seam.
    _write(
        app,
        "modules/billing/module.py",
        "from control_plane.permissions import BILLING_READ\n"
        "module = ModuleSpec(name='billing', policy=Policy(read=BILLING_READ))\n",
    )
    assert _rule_names(check_policy_refs_resolve(app)) == {"policy_refs_resolve"}

    _write(
        app,
        "modules/billing/router.py",
        "import control_plane.permissions as perms\n"
        "@router.post('/x', dependencies=[Depends(require_permission(perms.MISSING))])\n"
        "def x() -> None:\n    return None\n",
    )
    assert len(check_policy_refs_resolve(app)) == 2

    # Declared names resolve â€” assignment, tuple/annotated targets, aliased
    # from-import, and registry re-export.
    _write(
        tmp_path,
        "control_plane/permissions.py",
        "from terp.core import EDITOR, Permission\n"
        "BILLING_READ = Permission('billing.read', min_role=EDITOR)\n"
        "MISSING, _EXTRA = BILLING_READ, None\n"
        "ANNOTATED: Permission = BILLING_READ\n",
    )
    _write(
        app,
        "modules/billing/module.py",
        "from control_plane.permissions import BILLING_READ as CAN_READ\n"
        "module = ModuleSpec(name='billing', policy=Policy(read=CAN_READ))\n",
    )
    assert check_policy_refs_resolve(app) == []

    # References the scan cannot trace to the registry are left to the boot check â€”
    # kernel defaults, and expressions with no dotted-name root.
    _write(
        app,
        "modules/billing/module.py",
        "from control_plane import permissions as perms\n"
        "from terp.core import Roles\n"
        "module = ModuleSpec(name='billing', policy=Policy(read=Roles.VIEWER, write=perms.BILLING_READ))\n",
    )
    assert check_policy_refs_resolve(app) == []

    _write(
        app,
        "modules/billing/router.py",
        "import control_plane.permissions as perms\n"
        "@router.post('/x', dependencies=[Depends(require_permission(_pick(perms).MISSING))])\n"
        "def x() -> None:\n    return None\n",
    )
    assert check_policy_refs_resolve(app) == []

    # A file that never names the registry is out of scope.
    _write(
        app,
        "modules/notes/module.py",
        "module = ModuleSpec(name='notes', policy=Policy.default())\n",
    )
    assert check_policy_refs_resolve(app) == []


def test_table_models_use_base_table(tmp_path: pathlib.Path) -> None:
    app = tmp_path / "app"
    _write(
        app,
        "modules/notes/models.py",
        "class Note(SQLModel, table=True):\n    title: str\n",
    )
    assert _rule_names(check_table_models_use_base_table(app)) == {
        "table_models_use_base_table"
    }

    _write(
        app,
        "modules/notes/models.py",
        "class Note(BaseTable, table=True):\n    title: str = Field(max_length=20)\n",
    )
    assert check_table_models_use_base_table(app) == []


def test_no_manual_table_schema(tmp_path: pathlib.Path) -> None:
    app = tmp_path / "app"
    # A hand-written schema pin escapes the deployment-managed layout (ADR 0070).
    _write(
        app,
        "modules/notes/models.py",
        "class Note(BaseTable, table=True):\n"
        "    __table_args__ = {'schema': 'custom'}\n"
        "    title: str = Field(max_length=20)\n",
    )
    assert _rule_names(check_no_manual_table_schema(app)) == {"no_manual_table_schema"}

    # The dict-inside-tuple form (constraints + kwargs) is caught too.
    _write(
        app,
        "modules/notes/models.py",
        "class Note(BaseTable, table=True):\n"
        "    __table_args__ = (UniqueConstraint('title'), {'schema': 'custom'})\n"
        "    title: str = Field(max_length=20)\n",
    )
    assert _rule_names(check_no_manual_table_schema(app)) == {"no_manual_table_schema"}

    # Constraint-only __table_args__ (the legitimate use) stays clean.
    _write(
        app,
        "modules/notes/models.py",
        "class Note(BaseTable, table=True):\n"
        "    __table_args__ = (UniqueConstraint('title'),)\n"
        "    title: str = Field(max_length=20)\n",
    )
    assert check_no_manual_table_schema(app) == []


def test_no_unique_columns_on_soft_delete_models(tmp_path: pathlib.Path) -> None:
    app = tmp_path / "app"
    # A full-table unique on a soft-delete model: the dead row blocks reuse forever.
    _write(
        app,
        "modules/notes/models.py",
        "class Note(BaseTable, SoftDeleteMixin, table=True):\n"
        "    slug: str = Field(max_length=50, unique=True)\n",
    )
    assert _rule_names(check_no_unique_columns_on_soft_delete_models(app)) == {
        "no_unique_columns_on_soft_delete_models"
    }

    # The __table_args__ forms are caught too: UniqueConstraint and full-table Index.
    _write(
        app,
        "modules/notes/models.py",
        "class Note(BaseTable, SoftDeleteMixin, table=True):\n"
        "    __table_args__ = (UniqueConstraint('slug'),)\n"
        "    slug: str = Field(max_length=50)\n",
    )
    assert _rule_names(check_no_unique_columns_on_soft_delete_models(app)) == {
        "no_unique_columns_on_soft_delete_models"
    }
    _write(
        app,
        "modules/notes/models.py",
        "class Note(BaseTable, SoftDeleteMixin, table=True):\n"
        "    __table_args__ = (Index('uq_note_slug', 'slug', unique=True),)\n"
        "    slug: str = Field(max_length=50)\n",
    )
    assert _rule_names(check_no_unique_columns_on_soft_delete_models(app)) == {
        "no_unique_columns_on_soft_delete_models"
    }

    # The FIX is accepted: a partial unique index scoped to the live rows.
    _write(
        app,
        "modules/notes/models.py",
        "class Note(BaseTable, SoftDeleteMixin, table=True):\n"
        "    __table_args__ = (Index('uq_note_slug_live', 'slug', unique=True,\n"
        "        postgresql_where=text('deleted_at IS NULL'),\n"
        "        sqlite_where=text('deleted_at IS NULL')),)\n"
        "    slug: str = Field(max_length=50)\n",
    )
    assert check_no_unique_columns_on_soft_delete_models(app) == []

    # A unique on a NON-soft-delete model is fine (rows are truly gone on delete)â€¦
    _write(
        app,
        "modules/notes/models.py",
        "class Note(BaseTable, table=True):\n"
        "    slug: str = Field(max_length=50, unique=True)\n",
    )
    assert check_no_unique_columns_on_soft_delete_models(app) == []

    # â€¦as is a soft-delete model without unique columns, and a non-table schema class.
    _write(
        app,
        "modules/notes/models.py",
        "class Note(BaseTable, SoftDeleteMixin, table=True):\n"
        "    slug: str = Field(max_length=50, index=True)\n"
        "class NoteRead(BaseSchema, SoftDeleteMixin):\n"
        "    slug: str = Field(max_length=50, unique=True)\n",
    )
    assert check_no_unique_columns_on_soft_delete_models(app) == []


def test_no_unique_columns_on_soft_delete_models_follows_an_app_owned_base(
    tmp_path: pathlib.Path,
) -> None:
    app = tmp_path / "app"
    # ADR 0011's recommended pattern: the trait is factored into an app-owned base
    # (in its own file, outside modules/), and table models inherit *that*. The
    # guard must follow the inheritance, not only a direct SoftDeleteMixin base.
    _write(app, "_base.py", "class AppTable(BaseTable, SoftDeleteMixin):\n    pass\n")
    _write(
        app,
        "modules/notes/models.py",
        "class Note(AppTable, table=True):\n"
        "    slug: str = Field(max_length=50, unique=True)\n",
    )
    assert _rule_names(check_no_unique_columns_on_soft_delete_models(app)) == {
        "no_unique_columns_on_soft_delete_models"
    }

    # A transitive chain (base of a base) is followed too.
    _write(
        app,
        "_base.py",
        "class AppTable(BaseTable, SoftDeleteMixin):\n    pass\n"
        "class AuditedTable(AppTable):\n    pass\n",
    )
    _write(
        app,
        "modules/notes/models.py",
        "class Note(AuditedTable, table=True):\n"
        "    slug: str = Field(max_length=50, unique=True)\n",
    )
    assert _rule_names(check_no_unique_columns_on_soft_delete_models(app)) == {
        "no_unique_columns_on_soft_delete_models"
    }


def test_no_unique_columns_on_soft_delete_models_requires_every_verified_dialect(
    tmp_path: pathlib.Path,
) -> None:
    app = tmp_path / "app"
    # A Postgres-only partial index compiles to a FULL unique index on SQLite (the
    # dev/test dialect), reinstating the dead-row trap â€” so it must stay flagged.
    _write(
        app,
        "modules/notes/models.py",
        "class Note(BaseTable, SoftDeleteMixin, table=True):\n"
        "    __table_args__ = (Index('uq_note_slug_live', 'slug', unique=True,\n"
        "        postgresql_where=text('deleted_at IS NULL')),)\n"
        "    slug: str = Field(max_length=50)\n",
    )
    assert _rule_names(check_no_unique_columns_on_soft_delete_models(app)) == {
        "no_unique_columns_on_soft_delete_models"
    }


def test_no_app_instantiation(tmp_path: pathlib.Path) -> None:
    app = tmp_path / "app"
    _write(app, "modules/notes/router.py", "app = FastAPI()\n")
    assert _rule_names(check_no_app_instantiation(app)) == {"no_app_instantiation"}

    _write(
        app,
        "modules/notes/router.py",
        "from terp.core import create_app\nrouter = APIRouter()\n",
    )
    assert check_no_app_instantiation(app) == []


def test_no_adhoc_background_runtime(tmp_path: pathlib.Path) -> None:
    app = tmp_path / "app"
    # Broker / scheduler engines are flagged wherever they are imported (import + from),
    # including a submodule (apscheduler.schedulers...) and the azure.servicebus broker.
    for stmt in (
        "import celery",
        "from celery import Celery",
        "import redis",
        "from redis import Redis",
        "import apscheduler",
        "from apscheduler.schedulers.background import BackgroundScheduler",
        "import azure.servicebus",
        "from azure.servicebus import ServiceBusClient",
        "from azure.servicebus.aio import ServiceBusClient",
    ):
        _write(app, "modules/notes/service.py", f"{stmt}\n")
        assert _rule_names(check_no_adhoc_background_runtime(app)) == {
            "no_adhoc_background_runtime"
        }, stmt

    # A raw thread / process is ad-hoc background execution outside the jobs seam â€” flagged
    # (a bare ``import threading`` can reach Thread; an explicit Thread/Process/pool name).
    for stmt in (
        "import threading",
        "from threading import Thread",
        "import multiprocessing",
        "from multiprocessing import Process",
        "from multiprocessing import Pool",
    ):
        _write(app, "modules/notes/service.py", f"{stmt}\n")
        assert _rule_names(check_no_adhoc_background_runtime(app)) == {
            "no_adhoc_background_runtime"
        }, stmt

    # A synchronization primitive imported by name is a correctness tool, not background
    # execution â€” allowed (exactly what the users cap's last-admin lock imports).
    for stmt in (
        "from threading import RLock",
        "from threading import Lock, Event, Condition",
        "from multiprocessing import Lock",
    ):
        _write(app, "modules/notes/service.py", f"{stmt}\n")
        assert check_no_adhoc_background_runtime(app) == [], stmt

    # Reaching background work through the jobs seam is the clean path.
    _write(app, "modules/notes/service.py", "from terp.core import enqueue\n")
    assert check_no_adhoc_background_runtime(app) == []


def test_no_adhoc_middleware(tmp_path: pathlib.Path) -> None:
    app = tmp_path / "app"
    # Calling add_middleware in a module hand-rolls a cross-cutting HTTP concern.
    _write(app, "modules/notes/router.py", "app.add_middleware(CORSMiddleware)\n")
    assert _rule_names(check_no_adhoc_middleware(app)) == {"no_adhoc_middleware"}

    # Subclassing the Starlette middleware base is the same drift by another route.
    _write(
        app,
        "modules/notes/mw.py",
        "class Sneaky(BaseHTTPMiddleware):\n    async def dispatch(self, r, n):\n        return await n(r)\n",
    )
    assert _rule_names(check_no_adhoc_middleware(app)) == {"no_adhoc_middleware"}

    # The @app.middleware("http") decorator form is the same drift again.
    _write(
        app,
        "modules/notes/mw.py",
        "@app.middleware('http')\nasync def mw(request, call_next):\n    return await call_next(request)\n",
    )
    assert _rule_names(check_no_adhoc_middleware(app)) == {"no_adhoc_middleware"}

    # A module that wires no middleware is clean (security lives in SecurityConfig).
    _write(
        app,
        "modules/notes/router.py",
        "from terp.core import create_app\nrouter = APIRouter()\n",
    )
    _write(app, "modules/notes/mw.py", "from terp.core import SecurityConfig\n")
    assert check_no_adhoc_middleware(app) == []


def test_no_raw_app_routes(tmp_path: pathlib.Path) -> None:
    app = tmp_path / "app"
    # The app-level registration APIs have no legitimate app-code use at all:
    # each puts surface on the app outside the per-module deny-by-default guard.
    for stmt in (
        "app.mount('/static', files_app)",
        "app.include_router(router, prefix='/api/v1/raw')",
        "app.add_route('/raw', endpoint)",
        "app.add_websocket_route('/ws', endpoint)",
        "router.include_router(subrouter)",  # nesting: modules declare ONE flat router
    ):
        _write(app, "main.py", f"{stmt}\n")
        assert _rule_names(check_no_raw_app_routes(app)) == {"no_raw_app_routes"}, stmt

    # A verb route on a name bound from create_app(...) bypasses the module guard.
    _write(
        app,
        "main.py",
        "from terp.core import create_app\n"
        "app = create_app([])\n"
        "@app.get('/api/v1/hacks/')\n"
        "def hacks() -> dict:\n"
        "    return {}\n",
    )
    assert _rule_names(check_no_raw_app_routes(app)) == {"no_raw_app_routes"}

    # Equivalent create_app bindings must not dodge the app-receiver check.
    for source in (
        "from fastapi import FastAPI\n"
        "from terp.core import create_app\n"
        "app: FastAPI = create_app([])\n"
        "@app.get('/api/v1/hacks/')\n"
        "def hacks() -> dict:\n"
        "    return {}\n",
        "from terp.core import create_app as make_app\n"
        "app = make_app([])\n"
        "@app.route('/api/v1/hacks/')\n"
        "def hacks(request):\n"
        "    return {}\n",
        "from terp.core import create_app\n"
        "def build():\n"
        "    app = create_app([])\n"
        "    return app\n"
        "app = build()\n"
        "@app.websocket_route('/ws')\n"
        "async def ws(websocket):\n"
        "    ...\n",
    ):
        _write(app, "main.py", source)
        assert _rule_names(check_no_raw_app_routes(app)) == {"no_raw_app_routes"}

    # ... and the same through the canonical factory spelling (app = build()).
    _write(
        app,
        "main.py",
        "from terp.core import create_app\n"
        "def build():\n"
        "    return create_app([])\n"
        "app = build()\n"
        "app.add_api_route('/api/v1/hacks/', hacks, methods=['POST'])\n",
    )
    assert _rule_names(check_no_raw_app_routes(app)) == {"no_raw_app_routes"}

    # Reaching through FastAPI's underlying router is the same app-level bypass.
    _write(
        app,
        "main.py",
        "from terp.core import create_app\n"
        "app = create_app([])\n"
        "app.router.add_api_route('/api/v1/hacks/', hacks, methods=['GET'])\n",
    )
    assert _rule_names(check_no_raw_app_routes(app)) == {"no_raw_app_routes"}

    # Lifecycle hooks on the composed app are ungated executable registration.
    for hook in (
        "@app.on_event('startup')\ndef warm():\n    ...\n",
        "app.add_event_handler('startup', warm)\n",
    ):
        _write(
            app,
            "main.py",
            "from terp.core import create_app\napp = create_app([])\n" + hook,
        )
        assert _rule_names(check_no_raw_app_routes(app)) == {"no_raw_app_routes"}, hook

    # The canonical composition root is clean: build() + module-owned routers
    # (a verb decorator on a module ROUTER is not app surface).
    _write(
        app,
        "main.py",
        "from terp.core import create_app\n"
        "from app.modules.notes.module import module as notes_module\n"
        "def build():\n"
        "    return create_app([notes_module])\n"
        "app = build()\n",
    )
    _write(
        app,
        "modules/notes/router.py",
        "router = APIRouter()\n"
        "@router.get('/', response_model=Page[NoteRead])\n"
        "def list_notes() -> Page[NoteRead]:\n"
        "    ...\n",
    )
    assert check_no_raw_app_routes(app) == []


def test_no_dependency_overrides(tmp_path: pathlib.Path) -> None:
    app = tmp_path / "app"
    # Rebinding the principal seam in app code silently disables authentication.
    _write(
        app,
        "main.py",
        "from terp.core import create_app, get_principal\n"
        "app = create_app([])\n"
        "app.dependency_overrides[get_principal] = lambda: None\n",
    )
    assert _rule_names(check_no_dependency_overrides(app)) == {"no_dependency_overrides"}

    # ...any spelling that touches the mapping is the same bypass.
    _write(app, "main.py", "app.dependency_overrides.update({})\n")
    assert _rule_names(check_no_dependency_overrides(app)) == {"no_dependency_overrides"}

    # The canonical composition root never touches overrides.
    _write(
        app,
        "main.py",
        "from terp.core import create_app\n"
        "def build():\n"
        "    return create_app([])\n"
        "app = build()\n",
    )
    assert check_no_dependency_overrides(app) == []


def test_no_adhoc_logging_config(tmp_path: pathlib.Path) -> None:
    app = tmp_path / "app"
    for call in ("logging.basicConfig(level=10)", "dictConfig({})", "fileConfig('x.ini')"):
        _write(app, "modules/notes/service.py", f"{call}\n")
        assert _rule_names(check_no_adhoc_logging_config(app)) == {
            "no_adhoc_logging_config"
        }

    # Reading the central context var / logger is fine; only *configuring* is banned.
    _write(
        app,
        "modules/notes/service.py",
        "import logging\nlogger = logging.getLogger(__name__)\n",
    )
    assert check_no_adhoc_logging_config(app) == []


def test_mutations_emit_audit(tmp_path: pathlib.Path) -> None:
    app = tmp_path / "app"
    # A raw session write in a module bypasses the audited BaseService chokepoint.
    _write(app, "modules/notes/service.py", "session.add(note)\nsession.commit()\n")
    assert _rule_names(check_mutations_emit_audit(app)) == {"mutations_emit_audit"}

    # session.delete is the same drift, and a differently-named session var too.
    _write(app, "modules/notes/service.py", "db.delete(row)\n")
    assert _rule_names(check_mutations_emit_audit(app)) == {"mutations_emit_audit"}

    # Renaming the session variable does not evade the rule: a parameter annotated
    # SessionDep is a session handle whatever it is called (add + flush = 2 writes).
    _write(
        app,
        "modules/notes/service.py",
        "def run(s: SessionDep) -> None:\n    s.add(note)\n    s.flush()\n",
    )
    violations = check_mutations_emit_audit(app)
    assert _rule_names(violations) == {"mutations_emit_audit"}
    assert len(violations) == 2

    # A write smuggled through execute()/exec() with a DML statement is caught â€”
    # raw text and a chained update() both resolve to a DML chain-root.
    _write(
        app,
        "modules/notes/service.py",
        "session.execute(text('UPDATE notes SET title=:t'))\n",
    )
    assert _rule_names(check_mutations_emit_audit(app)) == {"mutations_emit_audit"}
    _write(
        app,
        "modules/notes/service.py",
        "def run(session: SessionDep):\n    session.exec(update(Note).values(title='x'))\n",
    )
    assert _rule_names(check_mutations_emit_audit(app)) == {"mutations_emit_audit"}

    # A precomputed DML statement is still a direct session write and is caught.
    _write(
        app,
        "modules/notes/service.py",
        "def run(session: SessionDep):\n    stmt = update(Note).values(title='x')\n    session.execute(stmt)\n",
    )
    assert _rule_names(check_mutations_emit_audit(app)) == {"mutations_emit_audit"}

    # Reading through exec(select(...)) or text('SELECT ...') is NOT a mutation.
    _write(
        app,
        "modules/notes/service.py",
        "def read(session: SessionDep):\n    return session.exec(select(Note)).all()\n",
    )
    assert check_mutations_emit_audit(app) == []

    _write(
        app,
        "modules/notes/service.py",
        "def read(session: SessionDep):\n    return session.execute(text('SELECT 1')).all()\n",
    )
    assert check_mutations_emit_audit(app) == []

    # Session-typed names are scoped to their function; a different function can
    # reuse the same parameter name for an ordinary collection without being flagged.
    _write(
        app,
        "modules/notes/service.py",
        "def writer(s: SessionDep):\n    s.commit()\n\ndef ordinary(s: set):\n    s.add('x')\n",
    )
    assert [(violation.rule, violation.line) for violation in check_mutations_emit_audit(app)] == [
        ("mutations_emit_audit", 2)
    ]

    # Calling the model's service / the audited _save hook is the sanctioned path;
    # a method named like a mutator on a non-session receiver is not flagged.
    _write(
        app,
        "modules/notes/router.py",
        "_service.delete(session, note_id)\nitems.add(thing)\n",
    )
    _write(
        app,
        "modules/notes/service.py",
        "self._save(session, note, AuditAction.DELETED)\n",
    )
    assert check_mutations_emit_audit(app) == []


def test_routes_declare_response_model(tmp_path: pathlib.Path) -> None:
    app = tmp_path / "app"
    _write(
        app,
        "modules/notes/router.py",
        "@router.get('/')\ndef list_notes():\n    return []\n",
    )
    assert _rule_names(check_routes_declare_response_model(app)) == {"routes_declare_response_model"}

    # A ``-> None`` annotation alone no longer exempts a route: only a no-body
    # status code (204/205/304) does. A handler annotated ``-> None`` that still
    # returns a body would otherwise leak it, so it must be flagged.
    _write(
        app,
        "modules/notes/router.py",
        "@router.delete('/{x}')\ndef remove(x) -> None:\n    return secret_payload()\n",
    )
    assert _rule_names(check_routes_declare_response_model(app)) == {"routes_declare_response_model"}

    # Clean: a declared response_model, and a delete that advertises a no-body 204.
    _write(
        app,
        "modules/notes/router.py",
        "@router.get('/', response_model=Page)\ndef list_notes() -> Page:\n    return Page()\n"
        "@router.delete('/{x}', status_code=204)\ndef remove(x) -> None:\n    return None\n",
    )
    assert check_routes_declare_response_model(app) == []

    # Imperative registration is covered too: add_api_route without a response_model
    # or a no-body status is flagged (constant and non-constant paths both reported).
    _write(
        app,
        "modules/notes/router.py",
        "router.add_api_route('/things', list_things)\n"
        "router.add_api_route(PREFIX, more_things)\n",
    )
    flagged = check_routes_declare_response_model(app)
    assert _rule_names(flagged) == {"routes_declare_response_model"}
    assert len(flagged) == 2

    # ...and clean when it declares a response_model, or a no-body status named
    # symbolically (status.HTTP_204_NO_CONTENT), not only a bare 204 literal.
    _write(
        app,
        "modules/notes/router.py",
        "router.add_api_route('/things', list_things, response_model=Page)\n"
        "router.add_api_route('/things/{x}', remove, status_code=status.HTTP_204_NO_CONTENT)\n",
    )
    assert check_routes_declare_response_model(app) == []


def test_response_model_not_table_model(tmp_path: pathlib.Path) -> None:
    app = tmp_path / "app"

    # Returning the persisted table model -- wrapped in Page[...] -- leaks it.
    _write(
        app,
        "modules/users/router.py",
        "class User(BaseTable, table=True):\n    secret: str\n\n"
        "@router.get('/', response_model=Page[User])\n"
        "def list_users() -> Page[User]:\n    return Page()\n",
    )
    assert _rule_names(check_response_model_not_table_model(app)) == {
        "response_model_not_table_model"
    }

    # An attribute-qualified table model (``models.User``) is caught too.
    _write(
        app,
        "modules/users/router.py",
        "class User(BaseTable, table=True):\n    secret: str\n\n"
        "@router.post('/', response_model=models.User, status_code=201)\n"
        "def create() -> None:\n    return None\n",
    )
    assert _rule_names(check_response_model_not_table_model(app)) == {
        "response_model_not_table_model"
    }

    # A *Read DTO is clean; non-call / non-HTTP decorators are ignored.
    _write(
        app,
        "modules/users/router.py",
        "class User(BaseTable, table=True):\n    secret: str\n\n"
        "class UserRead(BaseSchema):\n    name: str\n\n"
        "@staticmethod\ndef helper():\n    return None\n\n"
        "@guard()\ndef gated():\n    return None\n\n"
        "@app.on_event('startup')\ndef boot():\n    return None\n\n"
        "@router.get('/', response_model=Page[UserRead])\n"
        "def list_users() -> Page[UserRead]:\n    return Page()\n"
        "@router.delete('/{x}', status_code=204)\ndef remove(x) -> None:\n    return None\n",
    )
    assert check_response_model_not_table_model(app) == []

    # The same leak through the build_crud_router factory (read_schema=) is caught;
    # a *Read DTO passed as read_schema is clean.
    _write(
        app,
        "modules/users/router.py",
        "class User(BaseTable, table=True):\n    secret: str\n\n"
        "router = build_crud_router(UserService(), read_schema=User,\n"
        "    create_schema=UserCreate, update_schema=UserUpdate)\n",
    )
    assert _rule_names(check_response_model_not_table_model(app)) == {
        "response_model_not_table_model"
    }

    _write(
        app,
        "modules/users/router.py",
        "class User(BaseTable, table=True):\n    secret: str\n\n"
        "class UserRead(BaseSchema):\n    id: int\n\n"
        "router = build_crud_router(UserService(), read_schema=UserRead,\n"
        "    create_schema=UserCreate, update_schema=UserUpdate)\n",
    )
    assert check_response_model_not_table_model(app) == []


def test_no_raw_session_construction(tmp_path: pathlib.Path) -> None:
    app = tmp_path / "app"
    _write(
        app,
        "modules/notes/service.py",
        "def run(engine):\n    with Session(engine) as s:\n        return s\n",
    )
    assert _rule_names(check_no_raw_session_construction(app)) == {"no_raw_session_construction"}

    _write(
        app,
        "modules/notes/service.py",
        "from terp.core import SessionDep\ndef run(session: SessionDep):\n    return session\n",
    )
    assert check_no_raw_session_construction(app) == []


def test_no_dynamic_sql(tmp_path: pathlib.Path) -> None:
    app = tmp_path / "app"
    dynamic_sources = (
        "text(f'SELECT * FROM notes WHERE id={note_id}')",
        "text('SELECT * FROM ' + table_name)",
        "text('SELECT * FROM {}'.format(table_name))",
        "text('SELECT * FROM %s' % table_name)",
        "sqlalchemy.text(query)",
    )
    for source in dynamic_sources:
        _write(app, "modules/notes/service.py", f"def run():\n    return {source}\n")
        assert _rule_names(check_no_dynamic_sql(app)) == {"no_dynamic_sql"}, source

    # Literal SQL is reviewable; parameters belong outside the SQL string.
    _write(app, "modules/notes/service.py", "stmt = text('SELECT * FROM notes WHERE id=:id')\n")
    assert check_no_dynamic_sql(app) == []

    # The rule follows app-module scope, not arbitrary helper files.
    _write(app, "helpers/sql.py", "stmt = text(query)\n")
    _write(app, "modules/notes/service.py", "stmt = text('SELECT 1')\n")
    assert check_no_dynamic_sql(app) == []

    # tests/ and migrations/ dirs inside a module are importable code: still scanned (G1).
    _write(app, "modules/notes/tests/helper.py", "stmt = text(query)\n")
    assert _rule_names(check_no_dynamic_sql(app)) == {"no_dynamic_sql"}



def test_no_naive_datetime(tmp_path: pathlib.Path) -> None:
    app = tmp_path / "app"
    # The deprecated naive constructor and a bare now() both erase the timezone.
    naive_sources = (
        "datetime.utcnow()",
        "datetime.now()",
        "dt.datetime.utcnow()",
        "dt.datetime.now()",
    )
    for source in naive_sources:
        _write(app, "modules/notes/service.py", f"def run():\n    return {source}\n")
        assert _rule_names(check_no_naive_datetime(app)) == {"no_naive_datetime"}, source

    # An explicit zone makes now() aware â€” positional or keyword.
    _write(app, "modules/notes/service.py", "stamp = datetime.now(UTC)\n")
    assert check_no_naive_datetime(app) == []
    _write(app, "modules/notes/service.py", "stamp = datetime.now(tz=timezone.utc)\n")
    assert check_no_naive_datetime(app) == []

    # A ``now`` on some other object is not the datetime constructor: no false positive.
    _write(app, "modules/notes/service.py", "value = clock.now()\n")
    assert check_no_naive_datetime(app) == []


def test_datetime_columns_are_timezone_aware(tmp_path: pathlib.Path) -> None:
    app = tmp_path / "app"

    def model(fields: str) -> str:
        return f"class Note(BaseTable, table=True):\n{fields}"

    # Every way of declaring a timestamp column WITHOUT pinning the zone: a bare
    # annotation, a Field() that never names the column type, an optional column,
    # and an explicit timezone=False (the zone is dropped just as thoroughly).
    naive_columns = (
        "    due_at: datetime\n",
        "    due_at: datetime = Field(default=None)\n",
        "    due_at: datetime | None = Field(default=None, index=True)\n",
        "    due_at: datetime = Field(sa_type=DateTime(timezone=False))\n",
        "    due_at: datetime.datetime = Field(default=None)\n",
    )
    for fields in naive_columns:
        _write(app, "modules/notes/models.py", model(fields))
        assert _rule_names(check_datetime_columns_are_timezone_aware(app)) == {
            "datetime_columns_are_timezone_aware"
        }, fields

    # Pinning timezone=True is compliant, however the type is spelled or carried:
    # sa_type=, sa_column=Column(...), a qualified name, and the TIMESTAMP alias.
    aware_columns = (
        "    due_at: datetime = Field(sa_type=DateTime(timezone=True))\n",
        "    due_at: datetime | None = Field(sa_column=Column(DateTime(timezone=True)))\n",
        "    due_at: datetime = Field(sa_type=sa.DateTime(timezone=True))\n",
        "    due_at: datetime = Field(sa_type=TIMESTAMP(timezone=True))\n",
        "    due_at: datetime.datetime = Field(sa_type=DateTime(timezone=True))\n",
    )
    for fields in aware_columns:
        _write(app, "modules/notes/models.py", model(fields))
        assert check_datetime_columns_are_timezone_aware(app) == [], fields

    # Non-timestamp columns are none of this rule's business.
    _write(app, "modules/notes/models.py", model("    title: str = Field(max_length=200)\n"))
    assert check_datetime_columns_are_timezone_aware(app) == []

    # The rule is about *columns*: a class that is not a table (a schema DTO, a
    # mixin) declares no storage, so its timestamps are not flagged.
    _write(
        app,
        "modules/notes/schemas.py",
        "class NoteRead(BaseSchema):\n    due_at: datetime\n",
    )
    _write(app, "modules/notes/models.py", model("    title: str = Field(max_length=200)\n"))
    assert check_datetime_columns_are_timezone_aware(app) == []

    # A non-Name assignment target still reports, naming the field generically.
    _write(
        app,
        "modules/notes/models.py",
        "class Note(BaseTable, table=True):\n    obj.due_at: datetime = Field(default=None)\n",
    )
    assert _rule_names(check_datetime_columns_are_timezone_aware(app)) == {
        "datetime_columns_are_timezone_aware"
    }

    # A column inherited from a mixin lands on the table just the same, so a naive
    # timestamp cannot be hidden by declaring it one class up.
    _write(
        app,
        "modules/notes/models.py",
        "class ArchivedMixin:\n"
        "    archived_at: datetime | None = Field(default=None)\n\n\n"
        "class Note(ArchivedMixin, BaseTable, table=True):\n"
        "    title: str = Field(max_length=200)\n",
    )
    assert _rule_names(check_datetime_columns_are_timezone_aware(app)) == {
        "datetime_columns_are_timezone_aware"
    }

    # The same mixin with a timezone-aware column is clean.
    _write(
        app,
        "modules/notes/models.py",
        "class ArchivedMixin:\n"
        "    archived_at: datetime | None = Field(sa_type=DateTime(timezone=True))\n\n\n"
        "class Note(ArchivedMixin, BaseTable, table=True):\n"
        "    title: str = Field(max_length=200)\n",
    )
    assert check_datetime_columns_are_timezone_aware(app) == []

    # A class that no table inherits stays out of scope, even next to one that does.
    _write(
        app,
        "modules/notes/models.py",
        "class DraftPayload:\n"
        "    due_at: datetime = Field(default=None)\n\n\n"
        "class Note(BaseTable, table=True):\n"
        "    title: str = Field(max_length=200)\n",
    )
    assert check_datetime_columns_are_timezone_aware(app) == []

    # A subscripted base unwraps to its leaf name, and a base with no simple name
    # at all must not crash the mixin scan.
    _write(
        app,
        "modules/notes/models.py",
        "class Note(Base[int], make_mixin(), BaseTable, table=True):\n"
        "    due_at: datetime = Field(default=None)\n",
    )
    assert _rule_names(check_datetime_columns_are_timezone_aware(app)) == {
        "datetime_columns_are_timezone_aware"
    }


def test_no_oversized_python_files(tmp_path: pathlib.Path) -> None:
    app = tmp_path / "app"

    # A file over the 500-line cap is flagged once, at line 1 (so the opt-out marker
    # sits naturally at the top of the file).
    oversized = "\n".join(f"CONSTANT_{i} = {i}" for i in range(1, 521)) + "\n"
    _write(app, "modules/notes/service.py", oversized)
    violations = check_no_oversized_python_files(app)
    assert _rule_names(violations) == {"no_oversized_python_files"}
    assert [violation.line for violation in violations] == [1]

    # A file exactly at the cap is fine â€” the boundary is inclusive.
    at_cap = "\n".join(f"CONSTANT_{i} = {i}" for i in range(1, 501)) + "\n"
    _write(app, "modules/notes/service.py", at_cap)
    assert check_no_oversized_python_files(app) == []

    # The test tree and migration history are out of scope even when oversized.
    _write(app, "tests/test_big.py", oversized)
    _write(app, "modules/notes/migrations/0001_big.py", oversized)
    assert check_no_oversized_python_files(app) == []


def test_oversized_file_message_proposes_a_seam(tmp_path: pathlib.Path) -> None:
    """The cap names a number; the expensive half is finding the cut, so it names that too.

    The checker already parses the file, so the connected components of its
    top-level definitions are free information. Withholding them makes the author
    re-derive by hand what the tool computed — the one consistent friction.
    """
    app = tmp_path / "app"
    body = "\n".join(f"    x{i} = {i}" for i in range(520))

    # Two groups that never mention each other: one is liftable as a unit.
    source = (
        "def alpha_one():\n" + body + "\n\n"
        "def alpha_two():\n    return alpha_one()\n\n"
        "def beta_one():\n    return 1\n\n"
        "def beta_two():\n    return beta_one()\n"
    )
    _write(app, "modules/notes/service.py", source)
    violations = check_no_oversized_python_files(app)
    assert _rule_names(violations) == {"no_oversized_python_files"}
    message = violations[0].message
    assert "alpha_one" in message and "alpha_two" in message
    assert "beta_one" not in message  # the smaller group is not the proposal

    # A file whose definitions all reference one another has no honest seam, so the
    # message stays the bare cap rather than inventing a cut that would couple two files.
    welded = "def root():\n" + body + "\n\n" + "".join(
        f"def leaf_{i}():\n    return root()\n\n" for i in range(5)
    )
    _write(app, "modules/notes/service.py", welded)
    welded_violations = check_no_oversized_python_files(app)
    assert _rule_names(welded_violations) == {"no_oversized_python_files"}
    assert "largest group" not in welded_violations[0].message



def test_no_eval_or_exec(tmp_path: pathlib.Path) -> None:
    app = tmp_path / "app"
    for source in ("eval(payload)", "exec(payload)"):
        _write(app, "modules/notes/service.py", f"def run(payload):\n    return {source}\n")
        assert _rule_names(check_no_eval_or_exec(app)) == {"no_eval_or_exec"}, source

    # Attribute access named ``eval``/``exec`` on some object is not the builtin.
    _write(app, "modules/notes/service.py", "def run(m):\n    return m.eval(1)\n")
    assert check_no_eval_or_exec(app) == []

    # The security surface covers tests and migrations too.
    _write(app, "modules/notes/service.py", "value = 1\n")
    _write(app, "tests/test_notes.py", "def test_x():\n    eval('1')\n")
    assert _rule_names(check_no_eval_or_exec(app)) == {"no_eval_or_exec"}


def test_no_star_imports(tmp_path: pathlib.Path) -> None:
    app = tmp_path / "app"
    _write(app, "modules/notes/service.py", "from os.path import *\n")
    assert _rule_names(check_no_star_imports(app)) == {"no_star_imports"}

    # Explicit names are fine.
    _write(app, "modules/notes/service.py", "from os.path import join, dirname\n")
    assert check_no_star_imports(app) == []


def test_no_blocking_sleep(tmp_path: pathlib.Path) -> None:
    app = tmp_path / "app"
    _write(app, "modules/notes/service.py", "import time\n\n\ndef run():\n    time.sleep(1)\n")
    assert _rule_names(check_no_blocking_sleep(app)) == {"no_blocking_sleep"}

    # A ``sleep`` attribute on some other object is not ``time.sleep``.
    _write(app, "modules/notes/service.py", "def run(worker):\n    worker.sleep(1)\n")
    assert check_no_blocking_sleep(app) == []


def test_no_print(tmp_path: pathlib.Path) -> None:
    app = tmp_path / "app"
    _write(app, "modules/notes/service.py", "def run():\n    print('hello')\n")
    assert _rule_names(check_no_print(app)) == {"no_print"}

    # Logging is the sanctioned diagnostic path.
    _write(
        app,
        "modules/notes/service.py",
        "import logging\n\nlog = logging.getLogger(__name__)\n\n\ndef run():\n    log.info('hi')\n",
    )
    assert check_no_print(app) == []


def test_no_todo_fixme(tmp_path: pathlib.Path) -> None:
    app = tmp_path / "app"
    for marker in ("TODO", "FIXME", "HACK", "XXX"):
        _write(app, "modules/notes/service.py", f"value = 1  # {marker}: finish this\n")
        assert _rule_names(check_no_todo_fixme(app)) == {"no_todo_fixme"}, marker

    # A marker-shaped word inside a string is not a comment: no false positive.
    _write(app, "modules/notes/service.py", "label = 'TODO list feature'\n")
    assert check_no_todo_fixme(app) == []


def test_no_mutable_default_args(tmp_path: pathlib.Path) -> None:
    app = tmp_path / "app"
    for default in ("[]", "{}", "{1, 2}"):
        _write(app, "modules/notes/service.py", f"def run(items={default}):\n    return items\n")
        assert _rule_names(check_no_mutable_default_args(app)) == {
            "no_mutable_default_args"
        }, default

    # A keyword-only mutable default is caught too.
    _write(app, "modules/notes/service.py", "def run(*, items={}):\n    return items\n")
    assert _rule_names(check_no_mutable_default_args(app)) == {"no_mutable_default_args"}

    # ``None`` + in-body construction is the compliant shape.
    _write(
        app,
        "modules/notes/service.py",
        "def run(items=None):\n    items = items or []\n    return items\n",
    )
    assert check_no_mutable_default_args(app) == []


def test_no_empty_tests(tmp_path: pathlib.Path) -> None:
    app = tmp_path / "app"
    empty_bodies = (
        "def test_a():\n    pass\n",
        "def test_b():\n    '''docstring only'''\n",
        "def test_c():\n    assert True\n",
    )
    for body in empty_bodies:
        _write(app, "tests/test_notes.py", body)
        assert _rule_names(check_no_empty_tests(app)) == {"no_empty_tests"}, body

    # A test with a real assertion is fine.
    _write(app, "tests/test_notes.py", "def test_ok():\n    assert 1 + 1 == 2\n")
    assert check_no_empty_tests(app) == []

    # Non-test functions are out of scope even if empty.
    _write(app, "tests/test_notes.py", "def helper():\n    pass\n")
    assert check_no_empty_tests(app) == []

    # A test file inside a security-skip dir (.venv) is vendored, not scanned.
    _write(app, ".venv/test_vendored.py", "def test_a():\n    pass\n")
    assert check_no_empty_tests(app) == []



def test_no_manual_version_assignment(tmp_path: pathlib.Path) -> None:
    app = tmp_path / "app"
    # Every spelling of writing the concurrency token by hand is refused.
    manual_writes = (
        "db_obj.version = data.version",
        "row.version += 1",
        "entity.version: int = 5",
        'setattr(db_obj, "version", data.version)',
    )
    for source in manual_writes:
        _write(app, "modules/notes/service.py", f"def run():\n    {source}\n")
        assert _rule_names(check_no_manual_version_assignment(app)) == {
            "no_manual_version_assignment"
        }, source

    # A plain local named ``version`` is not an attribute write on a row: allowed.
    _write(app, "modules/notes/service.py", "version = 1\n")
    assert check_no_manual_version_assignment(app) == []

    # setattr of some other attribute, and reading ``.version``, are both fine.
    _write(app, "modules/notes/service.py", 'setattr(db_obj, "title", data.title)\n')
    assert check_no_manual_version_assignment(app) == []
    _write(app, "modules/notes/service.py", "token = db_obj.version\n")
    assert check_no_manual_version_assignment(app) == []



def test_update_schemas_inherit_base_update_schema(tmp_path: pathlib.Path) -> None:
    app = tmp_path / "app"
    # An ``*Update`` DTO that does not reach the OCC base is refused.
    _write(app, "modules/notes/schemas.py", "class NoteUpdate(BaseSchema):\n    title: str\n")
    assert _rule_names(check_update_schemas_inherit_base_update_schema(app)) == {
        "update_schemas_inherit_base_update_schema"
    }

    # Direct inheritance of the OCC base is compliant.
    _write(app, "modules/notes/schemas.py", "class NoteUpdate(BaseUpdateSchema):\n    title: str\n")
    assert check_update_schemas_inherit_base_update_schema(app) == []

    # Transitive inheritance through another scanned class is compliant too.
    _write(
        app,
        "modules/notes/schemas.py",
        "class _Base(BaseUpdateSchema):\n    pass\n\n\nclass NoteUpdate(_Base):\n    title: str\n",
    )
    assert check_update_schemas_inherit_base_update_schema(app) == []

    # A class wired as a CRUD router's update body is held to the same contract.
    _write(app, "modules/notes/schemas.py", "class NotePatch(BaseSchema):\n    title: str\n")
    _write(
        app,
        "modules/notes/router.py",
        "router = build_crud_router(update_schema=NotePatch)\n",
    )
    assert _rule_names(check_update_schemas_inherit_base_update_schema(app)) == {
        "update_schemas_inherit_base_update_schema"
    }

    # The base itself and non-update classes are not flagged.
    _write(
        app,
        "modules/notes/schemas.py",
        "class NoteCreate(BaseSchema):\n    title: str\n",
    )
    _write(app, "modules/notes/router.py", "router = None\n")
    assert check_update_schemas_inherit_base_update_schema(app) == []

    # A local class literally named like the OCC base is the base definition itself,
    # not a DTO that must inherit it â€” it is skipped.
    _write(
        app,
        "modules/notes/schemas.py",
        "class BaseUpdateSchema(BaseSchema):\n    version: int\n",
    )
    assert check_update_schemas_inherit_base_update_schema(app) == []

    # A diamond of scanned bases that never reaches the OCC base is still refused â€” the
    # base-graph walk deduplicates revisited nodes and returns to report the DTO.
    _write(
        app,
        "modules/notes/schemas.py",
        "class A(BaseSchema):\n    pass\n\n\n"
        "class B(A):\n    pass\n\n\n"
        "class C(A):\n    pass\n\n\n"
        "class NoteUpdate(B, C):\n    title: str\n",
    )
    assert _rule_names(check_update_schemas_inherit_base_update_schema(app)) == {
        "update_schemas_inherit_base_update_schema"
    }



def test_input_str_fields_have_max_length(tmp_path: pathlib.Path) -> None:
    app = tmp_path / "app"
    _write(
        app,
        "modules/notes/schemas.py",
        "class NoteCreate(BaseSchema):\n    title: str\n",
    )
    assert _rule_names(check_input_str_fields_have_max_length(app)) == {
        "input_str_fields_have_max_length"
    }

    # Capped input + an uncapped Read schema (exempt: not table/Create/Update).
    _write(
        app,
        "modules/notes/schemas.py",
        "class NoteCreate(BaseSchema):\n    title: str = Field(max_length=200)\n"
        "class NoteRead(BaseSchema):\n    title: str\n",
    )
    assert check_input_str_fields_have_max_length(app) == []

    # A sequence container of str is as unbounded as a bare str: it must cap too.
    _write(
        app,
        "modules/notes/schemas.py",
        "class NoteCreate(BaseSchema):\n    tags: list[str]\n",
    )
    assert _rule_names(check_input_str_fields_have_max_length(app)) == {
        "input_str_fields_have_max_length"
    }
    _write(
        app,
        "modules/notes/schemas.py",
        "class NoteCreate(BaseSchema):\n    tags: list[str] = Field(max_length=20)\n",
    )
    assert check_input_str_fields_have_max_length(app) == []

    # An off-convention input DTO (not *Create/*Update) used as a request body is
    # still an input: route correlation flags its uncapped str, while a Read DTO
    # that is never a body stays exempt.
    _write(
        app,
        "modules/auth/router.py",
        "@router.post('/login')\ndef login(credentials: LoginRequest) -> None:\n    return None\n",
    )
    _write(
        app,
        "modules/auth/schemas.py",
        "class LoginRequest(BaseSchema):\n    password: str\n"
        "class SessionRead(BaseSchema):\n    token: str\n",
    )
    flagged = check_input_str_fields_have_max_length(app)
    assert _rule_names(flagged) == {"input_str_fields_have_max_length"}
    # The body model's field is flagged; the never-a-body Read DTO is not.
    assert all("LoginRequest" in violation.message for violation in flagged)

    _write(
        app,
        "modules/auth/schemas.py",
        "class LoginRequest(BaseSchema):\n    password: str = Field(max_length=256)\n"
        "class SessionRead(BaseSchema):\n    token: str\n",
    )
    assert check_input_str_fields_have_max_length(app) == []


def test_input_schemas_exclude_managed_columns(tmp_path: pathlib.Path) -> None:
    app = tmp_path / "app"
    # A *Create that exposes a framework-managed column (the primary key) is an
    # over-posting hole.
    _write(
        app,
        "modules/notes/schemas.py",
        "class NoteCreate(BaseSchema):\n"
        "    id: uuid.UUID\n"
        "    title: str = Field(max_length=200)\n",
    )
    assert _rule_names(check_input_schemas_exclude_managed_columns(app)) == {
        "input_schemas_exclude_managed_columns"
    }

    # Every managed column is rejected (version / tenant_id / actor stamps), on
    # *Update too -- not only the primary key on *Create.
    _write(
        app,
        "modules/notes/schemas.py",
        "class NoteUpdate(BaseUpdateSchema):\n"
        "    version: int\n"
        "    tenant_id: uuid.UUID\n"
        "    created_by_id: uuid.UUID\n",
    )
    flagged = check_input_schemas_exclude_managed_columns(app)
    assert {violation.message.split(":")[0].split(".")[1] for violation in flagged} == {
        "version",
        "tenant_id",
        "created_by_id",
    }

    # The session-revocation epoch is framework-managed too: client inputs must not
    # set or roll it back (that would revive old tokens or force-log users out).
    _write(
        app,
        "modules/notes/schemas.py",
        "class NoteUpdate(BaseUpdateSchema):\n"
        "    version: int\n"
        "    token_version: int\n",
    )
    assert _rule_names(check_input_schemas_exclude_managed_columns(app)) == {
        "input_schemas_exclude_managed_columns"
    }

    # A clean input schema passes; a Read DTO that legitimately echoes a managed
    # column (id / tenant_id) is exempt -- it is not a *Create / *Update.
    _write(
        app,
        "modules/notes/schemas.py",
        "class NoteCreate(BaseSchema):\n    title: str = Field(max_length=200)\n"
        "class NoteRead(BaseSchema):\n    id: uuid.UUID\n    tenant_id: uuid.UUID\n",
    )
    assert check_input_schemas_exclude_managed_columns(app) == []

    # An off-convention request-body DTO (not *Create/*Update) is covered too: a
    # managed column on it is flagged via route correlation, while the Read DTO that
    # echoes one stays exempt.
    _write(
        app,
        "modules/auth/router.py",
        "@router.post('/provision')\ndef provision(payload: ProvisionRequest) -> None:\n    return None\n",
    )
    _write(
        app,
        "modules/auth/schemas.py",
        "class ProvisionRequest(BaseSchema):\n    email: str = Field(max_length=320)\n    tenant_id: uuid.UUID\n",
    )
    flagged = check_input_schemas_exclude_managed_columns(app)
    assert _rule_names(flagged) == {"input_schemas_exclude_managed_columns"}
    assert all("ProvisionRequest" in violation.message for violation in flagged)


def test_events_reference_catalog(tmp_path: pathlib.Path) -> None:
    app = tmp_path / "app"
    # Bare-string events anywhere they are named â€” emit / subscribe / ModuleSpec.
    _write(
        app,
        "modules/billing/service.py",
        "def settle(session) -> None:\n    emit(session, event='billing.paid')\n",
    )
    _write(
        app,
        "modules/billing/event_handlers.py",
        "@subscribe('billing.paid')\ndef on_paid(envelope) -> None:\n    return None\n",
    )
    _write(
        app,
        "modules/billing/module.py",
        "module = ModuleSpec(name='billing', emits=['billing.paid'], subscribes=['x.y'])\n",
    )
    assert _rule_names(check_events_reference_catalog(app)) == {"events_reference_catalog"}
    # Four literal references flagged: emit + subscribe + one emits + one subscribes.
    assert len(check_events_reference_catalog(app)) == 4

    # Typed catalog constants (Name / Attribute) are clean.
    _write(
        app,
        "modules/billing/service.py",
        "from control_plane.events import BILLING_PAID\n"
        "def settle(session) -> None:\n    emit(session, event=BILLING_PAID)\n",
    )
    _write(
        app,
        "modules/billing/event_handlers.py",
        "from control_plane import events\n"
        "@subscribe(events.BILLING_PAID)\ndef on_paid(envelope) -> None:\n    return None\n",
    )
    _write(
        app,
        "modules/billing/module.py",
        "from control_plane.events import BILLING_PAID, PAYMENT_SETTLED\n"
        "module = ModuleSpec(name='billing', emits=[BILLING_PAID], subscribes=[PAYMENT_SETTLED])\n",
    )
    assert check_events_reference_catalog(app) == []

    # An inline EventDefinition(...) is drift too â€” it bypasses the catalog.
    _write(
        app,
        "modules/billing/service.py",
        "def settle(session) -> None:\n    emit(session, event=EventDefinition('x.y', P))\n",
    )
    assert _rule_names(check_events_reference_catalog(app)) == {"events_reference_catalog"}

    # LifecycleEventMap names events too: a bare string is flagged; a typed ref and
    # an explicit None ("no event for this action") are clean.
    _write(
        app,
        "modules/billing/service.py",
        "from control_plane.events import BILLING_PAID\n"
        "m = LifecycleEventMap(created='billing.paid', updated=None, deleted=BILLING_PAID)\n",
    )
    violations = check_events_reference_catalog(app)
    assert _rule_names(violations) == {"events_reference_catalog"}
    assert len(violations) == 1  # only created='...'; updated=None + deleted=BILLING_PAID are clean


def test_emitted_events_are_declared(tmp_path: pathlib.Path) -> None:
    app = tmp_path / "app"
    # The manifest declares one event; the service emits a second one it never named.
    _write(
        app,
        "modules/billing/module.py",
        "from control_plane.events import BILLING_PAID\n"
        "module = ModuleSpec(name='billing', emits=[BILLING_PAID])\n",
    )
    _write(
        app,
        "modules/billing/service.py",
        "from control_plane import events\n"
        "def settle(session) -> None:\n    emit(session, event=events.BILLING_REFUNDED)\n",
    )
    violations = check_emitted_events_are_declared(app)
    assert _rule_names(violations) == {"emitted_events_are_declared"}
    assert len(violations) == 1
    assert "BILLING_REFUNDED" in violations[0].message

    # Declaring it makes the contract true again â€” and the declaration is matched by
    # the constant's own identifier, so each file may import it however it likes.
    _write(
        app,
        "modules/billing/module.py",
        "from control_plane.events import BILLING_PAID, BILLING_REFUNDED\n"
        "module = ModuleSpec(name='billing', emits=[BILLING_PAID, BILLING_REFUNDED])\n",
    )
    assert check_emitted_events_are_declared(app) == []

    # A LifecycleEventMap emits just as much as an explicit emit() call does.
    _write(
        app,
        "modules/billing/service.py",
        "from control_plane.events import BILLING_VOIDED\n"
        "m = LifecycleEventMap(created=None, deleted=BILLING_VOIDED)\n",
    )
    violations = check_emitted_events_are_declared(app)
    assert _rule_names(violations) == {"emitted_events_are_declared"}
    assert "BILLING_VOIDED" in violations[0].message

    # Each module answers for its own manifest: a neighbour's declaration is not cover.
    _write(
        app,
        "modules/billing/service.py",
        "from control_plane.events import BILLING_PAID\n"
        "def settle(session) -> None:\n    emit(session, event=BILLING_PAID)\n",
    )
    _write(
        app,
        "modules/ledger/module.py",
        "module = ModuleSpec(name='ledger')\n",
    )
    _write(
        app,
        "modules/ledger/service.py",
        "from control_plane.events import BILLING_PAID\n"
        "def post(session) -> None:\n    emit(session, event=BILLING_PAID)\n",
    )
    violations = check_emitted_events_are_declared(app)
    assert len(violations) == 1
    assert "ledger" in violations[0].path and "'ledger'" in violations[0].message


def test_jobs_reference_catalog(tmp_path: pathlib.Path) -> None:
    app = tmp_path / "app"
    # Bare-string jobs anywhere they are named â€” enqueue(job=) / ModuleSpec(jobs=).
    _write(
        app,
        "modules/billing/service.py",
        "def run(session) -> None:\n    enqueue(session, job='billing.settle', payload=p)\n",
    )
    _write(
        app,
        "modules/billing/module.py",
        "module = ModuleSpec(name='billing', jobs=['billing.settle'])\n",
    )
    assert _rule_names(check_jobs_reference_catalog(app)) == {"jobs_reference_catalog"}
    # Two literal references flagged: enqueue(job=) + one jobs= element.
    assert len(check_jobs_reference_catalog(app)) == 2

    # Typed catalog constants (Name / Attribute) are clean.
    _write(
        app,
        "modules/billing/service.py",
        "from control_plane.jobs import BILLING_SETTLE\n"
        "def run(session) -> None:\n    enqueue(session, job=BILLING_SETTLE, payload=p)\n",
    )
    _write(
        app,
        "modules/billing/module.py",
        "from control_plane.jobs import BILLING_SETTLE\n"
        "module = ModuleSpec(name='billing', jobs=[BILLING_SETTLE])\n",
    )
    assert check_jobs_reference_catalog(app) == []

    # An inline JobDefinition(...) is drift too â€” it bypasses the catalog.
    _write(
        app,
        "modules/billing/service.py",
        "def run(session) -> None:\n    enqueue(session, job=JobDefinition('x.y', P, h), payload=p)\n",
    )
    assert _rule_names(check_jobs_reference_catalog(app)) == {"jobs_reference_catalog"}


def test_no_adhoc_config_decrypt(tmp_path: pathlib.Path) -> None:
    app = tmp_path / "app"
    # A module decrypting sealed config ad hoc is flagged â€” bare call and attribute form.
    _write(
        app,
        "modules/billing/service.py",
        "def dsn() -> str:\n    return decrypt_config(settings.DB_DSN)\n",
    )
    assert _rule_names(check_no_adhoc_config_decrypt(app)) == {"no_adhoc_config_decrypt"}
    _write(
        app,
        "modules/billing/service.py",
        "import terp.core.secrets as secrets\n"
        "def dsn() -> str:\n    return secrets.decrypt_config(settings.DB_DSN)\n",
    )
    assert _rule_names(check_no_adhoc_config_decrypt(app)) == {"no_adhoc_config_decrypt"}

    # Masked rendering (and sealing) are freely usable â€” only decrypt is the chokepoint.
    _write(
        app,
        "modules/billing/service.py",
        "def shown() -> str:\n    return mask_config(settings.DB_DSN)\n"
        "def seal(value: str) -> str:\n    return encrypt_config(value)\n",
    )
    assert check_no_adhoc_config_decrypt(app) == []

    # The one sanctioned site is a justified, budgeted arch-allow opt-out (design Â§5.4).
    _write(
        app,
        "main.py",
        "def read_sealed(value: str) -> str:\n"
        "    return decrypt_config(value)  # arch-allow-no-adhoc-config-decrypt: the one Â§5.4 site\n",
    )
    assert "no_adhoc_config_decrypt" not in _rule_names(check_app(app))


def test_no_hardcoded_credentials(tmp_path: pathlib.Path) -> None:
    app = tmp_path / "app"
    for source in (
        "PASSWORD = 'not-from-config'",
        "self.api_key = 'not-from-config'",
        "client_secret: str = 'not-from-config'",
        "(password, label) = 'not-from-config'",
        # Destructured parallel literals pair element-wise: the credential-shaped
        # target is checked against ITS OWN value, not the tuple as a whole.
        "user, password = 'svc', 'not-from-config'",
        "(alpha, (beta, token)) = ('a', ('b', 'not-from-config'))",
    ):
        _write(app, "modules/billing/service.py", f"def configure(self):\n    {source}\n")
        assert _rule_names(check_no_hardcoded_credentials(app)) == {"no_hardcoded_credentials"}, source

    secret_literals = (
        "AKIA" + "A" * 16,
        "ghp_" + "A" * 36,
        "github_pat_" + "A" * 22,
        "-----BEGIN " + "PRIVATE KEY-----\\nabc\\n-----END PRIVATE KEY-----",
    )
    for literal in secret_literals:
        _write(app, "modules/billing/service.py", f"VALUE = {literal!r}\n")
        assert _rule_names(check_no_hardcoded_credentials(app)) == {"no_hardcoded_credentials"}, literal

    # Empty placeholders and dynamic config/env values are not source credentials.
    _write(
        app,
        "modules/billing/service.py",
        "password = ''\napi_key = settings.API_KEY\ntoken = os.environ['TOKEN']\n"
        "config['password'] = 'dev-only'\nlabel = 'not-secret'\n"
        # Element-wise pairing works both ways: the literal belongs to the
        # non-credential name, the credential name gets the dynamic value.
        "password, greeting = fetch_secret(), 'hello'\n",
    )
    assert check_no_hardcoded_credentials(app) == []

    # The rule follows app-module scope.
    _write(app, "scripts/bootstrap.py", "password = 'dev-only'\n")
    _write(app, "modules/billing/service.py", "password = ''\n")
    assert check_no_hardcoded_credentials(app) == []

    # tests/ and migrations/ dirs inside a module are committed source: still scanned (G1).
    _write(app, "modules/billing/tests/helper.py", "api_key = 'not-from-config'\n")
    assert _rule_names(check_no_hardcoded_credentials(app)) == {"no_hardcoded_credentials"}


def test_no_hardcoded_credentials_allows_self_naming_enum_members(tmp_path: pathlib.Path) -> None:
    # An enum member whose literal IS its own name is vocabulary, not a credential:
    # `SECRET_REFERENCE = "secret_reference"` names a parameter kind. Flagging it
    # pushed authors to spell the same value as auto(), hiding the wire format.
    app = tmp_path / "app"
    _write(
        app,
        "modules/billing/schemas.py",
        "class ParameterType(StrEnum):\n"
        "    TEXT = 'text'\n"
        "    SECRET_REFERENCE = 'secret_reference'\n",
    )
    assert check_no_hardcoded_credentials(app) == []

    # The exemption is exactly self-naming: a real value keeps failing...
    _write(
        app,
        "modules/billing/schemas.py",
        "class ParameterType(StrEnum):\n    SECRET_REFERENCE = 'hunter2'\n",
    )
    assert _rule_names(check_no_hardcoded_credentials(app)) == {"no_hardcoded_credentials"}

    # ...and so does a self-naming assignment outside an enum class body.
    _write(app, "modules/billing/schemas.py", "password = 'password'\n")
    assert _rule_names(check_no_hardcoded_credentials(app)) == {"no_hardcoded_credentials"}

    # An enum body carries members that hold no literal at all â€” an auto() value
    # and a bare annotation. There is nothing to compare a name against, so they
    # are simply not exemptions, and nothing about them is a credential either.
    _write(
        app,
        "modules/billing/schemas.py",
        "class ParameterType(StrEnum):\n    api_key: str\n    password = auto()\n",
    )
    assert check_no_hardcoded_credentials(app) == []



def test_no_manual_scope_filtering(tmp_path: pathlib.Path) -> None:
    app = tmp_path / "app"
    # Hand-writing the soft-delete predicate in a module is drift.
    _write(
        app,
        "modules/tasks/service.py",
        "def visible(q):\n    return q.where(Task.deleted_at.is_(None))\n",
    )
    assert _rule_names(check_no_manual_scope_filtering(app)) == {"no_manual_scope_filtering"}

    # Hand-writing the tenant predicate is drift too.
    _write(
        app,
        "modules/widgets/service.py",
        "def scoped(q, current):\n    return q.where(Widget.tenant_id == current)\n",
    )
    assert _rule_names(check_no_manual_scope_filtering(app)) == {"no_manual_scope_filtering"}

    # A module that never touches the managed columns is clean (the framework filters).
    _write(
        app,
        "modules/tasks/service.py",
        "class TaskService(BaseService[Task, TaskCreate, TaskUpdate]):\n    model = Task\n",
    )
    _write(
        app,
        "modules/widgets/service.py",
        "class WidgetService(BaseService[Widget, WidgetCreate, WidgetUpdate]):\n    model = Widget\n",
    )
    assert check_no_manual_scope_filtering(app) == []


def test_no_manual_actor_stamping(tmp_path: pathlib.Path) -> None:
    app = tmp_path / "app"
    # Setting created_by_id by hand forges provenance (the actor must come from the request).
    _write(
        app,
        "modules/notes/service.py",
        "def stamp(note, actor):\n    note.created_by_id = actor\n",
    )
    assert _rule_names(check_no_manual_actor_stamping(app)) == {"no_manual_actor_stamping"}

    # modified_by_id by hand is the same drift.
    _write(
        app,
        "modules/notes/service.py",
        "def touch(note, actor):\n    note.modified_by_id = actor\n",
    )
    assert _rule_names(check_no_manual_actor_stamping(app)) == {"no_manual_actor_stamping"}

    # Clean: the service never touches the stamp columns (BaseService fills them), and
    # a read DTO may still *expose* them as annotations (not attribute access).
    _write(
        app,
        "modules/notes/service.py",
        "class NoteService(BaseService[Note, NoteCreate, NoteUpdate]):\n    model = Note\n",
    )
    _write(
        app,
        "modules/notes/schemas.py",
        "class NoteRead(BaseSchema):\n"
        "    created_by_id: uuid.UUID | None\n"
        "    modified_by_id: uuid.UUID | None\n",
    )
    assert check_no_manual_actor_stamping(app) == []


def test_no_manual_ownership_checks(tmp_path: pathlib.Path) -> None:
    app = tmp_path / "app"
    # Hand-rolling the per-row owner check (compare owner_id to the principal) is the
    # easy-to-get-wrong pattern the object-authz seam replaces.
    _write(
        app,
        "modules/journals/service.py",
        "def guard(entry, principal):\n"
        "    if entry.owner_id != principal.id:\n"
        "        raise PermissionDeniedError()\n",
    )
    assert _rule_names(check_no_manual_ownership_checks(app)) == {"no_manual_ownership_checks"}

    # Hand-filtering reads by owner_id is the same drift (and drops the row scope).
    _write(
        app,
        "modules/journals/service.py",
        "def mine(q, principal):\n    return q.where(Journal.owner_id == principal.id)\n",
    )
    assert _rule_names(check_no_manual_ownership_checks(app)) == {"no_manual_ownership_checks"}

    # Clean: the service never touches owner_id (BaseService stamps + authorizes it),
    # and a read DTO may still *expose* it as an annotation (not attribute access).
    _write(
        app,
        "modules/journals/service.py",
        "class JournalService(BaseService[Journal, JournalCreate, JournalUpdate]):\n"
        "    model = Journal\n",
    )
    _write(
        app,
        "modules/journals/schemas.py",
        "class JournalRead(BaseSchema):\n    owner_id: uuid.UUID | None\n",
    )
    assert check_no_manual_ownership_checks(app) == []


def test_background_job_cannot_trade_away_owned_rows(tmp_path: pathlib.Path) -> None:
    app = tmp_path / "app"
    _write(
        app,
        "modules/notes/models.py",
        "class Note(BaseTable, ActorStampedMixin, table=True):\n"
        "    title: str = Field(max_length=200)\n",
    )
    _write(
        app,
        "modules/notes/service.py",
        "class NoteService(BaseService[Note, NoteCreate, NoteUpdate]):\n"
        "    model = Note\n",
    )
    _write(
        app,
        "modules/notes/module.py",
        "module = ModuleSpec(name='notes', services=(NoteService,), jobs=[PURGE])\n",
    )

    violations = check_no_manual_ownership_checks(app)
    assert _rule_names(violations) == {"no_manual_ownership_checks"}
    assert "maintenance-authority" in violations[0].message

    _write(
        app,
        "modules/notes/module.py",
        "module = ModuleSpec(name='notes', jobs=[PURGE])\n",
    )
    assert _rule_names(check_no_manual_ownership_checks(app)) == {
        "no_manual_ownership_checks"
    }

    _write(
        app,
        "modules/notes/models.py",
        "class Note(BaseTable, OwnedMixin, table=True):\n"
        "    title: str = Field(max_length=200)\n",
    )
    assert check_no_manual_ownership_checks(app) == []


def test_no_raw_file_references(tmp_path: pathlib.Path) -> None:
    app = tmp_path / "app"
    # A bare uuid file pointer on a table model is an undeclared reference: nothing ties
    # the file's access to the referencing row (the BOLA drift FileRef declares away).
    _write(
        app,
        "modules/invoices/models.py",
        "class Invoice(BaseTable, table=True):\n"
        "    attachment_file_id: uuid.UUID | None = Field(default=None)\n"
        "    file_id: uuid.UUID | None = None\n",
    )
    assert _rule_names(check_no_raw_file_references(app)) == {"no_raw_file_references"}
    assert len(check_no_raw_file_references(app)) == 2

    # Clean: the column is declared with FileRef(...) â€” greppable, runtime-verified by
    # FileService.load_for, and served through the module's own authorized row.
    _write(
        app,
        "modules/invoices/models.py",
        "class Invoice(BaseTable, table=True):\n"
        "    attachment_file_id: uuid.UUID | None = FileRef()\n",
    )
    assert check_no_raw_file_references(app) == []

    # A non-table schema may expose file_id (a Read DTO annotation is not a stored
    # reference), and a non-reference-shaped column is never policed.
    _write(
        app,
        "modules/invoices/schemas.py",
        "class InvoiceRead(BaseSchema):\n"
        "    attachment_file_id: uuid.UUID | None\n",
    )
    _write(
        app,
        "modules/invoices/other.py",
        "class Profile(BaseTable, table=True):\n"
        "    avatar_id: uuid.UUID | None = None\n",
    )
    assert check_no_raw_file_references(app) == []


def test_tenant_scoped_models_use_scoped_service(tmp_path: pathlib.Path) -> None:
    app = tmp_path / "app"
    _write(
        app,
        "modules/widgets/models.py",
        "class Widget(BaseTable, TenantScopedMixin, table=True):\n    name: str = Field(max_length=20)\n",
    )
    _write(
        app,
        "modules/widgets/service.py",
        "class WidgetService(BaseService[Widget, WidgetCreate, WidgetUpdate]):\n    model = Widget\n",
    )
    assert _rule_names(check_tenant_scoped_models_use_scoped_service(app)) == {
        "tenant_scoped_models_use_scoped_service"
    }

    _write(
        app,
        "modules/widgets/service.py",
        "class WidgetService(TenantScopedService[Widget, WidgetCreate, WidgetUpdate]):\n    model = Widget\n",
    )
    assert check_tenant_scoped_models_use_scoped_service(app) == []


def test_base_query_not_overridden(tmp_path: pathlib.Path) -> None:
    app = tmp_path / "app"
    # Overriding base_query is forbidden: a super()-less override drops soft-delete/tenant scope.
    _write(
        app,
        "modules/tasks/service.py",
        "class TaskService(BaseService[Task, TaskCreate, TaskUpdate]):\n"
        "    model = Task\n"
        "    def base_query(self):\n        return select(Task)\n",
    )
    assert _rule_names(check_base_query_not_overridden(app)) == {"base_query_not_overridden"}

    # Adding read filters via business_filters() is the clean, scope-safe alternative.
    _write(
        app,
        "modules/tasks/service.py",
        "class TaskService(BaseService[Task, TaskCreate, TaskUpdate]):\n"
        "    model = Task\n"
        "    def business_filters(self):\n        return (Task.status == 'open',)\n",
    )
    assert check_base_query_not_overridden(app) == []


def test_reads_use_base_query(tmp_path: pathlib.Path) -> None:
    app = tmp_path / "app"
    _write(
        app,
        "modules/leads/models.py",
        "class Lead(BaseTable, TenantScopedMixin, table=True):\n"
        "    email: str = Field(max_length=200)\n"
        "class Public(BaseTable, table=True):\n"
        "    name: str = Field(max_length=50)\n",
    )
    # A scope-trait model (TenantScopedMixin/SoftDeleteMixin) read via a raw select() â€”
    # in ANY chain position (args, select_from, join, where) â€” drops soft-delete /
    # tenant scope (the F1 leak ADR 0017's override-ban missed). self.model and a
    # module-level select are resolved too. A primary-key session.get(Lead, id) is
    # caught too (it has no select() node); self.get(session, id) and a get() of a
    # non-scope model are not.
    _write(
        app,
        "modules/leads/service.py",
        "_OPEN = select(Lead)\n"
        "class LeadService(TenantScopedService[Lead, LeadCreate, LeadUpdate]):\n"
        "    model = Lead\n"
        "    def search(self, session, term):\n"
        "        select(func.count()).select_from(Lead)\n"
        "        select(Lead.email)\n"
        "        session.execute(select(self.model))\n"
        "        session.exec(select(type(self).model))\n"
        "        session.exec(select(Public, Lead))\n"
        "        session.exec(select(Public).join(Lead))\n"
        "        session.get(Lead, term)\n"
        "        session.get(Public, term)\n"
        "        self.get(session, term)\n"
        "        return session.exec(select(Lead).where(Lead.email == term)).all()\n",
    )
    flagged = check_reads_use_base_query(app)
    assert _rule_names(flagged) == {"reads_use_base_query"}
    # Every one of the 9 raw reads of the scoped Lead is caught (a dropped shape would
    # lower this count), and each names Lead.
    assert len(flagged) == 9
    assert all("'Lead'" in violation.message for violation in flagged)

    # Clean: building on base_query() keeps the scope (a read is never rooted at a
    # select() call), self.get(session, id) reads through the audited service, and a
    # raw select()/get() of a NON-scope-trait model is allowed.
    _write(
        app,
        "modules/leads/service.py",
        "class LeadService(TenantScopedService[Lead, LeadCreate, LeadUpdate]):\n"
        "    model = Lead\n"
        "    def search(self, session, term):\n"
        "        return session.exec(self.base_query().where(Lead.email == term)).all()\n"
        "    def all_public(self, session):\n"
        "        session.get(Public, term)\n"
        "        return session.exec(select(Public)).all()\n",
    )
    assert check_reads_use_base_query(app) == []


def test_list_routes_paginate(tmp_path: pathlib.Path) -> None:
    app = tmp_path / "app"
    # A bare list[...] response_model serializes an unbounded collection â€” must be Page[...].
    _write(
        app,
        "modules/notes/router.py",
        "@router.get('/', response_model=list[NoteRead])\n"
        "def list_notes() -> list[NoteRead]:\n    return []\n",
    )
    assert _rule_names(check_list_routes_paginate(app)) == {"list_routes_paginate"}

    # FastAPI's api_route spelling and an unparameterized collection are covered too.
    _write(
        app,
        "modules/notes/router.py",
        "@router.api_route('/', methods=['GET'], response_model=list[NoteRead])\n"
        "def list_notes() -> list[NoteRead]:\n    return []\n"
        "@router.get('/raw', response_model=list)\n"
        "def raw_list():\n    return []\n",
    )
    flagged = check_list_routes_paginate(app)
    assert _rule_names(flagged) == {"list_routes_paginate"}
    assert len(flagged) == 2

    # Imperative add_api_route is covered too (constant and non-constant paths).
    _write(
        app,
        "modules/notes/router.py",
        "router.add_api_route('/things', list_things, response_model=list[NoteRead])\n"
        "router.add_api_route(PREFIX, more, response_model=Sequence[NoteRead])\n",
    )
    flagged = check_list_routes_paginate(app)
    assert _rule_names(flagged) == {"list_routes_paginate"}
    assert len(flagged) == 2

    # Clean: Page[...] is the capped, paginated shape; a single-object DTO is fine.
    _write(
        app,
        "modules/notes/router.py",
        "@router.get('/', response_model=Page[NoteRead])\n"
        "def list_notes() -> Page[NoteRead]:\n    return Page()\n"
        "@router.get('/{x}', response_model=NoteRead)\n"
        "def get_note(x) -> NoteRead:\n    return NoteRead()\n",
    )
    assert check_list_routes_paginate(app) == []


def test_path_id_params_are_uuid(tmp_path: pathlib.Path) -> None:
    app = tmp_path / "app"
    # A path param named like a resource id (id / *_id) that also appears in the route's
    # URL template must be typed uuid.UUID â€” a bare int / str skips boundary validation.
    _write(
        app,
        "modules/notes/router.py",
        "@router.get('/{note_id}', response_model=NoteRead)\n"
        "def get_note(note_id: int) -> NoteRead:\n    return NoteRead()\n"
        "@router.delete('/{id}')\n"
        "def delete_note(id) -> None:\n    return None\n",
    )
    flagged = check_path_id_params_are_uuid(app)
    assert _rule_names(flagged) == {"path_id_params_are_uuid"}
    assert len(flagged) == 2  # the int-typed one and the un-annotated one

    # Clean: uuid.UUID (attribute) and a bare UUID name are both accepted; a non-id
    # path param and an id-shaped *query* param (not in the URL template) are ignored.
    _write(
        app,
        "modules/notes/router.py",
        "@router.get('/{note_id}', response_model=NoteRead)\n"
        "def get_note(note_id: uuid.UUID) -> NoteRead:\n    return NoteRead()\n"
        "@router.get('/{slug}', response_model=NoteRead)\n"
        "def by_slug(slug: str, tenant_id: int) -> NoteRead:\n    return NoteRead()\n"
        "@router.put('/{note_id}', response_model=NoteRead)\n"
        "def replace(note_id: UUID) -> NoteRead:\n    return NoteRead()\n",
    )
    assert check_path_id_params_are_uuid(app) == []

    # A path id param annotated with a *subscripted* type (not a plain name/attribute)
    # is not a bare UUID annotation, so it is still refused.
    _write(
        app,
        "modules/notes/router.py",
        "@router.get('/{note_id}', response_model=NoteRead)\n"
        "def get_note(note_id: Optional[UUID]) -> NoteRead:\n    return NoteRead()\n",
    )
    assert _rule_names(check_path_id_params_are_uuid(app)) == {"path_id_params_are_uuid"}


def test_offset_queries_declare_ordering(tmp_path: pathlib.Path) -> None:
    app = tmp_path / "app"
    # A query paginated with .offset() but no .order_by() has undefined row order, so
    # pages can skip or repeat rows.
    _write(
        app,
        "modules/notes/service.py",
        "def page(session, skip):\n"
        "    return session.exec(select(Note).offset(skip).limit(20)).all()\n",
    )
    flagged = check_offset_queries_declare_ordering(app)
    assert _rule_names(flagged) == {"offset_queries_declare_ordering"}
    assert len(flagged) == 1

    # Clean: an ordered offset query is deterministic; a query without offset is fine.
    _write(
        app,
        "modules/notes/service.py",
        "def page(session, skip):\n"
        "    return session.exec(\n"
        "        select(Note).order_by(Note.created_at).offset(skip).limit(20)\n"
        "    ).all()\n"
        "def all_notes(session):\n"
        "    return session.exec(select(Note)).all()\n",
    )
    assert check_offset_queries_declare_ordering(app) == []


def test_forwarded_filters_are_declared(tmp_path: pathlib.Path) -> None:
    app = tmp_path / "app"
    # A route forwards its optional query parameters unbranched, so a typo'd key is
    # None on every request that omits that parameter: the read is never narrowed and
    # nothing says so. Two misspellings, both flagged at the key's own line.
    _write(
        app,
        "modules/notes/service.py",
        "class NoteService(BaseService):\n"
        "    filterable = (\n"
        "        FilterField('connection_id', Note.connection_id),\n"
        "        FilterField('captured_from', Note.captured_at, op='gte'),\n"
        "    )\n",
    )
    _write(
        app,
        "modules/notes/router.py",
        "def list_notes(session, connection_id=None, captured_from=None):\n"
        "    return service.list(\n"
        "        session,\n"
        "        filters={'connection_id': connection_id, 'captured_frm': captured_from},\n"
        "    )\n"
        "def other(session):\n"
        "    return service.list(session, filters={'nope': 1})\n",
    )
    flagged = check_forwarded_filters_are_declared(app)
    assert _rule_names(flagged) == {"forwarded_filters_are_declared"}
    assert len(flagged) == 2
    # The message names the near-miss, matching what resolve_filters raises at runtime.
    assert "captured_from" in flagged[0].message

    # Clean: declared keys pass, and so does anything not statically knowable — a
    # filters mapping built elsewhere, or a computed key. Guessing at those would flag
    # correct code, which is the one failure this rule must not have.
    _write(
        app,
        "modules/notes/router.py",
        "def list_notes(session, connection_id=None):\n"
        "    return service.list(session, filters={'connection_id': connection_id})\n"
        "def dynamic(session, chosen, built):\n"
        "    service.list(session, filters=built)\n"
        "    service.list(session, filters={chosen: 1})\n"
        "    service.list(session, skip=0, limit=10)\n",
    )
    assert check_forwarded_filters_are_declared(app) == []


def test_forwarded_filters_declaration_scan_is_tree_wide_and_literal(
    tmp_path: pathlib.Path,
) -> None:
    """Which service a route calls is not decidable from the AST, so the declared
    set is collected tree-wide: a name declared in *any* service satisfies *any*
    route. A misspelling matches nothing anywhere, so nothing is lost — and the
    rule can never call a correct filter undeclared by mispairing the two."""
    app = tmp_path / "app"
    _write(
        app,
        "modules/other/service.py",
        "filterable = (FilterField('owner_id', Other.owner_id),)\n",
    )
    _write(
        app,
        "modules/notes/router.py",
        "service.list(session, filters={'owner_id': owner_id})\n",
    )
    assert check_forwarded_filters_are_declared(app) == []

    # A non-literal filter name declares nothing this rule can read, so a route
    # forwarding it is reported rather than silently accepted.
    _write(app, "modules/other/service.py", "f = (FilterField(NAME, Other.owner_id),)\n")
    assert _rule_names(check_forwarded_filters_are_declared(app)) == {
        "forwarded_filters_are_declared"
    }

    # Files outside a module are not the surface this rule guards (the composition
    # root wires modules together; it declares no service filters of its own).
    _write(app, "modules/other/service.py", "f = (FilterField('owner_id', C.owner_id),)\n")
    _write(app, "main.py", "call(filters={'whatever': 1})\n")
    assert check_forwarded_filters_are_declared(app) == []


def test_safe_methods_are_read_only(tmp_path: pathlib.Path) -> None:
    app = tmp_path / "app"
    # Any handler REACHABLE via a safe method (GET/HEAD/OPTIONS) must not call a mutating
    # BaseService method: create/update/delete on a self/*service* receiver, or the
    # _save/_remove primitives. This covers a decorator route, a mixed-method api_route
    # (the GET path still runs at the read tier), an api_route defaulting to GET, and an
    # imperative add_api_route (default GET or an explicit safe method) â€” six writes.
    _write(
        app,
        "modules/notes/router.py",
        "@router.get('/seed')\n"
        "def seed(session):\n    return _service.create(session, payload)\n"
        "@router.api_route('/wipe', methods=['GET', 'HEAD'])\n"
        "def wipe(session):\n    _service._remove(session, row)\n"
        "@router.api_route('/mix', methods=['GET', 'POST'])\n"
        "def mix(session):\n    return _service.update(session, x, data)\n"
        "@router.api_route('/dft')\n"
        "def dft(session):\n    return self.update(session, x, data)\n"
        "def imp(session):\n    return _service.create(session, payload)\n"
        "def impd(session):\n    _service._remove(session, row)\n"
        "router.add_api_route('/imp', imp, methods=['GET'])\n"
        "router.add_api_route('/impd', impd)\n",
    )
    flagged = check_safe_methods_are_read_only(app)
    assert _rule_names(flagged) == {"safe_methods_are_read_only"}
    assert len(flagged) == 6

    # Clean: a safe-method handler that only reads; a mutation behind a write-tier route
    # (POST/DELETE, decorator or imperative); a non-literal api_route methods= (the set
    # cannot be resolved, so it is left unchecked); and a non-route decorator (a name
    # call @cached(), an attribute @app.on_event(...)). An unrelated .update() on a
    # non-service receiver (a dict / header map) is never a mutation.
    _write(
        app,
        "modules/notes/router.py",
        "@router.get('/{x}', response_model=NoteRead)\n"
        "def get_note(x, session):\n"
        "    headers.update({'x': '1'})\n"
        "    return _service.get(session, x)\n"
        "@router.post('/', response_model=NoteRead)\n"
        "def create_note(session):\n    return _service.create(session, payload)\n"
        "@router.delete('/{x}')\n"
        "def delete_note(x, session):\n    _service.delete(session, x)\n"
        "@router.api_route('/dyn', methods=DYN)\n"
        "def dyn(session):\n    return _service.update(session, x, data)\n"
        "@cached()\n"
        "def helper(session):\n    _service.update(session, x, data)\n"
        "@app.on_event('startup')\n"
        "def boot(session):\n    _service.create(session, payload)\n"
        "def wr(session):\n    return _service.create(session, payload)\n"
        "router.add_api_route('/wr', wr, methods=['POST'])\n",
    )
    assert check_safe_methods_are_read_only(app) == []


def test_no_raw_connection_access(tmp_path: pathlib.Path) -> None:
    app = tmp_path / "app"
    # Reaching the raw connection/engine behind the session escapes the write guard;
    # a get_bind().connect() escape is caught at the get_bind() call.
    _write(
        app,
        "modules/notes/service.py",
        "def leak(session):\n"
        "    session.connection().execute(stmt)\n"
        "    return session.get_bind().connect()\n",
    )
    flagged = check_no_raw_connection_access(app)
    assert _rule_names(flagged) == {"no_raw_connection_access"}
    assert len(flagged) == 2  # connection() and get_bind() â€” once each, no duplicate

    # Clean: a normal read needs no raw connection/engine, and an unrelated .connect()
    # on a domain object (websocket / cache / search client) is deliberately not flagged.
    _write(
        app,
        "modules/notes/service.py",
        "def ok(session, websocket_manager, client):\n"
        "    websocket_manager.connect(client)\n"
        "    return session.exec(select(Note)).all()\n",
    )
    assert check_no_raw_connection_access(app) == []


def test_tables_have_migrations(tmp_path: pathlib.Path) -> None:
    app = tmp_path / "app"
    # A module that declares a table model but ships no migrations/versions/ revision
    # would deploy with the table missing (the boot guard checks only declared trees).
    _write(
        app,
        "modules/widgets/models.py",
        "class Widget(BaseTable, table=True):\n    name: str = Field(max_length=50)\n",
    )
    flagged = check_tables_have_migrations(app)
    assert _rule_names(flagged) == {"tables_have_migrations"}
    assert len(flagged) == 1 and "widgets" in flagged[0].message

    # Clean once a revision is committed under the module's migrations/versions/, and a
    # module with no table model needs none.
    _write(
        app,
        "modules/widgets/migrations/versions/0001_init.py",
        "revision = '0001'\ndown_revision = None\n",
    )
    _write(app, "modules/pages/router.py", "router = APIRouter()\n")
    assert check_tables_have_migrations(app) == []


def test_no_destructive_migrations(tmp_path: pathlib.Path) -> None:
    app = tmp_path / "app"
    destructive_sources = (
        "op.drop_table('notes')",
        "op.drop_column('notes', 'legacy')",
        "op.alter_column('notes', 'title', type_=sa.Text())",
        # Receiver-agnostic: a batch block or an aliased handle is the same drop (G4).
        "batch_op.drop_column('notes', 'legacy')",
        "ops.drop_table('notes')",
        # Destructive SQL smuggled through execute() is the same risk (G4).
        "op.execute('DROP TABLE notes')",
        "op.execute(f'DELETE FROM notes WHERE tenant={tenant}')",
        "conn.execute('ALTER TABLE notes DROP COLUMN legacy')",
        "op.execute('TRUNCATE notes')",
    )
    for source in destructive_sources:
        _write(app, "modules/notes/migrations/versions/0001_change.py", f"def upgrade():\n    {source}\n")
        assert _rule_names(check_no_destructive_migrations(app)) == {"no_destructive_migrations"}, source

    # Non-destructive operations and alter_column calls without type changes are clean.
    _write(
        app,
        "modules/notes/migrations/versions/0001_change.py",
        "def upgrade():\n    helper()\n    op.add_column('notes', column)\n    op.alter_column('notes', 'title', nullable=False)\n",
    )
    assert check_no_destructive_migrations(app) == []

    # execute() of non-destructive DDL, or of a statement the rule cannot resolve
    # statically (a variable), stays clean â€” triggers/indexes destroy no row data.
    _write(
        app,
        "modules/notes/migrations/versions/0001_change.py",
        "def upgrade():\n    op.execute('CREATE TRIGGER trg AFTER INSERT ON notes BEGIN SELECT 1; END')\n"
        "    op.execute(statement)\n",
    )
    assert check_no_destructive_migrations(app) == []

    # A reason-bearing standard marker on the operation's line (or immediately
    # above) permits a reviewed destructive migration â€” the same governed escape
    # hatch as every other rule, counted by the budget ratchet.
    _write(
        app,
        "modules/notes/migrations/versions/0001_change.py",
        "def upgrade():\n"
        "    # arch-allow-no-destructive-migrations: removing obsolete beta table\n"
        "    op.drop_table('notes_beta')\n",
    )
    assert check_app(app) == []

    # The pre-0.6.0 file-level waiver is gone: a bespoke file-wide marker no longer
    # blankets every destructive operation in the revision.
    _write(
        app,
        "modules/notes/migrations/versions/0001_change.py",
        "# terp-allow-destructive-migration: removing obsolete beta table\n"
        "def upgrade():\n    op.drop_table('notes_beta')\n",
    )
    assert _rule_names(check_no_destructive_migrations(app)) == {"no_destructive_migrations"}

    # A marker without a reason is not enough.
    _write(
        app,
        "modules/notes/migrations/versions/0001_change.py",
        "def upgrade():\n"
        "    # arch-allow-no-destructive-migrations:\n"
        "    op.drop_column('notes', 'legacy')\n",
    )
    assert _rule_names(check_app(app)) == {"ungoverned_escape_hatch"}

    # Downgrade teardown and non-revision files are ignored.
    _write(app, "modules/notes/migrations/env.py", "def upgrade():\n    op.drop_table('notes')\n")
    _write(
        app,
        "modules/notes/migrations/versions/0001_change.py",
        "def upgrade():\n    op.add_column('notes', column)\ndef downgrade():\n    op.drop_table('notes')\n",
    )
    assert check_no_destructive_migrations(app) == []


def test_alembic_downgrades_not_empty(tmp_path: pathlib.Path) -> None:
    app = tmp_path / "app"
    # An empty downgrade() makes a revision irreversible â€” a lone pass, an ellipsis, or
    # only a docstring all leave a rollback with nothing to run.
    empty_bodies = (
        "def downgrade():\n    pass\n",
        "def downgrade():\n    ...\n",
        "def downgrade():\n    '''revert.'''\n",
    )
    for body in empty_bodies:
        _write(
            app,
            "modules/notes/migrations/versions/0001_change.py",
            "def upgrade():\n    op.add_column('notes', column)\n" + body,
        )
        assert _rule_names(check_alembic_downgrades_not_empty(app)) == {
            "alembic_downgrades_not_empty"
        }, body

    # Clean: a downgrade that reverses the change, or a documented intentional no-op
    # (a '#' comment explaining why the step is irreversible).
    _write(
        app,
        "modules/notes/migrations/versions/0001_change.py",
        "def upgrade():\n    op.add_column('notes', column)\n"
        "def downgrade():\n    op.drop_column('notes', 'title')\n",
    )
    assert check_alembic_downgrades_not_empty(app) == []
    _write(
        app,
        "modules/notes/migrations/versions/0002_backfill.py",
        "def upgrade():\n    backfill()\n"
        "def downgrade():\n    # irreversible data backfill; nothing to undo\n    pass\n",
    )
    assert check_alembic_downgrades_not_empty(app) == []


def test_migration_history_is_intact(tmp_path: pathlib.Path) -> None:
    app = tmp_path / "app"
    versions = "modules/notes/migrations/versions"
    _write(app, f"{versions}/0001_base.py", "revision = 'aaa'\ndown_revision = None\n")
    _write(app, f"{versions}/0002_next.py", "revision = 'bbb'\ndown_revision = 'aaa'\n")
    assert check_migration_history_is_intact(app) == []

    # The parent was deleted or renamed: every database that applied it is stranded.
    _write(app, f"{versions}/0002_next.py", "revision = 'bbb'\ndown_revision = 'gone'\n")
    assert _rule_names(check_migration_history_is_intact(app)) == {
        "migration_history_is_intact"
    }

    # A second baseline is the same wound from the other side: two first revisions
    # means the chain was rewritten rather than extended.
    _write(app, f"{versions}/0002_next.py", "revision = 'bbb'\ndown_revision = None\n")
    assert len(check_migration_history_is_intact(app)) == 2

    # A cycle can name only revisions that exist and still have no usable baseline.
    _write(app, f"{versions}/0001_base.py", "revision = 'aaa'\ndown_revision = 'bbb'\n")
    _write(app, f"{versions}/0002_next.py", "revision = 'bbb'\ndown_revision = 'aaa'\n")
    violations = check_migration_history_is_intact(app)
    assert len(violations) == 1
    assert "no first revision" in violations[0].message

    # One valid root does not make a disconnected cycle part of that history.
    _write(app, f"{versions}/0001_base.py", "revision = 'aaa'\ndown_revision = None\n")
    _write(app, f"{versions}/0002_next.py", "revision = 'bbb'\ndown_revision = 'ccc'\n")
    _write(app, f"{versions}/0003_cycle.py", "revision = 'ccc'\ndown_revision = 'bbb'\n")
    assert len(check_migration_history_is_intact(app)) == 2

    # A merge revision names several parents; all of them must resolve.
    _write(app, f"{versions}/0002_next.py", "revision = 'bbb'\ndown_revision = 'aaa'\n")
    _write(app, f"{versions}/0003_merge.py", "revision = 'ccc'\ndown_revision = ('aaa', 'bbb')\n")
    assert check_migration_history_is_intact(app) == []
    _write(app, f"{versions}/0003_merge.py", "revision = 'ccc'\ndown_revision = ('aaa', 'gone')\n")
    assert _rule_names(check_migration_history_is_intact(app)) == {
        "migration_history_is_intact"
    }

    # Separate packages keep separate histories, each with its own first revision.
    _write(app, f"{versions}/0003_merge.py", "revision = 'ccc'\ndown_revision = 'bbb'\n")
    _write(
        app,
        "modules/tags/migrations/versions/0001_base.py",
        "revision = 'zzz'\ndown_revision = None\n",
    )
    assert check_migration_history_is_intact(app) == []


def test_session_imported_from_sqlmodel(tmp_path: pathlib.Path) -> None:
    app = tmp_path / "app"
    # Importing the ORM Session from SQLAlchemy forks the app onto a second session type.
    _write(app, "modules/notes/service.py", "from sqlalchemy.orm import Session\n")
    assert _rule_names(check_session_imported_from_sqlmodel(app)) == {
        "session_imported_from_sqlmodel"
    }
    _write(app, "modules/notes/service.py", "from sqlalchemy import Session, select\n")
    assert _rule_names(check_session_imported_from_sqlmodel(app)) == {
        "session_imported_from_sqlmodel"
    }
    # A deeper sqlalchemy.* path to the same class must not slip through.
    _write(app, "modules/notes/service.py", "from sqlalchemy.orm.session import Session\n")
    assert _rule_names(check_session_imported_from_sqlmodel(app)) == {
        "session_imported_from_sqlmodel"
    }
    # Clean: the canonical SQLModel session, and an unrelated sqlalchemy import.
    _write(app, "modules/notes/service.py", "from sqlmodel import Session\nfrom sqlalchemy import select\n")
    assert check_session_imported_from_sqlmodel(app) == []


def test_mutations_require_write_role(tmp_path: pathlib.Path) -> None:
    app = tmp_path / "app"
    _write(app, "modules/notes/router.py", "@router.post('/')\ndef create(): ...\n")
    # A write surface whose Policy collapses the write tier to the read floor is inverted.
    _write(
        app,
        "modules/notes/module.py",
        "module = ModuleSpec(name='notes', policy=Policy(write=Roles.VIEWER))\n",
    )
    assert _rule_names(check_mutations_require_write_role(app)) == {"mutations_require_write_role"}

    # write_role= is the same collapse by another spelling.
    _write(
        app,
        "modules/notes/module.py",
        "module = ModuleSpec(name='notes', policy=Policy(write_role=Roles.VIEWER))\n",
    )
    assert _rule_names(check_mutations_require_write_role(app)) == {"mutations_require_write_role"}

    # Policy.tiers(write=VIEWER) is the same collapse through the tier sugar.
    _write(
        app,
        "modules/notes/module.py",
        "module = ModuleSpec(name='notes', policy=Policy.tiers(read=Roles.VIEWER, write=Roles.VIEWER))\n",
    )
    assert _rule_names(check_mutations_require_write_role(app)) == {"mutations_require_write_role"}

    # Default-ladder INVERSION: write (EDITOR) ranks below read (ADMIN) -- a reader needs
    # MORE than a writer. Statically resolvable, so the build rule catches it now.
    _write(
        app,
        "modules/notes/module.py",
        "module = ModuleSpec(name='notes', policy=Policy(read=Roles.ADMIN, write=Roles.EDITOR))\n",
    )
    assert _rule_names(check_mutations_require_write_role(app)) == {"mutations_require_write_role"}

    # Same inversion when write is OMITTED (defaults to EDITOR) under a raised read tier.
    _write(
        app,
        "modules/notes/module.py",
        "module = ModuleSpec(name='notes', policy=Policy(read=Roles.ADMIN))\n",
    )
    assert _rule_names(check_mutations_require_write_role(app)) == {"mutations_require_write_role"}

    # A PUBLIC module is governed by public_modules_are_read_only, not this rule.
    _write(
        app,
        "modules/notes/module.py",
        "module = ModuleSpec(name='notes', policy=Policy.public(reason='public form'))\n",
    )
    assert check_mutations_require_write_role(app) == []

    # A CUSTOM role ladder's ranks are not statically knowable, so equality is left to the
    # boot check (create_app); the build rule does not guess and stays silent.
    _write(
        app,
        "modules/notes/module.py",
        "module = ModuleSpec(name='notes', policy=Policy(read=GUEST, write=GUEST))\n",
    )
    assert check_mutations_require_write_role(app) == []

    # A read-only module (no mutating route) is not a write surface, so a weak write tier
    # on it is not this rule's concern.
    _write(app, "modules/notes/router.py", "@router.get('/')\ndef show(): ...\n")
    _write(
        app,
        "modules/notes/module.py",
        "module = ModuleSpec(name='notes', policy=Policy(write=Roles.VIEWER))\n",
    )
    assert check_mutations_require_write_role(app) == []

    # An unrelated weak Policy NOT bound to the ModuleSpec is not the module's posture.
    _write(app, "modules/notes/router.py", "@router.post('/')\ndef create(): ...\n")
    _write(
        app,
        "modules/notes/module.py",
        "_unused = Policy(write=Roles.VIEWER)\n"
        "module = ModuleSpec(name='notes', policy=Policy.default())\n",
    )
    assert check_mutations_require_write_role(app) == []

    # Clean: the secure default (EDITOR write). A read-only module may sit at VIEWER â€”
    # even one registered imperatively (add_api_route with a non-mutating methods=).
    _write(app, "modules/notes/module.py", "module = ModuleSpec(name='notes', policy=Policy.default())\n")
    assert check_mutations_require_write_role(app) == []
    _write(app, "modules/reports/router.py", "router.add_api_route('/r', h, methods=['GET'])\n")
    _write(
        app,
        "modules/reports/module.py",
        "module = ModuleSpec(name='reports', policy=Policy(write=Roles.VIEWER))\n",
    )
    assert check_mutations_require_write_role(app) == []

    # Imperative add_api_route(methods=['POST']) is a write surface on its own.
    _write(app, "modules/bulk/router.py", "router.add_api_route('/x', handler, methods=['POST'])\n")
    _write(
        app,
        "modules/bulk/module.py",
        "module = ModuleSpec(name='bulk', policy=Policy(write=Roles.VIEWER))\n",
    )
    assert _rule_names(check_mutations_require_write_role(app)) == {"mutations_require_write_role"}

    # The generic decorator form (@router.api_route(methods=['PUT'])) counts too.
    _write(app, "modules/bulk/router.py", "@router.api_route('/y', methods=['PUT'])\ndef edit(): ...\n")
    assert _rule_names(check_mutations_require_write_role(app)) == {"mutations_require_write_role"}


def test_public_modules_are_read_only(tmp_path: pathlib.Path) -> None:
    app = tmp_path / "app"
    _write(app, "modules/contact/router.py", "@router.post('/')\ndef submit(): ...\n")
    # A public module that exposes a write is an unauthenticated write -- flagged.
    _write(
        app,
        "modules/contact/module.py",
        "module = ModuleSpec(name='contact', policy=Policy.public(reason='public form'))\n",
    )
    assert _rule_names(check_public_modules_are_read_only(app)) == {"public_modules_are_read_only"}

    # A public module with only reads is fine (a public read API).
    _write(app, "modules/contact/router.py", "@router.get('/')\ndef show(): ...\n")
    assert check_public_modules_are_read_only(app) == []

    # A non-public mutating module is governed by mutations_require_write_role, not here.
    _write(app, "modules/contact/router.py", "@router.post('/')\ndef submit(): ...\n")
    _write(
        app,
        "modules/contact/module.py",
        "module = ModuleSpec(name='contact', policy=Policy.default())\n",
    )
    assert check_public_modules_are_read_only(app) == []


def test_schemas_exclude_sensitive_fields(tmp_path: pathlib.Path) -> None:
    app = tmp_path / "app"
    # A Read DTO that mirrors a credential leaks it out of the boundary.
    _write(
        app,
        "modules/users/schemas.py",
        "class UserRead(BaseSchema):\n    id: uuid.UUID\n    hashed_password: str\n",
    )
    assert _rule_names(check_schemas_exclude_sensitive_fields(app)) == {
        "schemas_exclude_sensitive_fields"
    }

    # An input DTO reused as a response_model is no longer exempt â€” it leaks too.
    _write(
        app,
        "modules/users/router.py",
        "@router.post('/', response_model=UserCreate)\ndef make(): ...\n",
    )
    _write(
        app,
        "modules/users/schemas.py",
        "class UserCreate(BaseSchema):\n    password: str = Field(max_length=128)\n",
    )
    assert _rule_names(check_schemas_exclude_sensitive_fields(app)) == {
        "schemas_exclude_sensitive_fields"
    }

    # Broadened detection (ADR fix): credential spellings the old `.*secret$` regex
    # missed -- secret_key / private_key / salt / passphrase -- are caught as
    # underscore-delimited words.
    _write(app, "modules/users/router.py", "@router.get('/', response_model=UserRead)\ndef get(): ...\n")
    _write(
        app,
        "modules/users/schemas.py",
        "class UserRead(BaseSchema):\n    id: uuid.UUID\n    secret_key: str\n",
    )
    assert _rule_names(check_schemas_exclude_sensitive_fields(app)) == {
        "schemas_exclude_sensitive_fields"
    }

    # Clean: input bodies may take a password, a table may store the hash, a non-DTO
    # helper is not policed, and a Read DTO without secrets is fine (token_version /
    # version are counters and a benign `*_key` like sort_key is not a credential).
    # Drop the router so UserCreate is only ever a body.
    _write(app, "modules/users/router.py", "@router.get('/', response_model=UserRead)\ndef get(): ...\n")
    _write(
        app,
        "modules/users/schemas.py",
        "class UserCreate(BaseSchema):\n    password: str = Field(max_length=128)\n"
        "class UserRead(BaseSchema):\n    id: uuid.UUID\n    token_version: int\n"
        "    version: int\n    sort_key: str\n"
        "class _OAuthClient:\n    client_secret: str\n",
    )
    _write(
        app,
        "modules/users/models.py",
        "class User(BaseTable, table=True):\n    hashed_password: str\n",
    )
    assert check_schemas_exclude_sensitive_fields(app) == []


def test_canonical_module_shape(tmp_path: pathlib.Path) -> None:
    app = tmp_path / "app"
    # A module (declares a module.py) with only a router is incomplete; names the gaps.
    _write(app, "modules/notes/module.py", "module = ModuleSpec(name='notes', policy=Policy.default())\n")
    _write(app, "modules/notes/router.py", "router = APIRouter()\n")
    notes = [v for v in check_canonical_module_shape(app) if "/notes" in v.path]
    assert {v.rule for v in notes} == {"canonical_module_shape"}
    assert any("'models.py'" in v.message for v in notes)

    # A dir that looks like a module (carries canonical files) but has NO module.py manifest
    # is flagged for the missing manifest â€” otherwise it is invisible to this rule AND to
    # modules_declare_policy, so it could ship a router with no declared Policy unnoticed.
    _write(app, "modules/orphan/service.py", "# logic\n")
    _write(app, "modules/orphan/router.py", "router = APIRouter()\n")
    orphan = [v for v in check_canonical_module_shape(app) if "/orphan" in v.path]
    assert any("'module.py'" in v.message for v in orphan)

    # A dir with NO canonical file (a shared-asset / helper dir) is left alone.
    _write(app, "modules/_assets/logo.py", "# not a module\n")
    assert all("_assets" not in v.path for v in check_canonical_module_shape(app))

    # Clean: a dir carrying all five canonical slots passes.
    for name in ("models", "schemas", "service", "router", "module"):
        _write(app, f"modules/full/{name}.py", "# present\n")
    assert [v for v in check_canonical_module_shape(app) if "/full" in v.path] == []


# --------------------------------------------------------------------------- #
# harness self-completeness (meta): the suite cannot silently become incomplete
# --------------------------------------------------------------------------- #
# Orchestrators / standalone checks that are intentionally NOT in _ALL_RULES.
_NON_SCANNER_CHECKS = {"check_app", "check_escape_hatch_budget"}


def test_harness_registers_and_tests_every_rule() -> None:
    """Every scanner rule is wired into ``_ALL_RULES`` and has a matching test.

    This is the drift/incompleteness guard for the harness itself: adding a
    ``check_*`` rule but forgetting to register it in ``check_app`` (so it never
    runs) â€” or forgetting to test it â€” fails this meta-test.
    """
    import terp.arch.rules as rules_module

    scanner_checks = {
        name
        for name in dir(rules_module)
        if name.startswith("check_") and name not in _NON_SCANNER_CHECKS
    }
    registered = {rule.__name__ for rule in rules_module._ALL_RULES}
    assert scanner_checks == registered, (
        "every scanner rule must be wired into _ALL_RULES â€” "
        f"unwired: {sorted(scanner_checks - registered)}; "
        f"stray: {sorted(registered - scanner_checks)}"
    )

    tests_here = {name for name in globals() if name.startswith("test_")}
    missing_tests = {
        rule_name
        for rule_name in registered
        if f"test_{rule_name.removeprefix('check_')}" not in tests_here
    }
    assert not missing_tests, (
        "every registered rule needs a matching test_<rule> in this module; "
        f"missing: {sorted(missing_tests)}"
    )


def test_example_app_passes_the_whole_harness() -> None:
    # Dogfood: the real secure-CRUD example app must satisfy every rule. Its one
    # justified opt-out (the journals read-visibility predicate, ADR 0061) is
    # governed by the checked-in budget.
    assert check_app(_EXAMPLE_APP) == []
    assert_app_clean(_EXAMPLE_APP, budget_path=_EXAMPLE_BUDGET)


# --------------------------------------------------------------------------- #
# escape-hatch opt-out: justified suppression + governed budget ratchet (Â§8)
# --------------------------------------------------------------------------- #
def test_justified_marker_suppresses_its_rule(tmp_path: pathlib.Path) -> None:
    app = tmp_path / "app"
    _write(
        app,
        "modules/notes/service.py",
        f"{_INTERNAL_IMPORT}  # arch-allow-no-internal-imports: kernel bootstrap shim\n",
    )
    # The justified opt-out removes exactly that violation; nothing else fires.
    assert check_app(app) == []


def test_unjustified_marker_does_not_suppress(tmp_path: pathlib.Path) -> None:
    app = tmp_path / "app"
    _write(app, "modules/notes/service.py", f"{_INTERNAL_IMPORT}  # arch-allow-no-internal-imports\n")
    # A reason-less opt-out fails closed: the breach is re-reported under the
    # catalogued fail-closed governance condition (never an uncatalogued rule id).
    assert _rule_names(check_app(app)) == {"ungoverned_escape_hatch"}


def test_marker_on_the_line_above_suppresses(tmp_path: pathlib.Path) -> None:
    # The escape-hatch contract's second sanctioned position: a justified marker
    # comment immediately above the violating line.
    app = tmp_path / "app"
    _write(
        app,
        "modules/notes/service.py",
        "# arch-allow-no-internal-imports: kernel bootstrap shim\n"
        f"{_INTERNAL_IMPORT}\n",
    )
    assert check_app(app) == []


def test_marker_inside_a_string_literal_is_inert(tmp_path: pathlib.Path) -> None:
    # Markers live in real comments only: marker-shaped text in a string neither
    # suppresses (same line or line above) nor counts toward the budget.
    app = tmp_path / "app"
    _write(
        app,
        "modules/notes/service.py",
        'DOC = "# arch-allow-no-internal-imports: not a comment"\n'
        f"{_INTERNAL_IMPORT}  # noqa\n",
    )
    assert _rule_names(check_app(app)) == {"no_internal_imports"}
    budget = tmp_path / "escape-hatch-budget.json"
    budget.write_text("{}", encoding="utf-8")
    assert check_escape_hatch_budget(app, budget_path=budget) == []


def test_an_untokenizable_file_counts_no_markers(tmp_path: pathlib.Path) -> None:
    # Fail closed: a file the tokenizer refuses (here an unterminated triple-quote)
    # yields no comments at all, so a marker inside it is neither honoured nor
    # counted toward the budget â€” even a marker on a line the tokenizer had
    # already passed is discarded with the file.
    app = tmp_path / "app"
    _write(
        app,
        "modules/notes/service.py",
        "# arch-allow-no-internal-imports: smuggled into a broken file\n"
        'BROKEN = """\n',
    )
    budget = tmp_path / "escape-hatch-budget.json"
    budget.write_text("{}", encoding="utf-8")
    assert check_escape_hatch_budget(app, budget_path=budget) == []


def test_marker_only_suppresses_the_named_rule(tmp_path: pathlib.Path) -> None:
    app = tmp_path / "app"
    # Marker names a *different* rule, so the real violation still stands.
    _write(
        app,
        "modules/notes/service.py",
        f"{_INTERNAL_IMPORT}  # arch-allow-no-raw-session-construction: wrong rule\n",
    )
    assert _rule_names(check_app(app)) == {"no_internal_imports"}


def test_escape_hatch_budget_accepts_exact_match(tmp_path: pathlib.Path) -> None:
    app = tmp_path / "app"
    _write(
        app,
        "modules/notes/service.py",
        f"{_INTERNAL_IMPORT}  # arch-allow-no-internal-imports: kernel bootstrap shim\n",
    )
    budget = tmp_path / "escape-hatch-budget.json"
    budget.write_text(json.dumps({"arch-allow-no-internal-imports": 1}), encoding="utf-8")
    assert check_escape_hatch_budget(app, budget_path=budget) == []
    # End to end: suppressed violation + matching budget â‡’ a clean app.
    assert check_app(app, budget_path=budget) == []
    assert_app_clean(app, budget_path=budget)


def test_escape_hatch_budget_rejects_unbudgeted_marker(tmp_path: pathlib.Path) -> None:
    app = tmp_path / "app"
    _write(
        app,
        "modules/notes/service.py",
        f"{_INTERNAL_IMPORT}  # arch-allow-no-internal-imports: shim\n",
    )
    budget = tmp_path / "escape-hatch-budget.json"
    budget.write_text("{}", encoding="utf-8")
    violations = check_escape_hatch_budget(app, budget_path=budget)
    assert _rule_names(violations) == {"escape_hatch_budget"}
    assert "is not in the budget" in violations[0].message


def test_escape_hatch_budget_rejects_a_rise(tmp_path: pathlib.Path) -> None:
    app = tmp_path / "app"
    _write(
        app,
        "modules/notes/service.py",
        f"{_INTERNAL_IMPORT}  # arch-allow-no-internal-imports: shim\n"
        f"{_INTERNAL_IMPORT}  # arch-allow-no-internal-imports: shim two\n",
    )
    budget = tmp_path / "escape-hatch-budget.json"
    budget.write_text(json.dumps({"arch-allow-no-internal-imports": 1}), encoding="utf-8")
    violations = check_escape_hatch_budget(app, budget_path=budget)
    assert _rule_names(violations) == {"escape_hatch_budget"}
    assert "rose to 2" in violations[0].message


def test_escape_hatch_budget_rejects_a_stale_entry(tmp_path: pathlib.Path) -> None:
    # The win is locked in: removing a marker forces lowering the budget.
    app = tmp_path / "app"
    _write(app, "modules/notes/service.py", "from terp.core import BaseService\n")
    budget = tmp_path / "escape-hatch-budget.json"
    budget.write_text(json.dumps({"arch-allow-no-internal-imports": 2}), encoding="utf-8")
    violations = check_escape_hatch_budget(app, budget_path=budget)
    assert _rule_names(violations) == {"escape_hatch_budget"}
    assert "dropped to 0" in violations[0].message


def test_escape_hatch_budget_rejects_an_unknown_marker_name(tmp_path: pathlib.Path) -> None:
    # A typo, a stale name, or the governance rule's own token names no governed
    # opt-out â€” it can never be budgeted into legitimacy.
    app = tmp_path / "app"
    _write(
        app,
        "modules/notes/service.py",
        "from terp.core import BaseService  # arch-allow-made-up-rule: stale\n",
    )
    budget = tmp_path / "escape-hatch-budget.json"
    budget.write_text(
        json.dumps({"arch-allow-made-up-rule": 1, "arch-allow-escape-hatch-budget": 1}),
        encoding="utf-8",
    )
    violations = check_escape_hatch_budget(app, budget_path=budget)
    assert _rule_names(violations) == {"escape_hatch_budget"}
    assert all("names no rule with a governed opt-out" in v.message for v in violations)
    assert len(violations) == 2


def test_markers_require_a_budget_to_be_clean(tmp_path: pathlib.Path) -> None:
    app = tmp_path / "app"
    _write(
        app,
        "modules/notes/service.py",
        f"{_INTERNAL_IMPORT}  # arch-allow-no-internal-imports: shim\n",
    )
    # An opt-out may not be used un-governed: assert_app_clean demands a budget.
    with pytest.raises(AssertionError, match="budget"):
        assert_app_clean(app)


def test_expired_review_by_token_is_surfaced(tmp_path: pathlib.Path) -> None:
    # The spec's escape-hatch contract: a reason MAY carry review-by:<YYYY-MM-DD>;
    # a toolchain SHOULD surface expired dates â€” so a long-lived opt-out is
    # re-justified on schedule instead of staying silently eternal.
    import datetime

    app = tmp_path / "app"
    _write(
        app,
        "modules/notes/service.py",
        f"{_INTERNAL_IMPORT}  # arch-allow-no-internal-imports: shim owner:core "
        "ticket:APP-7 review-by:2026-01-31\n",
    )
    budget = tmp_path / "escape-hatch-budget.json"
    budget.write_text(json.dumps({"arch-allow-no-internal-imports": 1}), encoding="utf-8")
    violations = check_escape_hatch_budget(
        app, budget_path=budget, today=datetime.date(2026, 2, 1)
    )
    assert _rule_names(violations) == {"escape_hatch_budget"}
    assert len(violations) == 1
    assert violations[0].path.replace("\\", "/") == "app/modules/notes/service.py"
    assert violations[0].line == 1
    assert "review-by:2026-01-31" in violations[0].message
    assert "re-justify" in violations[0].message
    # Due today = not yet passed; a future date is simply fine.
    assert (
        check_escape_hatch_budget(
            app, budget_path=budget, today=datetime.date(2026, 1, 31)
        )
        == []
    )


def test_review_by_is_a_convention_not_a_gate(tmp_path: pathlib.Path) -> None:
    # A reason without the token is never rejected (the spec's MUST NOT), and a
    # malformed date is not a well-formed token â€” neither fires, ever.
    import datetime

    app = tmp_path / "app"
    _write(
        app,
        "modules/notes/service.py",
        f"{_INTERNAL_IMPORT}  # arch-allow-no-internal-imports: no token here\n"
        f"{_INTERNAL_IMPORT}  # arch-allow-no-internal-imports: review-by:2020-13-45 broken\n"
        f"{_INTERNAL_IMPORT}  # arch-allow-no-internal-imports: review-by:someday prose\n",
    )
    budget = tmp_path / "escape-hatch-budget.json"
    budget.write_text(json.dumps({"arch-allow-no-internal-imports": 3}), encoding="utf-8")
    assert (
        check_escape_hatch_budget(
            app, budget_path=budget, today=datetime.date(2030, 1, 1)
        )
        == []
    )


def test_example_app_escape_hatch_budget_is_clean() -> None:
    # Dogfood: the example app's single opt-out (the journals read-visibility
    # predicate's owner_id comparison, ADR 0061) is governed â€” the budget agrees exactly.
    assert check_escape_hatch_budget(_EXAMPLE_APP, budget_path=_EXAMPLE_BUDGET) == []
    assert_app_clean(_EXAMPLE_APP, budget_path=_EXAMPLE_BUDGET)


def test_table_ownership_is_not_split(tmp_path: pathlib.Path) -> None:
    app = tmp_path / "app"
    # Aligned: the package whose model declares the table is the one whose history
    # creates it.
    _write(
        app,
        "modules/notes/models.py",
        "class Note(BaseTable, table=True):\n"
        "    __tablename__ = 'notes_note'\n",
    )
    _write(
        app,
        "modules/notes/migrations/versions/0001_create.py",
        "def upgrade():\n    op.create_table('notes_note')\n",
    )
    assert check_table_ownership_is_not_split(app) == []

    # A second package that owns nothing of notes' is irrelevant.
    _write(
        app,
        "modules/tasks/migrations/versions/0001_create.py",
        "def upgrade():\n    op.create_table('tasks_task')\n",
    )
    assert check_table_ownership_is_not_split(app) == []

    # Split: the model moved to tasks but notes' history still creates the table.
    # This is the state that emits no ddl at all and breaks only fresh installs.
    (app / "modules/notes/models.py").unlink()
    _write(
        app,
        "modules/tasks/models.py",
        "class Note(BaseTable, table=True):\n"
        "    __tablename__ = 'notes_note'\n",
    )
    violations = check_table_ownership_is_not_split(app)
    assert _rule_names(violations) == {"table_ownership_is_not_split"}
    assert len(violations) == 1
    assert "notes" in violations[0].message  # the creating package is named
    assert "expand/contract" in violations[0].message  # the remedy is named

    # A table declared but created by nobody yet is the normal pre-`make` state, and
    # an annotated __tablename__ is read the same way as a plain assignment.
    _write(
        app,
        "modules/tasks/models.py",
        "class Task(BaseTable, table=True):\n"
        "    __tablename__: str = 'tasks_pending'\n",
    )
    assert check_table_ownership_is_not_split(app) == []

    # A create in downgrade (reverting a drop) is not a claim of ownership, and a
    # computed __tablename__ is skipped rather than guessed at.
    _write(
        app,
        "modules/tasks/models.py",
        "class Note(BaseTable, table=True):\n"
        "    __tablename__ = _name()\n",
    )
    _write(
        app,
        "modules/notes/migrations/versions/0001_create.py",
        "def downgrade():\n    op.create_table('notes_note')\n",
    )
    assert check_table_ownership_is_not_split(app) == []

    # Neither a model nor a history that sits outside a module/capability package has
    # an owning package, so neither can claim a table. The rule is about which of two
    # packages owns a table; code that belongs to no package is not one of the two.
    _write(
        app,
        "models.py",
        "class Loose(BaseTable, table=True):\n    __tablename__ = 'loose_thing'\n",
    )
    _write(
        app,
        "migrations/versions/0001_create.py",
        "def upgrade():\n    op.create_table('loose_thing')\n",
    )
    assert check_table_ownership_is_not_split(app) == []

