"""Import-boundary rules: modules use only the public surface, never each other.

Pairs with the layering keystone — ``terp.core`` exposes a public surface and
forbids ``_internal`` imports, and leaf modules stay independent.
"""

from __future__ import annotations

import ast
import pathlib

from terp.arch._ast import _SECURITY_SKIP_DIRS, iter_imports, iter_python_files, parse
from terp.arch.rules._support import (
    ArchViolation,
    _module_parts,
    _module_under,
    _rel,
    _resolve_relative_import,
)


def check_no_internal_imports(
    app_root: str | pathlib.Path, *, package: str = "app"
) -> list[ArchViolation]:
    """Modules may import only the public ``terp.core`` surface, never ``_internal``."""
    root = pathlib.Path(app_root)
    violations: list[ArchViolation] = []
    for path in iter_python_files(root):
        tree = parse(path)
        rel = _rel(path, root)
        for module, line in iter_imports(tree):
            if module == "terp.core._internal" or module.startswith("terp.core._internal."):
                violations.append(
                    ArchViolation(
                        "no_internal_imports",
                        rel,
                        line,
                        f"imports {module!r}; use the public terp.core surface instead",
                    )
                )
    return violations


# The ORM ``Session`` ships in both SQLAlchemy and SQLModel; Terp standardises on
# the SQLModel one (it is what ``SessionDep`` hands out, what ``BaseService`` and the
# write guard wrap, and what migrations import). Importing the bare SQLAlchemy
# ``Session`` is the subtle drift that splits the codebase across two session types.
def _is_sqlalchemy_module(module: str) -> bool:
    """True for ``sqlalchemy`` and any submodule (``sqlalchemy.orm``, ``.orm.session``)."""
    return module == "sqlalchemy" or module.startswith("sqlalchemy.")


def check_session_imported_from_sqlmodel(
    app_root: str | pathlib.Path, *, package: str = "app"
) -> list[ArchViolation]:
    """The ORM ``Session`` is imported from ``sqlmodel``, never from ``sqlalchemy``.

    SQLModel re-exports SQLAlchemy's ``Session``, and the framework standardises on
    that one everywhere — ``SessionDep``, ``BaseService``, the write guard, and the
    migrations all speak ``sqlmodel.Session``. Importing ``Session`` from
    ``sqlalchemy`` / ``sqlalchemy.orm`` quietly forks the app onto a second session
    type, so the rule names the one canonical import. (Constructing a session is
    separately banned by ``no_raw_session_construction`` — this only fixes the spelling.)
    """
    root = pathlib.Path(app_root)
    violations: list[ArchViolation] = []
    for path in iter_python_files(root):
        tree = parse(path)
        rel = _rel(path, root)
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.ImportFrom)
                and node.level == 0
                and node.module is not None
                and _is_sqlalchemy_module(node.module)
                and any(alias.name == "Session" for alias in node.names)
            ):
                violations.append(
                    ArchViolation(
                        "session_imported_from_sqlmodel",
                        rel,
                        node.lineno,
                        f"imports Session from {node.module!r}; import it from sqlmodel so "
                        "the app uses the one canonical session type (SessionDep / BaseService)",
                    )
                )
    return violations


def _imported_modules(
    tree: ast.Module, importing_parts: list[str]
) -> list[tuple[str, int]]:
    """Every imported absolute module in *tree*, with **relative** imports resolved.

    ``import a.b`` yields ``a.b``; ``from a.b import c`` yields ``a.b``; and a
    relative ``from ..sibling import x`` is resolved against *importing_parts* to
    its absolute module — so relative imports can no longer evade the boundary
    rules the way a bare ``iter_imports`` (absolute-only) would let them.
    """
    imported: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported.append((alias.name, node.lineno))
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:
                if node.module:
                    imported.append((node.module, node.lineno))
                    for alias in node.names:
                        imported.append((f"{node.module}.{alias.name}", node.lineno))
            else:
                resolved = _resolve_relative_import(importing_parts, node.level, node.module)
                imported.append((resolved, node.lineno))
                for alias in node.names:
                    imported.append((f"{resolved}.{alias.name}", node.lineno))
    return imported


def check_no_cross_module_imports(
    app_root: str | pathlib.Path, *, package: str = "app"
) -> list[ArchViolation]:
    """A module never imports a sibling module (leaf domains stay independent).

    Both absolute (``from app.modules.tasks...``) and relative
    (``from ..tasks...``) sibling imports are caught — a relative import is
    resolved to its absolute module first, so renaming the import style does not
    re-couple two leaf modules.
    """
    root = pathlib.Path(app_root)
    prefix = f"{package}.modules."
    violations: list[ArchViolation] = []
    for path in iter_python_files(root):
        own = _module_under(path, package)
        if own is None:
            continue
        tree = parse(path)
        rel = _rel(path, root)
        importing_parts = _module_parts(path, root)
        for module, line in _imported_modules(tree, importing_parts):
            if module.startswith(prefix):
                target = module[len(prefix):].split(".")[0]
                if target != own:
                    violations.append(
                        ArchViolation(
                            "no_cross_module_imports",
                            rel,
                            line,
                            f"module {own!r} imports sibling module {target!r}; "
                            "modules must not import each other",
                        )
                    )
    return violations


# Background-execution engines / brokers / schedulers an app module must not reach for
# directly: a queue / broker / cron-runner belongs **behind the jobs seam**
# (``terp.core.jobs``) inside an opt-in adapter capability, never inline in domain code —
# so an engine choice (Celery / Azure Service Bus / Redis / APScheduler) stays a
# composition-root decision and background work flows through the audited, context-binding
# kernel runner. There is no legitimate non-background use of these in app code, so any
# import is flagged (a justified adapter reaches them under a budgeted ``# arch-allow-*``).
_BACKGROUND_ENGINE_MODULES = frozenset({"celery", "redis", "apscheduler"})
# Dotted broker module(s) banned by exact prefix — ``azure`` ships many unrelated SDKs,
# so only the Service Bus broker is the background runtime, not all of ``azure``.
_BACKGROUND_ENGINE_DOTTED = ("azure.servicebus",)

_RAW_OUTBOUND_HTTP_ROOTS = frozenset({"httpx", "requests", "urllib3", "aiohttp", "socket"})
_RAW_OUTBOUND_HTTP_DOTTED = ("urllib.request", "http.client")


def _is_raw_outbound_http_module(module: str) -> bool:
    """True for HTTP client libraries that must live behind an SSRF-safe capability."""
    if module in _RAW_OUTBOUND_HTTP_ROOTS:
        return True
    if any(module == dotted or module.startswith(f"{dotted}.") for dotted in _RAW_OUTBOUND_HTTP_DOTTED):
        return True
    return any(module.startswith(f"{root}.") for root in _RAW_OUTBOUND_HTTP_ROOTS)


# The stdlib concurrency modules are background *execution* when used to spawn a
# thread / process, but also ship pure **synchronization primitives** that are a
# correctness tool (a lock guarding an invariant), not background work. So an explicit
# ``from threading import RLock`` is allowed, while a bare ``import threading`` (which can
# then reach ``Thread``) or importing an execution name (``Thread`` / ``Process`` / a
# pool) is flagged — ad-hoc background work must go through the jobs seam.
_CONCURRENCY_MODULES = frozenset({"threading", "multiprocessing"})
_SYNC_PRIMITIVES = frozenset(
    {"Lock", "RLock", "Event", "Condition", "Semaphore", "BoundedSemaphore", "Barrier", "local"}
)


def _is_background_engine_module(module: str) -> bool:
    """True for a banned broker / scheduler engine module (or a submodule of one)."""
    if module in _BACKGROUND_ENGINE_MODULES:
        return True
    if any(module == dotted or module.startswith(f"{dotted}.") for dotted in _BACKGROUND_ENGINE_DOTTED):
        return True
    return any(module.startswith(f"{engine}.") for engine in _BACKGROUND_ENGINE_MODULES)


def check_no_raw_outbound_http(
    app_root: str | pathlib.Path, *, package: str = "app"
) -> list[ArchViolation]:
    """App modules do not import raw HTTP clients; outbound calls use a capability.

    Direct ``httpx`` / ``requests`` / ``urllib.request`` / ``urllib3`` / ``aiohttp``
    imports — and the lower-level ``socket`` / ``http.client`` escape routes to the
    same network — make SSRF protection, allowlists, egress auditing, and timeout
    policy a per-call-site choice. Outbound traffic belongs behind a declared
    capability that centralizes those controls. As a security rule this also scans
    ``tests/`` and ``migrations/`` dirs inside a module — they are importable
    Python, so they are application surface too.
    """
    root = pathlib.Path(app_root)
    violations: list[ArchViolation] = []
    for path in iter_python_files(root, skip_dirs=_SECURITY_SKIP_DIRS):
        if _module_under(path, package) is None:
            continue
        tree = parse(path)
        rel = _rel(path, root)
        importing_parts = _module_parts(path, root)
        reported_lines: set[int] = set()
        for module, line in _imported_modules(tree, importing_parts):
            if line not in reported_lines and _is_raw_outbound_http_module(module):
                reported_lines.add(line)
                violations.append(
                    ArchViolation(
                        "no_raw_outbound_http",
                        rel,
                        line,
                        f"imports {module!r}; outbound HTTP must go through a declared "
                        "capability with SSRF protection",
                    )
                )
    return violations



def check_no_adhoc_background_runtime(
    app_root: str | pathlib.Path, *, package: str = "app"
) -> list[ArchViolation]:
    """App modules don't import a background engine / runtime directly — only adapter caps do.

    Background work (a scheduled sync, an export, a webhook) goes through the typed
    :func:`terp.core.enqueue` chokepoint and the context-binding kernel runner, so the
    engine that actually runs it — Celery, Azure Service Bus, Redis, APScheduler — stays a
    composition-root choice wired into an **opt-in adapter capability**, never an import
    baked into domain code. This rule forbids importing those broker / scheduler engines
    (and a raw ``threading`` / ``multiprocessing`` *execution* construct — ``Thread`` /
    ``Process`` / a pool, or a bare ``import threading`` that can reach one) anywhere in an
    app module; an explicit synchronization primitive (``from threading import RLock``) is a
    correctness tool, not background execution, and stays allowed. Its runtime half is the
    jobs seam itself: every job runs through :func:`terp.core.enqueue` and the active
    :class:`~terp.core.JobQueue`, so an adapter swap never touches a call site. An adapter
    capability legitimately imports its engine under a budgeted ``# arch-allow-*`` marker.
    """
    root = pathlib.Path(app_root)
    violations: list[ArchViolation] = []
    for path in iter_python_files(root):
        tree = parse(path)
        rel = _rel(path, root)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    name = alias.name
                    if _is_background_engine_module(name):
                        violations.append(
                            ArchViolation(
                                "no_adhoc_background_runtime",
                                rel,
                                node.lineno,
                                f"imports {name!r}; a background/broker engine belongs behind "
                                "the terp.core jobs seam in an opt-in adapter capability, not "
                                "in app code",
                            )
                        )
                    elif name.split(".")[0] in _CONCURRENCY_MODULES:
                        violations.append(
                            ArchViolation(
                                "no_adhoc_background_runtime",
                                rel,
                                node.lineno,
                                f"imports {name!r}; run background work through the terp.core "
                                "jobs seam (enqueue), not an ad-hoc thread/process — import a "
                                "sync primitive by name (from threading import RLock) if you "
                                "only need a lock",
                            )
                        )
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                module = node.module
                if _is_background_engine_module(module):
                    violations.append(
                        ArchViolation(
                            "no_adhoc_background_runtime",
                            rel,
                            node.lineno,
                            f"imports from {module!r}; a background/broker engine belongs behind "
                            "the terp.core jobs seam in an opt-in adapter capability, not in app "
                            "code",
                        )
                    )
                elif module.split(".")[0] in _CONCURRENCY_MODULES:
                    # Allowed only when the import is exactly threading / multiprocessing AND
                    # every name pulled in is a synchronization primitive — anything else can
                    # spawn background execution, which must go through the jobs seam.
                    if module in _CONCURRENCY_MODULES and all(
                        alias.name in _SYNC_PRIMITIVES for alias in node.names
                    ):
                        continue
                    violations.append(
                        ArchViolation(
                            "no_adhoc_background_runtime",
                            rel,
                            node.lineno,
                            f"imports from {module!r}; run background work through the terp.core "
                            "jobs seam (enqueue), not an ad-hoc thread/process — only a sync "
                            "primitive (Lock/RLock/Event/…) may be imported from a concurrency "
                            "module",
                        )
                    )
    return violations
