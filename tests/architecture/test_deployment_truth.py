"""``deployment.json`` states nothing its profile or its app contradicts (ADR 0184).

Truth about self, never conformance. The cases that assert a REFUSAL each break one
claim the template's seed makes; the cases that assert a PASS are the shapes a real
deployment legitimately has, and they are the ones that keep this check from becoming a
gate on topology. The file part is the ``terp.arch`` rule; the app part, the notes and
the runner's output are ``terp verify --only deployment``'s.
"""

from __future__ import annotations

import copy
import json
import pathlib
import sys

import pytest
import yaml

from terp.arch import check_deployment_declaration_tells_the_truth
from terp.arch.deployment import Declaration, DatastoreTable, Datastore, readable, resolve_profile
from terp.arch.deployment.profile import rendered_files as arch_rendered_files
from terp.cli import deployment_app
from terp.cli.deployment_check import run_deployment_check
from terp.cli.envschema import rendered_files as cli_rendered_files
from tests.architecture.deployment_fixtures import (
    POSTGRES,
    PROBE_REF,
    REPO_ROOT,
    profile,
    project,
    seed,
    unit,
)


@pytest.fixture(autouse=True)
def _probe_app(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every project here builds the probe app, and leaves sys.path as it found it."""
    monkeypatch.setattr(deployment_app, "APP_REF", PROBE_REF)
    monkeypatch.setattr(sys, "path", list(sys.path))


def _untrue(root: pathlib.Path) -> str:
    violations = check_deployment_declaration_tells_the_truth(root)
    assert violations, "expected the truth rule to refuse this project"
    return "\n".join(violation.message for violation in violations)


def _true(root: pathlib.Path) -> None:
    assert check_deployment_declaration_tells_the_truth(root) == []
    code, output = run_deployment_check(root)
    assert code == 0, output


# --- rule 2 from the files -------------------------------------------------


def test_the_template_seed_tells_the_truth_about_the_template_profile(tmp_path) -> None:
    text = (REPO_ROOT / "template" / "project" / "docker-compose.prod.yml.jinja").read_text(
        encoding="utf-8"
    )
    text = text.replace("{{ project_slug }}", "app").replace("{{ project_name }}", "App")
    _true(project(tmp_path, seed(), text))


def test_a_unit_that_is_not_a_service_is_a_lie(tmp_path) -> None:
    message = _untrue(project(tmp_path, seed(), profile(web=None)))
    assert (
        'units[3].id "web" is not a service of docker-compose.prod.yml (allowed: a service of the profile: api, db, migrate)'
        in message
    )


def test_a_profile_that_is_not_there_is_named(tmp_path) -> None:
    raw = seed()
    raw["compose"]["overrides"] = ["docker-compose.gone.yml"]
    assert 'compose.overrides[0] "docker-compose.gone.yml" does not exist' in _untrue(
        project(tmp_path, raw)
    )


def test_a_restated_command_must_be_the_profile_s(tmp_path) -> None:
    raw = seed()
    unit(raw, "migrate")["command"] = ["terp", "migrate", "upgrade"]
    assert (
        "units[1].command restates ['terp', 'migrate', 'upgrade'], and docker-compose.prod.yml runs terp migrate upgrade --app-root /srv/app"
        in _untrue(project(tmp_path, raw))
    )


def test_a_command_restated_from_a_shell_form_profile_compares_as_a_list(tmp_path) -> None:
    raw = seed()
    unit(raw, "migrate")["command"] = ["terp", "migrate", "upgrade", "--app-root", "/srv/app"]
    migrate = dict(
        profile()["services"]["migrate"], command="terp migrate upgrade --app-root /srv/app"
    )
    _true(project(tmp_path, raw, profile(migrate=migrate)))


def test_a_command_for_a_service_that_runs_its_image_default_is_a_lie(tmp_path) -> None:
    raw = seed()
    unit(raw, "web")["command"] = ["nginx", "-g", "daemon off;"]
    assert "runs the image's own command for web" in _untrue(project(tmp_path, raw))


def test_a_restated_start_order_must_be_the_profile_s_among_declared_units(tmp_path) -> None:
    raw = seed()
    unit(raw, "api")["dependsOn"] = ["db"]
    assert (
        "units[2].dependsOn restates ['db'], and docker-compose.prod.yml starts api after db, migrate"
        in _untrue(project(tmp_path, raw))
    )


def test_an_undeclared_dependency_is_not_part_of_the_restatement(tmp_path) -> None:
    """The order is restricted to declared units: a cache nobody declared is not a lie."""
    api = copy.deepcopy(profile()["services"]["api"])
    api["depends_on"]["cache"] = {"condition": "service_started"}
    _true(project(tmp_path, seed(), profile(api=api, cache={"image": "memcached:1"})))


def test_an_env_name_the_profile_never_passes_is_a_lie(tmp_path) -> None:
    raw = seed()
    unit(raw, "api")["env"] = ["SOME_API_BASE_URL"]
    assert (
        "units[2].env[0] SOME_API_BASE_URL is never passed to api by docker-compose.prod.yml"
        in _untrue(project(tmp_path, raw))
    )


def test_an_env_name_arrives_through_its_environment_block(tmp_path) -> None:
    raw = seed()
    unit(raw, "api")["env"] = ["SECRET_KEY"]
    _true(project(tmp_path, raw))


def test_an_env_name_arrives_through_the_file_the_manifest_renders(tmp_path) -> None:
    raw = seed()
    unit(raw, "api")["env"] = ["SOME_API_BASE_URL"]
    manifest = {"type": "object", "properties": {"SOME_API_BASE_URL": {"type": "string"}}}
    _true(project(tmp_path, raw, manifest=manifest))


def test_a_name_scoped_to_another_service_does_not_reach_this_one(tmp_path) -> None:
    raw = seed()
    unit(raw, "api")["env"] = ["SOME_API_BASE_URL"]
    manifest = {
        "type": "object",
        "properties": {"SOME_API_BASE_URL": {"type": "string", "services": ["worker"]}},
    }
    assert "is never passed to api" in _untrue(project(tmp_path, raw, manifest=manifest))


@pytest.mark.parametrize(
    "declaration",
    [
        {"type": "string"},
        {"services": ["worker"]},
        {"services": ["worker", "api"]},
        {"services": []},
        {"services": "worker"},
        {"services": ["Not A Service", "api"]},
        "not a declaration",
    ],
)
def test_the_harness_routes_a_variable_exactly_as_the_renderer_does(declaration) -> None:
    """The harness cannot import the CLI, so it states the routing rule a second time."""
    assert arch_rendered_files(declaration) == cli_rendered_files(declaration)


@pytest.mark.parametrize(
    "image",
    [
        "postgres:17-alpine",
        f"registry.example.invalid/library/postgres@{POSTGRES.image.split('@')[1]}",
        "postgres@sha256:" + "0" * 64,
        f"postgres:17-alpine@{POSTGRES.image.split('@')[1]}",
        None,
    ],
    ids=["tag-only", "foreign-registry", "other-digest", "tag-beside-the-digest", "no-image"],
)
def test_a_kind_unit_runs_exactly_the_table_image(tmp_path, image) -> None:
    db = {"volumes": ["db-data:/var/lib/postgresql/data"]}
    if image is not None:
        db["image"] = image
    message = _untrue(project(tmp_path, seed(), profile(db=db)))
    assert (
        f"units[0].kind postgres 17: service db runs {image or 'no image'}, and the datastore table pins {POSTGRES.image}"
        in message
    )


def test_the_table_image_reads_the_same_in_its_long_form(tmp_path) -> None:
    db = {"image": f"docker.io/library/{POSTGRES.image}", "volumes": ["db-data:/x"]}
    _true(project(tmp_path, seed(), profile(db=db)))


def test_a_unit_without_kind_must_be_built_from_the_checkout(tmp_path) -> None:
    web = dict(profile()["services"]["web"])
    del web["build"]
    web["image"] = "nginx:1.29"
    message = _untrue(project(tmp_path, seed(), profile(web=web)))
    assert (
        'units[3].id "web" runs nginx:1.29, which no service of docker-compose.prod.yml builds from the checkout'
        in message
    )


def test_a_declared_volume_that_is_not_a_named_volume_backs_up_nothing(tmp_path) -> None:
    raw = seed()
    raw["volumes"] = [{"id": "files-data", "backup": {"every": "P1D", "keep": "P30D"}}]
    assert (
        'volumes[0].id "files-data" is not a named volume of docker-compose.prod.yml (allowed: a named volume of the profile: db-data)'
        in _untrue(project(tmp_path, raw))
    )


def test_a_declared_volume_nothing_mounts_backs_up_nothing(tmp_path) -> None:
    raw = seed()
    raw["volumes"] = [{"id": "files-data"}]
    compose = profile()
    compose["volumes"]["files-data"] = None
    assert "is mounted by no service" in _untrue(project(tmp_path, raw, compose))


def test_a_volume_a_stateful_unit_already_covers_is_not_declared_twice(tmp_path) -> None:
    raw = seed()
    raw["volumes"] = [{"id": "db-data", "backup": {"every": "PT1H", "keep": "P1D"}}]
    assert "is mounted only by declared stateful units (db)" in _untrue(project(tmp_path, raw))


def test_a_files_volume_the_api_mounts_is_declared_with_its_own_policy(tmp_path) -> None:
    raw = seed()
    raw["volumes"] = [{"id": "files-data", "backup": {"every": "P1D", "keep": "P30D"}}]
    api = copy.deepcopy(profile()["services"]["api"])
    api["volumes"] = [{"type": "volume", "source": "files-data", "target": "/srv/var/files"}]
    compose = profile(api=api)
    compose["volumes"]["files-data"] = None
    _true(project(tmp_path, raw, compose))


_EXTERNAL_DB_OVERRIDE = """\
services:
  db: !reset null
  migrate:
    depends_on: !reset {}
  api:
    depends_on: !override
      migrate:
        condition: service_completed_successfully
"""


def _external(raw: dict) -> dict:
    raw["units"] = [entry for entry in raw["units"] if entry["id"] != "db"]
    raw["externalDatabase"] = {"backup": "client"}
    unit(raw, "migrate")["dependsOn"] = []
    unit(raw, "api")["dependsOn"] = ["migrate"]
    return raw


def test_an_external_database_beside_a_profile_that_still_runs_one_is_refused(tmp_path) -> None:
    message = _untrue(project(tmp_path, _external(seed())))
    assert (
        "externalDatabase is declared, and docker-compose.prod.yml still runs a database service (db)"
        in message
    )
    assert (
        "name the override that removes it in compose.overrides, or drop externalDatabase"
        in message
    )


def test_a_database_by_tag_still_runs_a_database(tmp_path) -> None:
    db = {"image": "postgres:17-alpine"}
    assert "still runs a database service (db)" in _untrue(
        project(tmp_path, _external(seed()), profile(db=db))
    )


def test_a_database_behind_a_profile_switch_is_not_run_by_default(tmp_path) -> None:
    db = {"image": POSTGRES.image, "profiles": ["bundled-db"]}
    _true(project(tmp_path, _external(seed()), profile(db=db)))


def test_an_external_database_with_the_override_that_removes_db_passes(tmp_path) -> None:
    """The template's documented route: the base file, plus an override dropping `db`.

    The base file's `db-data` stays declared and mounted by nothing; that is never red.
    """
    raw = _external(seed())
    raw["compose"]["overrides"] = ["docker-compose.external-db.yml"]
    _true(project(tmp_path, raw, files={"docker-compose.external-db.yml": _EXTERNAL_DB_OVERRIDE}))


def test_a_field_read_by_role_under_an_unknown_role_has_no_reader(tmp_path) -> None:
    """ADR 0110 decision 3's boundary, kept: the field is never read, so it is a lie."""
    raw = seed()
    unit(raw, "api")["role"] = "backend"
    message = _untrue(project(tmp_path, raw))
    assert (
        'units[2].healthPath is declared under role "backend", which no reader resolves' in message
    )
    assert 'units[2].livenessPath is declared under role "backend"' in message


# --- never red -------------------------------------------------------------


def test_a_service_nobody_declared_is_nobody_s_business(tmp_path) -> None:
    compose = profile(
        worker={"image": "app-backend-prod", "command": ["terp", "jobs", "worker"]},
        scanner={"image": "vendor.example.invalid/scanner:latest"},
        cache={"image": "redis:7-alpine"},
    )
    _true(project(tmp_path, seed(), compose))


def test_no_frontend_and_three_apis_are_shapes_not_defects(tmp_path) -> None:
    raw = seed()
    raw["units"] = [entry for entry in raw["units"] if entry["id"] != "web"]
    for name in ("admin-api", "public-api"):
        raw["units"].append(
            {"id": name, "role": "api", "healthPath": "/health/ready", "dependsOn": ["db"]}
        )
    apis = {
        name: {"image": "app-backend-prod", "depends_on": ["db"]}
        for name in ("admin-api", "public-api")
    }
    _true(project(tmp_path, raw, profile(web=None, **apis)))


def test_an_unknown_role_that_carries_nothing_read_by_role_is_information(tmp_path) -> None:
    raw = seed()
    raw["units"].append({"id": "relay", "role": "message-bus", "dependsOn": ["db"]})
    _true(
        project(tmp_path, raw, profile(relay={"image": "app-backend-prod", "depends_on": ["db"]}))
    )


def test_a_stateful_unit_without_a_backup_and_many_instances_are_allowed(tmp_path) -> None:
    raw = seed()
    del unit(raw, "db")["backup"]
    unit(raw, "api")["instances"] = "many"
    raw["sizes"] = {"small": {"cpu": 0.5, "memoryMiB": 512}}
    unit(raw, "api")["size"] = "small"
    _true(project(tmp_path, raw))


def test_an_unreadable_declaration_is_the_readable_rule_s_alone(tmp_path) -> None:
    """A reader stops at the first: the truth rule says nothing about a broken file."""
    assert check_deployment_declaration_tells_the_truth(project(tmp_path, "{ nope")) == []
    unmanaged = {"unmanaged": True, "reason": "a platform team deploys it"}
    assert check_deployment_declaration_tells_the_truth(project(tmp_path, unmanaged)) == []


# --- the profile, merged the way compose merges it -------------------------


def _resolved(root: pathlib.Path) -> dict:
    declared, findings = readable(root)
    assert isinstance(declared, Declaration), findings
    merged, findings = resolve_profile(root, declared)
    assert findings == []
    return merged


def test_overrides_merge_the_way_compose_merges_them(tmp_path) -> None:
    raw = seed()
    raw["compose"]["overrides"] = ["one.yml", "two.yml"]
    one = (
        "services:\n"
        "  api:\n"
        "    environment: [FEATURE=on]\n"
        "    command: [uvicorn, app.main:app]\n"
        "    labels: !override {tier: edge}\n"
        "    volumes: [files:/srv/var/files]\n"
    )
    two = "services:\n  api:\n    command: [uvicorn, app.main:build]\n    secrets: !reset null\n"
    api = _resolved(project(tmp_path, raw, files={"one.yml": one, "two.yml": two}))["services"][
        "api"
    ]
    assert api["environment"] == {
        "SECRET_KEY": "${SECRET_KEY:?}",
        "ENVIRONMENT": "production",
        "FEATURE": "on",
    }
    assert api["command"] == ["uvicorn", "app.main:build"], "a command is replaced, never appended"
    assert api["labels"] == {"tier": "edge"}
    assert api["volumes"] == ["files:/srv/var/files"]
    assert "secrets" not in api


def test_a_reset_or_override_in_the_base_file_is_plain_data(tmp_path) -> None:
    compose = (
        "services:\n  db: !override {image: x}\n  gone: !reset null\n  tagged: !override [a]\n"
    )
    assert _resolved(project(tmp_path, seed(), compose))["services"] == {
        "db": {"image": "x"},
        "tagged": ["a"],
    }
    scalar = project(tmp_path / "scalar", seed(), "services: !override plain\n")
    assert _resolved(scalar) == {"services": "plain"}


def test_a_list_merges_into_a_list_and_the_rest_is_replaced(tmp_path) -> None:
    raw = seed()
    raw["compose"]["overrides"] = ["more.yml"]
    more = "services:\n  api:\n    env_file: [.extra.env]\n    image: app-backend-prod\n"
    api = _resolved(project(tmp_path, raw, files={"more.yml": more}))["services"]["api"]
    assert api["env_file"] == [{"path": ".app.env", "required": False}, ".extra.env"]


def test_an_unreadable_profile_is_refused_rather_than_assumed_empty(tmp_path) -> None:
    assert "compose.file docker-compose.prod.yml is not readable YAML" in _untrue(
        project(tmp_path, seed(), "services: [unclosed")
    )


def test_a_profile_that_is_not_a_mapping_is_refused(tmp_path) -> None:
    assert "is not a compose file: it holds no mapping" in _untrue(
        project(tmp_path, seed(), "- a\n- b\n")
    )


def test_a_profile_with_no_services_declares_none_of_the_units(tmp_path) -> None:
    assert "(allowed: a service of the profile: none)" in _untrue(
        project(tmp_path, seed(), "volumes: {}\n")
    )


# --- the datastore table a case resolves against --------------------------


def test_the_rule_resolves_kinds_against_the_table_it_is_given(tmp_path) -> None:
    other = "postgres@sha256:" + "5e" * 32
    root = project(tmp_path, seed(), profile(db={"image": other, "volumes": ["db-data:/x"]}))
    assert check_deployment_declaration_tells_the_truth(root), (
        "the published table pins another digest"
    )
    table = tmp_path / "datastore-table.json"
    table.write_text(
        json.dumps({"kinds": {"postgres": {"role": "database", "versions": {"17": other}}}}),
        encoding="utf-8",
    )
    assert check_deployment_declaration_tells_the_truth(root, datastore_table=table) == []
    given = DatastoreTable((Datastore("postgres", "17", "database", other),))
    assert check_deployment_declaration_tells_the_truth(root, datastore_table=given) == []
    assert check_deployment_declaration_tells_the_truth(
        root, datastore_table=tmp_path / "absent.json"
    ), "a table that is not there is the published one"


# --- the shipped declarations ---------------------------------------------


def test_the_example_app_declares_a_deployment_that_is_true(monkeypatch) -> None:
    """Against the real app: its four module histories and its served health routes."""
    monkeypatch.setattr(deployment_app, "APP_REF", "app.main:build")
    example = REPO_ROOT / "apps" / "example"
    assert check_deployment_declaration_tells_the_truth(example) == []
    code, output = run_deployment_check(example)
    assert code == 0, output
    assert "4 declared unit(s) match docker-compose.prod.yml" in output
    declared, _ = readable(example)
    assert declared.units[2].migrations == ("journals", "notes", "projects", "tasks")


def test_the_reference_app_declaration_holds_against_its_profile(tmp_path) -> None:
    """The overlay's own files; the CI lane runs the whole check on a render."""
    overlay = REPO_ROOT / "apps" / "reference" / "overlay"
    root = project(
        tmp_path,
        (overlay / "deployment.json").read_text(encoding="utf-8"),
        (overlay / "docker-compose.prod.yml").read_text(encoding="utf-8"),
        manifest=json.loads((overlay / "environment.schema.json").read_text(encoding="utf-8")),
        files={"app/modules/notices/__init__.py": ""},
    )
    declared, findings = readable(root)
    assert findings == [] and isinstance(declared, Declaration)
    assert {"worker", "scheduler", "monitor"} <= {entry.id for entry in declared.units}
    assert [volume.id for volume in declared.volumes] == ["files-data"]
    _true(root)
    assert yaml.safe_load((overlay / "docker-compose.prod.yml").read_text(encoding="utf-8"))
