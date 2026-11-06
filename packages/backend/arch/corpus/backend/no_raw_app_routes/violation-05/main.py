"""Violation: factory returns a local create_app result; app.router adds a route."""

from terp.core import create_app


def build():
    app = create_app([])
    return app


app = build()
app.router.add_api_route("/api/v1/raw", endpoint, methods=["GET"])
