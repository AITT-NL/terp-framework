"""Terp Reference composition root — wire the platform once.

``create_app`` mounts the app's modules behind the deny-by-default guard;
installed capabilities are discovered by entry point. App modules are mounted
**explicitly**: after ``uv run terp new module <name>``, import its
``module`` here and add it to the ``modules`` list below — a module that is
not listed serves no routes (the gate's mounted-modules test fails until it
is listed).

Beyond the template, this root declares the two things the reference app's background
work needs, and every process runs it — the API, ``terp jobs worker`` and ``terp jobs
scheduler`` all build the app through :func:`build`, so each one has the same relay and
the same durable queue:

* the **mail relay**, from the fixed ``MAIL_FROM`` / ``SMTP_*`` variables (``terp guide
  mail``). With none set, development logs each message instead of sending it and a
  production boot is refused;
* the **durable job queue**: ``OutboxJobQueue`` records every enqueued job in the same
  transaction as the write that caused it, and production refuses the in-process default;
* the **durable schedule ledger**: ``DatabaseScheduleLedger`` records each slot the
  scheduler settles in the same transaction as the job it enqueued, so a scheduler a
  deploy restarted applies the schedule's misfire policy to the hour it missed (ADR 0191),
  and production refuses the per-process default.
"""

from __future__ import annotations

import functools
import os
import pathlib

from terp.capabilities.audit import persist_audit
from terp.capabilities.mail import configure_mail, mail_settings_from_environment
from terp.capabilities.outbox import DatabaseScheduleLedger, OutboxJobQueue
from terp.core import create_app, get_settings
from terp.migrations import assert_migrations_current

from app.auth import login_module, me_module, principal_provider
from app.modules.notices.module import module as notices_module
from control_plane import control_plane


def build():
    configure_mail(mail_settings_from_environment(os.environ))
    modules = [login_module, me_module, notices_module]
    migrations_current = functools.partial(
        assert_migrations_current,
        app_root=pathlib.Path(__file__).resolve().parent,
        package="app",
    )
    return create_app(
        modules,
        title="Terp Reference",
        principal_provider=principal_provider,
        discover_capabilities=True,
        control_plane=control_plane,
        audit_sink=persist_audit,
        require_token_revocation=True,
        job_queue=OutboxJobQueue(),
        require_durable_jobs=get_settings().is_production,
        schedule_ledger=DatabaseScheduleLedger(),
        require_durable_schedules=get_settings().is_production,
        # In production the app refuses to serve against a database that is behind
        # the code, missing a module's history, or holding a revision this code does
        # not define outside its schema window - a wrong schema fails loudly at boot
        # instead of at the first request. A database one expand-only migration run
        # ahead is the window: the previous release starts again on it (ADR 0185).
        migration_check=migrations_current if get_settings().is_production else None,
        # Everywhere else the app starts, and readiness answers 503 (`migrations`)
        # until the schema has caught up: the dev stack applies migrations when it
        # comes up, not when a running stack's code gains one (ADR 0221).
        migration_readiness=migrations_current,
    )


app = build()
