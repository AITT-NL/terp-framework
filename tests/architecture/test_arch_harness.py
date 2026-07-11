"""Gate for ``terp.arch``: every rule fires on a violation and the example app is clean.

The harness is Terp's build-time enforcement layer (design §5.10). These tests
prove each rule (1) catches the breach it targets and (2) does **not** fire on
correct code — and that the real ``apps/example/app`` passes the whole suite,
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
    check_no_destructive_migrations,
    check_no_dynamic_sql,
    check_no_cross_module_imports,
    check_no_hardcoded_credentials,
    check_no_internal_imports,
    check_no_manual_actor_stamping,
    check_no_manual_ownership_checks,
    check_no_raw_app_routes,
    check_no_raw_file_references,
    check_no_manual_scope_filtering,
    check_no_raw_connection_access,
    check_no_raw_outbound_http,
    check_no_raw_session_construction,
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

    # Importing one's own module is fine — absolute or relative.
    _write(app, "modules/a/service.py", "from app.modules.a.models import Thing\n")
    assert check_no_cross_module_imports(app) == []

    _write(app, "modules/a/service.py", "from .models import Thing\n")
    assert check_no_cross_module_imports(app) == []


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
    assert _rule_names(check_modules_declare_policy(app)) == {"modules_declare_policy"}

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

    # An undeclared authority name is a violation — module alias spelling.
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

    # Declared names resolve — assignment, tuple/annotated targets, aliased
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

    # References the scan cannot trace to the registry are left to the boot check —
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

    # A unique on a NON-soft-delete model is fine (rows are truly gone on delete)…
    _write(
        app,
        "modules/notes/models.py",
        "class Note(BaseTable, table=True):\n"
        "    slug: str = Field(max_length=50, unique=True)\n",
    )
    assert check_no_unique_columns_on_soft_delete_models(app) == []

    # …as is a soft-delete model without unique columns, and a non-table schema class.
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
    # dev/test dialect), reinstating the dead-row trap — so it must stay flagged.
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

    # A raw thread / process is ad-hoc background execution outside the jobs seam — flagged
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
    # execution — allowed (exactly what the users cap's last-admin lock imports).
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

    # A write smuggled through execute()/exec() with a DML statement is caught —
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
    # Bare-string events anywhere they are named — emit / subscribe / ModuleSpec.
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

    # An inline EventDefinition(...) is drift too — it bypasses the catalog.
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


def test_jobs_reference_catalog(tmp_path: pathlib.Path) -> None:
    app = tmp_path / "app"
    # Bare-string jobs anywhere they are named — enqueue(job=) / ModuleSpec(jobs=).
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

    # An inline JobDefinition(...) is drift too — it bypasses the catalog.
    _write(
        app,
        "modules/billing/service.py",
        "def run(session) -> None:\n    enqueue(session, job=JobDefinition('x.y', P, h), payload=p)\n",
    )
    assert _rule_names(check_jobs_reference_catalog(app)) == {"jobs_reference_catalog"}


def test_no_adhoc_config_decrypt(tmp_path: pathlib.Path) -> None:
    app = tmp_path / "app"
    # A module decrypting sealed config ad hoc is flagged — bare call and attribute form.
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

    # Masked rendering (and sealing) are freely usable — only decrypt is the chokepoint.
    _write(
        app,
        "modules/billing/service.py",
        "def shown() -> str:\n    return mask_config(settings.DB_DSN)\n"
        "def seal(value: str) -> str:\n    return encrypt_config(value)\n",
    )
    assert check_no_adhoc_config_decrypt(app) == []

    # The one sanctioned site is a justified, budgeted arch-allow opt-out (design §5.4).
    _write(
        app,
        "main.py",
        "def read_sealed(value: str) -> str:\n"
        "    return decrypt_config(value)  # arch-allow-no-adhoc-config-decrypt: the one §5.4 site\n",
    )
    assert "no_adhoc_config_decrypt" not in _rule_names(check_app(app))


def test_no_hardcoded_credentials(tmp_path: pathlib.Path) -> None:
    app = tmp_path / "app"
    for source in (
        "PASSWORD = 'not-from-config'",
        "self.api_key = 'not-from-config'",
        "client_secret: str = 'not-from-config'",
        "(password, label) = 'not-from-config'",
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
        "config['password'] = 'dev-only'\nlabel = 'not-secret'\n",
    )
    assert check_no_hardcoded_credentials(app) == []

    # The rule follows app-module scope.
    _write(app, "scripts/bootstrap.py", "password = 'dev-only'\n")
    _write(app, "modules/billing/service.py", "password = ''\n")
    assert check_no_hardcoded_credentials(app) == []

    # tests/ and migrations/ dirs inside a module are committed source: still scanned (G1).
    _write(app, "modules/billing/tests/helper.py", "api_key = 'not-from-config'\n")
    assert _rule_names(check_no_hardcoded_credentials(app)) == {"no_hardcoded_credentials"}



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

    # Clean: the column is declared with FileRef(...) — greppable, runtime-verified by
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
    # A scope-trait model (TenantScopedMixin/SoftDeleteMixin) read via a raw select() —
    # in ANY chain position (args, select_from, join, where) — drops soft-delete /
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
    # A bare list[...] response_model serializes an unbounded collection — must be Page[...].
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


def test_safe_methods_are_read_only(tmp_path: pathlib.Path) -> None:
    app = tmp_path / "app"
    # Any handler REACHABLE via a safe method (GET/HEAD/OPTIONS) must not call a mutating
    # BaseService method: create/update/delete on a self/*service* receiver, or the
    # _save/_remove primitives. This covers a decorator route, a mixed-method api_route
    # (the GET path still runs at the read tier), an api_route defaulting to GET, and an
    # imperative add_api_route (default GET or an explicit safe method) — six writes.
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
    assert len(flagged) == 2  # connection() and get_bind() — once each, no duplicate

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
    # statically (a variable), stays clean — triggers/indexes destroy no row data.
    _write(
        app,
        "modules/notes/migrations/versions/0001_change.py",
        "def upgrade():\n    op.execute('CREATE TRIGGER trg AFTER INSERT ON notes BEGIN SELECT 1; END')\n"
        "    op.execute(statement)\n",
    )
    assert check_no_destructive_migrations(app) == []

    # A reason-bearing file-level marker permits a reviewed destructive migration.
    _write(
        app,
        "modules/notes/migrations/versions/0001_change.py",
        "# terp-allow-destructive-migration: removing obsolete beta table\n"
        "def upgrade():\n    op.drop_table('notes_beta')\n",
    )
    assert check_no_destructive_migrations(app) == []

    # A marker without a reason is not enough.
    _write(
        app,
        "modules/notes/migrations/versions/0001_change.py",
        "# terp-allow-destructive-migration:\n"
        "def upgrade():\n    op.drop_column('notes', 'legacy')\n",
    )
    assert _rule_names(check_no_destructive_migrations(app)) == {"no_destructive_migrations"}

    # Downgrade teardown and non-revision files are ignored.
    _write(app, "modules/notes/migrations/env.py", "def upgrade():\n    op.drop_table('notes')\n")
    _write(
        app,
        "modules/notes/migrations/versions/0001_change.py",
        "def upgrade():\n    op.add_column('notes', column)\ndef downgrade():\n    op.drop_table('notes')\n",
    )
    assert check_no_destructive_migrations(app) == []



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

    # Clean: the secure default (EDITOR write). A read-only module may sit at VIEWER —
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

    # An input DTO reused as a response_model is no longer exempt — it leaks too.
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
    # is flagged for the missing manifest — otherwise it is invisible to this rule AND to
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
    runs) — or forgetting to test it — fails this meta-test.
    """
    import terp.arch.rules as rules_module

    scanner_checks = {
        name
        for name in dir(rules_module)
        if name.startswith("check_") and name not in _NON_SCANNER_CHECKS
    }
    registered = {rule.__name__ for rule in rules_module._ALL_RULES}
    assert scanner_checks == registered, (
        "every scanner rule must be wired into _ALL_RULES — "
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
# escape-hatch opt-out: justified suppression + governed budget ratchet (§8)
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
    # A reason-less opt-out fails closed: the breach is re-reported as needing a reason.
    assert _rule_names(check_app(app)) == {"escape_hatch_requires_justification"}


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
    # End to end: suppressed violation + matching budget ⇒ a clean app.
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


def test_example_app_escape_hatch_budget_is_clean() -> None:
    # Dogfood: the example app's single opt-out (the journals read-visibility
    # predicate's owner_id comparison, ADR 0061) is governed — the budget agrees exactly.
    assert check_escape_hatch_budget(_EXAMPLE_APP, budget_path=_EXAMPLE_BUDGET) == []
    assert_app_clean(_EXAMPLE_APP, budget_path=_EXAMPLE_BUDGET)
