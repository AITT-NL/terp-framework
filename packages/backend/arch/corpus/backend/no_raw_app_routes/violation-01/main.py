"""Violation: a verb route registered on the composed app bypasses the module guard."""

from terp.core import create_app

app = create_app([])


@app.get("/api/v1/hacks/")
def list_hacks() -> dict:
    return {}
