"""Violation: a lifecycle hook registered on the composed app (ungated executable surface)."""

from terp.core import create_app

app = create_app([])


@app.on_event("startup")
def warm_cache() -> None:
    pass
