"""``terp new module`` — scaffold a canonical secure-by-default module (Tier-C).

Emits the five fixed slots (``models`` / ``schemas`` / ``service`` / ``router`` /
``module``) plus the package ``__init__`` into ``<app>/modules/<name>/``. The output
is deliberately the *canonical* shape: it passes every ``terp.arch`` rule out of the
box, so the only remaining step before a green gate is the model's first migration
(``terp migrate make <name>``) — the 10-minute path of design §13.

The generated code is yours to edit (Level-1 sugar, never a runtime black box):
inherit ``BaseTable``, declare DTOs, set ``model`` on a ``BaseService``, keep the
router thin. There is no magic to remove.
"""

from __future__ import annotations

import keyword
import pathlib
from collections.abc import Sequence


def _singular(name: str) -> str:
    """``invoices`` -> ``invoice``; ``billing`` -> ``billing`` (drop a trailing ``s``)."""
    return name[:-1] if name.endswith("s") else name


def _model_name(name: str) -> str:
    """``invoices`` -> ``Invoice``; ``billing`` -> ``Billing`` (PascalCase, singular)."""
    singular = _singular(name)
    return singular[:1].upper() + singular[1:]


def _pascal(name: str) -> str:
    """``invoices`` -> ``Invoices`` (PascalCase, plurality unchanged) for view/nav names."""
    return name[:1].upper() + name[1:]


def _validate_name(name: str) -> str:
    """A module name must be a lowercase, importable identifier (no dots / spaces)."""
    if not name.isidentifier() or keyword.iskeyword(name):
        raise SystemExit(
            f"invalid module name {name!r}: use a lowercase Python identifier "
            "(e.g. 'invoices')"
        )
    return name


def _models_py(model: str, name: str) -> str:
    return f'''\
"""``{name}`` table model — composes the kernel ``BaseTable`` (UUID + timestamps + OCC)."""

from __future__ import annotations

from sqlmodel import Field

from terp.core import BaseTable


class {model}(BaseTable, table=True):
    """``id`` / ``created_at`` / ``updated_at`` / ``version`` are inherited — never redeclared."""

    __tablename__ = "{_singular(name)}"

    name: str = Field(max_length=200, index=True)
'''


def _schemas_py(model: str) -> str:
    return f'''\
"""``{model}`` DTOs — compose the kernel schema bases; cap every input string."""

from __future__ import annotations

import datetime
import uuid

from sqlmodel import Field

from terp.core import BaseSchema, BaseUpdateSchema


class {model}Create(BaseSchema):
    name: str = Field(max_length=200)


class {model}Update(BaseUpdateSchema):
    name: str | None = Field(default=None, max_length=200)
    # `version: int` is inherited and required (optimistic concurrency).


class {model}Read(BaseSchema):
    id: uuid.UUID
    name: str
    version: int
    created_at: datetime.datetime
    updated_at: datetime.datetime
'''


def _service_py(model: str, name: str, package: str) -> str:
    return f'''\
"""``{name}`` service — CRUD is inherited from ``BaseService`` (audited, OCC, scoped)."""

from __future__ import annotations

from terp.core import BaseService

from {package}.modules.{name}.models import {model}
from {package}.modules.{name}.schemas import {model}Create, {model}Update


class {model}Service(BaseService[{model}, {model}Create, {model}Update]):
    model = {model}
'''


def _router_py(model: str, name: str, package: str) -> str:
    return f'''\
"""``{name}`` router — thin CRUD over :class:`{model}Service` using kernel seams only."""

from __future__ import annotations

import uuid

from fastapi import APIRouter

from terp.core import Page, PaginationDep, SessionDep

from {package}.modules.{name}.schemas import {model}Create, {model}Read, {model}Update
from {package}.modules.{name}.service import {model}Service

router = APIRouter(tags=["{name}"])
_service = {model}Service()


@router.get("/", response_model=Page[{model}Read])
def list_{name}(session: SessionDep, pagination: PaginationDep) -> Page[{model}Read]:
    rows, total = _service.list(session, skip=pagination.skip, limit=pagination.limit)
    return Page[{model}Read].of(
        [{model}Read.model_validate(row) for row in rows], total, pagination
    )


@router.post("/", response_model={model}Read, status_code=201)
def create_{model.lower()}(payload: {model}Create, session: SessionDep) -> {model}Read:
    return {model}Read.model_validate(_service.create(session, payload))


@router.get("/{{item_id}}", response_model={model}Read)
def get_{model.lower()}(item_id: uuid.UUID, session: SessionDep) -> {model}Read:
    return {model}Read.model_validate(_service.get(session, item_id))


@router.patch("/{{item_id}}", response_model={model}Read)
def update_{model.lower()}(
    item_id: uuid.UUID, payload: {model}Update, session: SessionDep
) -> {model}Read:
    return {model}Read.model_validate(_service.update(session, item_id, payload))


@router.delete("/{{item_id}}", status_code=204)
def delete_{model.lower()}(item_id: uuid.UUID, session: SessionDep) -> None:
    _service.delete(session, item_id)
'''


def _module_py(name: str, package: str) -> str:
    return f'''\
"""``{name}`` manifest — the entire public surface; ``Policy.default()`` is secure-by-default."""

from __future__ import annotations

from terp.core import ModuleSpec, Policy

from {package}.modules.{name}.router import router

module = ModuleSpec(name="{name}", router=router, policy=Policy.default())
'''


def _files(name: str, package: str) -> dict[str, str]:
    model = _model_name(name)
    return {
        "__init__.py": "",
        "models.py": _models_py(model, name),
        "schemas.py": _schemas_py(model),
        "service.py": _service_py(model, name, package),
        "router.py": _router_py(model, name, package),
        "module.py": _module_py(name, package),
    }


_MODULE_TSX = """\
import { defineModuleManifest } from "@terp/contract";

import { __PASCAL__List } from "./__PASCAL__List";

// Dropped in and auto-discovered by renderTerpApp's import.meta.glob — no registration.
export const manifest = defineModuleManifest({
  name: "__NAME__",
  routes: [{ path: "/__NAME__", view: "__PASCAL__List" }],
  nav: [{ label: "__PASCAL__", to: "/__NAME__" }],
});

export const views = { __PASCAL__List };
"""

_VIEW_TSX = """\
// The `__NAME__` module view — a starting point you own (real React, no hidden DSL). It composes
// the shared <ResourceList> so every module lists + creates the same way, with the write-gate
// applied for you. Wire it to YOUR endpoint once you've generated the typed client:
//
//   uv run terp openapi && npm --prefix frontend run generate   // -> src/api/schema.d.ts
//
//   import { useResource, useTerpClient } from "@terp/react-core";
//   import type { paths, components } from "../../api/schema";
//   type __PASCAL__ = components["schemas"]["__PASCAL__Read"];
//   const client = useTerpClient<paths>();
//   const __NAME__ = useResource<__PASCAL__, string>({
//     list: async () => (await client.GET("/api/v1/__NAME__/", {})).data?.items ?? [],
//     create: async (name) => { await client.POST("/api/v1/__NAME__/", { body: { name } }); },
//   });
//   // ...then pass createPlaceholder="New __NAME__" to <ResourceList> so writers can add rows.
//
import { OverviewPage, ResourceList, useResource } from "@terp/react-core";

export function __PASCAL__List() {
  // Placeholder until you wire the typed client above: an empty, read-only list (compiles pre-codegen).
  const __NAME__ = useResource<{ id: string; name: string }, string>({ list: async () => [] });
  return (
    <OverviewPage title="__PASCAL__">
      <ResourceList
        resource={__NAME__}
        renderItem={(item) => <strong>{item.name}</strong>}
      />
    </OverviewPage>
  );
}
"""


def _frontend_files(name: str) -> dict[str, str]:
    """The frontend slot: a self-describing ``module.tsx`` + a starter list view."""
    pascal = _pascal(name)
    return {
        "module.tsx": _MODULE_TSX.replace("__PASCAL__", pascal).replace("__NAME__", name),
        f"{pascal}List.tsx": _VIEW_TSX.replace("__PASCAL__", pascal).replace("__NAME__", name),
    }


def new_module(
    name: str,
    *,
    root: str | pathlib.Path = ".",
    package: str = "app",
    frontend: bool = True,
) -> list[pathlib.Path]:
    """Scaffold the canonical ``<package>/modules/<name>/`` module under *root*.

    When *frontend* is true and a ``frontend/src/modules`` app exists under *root*, the
    matching frontend slot (``module.tsx`` + a starter ``<Name>List.tsx`` view) is emitted
    too, so the module is full-stack and auto-discovered by ``renderTerpApp`` — no central
    registration. A backend-only repo (no frontend app) silently gets just the backend.

    Returns the created file paths. Raises :class:`SystemExit` for an invalid name or
    an existing destination, so a partial overwrite never happens.
    """
    name = _validate_name(name)
    root_path = pathlib.Path(root)
    destination = root_path / package / "modules" / name
    if destination.exists():
        raise SystemExit(f"refusing to overwrite existing module directory: {destination}")

    frontend_modules = root_path / "frontend" / "src" / "modules"
    emit_frontend = frontend and frontend_modules.is_dir()
    frontend_destination = frontend_modules / name
    if emit_frontend and frontend_destination.exists():
        raise SystemExit(
            f"refusing to overwrite existing frontend module directory: {frontend_destination}"
        )

    destination.mkdir(parents=True)
    created: list[pathlib.Path] = []
    for filename, content in _files(name, package).items():
        path = destination / filename
        path.write_text(content, encoding="utf-8")
        created.append(path)

    if emit_frontend:
        frontend_destination.mkdir(parents=True)
        for filename, content in _frontend_files(name).items():
            path = frontend_destination / filename
            path.write_text(content, encoding="utf-8")
            created.append(path)

    return created


def new_module_message(name: str, paths: Sequence[pathlib.Path]) -> str:
    """The human/agent-facing next-steps note after scaffolding *name*."""
    listing = "\n".join(f"  {path}" for path in paths)
    has_frontend = any(path.suffix == ".tsx" for path in paths)
    steps = [
        f"  app/main.py                       # mount it: from app.modules.{name}.module "
        f"import module as {name}_module; add {name}_module to the modules list",
        f"  uv run terp migrate make {name}   # first migration (before a green gate)",
    ]
    if has_frontend:
        steps.append(
            f"  uv run terp openapi               # regenerate the contract so the client sees /api/v1/{name}/"
        )
        steps.append(
            "  npm --prefix frontend run generate   # openapi.json -> frontend/src/api/schema.d.ts (typed client)"
        )
    steps.append("  uv run terp check                 # run the architecture gate locally")
    return (
        f"Scaffolded module {name!r} ({len(paths)} files):\n{listing}\n\n"
        "Next:\n" + "\n".join(steps)
    )
