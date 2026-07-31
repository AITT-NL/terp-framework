"""Repo-root pytest configuration for every suite (``tests`` + ``apps/example``).

Process-global runtime isolation used to live here, as a hand-maintained autouse
fixture naming each seam. It now ships **with the platform** — ``terp-core``
registers :mod:`terp.core.testing` under pytest's ``pytest11`` entry point — so this
repo receives it the same way every app on Terp does. The framework no longer holds
a protection its users had to rediscover.

Deleting the fixture from here is the point, not an accident: if the shipped plugin
ever regressed, these suites would go order-dependent exactly like an app's would.

The one difference from an app: an app pip-installs ``terp-core``, so pytest discovers
the plugin through its ``pytest11`` entry point with nothing to declare. This repo runs
from source on ``pythonpath``, where entry points are never read — hence the explicit
``pytest_plugins`` below. It loads the same module an app loads.
"""

from __future__ import annotations

pytest_plugins = ("terp.core.testing",)
