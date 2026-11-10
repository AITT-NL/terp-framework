"""Violation: modules that are None in some environment, filtered out of the list."""

from terp.core import create_app

from app.auth import login_module, me_module, oidc_module


def build():
    return create_app(
        modules=[module for module in (login_module, me_module, oidc_module) if module is not None],
        title="demo",
    )
