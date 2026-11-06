"""Compliant: the composition root only composes; modules own every route."""

from terp.core import create_app

from app.modules.notes.module import module as notes_module


def build():
    return create_app([notes_module])


app = build()
