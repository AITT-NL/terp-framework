"""Violation: aliased create_app binding plus websocket route decorator."""

from terp.core import create_app as make_app

app = make_app([])


@app.websocket_route("/ws")
async def ws(websocket):
    return None
