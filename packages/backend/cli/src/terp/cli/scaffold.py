"""``terp new module`` — scaffold a canonical secure-by-default module (Tier-C).

Emits the five fixed slots (``models`` / ``schemas`` / ``service`` / ``router`` /
``module``) plus the package ``__init__`` into ``<app>/modules/<name>/``. The output
includes the module manifest and its tests. The CLI prints the project-specific steps
to mount the module, create its first migration and refresh generated contracts.

The generated code is yours to edit (Level-1 sugar, never a runtime black box):
inherit ``BaseTable``, declare DTOs, set ``model`` on a ``BaseService``, keep the
router thin. There is no magic to remove.

``--profile`` picks a :mod:`permission profile <terp.cli.profiles>` — a preset that
only decides which existing primitives the slots compose (``Policy``, model traits,
service base); the output stays canonical and gate-checked either way.
"""

from __future__ import annotations

import keyword
import pathlib
from collections.abc import Sequence

from terp.cli.profiles import DEFAULT_PROFILE, ModuleProfile, get_profile
from terp.cli.scaffold_frontend import frontend_files


def _singular(name: str) -> str:
    """``invoices`` -> ``invoice``; ``billing`` -> ``billing`` (drop a trailing ``s``)."""
    return name[:-1] if len(name) > 1 and name.endswith("s") else name


def _model_name(name: str) -> str:
    """``invoices`` -> ``Invoice``; ``billing`` -> ``Billing`` (PascalCase, singular)."""
    model = _pascal(_singular(name))
    return f"{model}Record" if keyword.iskeyword(model) else model


def _pascal(name: str) -> str:
    """``invoices`` -> ``Invoices`` (PascalCase, plurality unchanged) for view/nav names."""
    pascal = "".join(word[:1].upper() + word[1:] for word in name.split("_"))
    return pascal if pascal.isidentifier() else f"Module{pascal}"


def _validate_name(name: str) -> str:
    """A module name must be a lowercase, importable identifier (no dots / spaces)."""
    if not name.isidentifier() or keyword.iskeyword(name):
        raise SystemExit(
            f"invalid module name {name!r}: use a lowercase Python identifier "
            "(e.g. 'invoices')"
        )
    return name


def _models_py(model: str, name: str, profile: ModuleProfile) -> str:
    core_imports = ", ".join(("BaseTable", *sorted(profile.core_model_mixins)))
    extra_imports = "".join(f"{line}\n" for line in profile.model_import_lines)
    bases = ", ".join(("BaseTable", *profile.model_mixins))
    return f'''\
"""``{name}`` table model — composes the kernel ``BaseTable`` (UUID + timestamps + OCC)."""

from __future__ import annotations

from sqlmodel import Field

{extra_imports}from terp.core import {core_imports}


class {model}({bases}, table=True):
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


def _service_py(model: str, name: str, package: str, profile: ModuleProfile) -> str:
    base = profile.service_base
    return f'''\
"""``{name}`` service — CRUD is inherited from ``{base}`` (audited, OCC, scoped)."""

from __future__ import annotations

{profile.service_import_line}

from {package}.modules.{name}.models import {model}
from {package}.modules.{name}.schemas import {model}Create, {model}Update


class {model}Service({base}[{model}, {model}Create, {model}Update]):
    model = {model}
'''


def _router_py(model: str, name: str, package: str) -> str:
    singular = _singular(name).lower()
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
def create_{singular}(payload: {model}Create, session: SessionDep) -> {model}Read:
    return {model}Read.model_validate(_service.create(session, payload))


@router.get("/{{item_id}}", response_model={model}Read)
def get_{singular}(item_id: uuid.UUID, session: SessionDep) -> {model}Read:
    return {model}Read.model_validate(_service.get(session, item_id))


@router.patch("/{{item_id}}", response_model={model}Read)
def update_{singular}(
    item_id: uuid.UUID, payload: {model}Update, session: SessionDep
) -> {model}Read:
    return {model}Read.model_validate(_service.update(session, item_id, payload))


@router.delete("/{{item_id}}", status_code=204)
def delete_{singular}(item_id: uuid.UUID, session: SessionDep) -> None:
    _service.delete(session, item_id)
'''


def _module_py(name: str, package: str, profile: ModuleProfile) -> str:
    model = _model_name(name)
    core_imports = ", ".join(sorted(profile.policy_imports))
    return f'''\
"""``{name}`` manifest — the entire public surface; profile ``{profile.name}``."""

from __future__ import annotations

from terp.core import {core_imports}

from {package}.modules.{name}.router import router
from {package}.modules.{name}.service import {model}Service

module = ModuleSpec(
    name="{name}",
    router=router,
    policy={profile.policy_expr},
    services=({model}Service,),
)
'''


_TEST_PY = '''\
"""Tests for the ``{name}`` module.

These start at the manifest, because that is what decides who may reach this module at
all — and they are here so the module is not born untested (``modules_ship_tests``).
Extend them: the tests worth having drive the routes against a client, and the example
application's ``tests/conftest.py`` shows the fixtures that takes.
"""

from __future__ import annotations

from {package}.modules.{name}.module import module
from {package}.modules.{name}.service import {model}Service


def test_the_manifest_declares_the_module_and_its_data_layer() -> None:
    assert module.name == "{name}"
    # Declaring `services` is what makes the data layer visible to `terp inspect access`
    # and to Studio; an undeclared one is a warning there and a blank in the diagram.
    assert {model}Service in module.services


def test_writing_requires_more_authority_than_reading() -> None:
    # The profile's whole point, and the one line of the manifest that is worth
    # asserting rather than reading: if a later edit ever levels these two, everyone who
    # can see a record can also change one, and nothing else in the gate would say so.
    policy = module.policy
    assert policy.authenticated
    assert policy.write_requirement.min_rank > policy.read_requirement.min_rank
'''


def _test_py(model: str, name: str, package: str) -> str:
    return _TEST_PY.format(model=model, name=name, package=package)


def _files(name: str, package: str, profile: ModuleProfile) -> dict[str, str]:
    model = _model_name(name)
    return {
        "__init__.py": "",
        "models.py": _models_py(model, name, profile),
        "schemas.py": _schemas_py(model),
        "service.py": _service_py(model, name, package, profile),
        "router.py": _router_py(model, name, package),
        "module.py": _module_py(name, package, profile),
    }


def _test_files(name: str, package: str) -> dict[str, str]:
    """The module's test package, written to ``<project>/tests/<name>/``.

    Not into the module directory: this platform keeps a project's tests in one tree,
    and a test that drives the composed app has to live where the app fixtures are
    (ADR 0119). ``__init__.py`` makes it a package, which is what lets two modules both
    have a ``test_api.py`` without pytest colliding on the basename.
    """
    return {
        "__init__.py": "",
        f"test_{name}_module.py": _test_py(_model_name(name), name, package),
    }


def new_module(
    name: str,
    *,
    root: str | pathlib.Path = ".",
    package: str = "app",
    frontend: bool = True,
    profile: str = DEFAULT_PROFILE,
) -> list[pathlib.Path]:
    """Scaffold the canonical ``<package>/modules/<name>/`` module under *root*.

    When *frontend* is true and a ``frontend/src/modules`` app exists under *root*, the
    matching frontend slot (``module.tsx``, the ``title.ts`` its navigation entry and page
    heading share, a starter ``<Name>List.tsx`` view and that view's first test) is emitted
    too, so the module is full-stack and auto-discovered by
    ``renderTerpApp`` — no central registration. A backend-only repo (no frontend app)
    silently gets just the backend.

    Returns the created file paths. Raises :class:`SystemExit` for an invalid name or
    an existing destination, so a partial overwrite never happens.
    """
    name = _validate_name(name)
    module_profile = get_profile(profile)
    root_path = pathlib.Path(root)
    if not package.isidentifier() or keyword.iskeyword(package):
        raise SystemExit(f"invalid package {package!r}: use a top-level Python import package such as app")
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
    for filename, content in _files(name, package, module_profile).items():
        path = destination / filename
        path.write_text(content, encoding="utf-8")
        created.append(path)

    # A module with no tests used to be the *default* shape, because the scaffold emitted
    # the five production files and nothing else (ADR 0119). Write the test package in the
    # same breath, so the module a generated project starts from is conformant rather than
    # owing a debt nobody mentioned.
    tests_destination = root_path / "tests" / name
    tests_destination.mkdir(parents=True, exist_ok=True)
    for filename, content in _test_files(name, package).items():
        path = tests_destination / filename
        if path.exists():
            continue  # never clobber a test someone already wrote
        path.write_text(content, encoding="utf-8")
        created.append(path)

    if emit_frontend:
        frontend_destination.mkdir(parents=True)
        for filename, content in frontend_files(name, _pascal(name), _model_name(name)).items():
            path = frontend_destination / filename
            path.write_text(content, encoding="utf-8")
            created.append(path)

    return created


def new_module_message(
    name: str,
    paths: Sequence[pathlib.Path],
    *,
    profile: str = DEFAULT_PROFILE,
    root: str | pathlib.Path = ".",
    package: str = "app",
) -> str:
    """The human/agent-facing next-steps note after scaffolding *name*."""
    module_profile = get_profile(profile)
    listing = "\n".join(f"  {path}" for path in paths)
    project = pathlib.Path(root)
    migrate_args = check_args = app_arg = ""
    if package != "app":
        migrate_args = f" --app-root {package} --package {package}"
        check_args = f" --package {package}"
        app_arg = f" --app {package}.main:app"
    if (project / "escape-hatch-budget.json").is_file():
        check_args += " --budget escape-hatch-budget.json"
    steps = [
        f"  {package}/main.py   # mount it: from {package}.modules.{name}.module "
        f"import module as {name}_module; add {name}_module to the modules list",
        f"  uv run terp migrate make {name}{migrate_args}   # generate the first migration",
        f"  uv run terp openapi{app_arg}   # regenerate the contract for /api/v1/{name}/",
    ]
    if (project / "authz-surface.json").is_file():
        steps.append(
            f"  uv run terp inspect access --app {package}.main:app --format surface > authz-surface.json"
            "   # review and commit the changed access surface"
        )
    if any(path.suffix == ".tsx" for path in paths):
        steps.extend(
            [
                f"  frontend/src/modules/{name}/title.ts   # set the source-language title, then translate "
                f"{name}.title in frontend/i18n.json for each non-source locale",
                "  npm --prefix frontend run generate   # regenerate the typed client",
                f"  uv run terp routes   # regenerate src/routes.gen.d.ts for /{name}",
            ]
        )
    steps.append(f"  uv run terp check{check_args}   # run the architecture gate locally")
    notes = "".join(f"\nNote: {note}" for note in module_profile.notes)
    return (
        f"Scaffolded module {name!r} ({len(paths)} files, profile {module_profile.name!r}):\n"
        f"{listing}\n\n"
        f"Next (from {project}):\n" + "\n".join(steps) + notes
    )
