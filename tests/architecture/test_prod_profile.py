"""The production profile (ADR 0062) keeps its hardening invariants.

Structure guards over ``apps/example/docker-compose.prod.yml`` + ``Dockerfile.prod`` and
their template mirrors, in the style of ``test_compose_workbench.py``: parsed as data, no
Docker required. The runtime half of the two-layer control is ``terp.core.config``'s
production fail-fast guardrails (the app refuses to boot on unsafe settings); these tests
are the build-time half — the profile cannot silently drift back to dev ergonomics
(``--reload``, seed data, a fallback SECRET_KEY, editable installs, root).
"""

from __future__ import annotations

import pathlib

import yaml

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_PROD_COMPOSE = _REPO_ROOT / "apps" / "example" / "docker-compose.prod.yml"
_TEMPLATE_PROD_COMPOSE = _REPO_ROOT / "template" / "project" / "docker-compose.prod.yml.jinja"
_PROD_DOCKERFILE = _REPO_ROOT / "apps" / "example" / "Dockerfile.prod"
_TEMPLATE_PROD_DOCKERFILE = _REPO_ROOT / "template" / "project" / "Dockerfile.prod"
_PROD_WEB_DOCKERFILE = _REPO_ROOT / "apps" / "example" / "frontend" / "Dockerfile.prod"
_TEMPLATE_PROD_WEB_DOCKERFILE = _REPO_ROOT / "template" / "project" / "frontend" / "Dockerfile.prod"
_NGINX_CONF = _REPO_ROOT / "apps" / "example" / "frontend" / "nginx.conf"
_TEMPLATE_NGINX_CONF = _REPO_ROOT / "template" / "project" / "frontend" / "nginx.conf"


def _prod_compose() -> dict:
    return yaml.safe_load(_PROD_COMPOSE.read_text(encoding="utf-8"))


def _template_prod_compose() -> dict:
    text = _TEMPLATE_PROD_COMPOSE.read_text(encoding="utf-8")
    text = text.replace("{{ project_slug }}", "app").replace("{{ project_name }}", "App")
    return yaml.safe_load(text)


def _both_composes() -> list[dict]:
    return [_prod_compose(), _template_prod_compose()]


def test_prod_compose_is_present_and_valid_yaml() -> None:
    for data in _both_composes():
        assert isinstance(data, dict)
        assert "services" in data


def test_prod_profile_has_no_seed_service() -> None:
    """Seed data is dev/demo only; production bootstraps via `terp user create`."""
    for data in _both_composes():
        assert "seed" not in data["services"]


def test_prod_backend_runs_with_environment_production() -> None:
    """ENVIRONMENT=production arms the fail-fast config guardrails (runtime half)."""
    for data in _both_composes():
        env = data["services"]["api"]["environment"]
        assert env["ENVIRONMENT"] == "production"


def test_prod_secrets_have_no_dev_fallback() -> None:
    """SECRET_KEY / POSTGRES_PASSWORD are `:?`-required — compose fails fast unset."""
    for data in _both_composes():
        env = data["services"]["api"]["environment"]
        assert ":?" in env["SECRET_KEY"], "SECRET_KEY must be required (no dev default)"
        db_env = data["services"]["db"]["environment"]
        assert ":?" in db_env["POSTGRES_PASSWORD"], "POSTGRES_PASSWORD must be required"


def test_prod_api_serves_immutable_code() -> None:
    """No --reload and no source watch: production images are immutable."""
    for data in _both_composes():
        api = data["services"]["api"]
        command = api.get("command") or []
        assert "--reload" not in command
        assert "develop" not in api


def test_prod_api_waits_for_db_and_migrate() -> None:
    """Migrate-then-serve ordering; the boot guard backs it up at runtime."""
    for data in _both_composes():
        deps = data["services"]["api"]["depends_on"]
        assert deps["db"]["condition"] == "service_healthy"
        assert deps["migrate"]["condition"] == "service_completed_successfully"


def test_prod_long_running_services_restart_and_healthcheck() -> None:
    for data in _both_composes():
        for name in ("db", "api", "web"):
            service = data["services"][name]
            assert service.get("restart") == "unless-stopped", f"{name} needs a restart policy"
            assert "healthcheck" in service, f"{name} needs a healthcheck"


def test_prod_backend_images_are_multistage_wheel_builds() -> None:
    """Wheels-only runtime: multi-stage, no editable installs, non-root, no --reload."""
    for path in (_PROD_DOCKERFILE, _TEMPLATE_PROD_DOCKERFILE):
        text = path.read_text(encoding="utf-8")
        assert text.count("FROM python:") == 2, f"{path.name} must be multi-stage"
        assert "uv build --wheel" in text
        assert "-e " not in text, f"{path.name} must not install editable"
        assert "USER " in text, f"{path.name} must drop root"
        code_lines = [
            line for line in text.splitlines() if line.strip() and not line.strip().startswith("#")
        ]
        assert not any("--reload" in line for line in code_lines)
        assert "HEALTHCHECK" in text


def test_prod_web_images_build_the_bundle_and_serve_nonroot() -> None:
    for path in (_PROD_WEB_DOCKERFILE, _TEMPLATE_PROD_WEB_DOCKERFILE):
        text = path.read_text(encoding="utf-8")
        assert "build" in text and "FROM nginxinc/nginx-unprivileged" in text
        assert "HEALTHCHECK" in text


def test_prod_nginx_serves_spa_fallback_and_same_origin_api() -> None:
    for path in (_NGINX_CONF, _TEMPLATE_NGINX_CONF):
        text = path.read_text(encoding="utf-8")
        assert "try_files $uri /index.html;" in text, "SPA fallback required"
        assert "proxy_pass http://api:8000;" in text, "same-origin /api proxy required"


def test_example_and_template_prod_profiles_share_a_topology() -> None:
    """Template parity: a generated repo deploys exactly like the dogfood app."""
    example = _prod_compose()["services"]
    template = _template_prod_compose()["services"]
    assert set(example) == set(template) == {"db", "migrate", "api", "web"}
