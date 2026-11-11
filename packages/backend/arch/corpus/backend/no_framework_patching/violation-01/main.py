"""Violation: the comparison an app makes when it starts, replaced by one that always passes."""

import terp.core.authz_surface as surface
from terp.core import create_app

from app.auth import login_module, me_module


def _always_starts(*args, **kwargs):
    return None


surface.startup_refusal = _always_starts


def build():
    return create_app([login_module, me_module], title="demo")
