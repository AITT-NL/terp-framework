"""Violation: annotated create_app binding plus legacy route decorator."""

from fastapi import FastAPI

from terp.core import create_app

app: FastAPI = create_app([])


@app.route("/api/v1/raw")
def raw(request):
    return {}
