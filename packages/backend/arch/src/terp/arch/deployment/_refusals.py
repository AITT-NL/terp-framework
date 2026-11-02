"""What keeps a declaration from rendering faithfully: the generator's refusals (ADR 0187).

It refuses what it cannot render faithfully and never what it would rather not. Each refusal
is a :class:`~terp.arch.deployment.reader.Finding` naming the field and what is allowed, with
``own`` as the way out; :func:`refusals` gives them in a fixed order.
"""

from __future__ import annotations

import re

from terp.arch.deployment._generator_text import (
    DEFAULT_COMMANDS,
    FRONTEND_LOCK,
    MIGRATION_STEP,
    MOUNT_PATH,
    OWN_REMEDY,
    PROFILE_FILE,
)
from terp.arch.deployment._yaml import _escape
from terp.arch.deployment.reader import Declaration, Finding, Unit
from terp.arch.deployment.tables import Tables

_UNIT_ID = re.compile(r"[a-z0-9][a-z0-9_.-]{0,62}")
_COMPOSE_PROJECT = re.compile(r"[a-z0-9][a-z0-9_-]*")
_REPOSITORY = re.compile(r"[a-z0-9]+(?:(?:[._]|__|-+)[a-z0-9]+)*")


def _finding(message: str, file: str = "deployment.json") -> Finding:
    return Finding(message, OWN_REMEDY, file)


def _project_findings(project: str) -> list[Finding]:
    names = (f"{project}-prod", f"{project}-backend-prod", f"{project}-frontend-prod")
    accepted = (
        _COMPOSE_PROJECT.fullmatch(names[0]) is not None
        and all(_REPOSITORY.fullmatch(name) for name in names[1:])
        and len(names[2]) <= 255
    )
    if accepted:
        return []
    return [
        _finding(
            f'project.name "{_escape(project)}" in pyproject.toml is not a name compose and '
            f"Docker accept for this deployment: compose runs it as the project {names[0]} and "
            f"Docker names the images {names[1]} and {names[2]} (allowed: lower-case letters "
            "and digits, joined by -, _ or __)",
            "pyproject.toml",
        )
    ]


def _compose_findings(declaration: Declaration) -> list[Finding]:
    found: list[Finding] = []
    if declaration.compose_file != PROFILE_FILE:
        found.append(
            _finding(
                f'compose.file is "{declaration.compose_file}": the generator renders one '
                f"profile (allowed: {PROFILE_FILE})"
            )
        )
    if declaration.compose_overrides:
        found.append(
            _finding(
                "compose.overrides names "
                f"{', '.join(declaration.compose_overrides)}: a generated profile is one file, "
                "so nothing could be merged over it (allowed: no override)"
            )
        )
    return found


def _kind_findings(declaration: Declaration, tables: Tables) -> list[Finding]:
    found: list[Finding] = []
    databases = 0
    stores: set[str] = set()
    for index, unit in enumerate(declaration.units):
        where = f"units[{index}]"
        if unit.kind is None:
            if unit.role in ("database", "store"):
                found.append(
                    _finding(
                        f'{where}.kind is missing: a {unit.role} unit is rendered from the '
                        f"datastore table (allowed: {tables.datastores.describe() or 'none'})"
                    )
                )
            continue
        entry = tables.datastores.find(unit.kind, str(unit.version))
        if entry is None:
            found.append(
                _finding(
                    f"{where}.version: the datastore table carries no {unit.kind} "
                    f"{unit.version} (allowed: {tables.datastores.describe() or 'none'})"
                )
            )
            continue
        if tables.recipe(unit.kind) is None:
            known = ", ".join(recipe.kind for recipe in tables.recipes) or "none"
            found.append(
                _finding(
                    f'{where}.kind "{unit.kind}" has no recipe in this framework release, so '
                    f"the generator cannot say where its data lives or how it is healthy "
                    f"(allowed: {known})"
                )
            )
            continue
        if unit.role != entry.role:
            found.append(
                _finding(
                    f'{where}.role is "{unit.role}", and {unit.kind} is a {entry.role} in the '
                    f"datastore table (allowed: {entry.role})"
                )
            )
            continue
        if entry.role == "database":
            databases += 1
            if databases > 1:
                found.append(
                    _finding(
                        f"{where}.role: a second database unit; the backend units reach one "
                        "database through DATABASE_URL (allowed: one database unit)"
                    )
                )
        elif unit.kind in stores:
            found.append(
                _finding(
                    f'{where}.kind: a second "{unit.kind}" store; the backend units reach it '
                    f"through one variable (allowed: one store of each kind)"
                )
            )
        stores.add(unit.kind)
    if declaration.external_database and databases:
        found.append(
            _finding(
                "externalDatabase stands beside a database unit: the generator renders one "
                "database seam (allowed: externalDatabase, or a database unit, not both)"
            )
        )
    return found


def _command_findings(declaration: Declaration) -> list[Finding]:
    found: list[Finding] = []
    steps = 0
    for index, unit in enumerate(declaration.units):
        where = f"units[{index}].command"
        if unit.kind is not None:
            continue
        if unit.role == "one-shot":
            if unit.command is None:
                steps += 1
                if steps > 1:
                    found.append(
                        _finding(
                            f"{where} is missing on a second one-shot unit: the one without a "
                            "command is the migration step, and there is one (allowed: a "
                            "command on every other one-shot unit)"
                        )
                    )
            elif unit.command[:3] == MIGRATION_STEP[:3]:
                found.append(
                    _finding(
                        f"{where} runs {' '.join(unit.command[:3])}: drop `command`, the "
                        "generator owns the migration step (allowed: no command on the "
                        "migration step)"
                    )
                )
        elif unit.role == "web" and unit.command is not None:
            found.append(
                _finding(
                    f"{where}: a web unit runs its image's own server, so it declares no "
                    "command (allowed: no command)"
                )
            )
        elif (
            unit.command is None
            and unit.role not in ("api", "web", *DEFAULT_COMMANDS)
            and unit.role not in ("database", "store")
        ):
            found.append(
                _finding(
                    f'{where} is missing: the generator has no command of its own for role '
                    f'"{unit.role}" (allowed: an argument list)'
                )
            )
    return found


def _web_findings(declaration: Declaration, frontend: bool) -> list[Finding]:
    found: list[Finding] = []
    apis = [unit.id for unit in declaration.units if unit.kind is None and unit.role == "api"]
    webs = 0
    for index, unit in enumerate(declaration.units):
        if unit.kind is not None or unit.role != "web":
            continue
        webs += 1
        where = f"units[{index}]"
        if webs > 1:
            found.append(
                _finding(
                    f"{where}.role: a second web unit; the generator renders one web tier "
                    "(allowed: one web unit)"
                )
            )
            continue
        if not frontend:
            found.append(
                _finding(
                    f'{where}: web unit "{unit.id}" is built from frontend/, and the checkout '
                    f"has no {FRONTEND_LOCK} (allowed: a web unit beside a locked frontend)"
                )
            )
        if _upstream(unit, apis) is None:
            found.append(
                _finding(
                    f"{where}.dependsOn: the web tier proxies /api to one api unit, and "
                    f"{_single_api_question(unit, apis)} (allowed: depend on exactly one api "
                    "unit, or declare only one)"
                )
            )
    return found


def _upstream(web: Unit, apis: list[str]) -> str | None:
    """The one api the web tier proxies to: the one it depends on, or the only one."""
    depended = [ident for ident in (web.depends_on or ()) if ident in apis]
    if len(depended) == 1:
        return depended[0]
    if not depended and len(apis) == 1:
        return apis[0]
    return None


def _single_api_question(web: Unit, apis: list[str]) -> str:
    depended = [ident for ident in (web.depends_on or ()) if ident in apis]
    if depended:
        return f"it depends on {len(depended)} ({', '.join(depended)})"
    return f"the declaration has {len(apis)} ({', '.join(apis) or 'none'})"


def _health_findings(declaration: Declaration) -> list[Finding]:
    return [
        _finding(
            f"units[{index}].{field} is missing: an api unit is probed on its liveness path and "
            "answers readiness on its health path (allowed: a path, such as "
            f"{'/health/ready' if field == 'healthPath' else '/health/live'})"
        )
        for index, unit in enumerate(declaration.units)
        if unit.kind is None and unit.role == "api"
        for field, present in (("healthPath", unit.health_path), ("livenessPath", unit.liveness_path))
        if present is None
    ]


def _order_findings(declaration: Declaration) -> list[Finding]:
    found: list[Finding] = []
    ids = [unit.id for unit in declaration.units]
    graph = {unit.id: tuple(unit.depends_on or ()) for unit in declaration.units}
    for index, unit in enumerate(declaration.units):
        for position, ident in enumerate(unit.depends_on or ()):
            if ident not in graph:
                found.append(
                    _finding(
                        f'units[{index}].dependsOn[{position}] "{ident}" is no declared unit, '
                        f"and a generated profile runs only declared units (allowed: "
                        f"{', '.join(ids)})"
                    )
                )
    for index, unit in enumerate(declaration.units):
        cycle = _cycle_from(unit.id, graph)
        if cycle:
            found.append(
                _finding(
                    f"units[{index}].dependsOn closes a cycle, {' -> '.join(cycle)}, which no "
                    "start order can satisfy (allowed: a start order without a cycle)"
                )
            )
            break
    return found


def _cycle_from(start: str, graph: dict[str, tuple[str, ...]]) -> list[str]:
    """A path from *start* back to itself through the start order, or ``[]``."""
    stack: list[tuple[str, list[str]]] = [(start, [start])]
    seen: set[str] = set()
    while stack:
        node, path = stack.pop()
        for following in graph.get(node, ()):
            if following == start:
                return [*path, start]
            if following not in seen:
                seen.add(following)
                stack.append((following, [*path, following]))
    return []


def _unit_id_findings(declaration: Declaration) -> list[Finding]:
    return [
        _finding(
            f'units[{index}].id "{unit.id}" is not a lower-case compose service name, which a '
            "generated profile and its .app.<id>.env need (allowed: lower-case letters, "
            "digits, _ . and -, beginning with a letter or a digit)"
        )
        for index, unit in enumerate(declaration.units)
        if _UNIT_ID.fullmatch(unit.id) is None
    ]


def _backend_ids(declaration: Declaration) -> list[str]:
    return [
        unit.id
        for unit in declaration.units
        if unit.kind is None and unit.role not in ("web", "database", "store")
    ]


def _volume_findings(declaration: Declaration) -> list[Finding]:
    found: list[Finding] = []
    backend = _backend_ids(declaration)
    data = {f"{unit.id}-data" for unit in declaration.units if unit.kind is not None}
    # Which volume already holds each (unit, path). Compose does not refuse a second volume
    # at a mount point a service already has: it keeps the last and drops the others
    # without a word (2.40, measured), so that render would start with the unit's files in
    # a volume the declaration did not put there.
    holder: dict[tuple[str, str], tuple[int, str]] = {}
    for index, volume in enumerate(declaration.volumes):
        where = f"volumes[{index}]"
        if volume.id in data:
            found.append(
                _finding(
                    f'{where}.id "{volume.id}" is the data volume the generator renders for a '
                    "kind unit (allowed: a name no <id>-data of a kind unit takes)"
                )
            )
        if volume.mount is None:
            found.append(
                _finding(
                    f"{where}.mount is missing: the generator renders where each volume is "
                    f'mounted (allowed: {{"path": "{MOUNT_PATH}", "units": [...]}})'
                )
            )
            continue
        if volume.mount.path != MOUNT_PATH:
            found.append(
                _finding(
                    f'{where}.mount.path is "{volume.mount.path}": this version renders the one '
                    f"mount point the backend image makes (allowed: {MOUNT_PATH})"
                )
            )
        for position, ident in enumerate(volume.mount.units):
            if ident not in backend:
                found.append(
                    _finding(
                        f'{where}.mount.units[{position}] "{ident}" is no unit on the backend '
                        f"image, where {MOUNT_PATH} is a mount point (allowed: "
                        f"{', '.join(backend) or 'none'})"
                    )
                )
                continue
            first = holder.setdefault((ident, volume.mount.path), (index, volume.id))
            if first != (index, volume.id):
                found.append(
                    _finding(
                        f'{where}.mount.units[{position}] "{ident}" already mounts '
                        f'volumes[{first[0]}] "{first[1]}" at {volume.mount.path}, and Compose '
                        "keeps only the last volume at one mount point and drops the others "
                        "without a word (allowed: one volume per unit at each mount path)"
                    )
                )
    return found


def _package_findings(declaration: Declaration, tables: Tables) -> list[Finding]:
    offered = tables.system_packages.packages
    return [
        _finding(
            f'generator.systemPackages[{index}] "{name}" is not in the system-package table '
            f"(allowed: a package of the table: {', '.join(offered) or 'none in this release'})"
        )
        for index, name in enumerate(declaration.system_packages)
        if name not in offered
    ]


def refusals(
    declaration: Declaration, project: str, *, tables: Tables, frontend_lock: bool
) -> list[Finding]:
    """Everything that keeps *declaration* from rendering faithfully, in a fixed order."""
    return [
        *_project_findings(project),
        *_compose_findings(declaration),
        *_unit_id_findings(declaration),
        *_kind_findings(declaration, tables),
        *_command_findings(declaration),
        *_web_findings(declaration, frontend_lock),
        *_health_findings(declaration),
        *_order_findings(declaration),
        *_volume_findings(declaration),
        *_package_findings(declaration, tables),
    ]
