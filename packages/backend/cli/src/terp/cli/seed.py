"""``terp seed`` — run the app's declared seed routine (idempotent demo / bootstrap data).

Populates a fresh database so the app is immediately usable — the missing half of
``terp migrate upgrade`` for a dev / demo environment. The seed itself lives in the app
(default ``app.seed:seed``), a callable taking a :class:`~sqlmodel.Session`, so each app
decides what "seeded" means. The example's seed provisions users and a little content
through the real audited services, so seeding dogfoods audit, events, actor-stamping,
ownership, and tenancy.

Fail-closed: it refuses to run when ``ENVIRONMENT=production`` — seed data must never touch
a production store; a real deployment bootstraps its first admin with ``terp user create``.
"""

from __future__ import annotations

import contextlib
import importlib
import pathlib
from collections.abc import Callable

from sqlmodel import Session

from terp.cli._appref import load_app, push_app_root
from terp.core import settings
from terp.core.db import get_session

SeedFn = Callable[[Session], "str | None"]


def load_seed(dotted: str) -> SeedFn:
    """Resolve a ``module:attribute`` reference to a ``seed(session)`` callable."""
    module_name, _, attr = dotted.partition(":")
    if not module_name:
        raise SystemExit(f"{dotted!r} is not a valid 'module:attribute' reference")
    module = importlib.import_module(module_name)
    candidate = getattr(module, attr or "seed", None)
    if not callable(candidate):
        raise SystemExit(f"{dotted!r} did not resolve to a callable seed(session)")
    return candidate


def run_seed_command(
    *,
    app_ref: str = "app.main:app",
    app_root: str | pathlib.Path = ".",
    seed_ref: str = "app.seed:seed",
    production: bool | None = None,
) -> str:
    """Build *app_ref*, resolve *seed_ref*, and run it in one write-guarded session.

    *production* defaults to the app's environment; when true the command fails closed with a
    clean CLI error (seed data is dev / demo only). Injecting it keeps the guard unit-testable.
    """
    if production is None:
        production = settings.is_production
    if production:
        raise SystemExit(
            "terp seed refuses to run when ENVIRONMENT=production; seed data is dev/demo only "
            "(bootstrap a real first admin with `terp user create`)"
        )
    push_app_root(app_root)
    load_app(app_ref)
    seed = load_seed(seed_ref)
    with contextlib.closing(get_session()) as gen:
        session = next(gen)
        summary = seed(session)
    return summary or "seeded"
