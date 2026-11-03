"""The app part of ``terp verify --only deployment``: the declaration against the app.

Two facts only the composed app can settle -- which migration histories exist and which
paths the API serves -- turn red when the declaration names one the app does not have.
Where no app imports, the whole part is skipped by name, never passed in silence. Beside
them, notes on what the app's own declarations say it uses that the deploy declaration
leaves unstated; a note never turns the check red.
"""

from __future__ import annotations

import copy
import pathlib
import sys

import pytest

from terp.arch.deployment import Datastore, DatastoreTable, published_table
from terp.cli import deployment_app
from terp.cli.deployment_check import run_deployment_check
from tests.architecture.deployment_fixtures import (
    PROBE_REF,
    profile,
    project,
    seed,
    template_profile,
    unit,
)


@pytest.fixture(autouse=True)
def _probe_app(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(deployment_app, "APP_REF", PROBE_REF)
    monkeypatch.setattr(sys, "path", list(sys.path))


def _run(root: pathlib.Path) -> tuple[int, str]:
    return run_deployment_check(root)


# --- red: what only the app can contradict --------------------------------


def test_a_migration_label_nobody_owns_is_a_lie(tmp_path) -> None:
    raw = seed()
    unit(raw, "api")["migrations"] = ["notices", "ledger"]
    root = project(tmp_path, raw, files={"app/modules/notices/__init__.py": ""})
    code, output = _run(root)
    assert code == 1
    assert 'units[2].migrations[1] "ledger" is a history no installed package and no app module owns' in output
    assert "notices" in output.split("allowed:", 1)[1], "the owned labels are named"
    assert "units[2].migrations[0]" not in output, "an app module's label is its module name"


def test_a_capability_s_history_is_owned_by_its_entry_point(tmp_path) -> None:
    raw = seed()
    unit(raw, "api")["migrations"] = ["audit"]
    assert _run(project(tmp_path, raw))[0] == 0


def test_a_history_that_cannot_be_discovered_is_named(tmp_path, monkeypatch) -> None:
    import terp.core
    from terp.core import MigrationDiscoveryError

    def _refuse(*args, **kwargs):
        raise MigrationDiscoveryError("migration label 'notes' is declared twice")

    monkeypatch.setattr(terp.core, "resolve_all_migration_trees", _refuse)
    code, output = _run(project(tmp_path, seed()))
    assert code == 1
    assert "the app's migration histories cannot be discovered: migration label 'notes' is declared twice" in output


def test_a_health_path_the_api_does_not_serve_is_a_lie(tmp_path) -> None:
    raw = seed()
    unit(raw, "api")["healthPath"] = "/internal/ready"
    code, output = _run(project(tmp_path, raw))
    assert code == 1
    assert 'units[2].healthPath is "/internal/ready", which' in output and "does not serve" in output


def test_a_health_path_another_role_answers_is_not_the_app_s_to_judge(tmp_path) -> None:
    """A web tier answers its own paths; the app's routes say nothing about them."""
    raw = seed()
    unit(raw, "web")["healthPath"] = "/"
    assert _run(project(tmp_path, raw))[0] == 0


def test_no_importable_app_skips_the_app_part_by_name(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(deployment_app, "APP_REF", "no.such.module:build")
    raw = seed()
    unit(raw, "api")["migrations"] = ["ledger"]
    code, output = _run(project(tmp_path, raw))
    assert code == 0, "skipped, never failed"
    assert output.startswith("note: ")
    assert "no importable no.such.module:build" in output and "is skipped" in output


# --- notes, never red ------------------------------------------------------


_FILES_APP = '[project]\ndependencies = ["terp-cap-files==1", "terp_core==1"]\n'


def test_a_files_volume_with_no_backup_policy_is_noted(tmp_path) -> None:
    api = copy.deepcopy(profile()["services"]["api"])
    api["volumes"] = ["files-data:/srv/var/files"]
    compose = profile(api=api)
    compose["volumes"]["files-data"] = None
    code, output = _run(project(tmp_path, seed(), compose, files={"pyproject.toml": _FILES_APP}))
    assert code == 0 and output.startswith("note: ")
    assert 'volume files-data holds the files the app stores (api) and has no backup policy here' in output


def test_a_declared_files_volume_is_not_noted(tmp_path) -> None:
    raw = seed()
    raw["volumes"] = [{"id": "files-data", "backup": {"every": "P1D", "keep": "P30D"}}]
    api = copy.deepcopy(profile()["services"]["api"])
    api["volumes"] = ["files-data:/srv/var/files"]
    compose = profile(api=api)
    compose["volumes"]["files-data"] = None
    code, output = _run(project(tmp_path, raw, compose, files={"pyproject.toml": _FILES_APP}))
    assert code == 0 and not output.startswith("note: "), output


def test_file_storage_with_no_volume_at_its_root_is_noted(tmp_path) -> None:
    code, output = _run(project(tmp_path, seed(), files={"pyproject.toml": _FILES_APP}))
    assert code == 0
    assert "no declared unit mounts a named volume at its storage root (var/files)" in output


def test_the_template_rendered_with_files_leaves_nothing_to_note(tmp_path) -> None:
    """A render with use_files: the seed declares the volume its profile mounts at the
    storage root, with a backup policy. Without that answer's blocks, which is what such a
    render was before, its files lived in the api container, and the note said so."""
    with_files = project(
        tmp_path / "files",
        seed(use_files=True),
        template_profile(use_files=True),
        files={"pyproject.toml": _FILES_APP},
    )
    code, output = _run(with_files)
    assert code == 0 and "note: " not in output, output
    before = project(
        tmp_path / "before", seed(), template_profile(), files={"pyproject.toml": _FILES_APP}
    )
    code, output = _run(before)
    assert code == 0 and "so stored files live in a container's writable layer" in output


def test_a_volume_only_stateful_units_mount_is_covered_by_their_policy(tmp_path) -> None:
    db = {"image": published_table().entries[0].image, "volumes": ["db-data:/srv/var/files"]}
    code, output = _run(project(tmp_path, seed(), profile(db=db), files={"pyproject.toml": _FILES_APP}))
    assert code == 0
    assert "no declared unit mounts a named volume" in output, "a datastore is not the app's file store"


def test_a_companion_root_no_unit_runs_is_noted(tmp_path) -> None:
    pyproject = '[tool.terp.arch]\ncompanions = ["monitor", "relay"]\n'
    raw = seed()
    raw["units"].append({"id": "monitor", "role": "monitor", "command": ["python", "-m", "monitor.watch"]})
    compose = profile(monitor={"image": "app-backend-prod", "command": ["python", "-m", "monitor.watch"]})
    code, output = _run(project(tmp_path, raw, compose, files={"pyproject.toml": pyproject}))
    assert code == 0
    assert "companion root relay ([tool.terp.arch] companions) is run by no declared unit" in output
    assert "companion root monitor" not in output


def test_an_undeclared_database_and_a_capability_s_store_are_noted(tmp_path, monkeypatch) -> None:
    redis = "redis@sha256:" + "7d" * 32
    table = DatastoreTable(
        (*published_table().entries, Datastore("redis", "7", "store", redis))
    )
    monkeypatch.setattr("terp.cli.deployment_check.published_table", lambda: table)
    raw = seed()
    raw["units"] = [entry for entry in raw["units"] if entry["id"] != "db"]
    unit(raw, "migrate")["dependsOn"] = []
    unit(raw, "api")["dependsOn"] = ["migrate"]
    pyproject = '[project]\ndependencies = ["terp-cap-redis==1"]\n'
    code, output = _run(project(tmp_path, raw, files={"pyproject.toml": pyproject}))
    assert code == 0
    assert "the app uses postgres (the app's own database), and no declared unit is kind postgres and there is no externalDatabase" in output
    assert "the app uses redis (terp-cap-redis), and no declared unit is kind redis" in output


def test_a_capability_s_store_the_table_does_not_carry_is_noted_as_such(tmp_path) -> None:
    pyproject = '[project]\ndependencies = ["terp-cap-redis>=1", "  ", "not a requirement!"]\n'
    code, output = _run(project(tmp_path, seed(), files={"pyproject.toml": pyproject}))
    assert code == 0
    assert "the app uses redis (terp-cap-redis), which this release's datastore table does not carry" in output


def test_an_external_database_needs_no_database_unit(tmp_path) -> None:
    raw = seed()
    raw["units"] = [entry for entry in raw["units"] if entry["id"] != "db"]
    raw["externalDatabase"] = {"backup": "client"}
    unit(raw, "migrate")["dependsOn"] = []
    unit(raw, "api")["dependsOn"] = ["migrate"]
    compose = profile(db={"image": published_table().entries[0].image, "profiles": ["bundled"]})
    code, output = _run(project(tmp_path, raw, compose))
    assert code == 0 and "postgres" not in output, output


def test_an_unreadable_pyproject_reads_as_one_that_declares_nothing(tmp_path) -> None:
    code, output = _run(project(tmp_path, seed(), files={"pyproject.toml": "[project\n"}))
    assert (code, output) == (0, "deployment.json: 4 declared unit(s) match docker-compose.prod.yml (build: own)")


# --- the runner's output ---------------------------------------------------


def test_the_runner_says_what_it_did_in_every_state(tmp_path) -> None:
    assert _run(project(tmp_path / "absent", None)) == (0, "no deployment.json - deployment not declared")
    code, output = _run(project(tmp_path / "unmanaged", {"unmanaged": True, "reason": "a platform team deploys it"}))
    assert code == 0 and "unmanaged: a platform team deploys it" in output
    code, output = _run(project(tmp_path / "unreadable", "{ nope"))
    assert code == 1 and output.startswith("deployment.json cannot be read by this toolchain.")
    raw = seed()
    unit(raw, "api")["env"] = ["SOME_API_BASE_URL"]
    code, output = _run(project(tmp_path / "untrue", raw, files={"pyproject.toml": _FILES_APP}))
    assert code == 1 and output.startswith("The deployment this app declares does not match")
    assert "\nAlso noted (never red):\n" in output
    code, output = _run(project(tmp_path / "missing-profile", seed(), "services: [\n"))
    assert code == 1 and "is not readable YAML" in output and "Also noted" not in output
