"""Violation: an element chosen by a conditional expression."""

from terp.core import create_app, get_settings

from app.auth import login_module, me_module
from app.modules.debug.module import module as debug_module
from app.modules.notes.module import module as notes_module


def build():
    return create_app(
        [login_module, me_module, debug_module if get_settings().DEBUG else notes_module],
        title="demo",
    )
