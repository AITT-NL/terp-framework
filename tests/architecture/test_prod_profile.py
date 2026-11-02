"""The production profile (ADR 0062) keeps its hardening invariants.

Structure guards over ``apps/example/docker-compose.prod.yml`` + ``Dockerfile.prod`` and
their template mirrors, in the style of ``test_compose_workbench.py``: parsed as data, no
Docker required. The runtime half of the two-layer control is ``terp.core.config``'s
production fail-fast guardrails (the app refuses to boot on unsafe settings); these tests
are the build-time half — the profile cannot silently drift back to dev ergonomics
(``--reload``, seed data, a fallback SECRET_KEY, editable installs, root).
"""

from __future__ import annotations

import json
import pathlib
import re
import tomllib

import yaml

from tests.architecture.deployment_fixtures import template_profile

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_PROD_COMPOSE = _REPO_ROOT / "apps" / "example" / "docker-compose.prod.yml"
_PROD_DOCKERFILE = _REPO_ROOT / "apps" / "example" / "Dockerfile.prod"
_TEMPLATE_PROD_DOCKERFILE = _REPO_ROOT / "template" / "project" / "Dockerfile.prod"
_PROD_WEB_DOCKERFILE = _REPO_ROOT / "apps" / "example" / "frontend" / "Dockerfile.prod"
_TEMPLATE_PROD_WEB_DOCKERFILE = _REPO_ROOT / "template" / "project" / "frontend" / "Dockerfile.prod"
_NGINX_CONF = _REPO_ROOT / "apps" / "example" / "frontend" / "nginx.conf"
_TEMPLATE_NGINX_CONF = _REPO_ROOT / "template" / "project" / "frontend" / "nginx.conf"
_PROD_SMOKE_WORKFLOW = _REPO_ROOT / ".github" / "workflows" / "prod-smoke.yml"


def _prod_compose() -> dict:
    return yaml.safe_load(_PROD_COMPOSE.read_text(encoding="utf-8"))


def _template_prod_compose(*, use_files: bool = False) -> dict:
    return yaml.safe_load(template_profile(use_files=use_files))


def _both_composes() -> list[dict]:
    """The example's profile and the template's, rendered for each answer it renders on."""
    return [_prod_compose(), _template_prod_compose(), _template_prod_compose(use_files=True)]


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


def test_the_template_s_images_carry_a_required_per_release_tag() -> None:
    """ADR 0185 decision 6: both image names read the per-release tag, ``:?``-required like
    the secrets, so a release's images stay beside the next one's and an unset tag stops
    compose instead of overwriting a fixed one. Every backend service inherits the backend
    name through the merge key. The example app builds from the monorepo and is released by
    no `terp release`, so its profile keeps its untagged names."""
    from terp.arch.deployment.generator import RELEASE_TAG_SEAM, RELEASE_TAG_VARIABLE

    template = _template_prod_compose()
    services = template["services"]
    assert RELEASE_TAG_SEAM == (
        "${TERP_RELEASE_TAG:?TERP_RELEASE_TAG is required, one new image tag per release}"
    )
    assert RELEASE_TAG_VARIABLE == "TERP_RELEASE_TAG"
    assert template["x-backend"]["image"] == f"app-backend-prod:{RELEASE_TAG_SEAM}"
    for name in ("migrate", "api"):
        assert services[name]["image"] == f"app-backend-prod:{RELEASE_TAG_SEAM}", name
    assert services["web"]["image"] == f"app-frontend-prod:{RELEASE_TAG_SEAM}"


def test_prod_database_url_reads_from_the_environment() -> None:
    """The external-database seam: the bundled `db` service is the *default*,
    and a deployment can point the app at a PostgreSQL it operates itself by
    setting DATABASE_URL. Both backend services must honour it, or an
    external-database deploy would silently keep writing to the sidecar."""
    for data in _both_composes():
        for name in ("migrate", "api"):
            url = data["services"][name]["environment"]["DATABASE_URL"]
            assert url.startswith("${DATABASE_URL:-"), f"{name} must read the seam"
            assert "@db:5432/" in url, f"{name} must default to the bundled db"


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
    """Wheels-only runtime: multi-stage, no editable installs, non-root, no --reload.

    The WebSocket-capable server is named in the example's Dockerfile, which installs it
    there. The template's image installs it from the committed lock as a runtime
    dependency of the app (test_template_build_inputs.py), so the name its Dockerfile
    carries is the one CMD runs.
    """
    for path in (_PROD_DOCKERFILE, _TEMPLATE_PROD_DOCKERFILE):
        text = path.read_text(encoding="utf-8")
        # By tag in the example; by digest from the base-image table in the template, whose
        # files are the generator's render (ADR 0187).
        assert len(re.findall(r"^FROM python[:@]", text, re.MULTILINE)) == 2, (
            f"{path.name} must be multi-stage"
        )
        assert "uv build --wheel" in text
        assert "-e " not in text, f"{path.name} must not install editable"
        assert "USER " in text, f"{path.name} must drop root"
        code_lines = [
            line for line in text.splitlines() if line.strip() and not line.strip().startswith("#")
        ]
        assert not any("--reload" in line for line in code_lines)
        assert 'CMD ["uvicorn", "app.main:app"' in text
    # The example's image serves only its api. The template's backs every backend unit, and
    # changed on purpose (ADR 0187): no HEALTHCHECK of its own, because a worker or a
    # scheduler that inherits an HTTP probe turns unhealthy and `docker compose up --wait`
    # then refuses the deployment. Its profile probes each api unit itself.
    assert "HEALTHCHECK" in _PROD_DOCKERFILE.read_text(encoding="utf-8")
    assert not any(
        line.startswith("HEALTHCHECK")
        for line in _TEMPLATE_PROD_DOCKERFILE.read_text(encoding="utf-8").splitlines()
    )
    assert "healthcheck" in _template_prod_compose()["services"]["api"]
    example = _PROD_DOCKERFILE.read_text(encoding="utf-8")
    assert '"uvicorn[standard]"' in example, "the example image must serve WebSockets"


def _force_included_from_outside_the_package() -> dict[str, str]:
    """Every backend force-include whose SOURCE escapes its own package directory,
    mapped to the package that declares it."""
    outside: dict[str, str] = {}
    for pyproject in (_REPO_ROOT / "packages" / "backend").rglob("pyproject.toml"):
        config = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        forced = (
            config.get("tool", {})
            .get("hatch", {})
            .get("build", {})
            .get("targets", {})
            .get("wheel", {})
            .get("force-include", {})
        )
        package = pyproject.parent
        for source in forced:
            if package.resolve() not in (package / source).resolve().parents:
                outside[source] = package.relative_to(_REPO_ROOT).as_posix()
    return outside


def test_no_backend_package_force_includes_a_file_outside_itself() -> None:
    """A force-include is resolved when the WHEEL is built, and the wheel that
    reaches PyPI is built from the sdist — which contains only the package. A
    source reaching outside it therefore resolves against the unpacked sdist and
    hatchling aborts with "Forced include not found", on the publishing path
    alone: the local gate, CI's gate job and a plain editable install all build
    from the full checkout and never notice.

    So this is not a portability nicety, it is the difference between a
    releasable package and one that fails at the last step. Ship the file inside
    the package (checked in, held to its source by a test) instead.

    Cost of learning this the other way: v0.5.5, whose build-pypi job died here."""
    offenders = _force_included_from_outside_the_package()
    assert not offenders, "; ".join(
        f"{package} force-includes {source!r} from outside its own directory"
        for source, package in sorted(offenders.items())
    )


def test_prod_web_images_build_the_bundle_and_serve_nonroot() -> None:
    for path in (_PROD_WEB_DOCKERFILE, _TEMPLATE_PROD_WEB_DOCKERFILE):
        text = path.read_text(encoding="utf-8")
        assert "build" in text and "FROM nginxinc/nginx-unprivileged" in text
        assert "HEALTHCHECK" in text


def test_prod_nginx_serves_spa_fallback_and_same_origin_api() -> None:
    for path in (_NGINX_CONF, _TEMPLATE_NGINX_CONF):
        text = path.read_text(encoding="utf-8")
        assert "try_files $uri /index.html;" in text, "SPA fallback required"
        assert "proxy_pass http://${API_UPSTREAM};" in text, "same-origin /api proxy required"
        assert "proxy_set_header Upgrade $http_upgrade;" in text
        assert 'proxy_set_header Connection "upgrade";' in text


def test_prod_nginx_upstream_is_substituted_with_a_compose_default() -> None:
    """The /api upstream is a start-up substitution, not a baked-in hostname.

    Compose reaches the API by service name; a runtime that co-locates the two
    containers in one pod (Azure Container Apps) reaches it on localhost. One image
    must serve both, so the name is an env var — with the compose default baked in so
    `docker compose up` needs no extra configuration. The envsubst filter is part of
    the contract: without it nginx's own $uri / $host / $http_upgrade would be
    replaced with empty strings and the proxy would break in a way that only shows up
    at runtime.
    """
    for path in (_PROD_WEB_DOCKERFILE, _TEMPLATE_PROD_WEB_DOCKERFILE):
        text = path.read_text(encoding="utf-8")
        assert "/etc/nginx/templates/default.conf.template" in text, (
            f"{path} must install the config as an envsubst template"
        )
        assert "API_UPSTREAM=api:8000" in text, f"{path} must default to the compose service"
        assert "NGINX_ENVSUBST_FILTER=^API_UPSTREAM$" in text, (
            f"{path} must restrict substitution to API_UPSTREAM"
        )


def test_prod_smoke_exercises_websocket_through_nginx() -> None:
    workflow = yaml.safe_load(_PROD_SMOKE_WORKFLOW.read_text(encoding="utf-8"))
    steps = workflow["jobs"]["prod-smoke"]["steps"]
    websocket_steps = [
        step for step in steps
        if step.get("name") == "WebSocket upgrade + typed frame through production nginx"
    ]
    assert len(websocket_steps) == 1
    script = websocket_steps[0]["run"]
    assert "websockets.connect" in script
    assert "asyncio.wait_for" in script
    assert "personal.updates" in script
    assert "refresh accepted" in script


def test_example_and_template_prod_profiles_share_a_topology() -> None:
    """Template parity: a generated repo deploys exactly like the dogfood app."""
    example = _prod_compose()["services"]
    for use_files in (False, True):
        template = _template_prod_compose(use_files=use_files)["services"]
        assert set(example) == set(template) == {"db", "migrate", "api", "web"}


def test_with_files_the_api_keeps_them_in_a_volume_its_user_can_write() -> None:
    """With the files capability on, the production profile mounts a named volume at
    the capability's storage root, so stored files outlive the container. Before, only the
    development file mounted one, and production kept them in the api container's writable
    layer, gone at the next deploy.

    The volume is writable by the user the image runs as because the image makes the
    mount point and hands it to that user before it drops to it, and Docker gives an empty
    named volume the owner of the directory it is mounted over. The Docker half, a fresh
    volume written by that user and read back from a second container, runs in template
    acceptance."""
    with_files = _template_prod_compose(use_files=True)
    assert with_files["volumes"] == {"db-data": None, "files-data": None}
    assert with_files["services"]["api"]["volumes"] == ["files-data:/srv/var/files"]
    for name in ("db", "migrate", "web"):
        mounts = with_files["services"][name].get("volumes") or []
        assert "files-data:/srv/var/files" not in mounts, name
    without = _template_prod_compose()
    assert "volumes" not in without["services"]["api"]
    assert without["volumes"] == {"db-data": None}

    dockerfile = _TEMPLATE_PROD_DOCKERFILE.read_text(encoding="utf-8")
    runtime = dockerfile.rsplit("\nFROM ", 1)[1]
    assert "WORKDIR /srv\n" in runtime, "the storage root, var/files, is relative to /srv"
    made = runtime.index("mkdir -p /srv/var/files && chown appuser /srv/var/files")
    assert "useradd --create-home --uid 10001 appuser" in runtime
    assert made < runtime.index("\nUSER appuser\n"), "made and handed over before the drop"


# ---- app-declared environment variables (plan: app-declared-environment-config) --

_APP_ENV_SEAM = [{"path": ".app.env", "required": False}]
_ENV_SCHEMA_PATHS = (
    _REPO_ROOT / "apps" / "example" / "environment.schema.json",
    _REPO_ROOT / "template" / "project" / "environment.schema.json",
)
_ENV_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
_PLATFORM_OWNED_NAMES = {
    "SECRET_KEY",
    "POSTGRES_PASSWORD",
    "DATABASE_URL",
    "ENVIRONMENT",
    "WEB_PORT",
    "BACKEND_CORS_ORIGINS",
    "TERP_RELEASE_TAG",
}


def test_the_platform_owned_names_are_the_ones_the_cli_refuses() -> None:
    """One owner per variable: every name the profile interpolates for the platform, the
    per-release tag among them, is one a manifest may not declare into ``.app.env``."""
    from terp.arch.deployment.generator import RELEASE_TAG_VARIABLE
    from terp.cli.envschema import PLATFORM_OWNED_NAMES

    assert PLATFORM_OWNED_NAMES == _PLATFORM_OWNED_NAMES
    assert RELEASE_TAG_VARIABLE in PLATFORM_OWNED_NAMES


def test_prod_backend_forwards_app_declared_env() -> None:
    """The one generic seam: backend services read the optional .app.env the
    deploy pipeline renders from environment.schema.json. `required: false`
    keeps plain `docker compose up` working; the frontend (build-time vars
    only) deliberately gets no seam.

    Changed on purpose by ADR 0187: the template's profile is the generator's render, which
    lists on each backend unit `.app.env` and then that unit's own `.app.<id>.env` (where
    the manifest routes a variable scoped to it), while `x-backend` keeps `.app.env` alone,
    so a service an app added through the merge key still inherits it. The example app's
    profile is its own and keeps the single seam."""
    example, template = _prod_compose(), _template_prod_compose()
    for name in ("migrate", "api"):
        assert example["services"][name].get("env_file") == _APP_ENV_SEAM, (
            f"{name} must read the optional .app.env (app-declared variables)"
        )
        assert template["services"][name].get("env_file") == [
            *_APP_ENV_SEAM, {"path": f".app.{name}.env", "required": False}
        ], f"{name} reads .app.env, then its own .app.{name}.env"
    assert template["x-backend"]["env_file"] == _APP_ENV_SEAM
    for data in (example, template):
        assert "env_file" not in data["services"]["web"]


def test_environment_schema_manifest_is_present_and_well_shaped() -> None:
    """The app-declared variable manifest ships (empty) with every app: names
    are UPPER_SNAKE, platform-owned names are never shadowed, and the shape
    matches the target kinds' environment_schema dialect."""
    for path in _ENV_SCHEMA_PATHS:
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["type"] == "object", path
        properties = data["properties"]
        assert isinstance(properties, dict) and len(properties) <= 50, path
        assert isinstance(data["required"], list), path
        for name in data["required"]:
            assert name in properties, f"{path}: required key {name!r} is undeclared"
        for name in properties:
            assert _ENV_NAME_RE.fullmatch(name), f"{path}: {name!r} is not UPPER_SNAKE"
            assert name not in _PLATFORM_OWNED_NAMES, (
                f"{path}: {name!r} is platform-owned — one owner per variable"
            )


def test_rendered_app_env_is_excluded_from_every_build_context() -> None:
    root_ignore = (_REPO_ROOT / ".dockerignore").read_text(encoding="utf-8")
    template_ignore = (
        _REPO_ROOT / "template" / "project" / ".dockerignore"
    ).read_text(encoding="utf-8")
    assert "**/.app.env" in root_ignore
    assert ".app.env" in template_ignore
