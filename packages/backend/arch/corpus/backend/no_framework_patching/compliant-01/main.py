"""Compliant: behaviour is changed through the seams the framework gives."""

from terp.core import ControlPlane, create_app

from app.auth import login_module, me_module, resolve_principal


def build():
    app = create_app(
        [login_module, me_module],
        control_plane=ControlPlane(),
        principal_provider=resolve_principal,
        title="demo",
    )
    app.state.started_by = "build"
    return app
