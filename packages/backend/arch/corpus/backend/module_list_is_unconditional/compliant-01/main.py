"""Compliant: every module is named, in every environment."""

from terp.core import create_app

from app.auth import login_module, me_module, oidc_module


def build():
    return create_app([login_module, me_module, oidc_module], title="demo")
