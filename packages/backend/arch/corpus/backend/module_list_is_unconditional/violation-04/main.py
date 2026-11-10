"""Violation: the condition sits in the caller of the function that calls create_app."""

from terp.core import create_app

from app.auth import login_module, me_module, oidc_module


def _create(*specs, title):
    return create_app(list(specs), title=title)


def build():
    modules = [login_module, me_module]
    if oidc_module is not None:
        modules += [oidc_module]
    return _create(*modules, title="demo")
