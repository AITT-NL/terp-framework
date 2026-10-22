"""Shared fixtures for the deployment declaration's tests (ADR 0184).

A project tree on disk with its own ``.git`` marker, so it is its own checkout, a
production profile in the template's shape, and the template's own seed as the
declaration every case starts from and then breaks in one way.
"""

from __future__ import annotations

import copy
import json
import pathlib
from typing import Any

import yaml
from fastapi import FastAPI

from terp.arch.deployment import DEPLOYMENT_FILE, published_table

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
#: The seed is a copier template since ADR 0187: its build is the deploy_build answer.
SEED_PATH = REPO_ROOT / "template" / "project" / f"{DEPLOYMENT_FILE}.jinja"
SEED_PLACEHOLDER = "{{ deploy_build }}"
PROBE_REF = "tests.architecture.deployment_fixtures:probe_app"
POSTGRES = published_table().find("postgres", "17")
assert POSTGRES is not None, "the datastore table must carry the template's PostgreSQL"

_BACKEND_ENV_FILE = [{"path": ".app.env", "required": False}]


def probe_app() -> FastAPI:
    """The app the app part builds in these tests: the platform's two health routes."""
    app = FastAPI()

    @app.get("/health/ready")
    def ready() -> dict:
        return {}

    @app.get("/health/live")
    def live() -> dict:
        return {}

    return app


def seed(build: str = "own") -> dict[str, Any]:
    """The template's own seed, as data, rendered with *build* as copier renders it."""
    text = SEED_PATH.read_text(encoding="utf-8")
    assert text.count(SEED_PLACEHOLDER) == 1, "the seed takes build from the answer, once"
    return json.loads(text.replace(SEED_PLACEHOLDER, build))


def profile(**services: dict | None) -> dict[str, Any]:
    """The template's production profile, as data; a ``None`` service is removed."""
    base: dict[str, Any] = {
        "db": {"image": POSTGRES.image, "volumes": ["db-data:/var/lib/postgresql/data"]},
        "migrate": {
            "image": "app-backend-prod",
            "command": ["terp", "migrate", "upgrade", "--app-root", "/srv/app"],
            "env_file": copy.deepcopy(_BACKEND_ENV_FILE),
            "depends_on": {"db": {"condition": "service_healthy"}},
        },
        "api": {
            "image": "app-backend-prod",
            "build": {"context": ".", "dockerfile": "Dockerfile.prod"},
            "env_file": copy.deepcopy(_BACKEND_ENV_FILE),
            "environment": {"SECRET_KEY": "${SECRET_KEY:?}", "ENVIRONMENT": "production"},
            "depends_on": {
                "db": {"condition": "service_healthy"},
                "migrate": {"condition": "service_completed_successfully"},
            },
        },
        "web": {
            "image": "app-frontend-prod",
            "build": {"context": ".", "dockerfile": "frontend/Dockerfile.prod"},
            "depends_on": {"api": {"condition": "service_healthy"}},
        },
    }
    for name, service in services.items():
        if service is None:
            base.pop(name, None)
        else:
            base[name] = service
    return {"services": base, "volumes": {"db-data": None}}


def project(
    tmp_path: pathlib.Path,
    declaration: dict | str | None,
    compose: dict | str | None = None,
    *,
    manifest: dict | None = None,
    files: dict[str, str] | None = None,
) -> pathlib.Path:
    """A project root of its own: a checkout holding a declaration and a profile."""
    root = tmp_path / "project"
    root.mkdir(parents=True, exist_ok=True)
    (root / ".git").mkdir(exist_ok=True)
    if declaration is not None:
        text = declaration if isinstance(declaration, str) else json.dumps(declaration)
        (root / DEPLOYMENT_FILE).write_text(text, encoding="utf-8")
    compose = profile() if compose is None else compose
    text = compose if isinstance(compose, str) else yaml.safe_dump(compose)
    (root / "docker-compose.prod.yml").write_text(text, encoding="utf-8")
    if manifest is not None:
        (root / "environment.schema.json").write_text(json.dumps(manifest), encoding="utf-8")
    for relative, content in (files or {}).items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return root


def unit(declaration: dict, unit_id: str) -> dict:
    """The declared unit called *unit_id*, for a case to change in place."""
    return next(entry for entry in declaration["units"] if entry["id"] == unit_id)
