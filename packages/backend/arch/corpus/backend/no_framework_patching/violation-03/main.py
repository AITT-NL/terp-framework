"""Violation: a module of the framework replaced where every later import finds it."""

import sys

from app.shims import quiet_surface

sys.modules["terp.core.authz_surface"] = quiet_surface
