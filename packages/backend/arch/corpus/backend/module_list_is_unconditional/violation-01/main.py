"""Violation: a module appended only where a setting is present."""

import os

from terp.core import create_app

from app.auth import login_module, me_module, oidc_module


def build():
    modules = [login_module, me_module]
    if os.environ.get("OIDC_ISSUER"):
        modules.append(oidc_module)
    return create_app(modules, title="demo")
