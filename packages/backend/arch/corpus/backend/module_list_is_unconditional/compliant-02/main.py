"""Compliant: the list is built in steps, none of them under a condition."""

from terp.core import create_app

from app.auth import login_module, me_module
from app.modules.notes.module import module as notes_module


def _create(*specs, title):
    return create_app(list(specs), title=title)


def build():
    modules = [login_module, me_module]
    modules.append(notes_module)
    return _create(*modules, title="demo")
