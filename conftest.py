"""Repo-root pytest configuration for every suite (``tests`` + ``apps/example``).

Process-global runtime isolation used to live here, as a hand-maintained autouse
fixture naming each seam. It now ships **with the platform** — ``terp-core``
registers :mod:`terp.core.testing` under pytest's ``pytest11`` entry point — so this
repo receives it the same way every app on Terp does. The framework no longer holds
a protection its users had to rediscover.

Deleting the fixture from here is the point, not an accident: if the shipped plugin
ever regressed, these suites would go order-dependent exactly like an app's would.

The one difference from an app: an app pip-installs ``terp-core``, so pytest discovers
the plugin through its ``pytest11`` entry point with nothing to declare. This repo is
run both ways — installed (CI) and straight from source on ``pythonpath`` (a local venv
where entry points are never read) — so the plugin is named explicitly *only* when the
entry point is not there. Declaring it unconditionally makes pytest register one module
under two names and refuse to start.
"""

from __future__ import annotations

from importlib.metadata import entry_points

_PLUGIN = "terp.core.testing"
_VIA_ENTRY_POINT = any(ep.value == _PLUGIN for ep in entry_points(group="pytest11"))

pytest_plugins = () if _VIA_ENTRY_POINT else (_PLUGIN,)
