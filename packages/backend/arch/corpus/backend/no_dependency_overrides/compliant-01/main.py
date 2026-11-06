"""Compliant: the composition root wires seams through create_app only."""

from terp.core import create_app

from app.auth import principal_provider


def build():
    return create_app([], principal_provider=principal_provider)


app = build()
