"""The production profile a declaration renders to (ADR 0187 decision 5).

A plan is worked out once from a declaration that no refusal stops, then written in a fixed
key order, units and volumes in declaration order.
"""

from __future__ import annotations

from dataclasses import dataclass

from terp.arch.deployment._generator_text import (
    _LOGGING,
    _PROFILE_INTRO,
    _TIMING,
    APP_ROOT,
    BACKEND_DOCKERFILE,
    CORS_ORIGINS,
    DEFAULT_COMMANDS,
    EXTERNAL_DATABASE_URL,
    FRONTEND_DOCKERFILE,
    HEADER,
    HEALTH_PROBE,
    KEY_SEAM,
    MIGRATION_STEP,
    MOUNT_PATH,
    NO_DATABASE_URL,
    WEB_PORT,
)
from terp.arch.deployment._refusals import _backend_ids, _upstream
from terp.arch.deployment._yaml import _flow, fixed, scalar, value
from terp.arch.deployment.reader import Declaration, Unit
from terp.arch.deployment.tables import KindRecipe, Tables


@dataclass(frozen=True)
class _Plan:
    """What the declaration renders to, worked out once before anything is written."""

    declaration: Declaration
    project: str
    tables: Tables
    kinds: dict[str, KindRecipe]
    backend: tuple[str, ...]
    builder: str | None
    upstream: str | None
    migration_step: str | None
    database: Unit | None
    frontend: bool

    def unit(self, ident: str) -> Unit:
        return next(unit for unit in self.declaration.units if unit.id == ident)

    def kind_of(self, ident: str) -> str:
        """kind | api | web | one-shot | worker | scheduler | other."""
        unit = self.unit(ident)
        if unit.kind is not None:
            return "kind"
        if unit.role in ("api", "web", "one-shot", "worker", "scheduler"):
            return unit.role
        return "other"


def _plan(declaration: Declaration, project: str, tables: Tables, frontend: bool) -> _Plan:
    kinds = {
        unit.id: recipe
        for unit in declaration.units
        if unit.kind is not None and (recipe := tables.recipe(unit.kind)) is not None
    }
    backend = tuple(_backend_ids(declaration))
    apis = [ident for ident in backend if _role(declaration, ident) == "api"]
    builder = apis[0] if apis else (backend[0] if backend else None)
    web = next((unit for unit in declaration.units if unit.kind is None and unit.role == "web"), None)
    database = next(
        (unit for unit in declaration.units if unit.kind is not None and unit.role == "database"),
        None,
    )
    steps = [
        unit.id
        for unit in declaration.units
        if unit.kind is None and unit.role == "one-shot" and unit.command is None
    ]
    return _Plan(
        declaration=declaration,
        project=project,
        tables=tables,
        kinds=kinds,
        backend=backend,
        builder=builder,
        upstream=_upstream(web, apis) if web is not None else None,
        migration_step=steps[0] if steps else None,
        database=database,
        frontend=frontend,
    )


def _role(declaration: Declaration, ident: str) -> str:
    return next(unit.role for unit in declaration.units if unit.id == ident)


def _env_files(ident: str, indent: str) -> list[str]:
    return [
        f"{indent}env_file:",
        f"{indent}  - path: .app.env",
        f"{indent}    required: false",
        f"{indent}  - path: {scalar(f'.app.{ident}.env', leading_id=False)}",
        f"{indent}    required: false",
    ]


def _backend_block(plan: _Plan) -> list[str]:
    lines = [
        "x-backend: &backend",
        f"  image: {scalar(f'{plan.project}-backend-prod', leading_id=False)}",
        "  # App-declared environment variables (environment.schema.json): the deploy",
        "  # pipeline renders exactly the declared keys into .app.env per environment.",
        "  # Optional by design -- plain `docker compose up` works without the file. Each",
        "  # backend unit lists it again, then its own .app.<id>.env.",
        "  # No healthcheck, here or in the image: only an api unit serves HTTP, and each one",
        "  # carries its own probe. A unit with none is ready once it runs, which is what",
        "  # `docker compose up --wait` waits for; a disabled check would make it refuse.",
        "  env_file:",
        "    - path: .app.env",
        "      required: false",
        "  environment: &backend-env",
    ]
    if plan.database is not None:
        lines.extend(_seam(plan.database, plan.kinds[plan.database.id]))
    elif plan.declaration.external_database:
        lines += [
            "    # Required: the database this deployment does not run (externalDatabase).",
            f"    DATABASE_URL: {EXTERNAL_DATABASE_URL}",
        ]
    else:
        lines += [
            "    # Required: no unit of this deployment runs the database.",
            f"    DATABASE_URL: {NO_DATABASE_URL}",
        ]
    lines += [
        f"    SECRET_KEY: {KEY_SEAM}",
        "    ENVIRONMENT: production",
        f"    BACKEND_CORS_ORIGINS: '{CORS_ORIGINS}'",
    ]
    for unit in plan.declaration.units:
        if unit.kind is not None and unit.role == "store" and unit.id in plan.kinds:
            lines.extend(_seam(unit, plan.kinds[unit.id]))
    return lines


def _seam(unit: Unit, recipe: KindRecipe) -> list[str]:
    url = recipe.url.replace("{host}", unit.id)
    return [
        f"    # Unset: the bundled `{unit.id}` service. Set: any external {recipe.title} -- the "
        "seam an",
        f"    # external-{unit.role} deployment overrides (nothing else in the profile changes).",
        f"    {recipe.variable}: ${{{recipe.variable}:-{url}}}",
    ]


def _depends_on(plan: _Plan, unit: Unit) -> list[str]:
    if not unit.depends_on:
        return []
    conditions = {
        "kind": "service_healthy",
        "api": "service_healthy",
        "web": "service_healthy",
        "one-shot": "service_completed_successfully",
    }
    lines = ["    depends_on:"]
    for ident in unit.depends_on:
        condition = conditions.get(plan.kind_of(ident), "service_started")
        lines += [f"      {scalar(ident)}:", f"        condition: {condition}"]
    return lines


def _probe(test: tuple[str, ...]) -> list[str]:
    return ["    healthcheck:", f"      test: {test}", *(f"      {line}" for line in _TIMING)]


def _kind_service(plan: _Plan, unit: Unit) -> list[str]:
    recipe = plan.kinds[unit.id]
    entry = plan.tables.datastores.find(str(unit.kind), str(unit.version))
    assert entry is not None  # refused before planning
    lines = [
        f"  {scalar(unit.id)}:",
        f"    # {recipe.title} {unit.version}, pinned by digest to the datastore table this",
        "    # framework release publishes (terp-arch's datastore-table.json, ADR 0184): a tag",
        "    # can move under a deployed app, and a declared `kind` unit must run exactly this.",
        f"    image: {entry.image}",
    ]
    if unit.command is not None:
        lines.append(f"    command: {_flow(unit.command)}")
    lines.append("    restart: unless-stopped")
    if recipe.environment:
        lines.append("    environment:")
        lines += [f"      {name}: {text}" for name, text in recipe.environment]
    lines += ["    volumes:", f"      - {scalar(f'{unit.id}-data:{recipe.data_path}')}"]
    lines += _depends_on(plan, unit)
    lines += _probe(_flow(recipe.healthcheck, fixed))
    return lines


def _backend_service(plan: _Plan, unit: Unit) -> list[str]:
    kind = plan.kind_of(unit.id)
    lines: list[str] = []
    command = unit.command
    if unit.id == plan.migration_step:
        command = MIGRATION_STEP
        lines += [
            "  # The migration step: brings every package's schema to head before the units that",
            "  # wait for it start. The boot guard of every unit that builds the app",
            "  # (PendingMigrationsError) backs it up at runtime.",
        ]
    elif command is None and kind in DEFAULT_COMMANDS:
        command = DEFAULT_COMMANDS[kind]
        lines.append(
            "  # Drains the durable outbox until it is stopped (`terp jobs worker --forever`)."
            if kind == "worker"
            else "  # Fires the declared schedules until it is stopped (`terp jobs scheduler`)."
        )
    lines += [f"  {scalar(unit.id)}:", "    <<: *backend"]
    if unit.id == plan.builder:
        lines += [
            "    # The one service that declares the backend build: one builder produces the",
            "    # shared tag (concurrent builds of one tag race in the exporter), and every",
            "    # other backend unit runs it.",
            "    build:",
            "      context: .",
            f"      dockerfile: {BACKEND_DOCKERFILE}",
        ]
    if command is not None:
        lines.append(f"    command: {_flow(command)}")
    lines += _env_files(unit.id, "    ")
    if kind not in ("api", "one-shot"):
        lines.append("    init: true")
    lines.append('    restart: "no"' if kind == "one-shot" else "    restart: unless-stopped")
    mounts = [
        volume.id
        for volume in plan.declaration.volumes
        if volume.mount is not None and unit.id in volume.mount.units
    ]
    if mounts:
        lines += [
            "    # The files capability's storage root. The backend image makes it, owned by the",
            "    # user the image runs as, and Docker gives an empty named volume the owner of",
            "    # the directory it is mounted over, so that user can write the volume.",
            "    volumes:",
        ]
        lines += [
            f"      - {value(f'{volume}:{APP_ROOT}/{MOUNT_PATH}')}" for volume in mounts
        ]
    lines += _depends_on(plan, unit)
    if kind == "api":
        probe = ("CMD", "python", "-c", HEALTH_PROBE)
        lines += _probe(
            "[" + ", ".join(fixed(part) for part in probe) + f", {value(str(unit.liveness_path))}]"
        )
    return lines


def _web_service(plan: _Plan, unit: Unit) -> list[str]:
    lines = [
        f"  {scalar(unit.id)}:",
        "    build:",
        "      context: .",
        f"      dockerfile: {FRONTEND_DOCKERFILE}",
        f"    image: {scalar(f'{plan.project}-frontend-prod', leading_id=False)}",
        "    restart: unless-stopped",
    ]
    if plan.upstream != "api":
        lines += [
            "    environment:",
            "      # The api unit this tier proxies /api to; the image's default is api:8000.",
            f"      API_UPSTREAM: {scalar(f'{plan.upstream}:8000')}",
        ]
    lines += [
        "    ports:",
        "      # 23100, not 8080: the same argument as the development file, one range up.",
        "      # A deployment sets WEB_PORT explicitly -- this default only decides what a",
        "      # first `docker compose -f docker-compose.prod.yml up` grabs on a machine",
        "      # that is also running the developer's own things.",
        f"      - {fixed(WEB_PORT)}",
    ]
    lines += _depends_on(plan, unit)
    lines += _probe(_flow(("CMD-SHELL", "wget -q -O /dev/null http://127.0.0.1:8080/"), fixed))
    return lines


def _profile(plan: _Plan) -> str:
    lines = [
        *HEADER.splitlines(),
        *_PROFILE_INTRO.splitlines(),
        f"name: {scalar(f'{plan.project}-prod', leading_id=False)}",
        "",
    ]
    if plan.backend:
        lines += [*_backend_block(plan), ""]
    lines += [*_LOGGING.splitlines(), "", "services:"]
    for index, unit in enumerate(plan.declaration.units):
        if index:
            lines.append("")
        kind = plan.kind_of(unit.id)
        if kind == "kind":
            lines += _kind_service(plan, unit)
        elif kind == "web":
            lines += _web_service(plan, unit)
        else:
            lines += _backend_service(plan, unit)
        lines.append("    logging: *container-logging")
    volumes = [f"{unit.id}-data" for unit in plan.declaration.units if unit.kind is not None]
    volumes += [volume.id for volume in plan.declaration.volumes]
    if volumes:
        lines += ["", "volumes:", *(f"  {scalar(name)}:" for name in volumes)]
    return "\n".join(lines) + "\n"
