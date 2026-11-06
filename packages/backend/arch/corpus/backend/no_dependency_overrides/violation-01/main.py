"""Violation: rebinding the principal seam disables authentication app-wide."""

from terp.core import create_app, get_principal


def build():
    return create_app([])


app = build()
app.dependency_overrides[get_principal] = lambda: None
