"""Violation: raw surface mounted on the app returned by the composition factory."""

from fastapi import APIRouter

from terp.core import create_app


def build():
    return create_app([])


app = build()

router = APIRouter()
app.include_router(router, prefix="/api/v1/raw")
app.mount("/static", object())
