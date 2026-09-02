"""The example Docker workbench topology (apps/example/docker-compose.yml) stays intact.

A structure guard that parses the Compose file as data: the workbench services exist, the API
waits for a healthy database and a completed migrate, seeding follows migrate, and both app and
frontend source reach the running containers live (bind mounts + polling reloaders — compose
watch's inotify never fires across Docker Desktop / volume mounts, ADR: the Studio dev loop) —
so the "one command to a seeded, running app" contract cannot silently rot. Docker is not
required (this parses the file, it does not run it).
"""

from __future__ import annotations

import json
import pathlib
import re
import tomllib

import yaml

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_COMPOSE = _REPO_ROOT / "apps" / "example" / "docker-compose.yml"
_TEMPLATE_COMPOSE = _REPO_ROOT / "template" / "project" / "docker-compose.yml.jinja"
_TEMPLATE_PROD_COMPOSE = _REPO_ROOT / "template" / "project" / "docker-compose.prod.yml.jinja"
_EXAMPLE_DOCKERFILE = _REPO_ROOT / "apps" / "example" / "Dockerfile"
_TEMPLATE_DOCKERFILE = _REPO_ROOT / "template" / "project" / "Dockerfile"
_WORKBENCH_SERVICES = {"db", "migrate", "seed", "api", "web"}


def _compose() -> dict:
    return yaml.safe_load(_COMPOSE.read_text(encoding="utf-8"))


#: A non-nested `{% if ... %}...{% endif %}` Jinja block (the create wizard's optional
#: capability wiring). Dropping the blocks yields the template's default render.
_JINJA_IF_BLOCK = re.compile(r"\{%-?\s*if\b.*?%\}.*?\{%-?\s*endif\s*-?%\}", re.DOTALL)


def _template_compose() -> dict:
    # Substituting the one interpolation ({{ project_slug }}) and stripping the wizard's
    # conditional blocks (their default render — every capability toggle off) lets the file
    # parse as YAML without a Jinja engine (mirrors test_template.py's no-render checks).
    # The toggled-on renders are proven by the template-acceptance CI matrix.
    text = _TEMPLATE_COMPOSE.read_text(encoding="utf-8").replace("{{ project_slug }}", "app")
    text = _JINJA_IF_BLOCK.sub("", text)
    assert "{%" not in text, "unstripped Jinja block in the template compose"
    return yaml.safe_load(text)


def _template_prod_compose() -> dict:
    text = _TEMPLATE_PROD_COMPOSE.read_text(encoding="utf-8")
    text = text.replace("{{ project_slug }}", "app").replace("{{ project_name }}", "App")
    return yaml.safe_load(_JINJA_IF_BLOCK.sub("", text))


def _depends_conditions(service: dict) -> dict:
    """The ``depends_on`` name->condition map (list form -> None condition; absent -> {})."""
    deps = service.get("depends_on", {})
    if isinstance(deps, list):
        return {name: None for name in deps}
    return {name: spec.get("condition") for name, spec in deps.items()}


def test_compose_file_is_present_and_valid_yaml() -> None:
    data = _compose()
    assert isinstance(data, dict)
    assert "services" in data


def test_compose_declares_the_workbench_services() -> None:
    services = _compose()["services"]
    assert {"db", "migrate", "seed", "api", "web"} <= set(services)


def test_database_has_a_healthcheck() -> None:
    assert "healthcheck" in _compose()["services"]["db"]


def test_every_long_running_service_has_a_healthcheck() -> None:
    """`db` and `api` had one; `web` did not, and nothing said so.

    Without it `docker compose up --wait` returns before the frontend is
    listening and `depends_on: service_healthy` cannot name it — so the one
    service a person actually looks at was the one compose could say nothing
    about. The one-shots are excluded on purpose: `migrate` and `seed` are
    finished when they exit, and health is not a question about them.
    """
    services = _compose()["services"]
    long_running = {"db", "api", "web"}

    missing = [name for name in sorted(long_running) if "healthcheck" not in services[name]]

    assert missing == []


def test_the_frontend_healthcheck_uses_a_binary_its_image_actually_has() -> None:
    """`node:24-slim` ships neither wget nor curl.

    A healthcheck naming one of them does not fail loudly — the probe just
    never succeeds, and the service sits permanently unhealthy while serving
    perfectly well. Node is the runtime the image is built on, so it is the one
    thing guaranteed to be there.
    """
    for compose in (_compose(), _template_compose()):
        command = compose["services"]["web"]["healthcheck"]["test"]

        assert command[0] == "CMD"
        assert command[1] == "node"
        assert not any(part in ("wget", "curl") for part in command)


def test_api_waits_for_a_healthy_db_and_a_completed_migrate() -> None:
    deps = _compose()["services"]["api"]["depends_on"]
    assert deps["db"]["condition"] == "service_healthy"
    assert deps["migrate"]["condition"] == "service_completed_successfully"


def test_seed_follows_a_completed_migrate() -> None:
    deps = _compose()["services"]["seed"]["depends_on"]
    assert deps["migrate"]["condition"] == "service_completed_successfully"


def test_api_mounts_live_app_source_with_a_polling_reloader() -> None:
    """Every backend process sees live app source; uvicorn additionally polls.

    Sharing only with ``api`` is insufficient: a newly-authored migration would
    hot-reload into the model while the one-shot ``migrate`` container still ran
    the stale image copy.
    """
    services = _compose()["services"]
    for name in ("migrate", "seed", "api"):
        sources = {
            volume.rsplit(":", 1)[0]
            for volume in services[name].get("volumes", [])
        }
        assert "./app" in sources
        assert "./control_plane" in sources
    assert services["api"]["environment"]["WATCHFILES_FORCE_POLLING"] == "true"


def test_web_mounts_live_frontend_source_and_proxies_to_the_api() -> None:
    web = _compose()["services"]["web"]
    sources = {volume.rsplit(":", 1)[0] for volume in web.get("volumes", [])}
    assert "./frontend/src" in sources
    assert web["environment"]["TERP_DEV_FORCE_POLLING"] == "true"
    assert web["environment"]["TERP_API_PROXY"] == "http://api:8000"


def test_template_workbench_mounts_live_source_through_the_host_root_seam() -> None:
    """The template's bind sources interpolate TERP_DEV_HOST_ROOT (the checkout
    as the DAEMON sees it — a containerized Studio passes it; default `.` is
    the manual layout), so the Studio dev loop hot-reloads too."""
    services = _template_compose()["services"]
    for name in ("migrate", "seed", "api"):
        backend_sources = {
            volume.rsplit(":", 1)[0]
            for volume in services[name].get("volumes", [])
        }
        assert "${TERP_DEV_HOST_ROOT:-.}/app" in backend_sources
        assert "${TERP_DEV_HOST_ROOT:-.}/control_plane" in backend_sources
    web_sources = {volume.rsplit(":", 1)[0] for volume in services["web"].get("volumes", [])}
    assert "${TERP_DEV_HOST_ROOT:-.}/frontend/src" in web_sources
    assert services["api"]["environment"]["WATCHFILES_FORCE_POLLING"] == "true"
    assert services["web"]["environment"]["TERP_DEV_FORCE_POLLING"] == "true"


def test_workbench_backend_forwards_app_declared_env() -> None:
    """Inner-loop parity with the production profile: backend services read the
    optional .app.env (app-declared variables, environment.schema.json), so a
    declared variable behaves identically in `Mijn app` and in a deploy."""
    seam = [{"path": ".app.env", "required": False}]
    for data in (_compose(), _template_compose()):
        for name in ("migrate", "seed", "api"):
            assert data["services"][name].get("env_file") == seam, (
                f"{name} must read the optional .app.env (app-declared variables)"
            )


def test_no_declared_variable_is_also_forwarded_through_compose() -> None:
    """The seam Studio owns must not be overridden by the one it does not.

    Compose resolves `environment:` over `env_file:`, so a variable named in BOTH is
    supplied by the developer's `.env` and the rendered `.app.env` is discarded — and not
    only when `.env` sets it: with no `.env` at all, `${VAR:-}` still wins with an empty
    string, so there is no configuration in which the declared value arrives.

    This is the template's own regression test for that; `terp verify --only env-seams`
    is the same verdict for an app. Both read files, so CI needs no Docker daemon.
    """
    declared = set(
        json.loads(
            (_REPO_ROOT / "template" / "project" / "environment.schema.json").read_text(
                encoding="utf-8"
            )
        )["properties"]
    )
    for label, services in (
        ("workbench", _template_compose()["services"]),
        ("production", _template_prod_compose()["services"]),
    ):
        for name, service in services.items():
            forwarded = set(service.get("environment") or {}) & declared
            assert not forwarded, (
                f"{label} service {name!r} sets {sorted(forwarded)} in `environment:`, "
                "which overrides the .app.env value Studio renders for it"
            )


def test_the_workbench_ships_an_app_env_example_so_the_seam_is_exercised_locally() -> None:
    """`.app.env` does not exist in a fresh checkout and `env_file` is `required: false`,
    so its absence is invisible: all of local development ran on `.env` plus compose
    defaults, and the first time a value actually diverged was in a Studio-managed
    environment — the worst place to meet the precedence rule. Shipping an example makes
    the production seam the one the inner loop uses."""
    example = _REPO_ROOT / "template" / "project" / ".app.env.example"
    assert example.is_file(), "the template must ship .app.env.example"
    text = example.read_text(encoding="utf-8")
    assert "cp .app.env.example .app.env" in text
    # It has to explain the precedence, because that is the thing nobody could see.
    assert "environment:" in text and "env_file:" in text
    for party in ("container", "host", "browser"):
        assert party in text, f"the example must name the {party}-resolved class"


# --------------------------------------------------------------------------- #
# Drift guard: the example (monorepo) and the template (standalone) workbenches
# legitimately differ in build context, but their *topology* is the contract and
# must not drift — the same anti-drift discipline as the vendored core / OpenAPI gates.
# --------------------------------------------------------------------------- #
def test_example_and_template_workbenches_share_a_topology() -> None:
    example = _compose()["services"]
    template = _template_compose()["services"]
    assert set(example) == set(template) == _WORKBENCH_SERVICES
    # Identical health-gated ordering across every service (db -> migrate -> seed -> api + web).
    for service in _WORKBENCH_SERVICES:
        assert _depends_conditions(example[service]) == _depends_conditions(template[service])
    # Identical backend config contract, live-mounted source, same-origin proxy, and
    # configurable host ports.
    assert (
        set(example["api"]["environment"])
        == set(template["api"]["environment"])
        == {"DATABASE_URL", "SECRET_KEY", "ENVIRONMENT", "WATCHFILES_FORCE_POLLING"}
    )
    assert "watch" in example["api"]["develop"] and "watch" in template["api"]["develop"]
    assert (
        example["web"]["environment"]["TERP_API_PROXY"]
        == template["web"]["environment"]["TERP_API_PROXY"]
        == "http://api:8000"
    )
    assert any("${API_PORT" in port for port in example["api"]["ports"])
    assert any("${API_PORT" in port for port in template["api"]["ports"])
    assert any("${WEB_PORT" in port for port in example["web"]["ports"])
    assert any("${WEB_PORT" in port for port in template["web"]["ports"])
    # Same health signal on both sides: a probe added to one workbench and not
    # the other is exactly the drift this parity test exists to catch.
    assert (
        example["web"]["healthcheck"]["test"]
        == template["web"]["healthcheck"]["test"]
    )


def test_example_and_template_backend_images_share_the_security_invariants() -> None:
    for dockerfile in (_EXAMPLE_DOCKERFILE, _TEMPLATE_DOCKERFILE):
        text = dockerfile.read_text(encoding="utf-8")
        assert "FROM python:3.13-slim" in text  # pinned slim base
        assert "\nUSER " in text  # drops root
        assert "psycopg" in text  # the production database driver
        assert '"uvicorn[standard]"' in text and "app.main:app" in text


def test_local_dev_environments_install_websocket_server_support() -> None:
    root = tomllib.loads((_REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    root_dev = root["dependency-groups"]["dev"]
    assert any(dependency.startswith("uvicorn[standard]") for dependency in root_dev)

    template = (
        _REPO_ROOT / "template" / "project" / "pyproject.toml.jinja"
    ).read_text(encoding="utf-8")
    assert '"uvicorn[standard]>=0.30"' in template


def test_example_and_template_dev_proxies_forward_websocket_upgrades() -> None:
    for vite_config in (
        _REPO_ROOT / "apps" / "example" / "frontend" / "vite.config.ts",
        _REPO_ROOT / "template" / "project" / "frontend" / "vite.config.ts",
    ):
        text = vite_config.read_text(encoding="utf-8")
        assert "ws: true" in text, f"{vite_config} must proxy WebSocket upgrades"


def test_the_template_declaration_tells_the_truth_about_the_template_compose() -> None:
    """The seeded `workbench.json` is audited against the compose it describes.

    `terp verify --only workbench` cannot be run against `template/project`:
    the compose file there is Jinja and does not parse as YAML, so the one
    declaration every new app starts from was the one nobody checked. That is
    not hypothetical — the same gap let `apps/example` ship a declaration
    naming a `sourceRoot` seam its compose file does not use. This audits the
    template's declaration against the template's own default render, which is
    the only place the pairing can be verified before an app exists.
    """
    from terp.cli.workbench import Declaration, audit

    declared = json.loads(
        (_REPO_ROOT / "template" / "project" / "workbench.json").read_text(
            encoding="utf-8"
        )
    )

    findings = audit(
        Declaration(
            compose_file="docker-compose.yml",
            services=tuple(declared["services"]),
            env=declared.get("env", {}),
        ),
        _template_compose(),
    )

    assert [f.message for f in findings] == []
