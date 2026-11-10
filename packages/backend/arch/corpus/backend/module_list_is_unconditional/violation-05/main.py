"""Violation: a helper that returns one list or another."""

from terp.core import create_app, get_settings

from app.auth import login_module, me_module, oidc_module


def _modules():
    if get_settings().is_production:
        return [login_module, me_module]
    return [login_module, me_module, oidc_module]


def build():
    return create_app(_modules(), title="demo")
