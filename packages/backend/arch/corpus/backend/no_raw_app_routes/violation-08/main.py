"""Violation: a factory's composed app takes an exception handler imperatively."""

from terp.core import create_app


def build():
    app = create_app([])
    app.add_exception_handler(LookupError, not_found_as_text)
    return app
