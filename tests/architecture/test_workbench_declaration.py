"""The workbench declaration checks truth-about-self, never conformance.

Most of these tests assert that something is **allowed**. That is deliberate:
the risk this check carries is not that it misses a broken declaration, it is
that it quietly becomes a gate on what kind of application people may build.
Every "never red" case below is a shape a real app can legitimately have.
"""

from __future__ import annotations

import json
import pathlib

import yaml

from terp.cli.workbench import (
    WORKBENCH_FILE,
    Declaration,
    audit,
    load,
    run_workbench_check,
)

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


def _app(tmp_path: pathlib.Path, declaration: dict | None, compose: dict) -> pathlib.Path:
    root = tmp_path / "app"
    root.mkdir(exist_ok=True)
    if declaration is not None:
        (root / WORKBENCH_FILE).write_text(json.dumps(declaration), encoding="utf-8")
    (root / "docker-compose.yml").write_text(yaml.safe_dump(compose), encoding="utf-8")
    return root


def _standard(**services: dict) -> dict:
    base = {
        "web": {"ports": ["${WEB_PORT:-5173}:5173"]},
        "api": {"ports": ["${API_PORT:-8000}:8000"]},
    }
    base.update(services)
    return {"services": base}


def _declaring(*entries: dict) -> dict:
    return {"schemaVersion": 1, "services": list(entries)}


# --- what must never be red ------------------------------------------------


def test_a_service_nobody_declared_is_nobody_s_business(tmp_path) -> None:
    """Redis, a worker, a virus scanner — the app's own additions are fine."""
    root = _app(
        tmp_path,
        _declaring({"role": "web", "service": "web", "hostPortEnv": "WEB_PORT"}),
        _standard(
            redis={"image": "redis:7"},
            clamav={"image": "clamav/clamav"},
            worker={"command": ["python", "-m", "worker"]},
        ),
    )

    assert run_workbench_check(root)[0] == 0


def test_an_app_with_no_frontend_is_not_a_defect(tmp_path) -> None:
    root = _app(
        tmp_path,
        _declaring({"role": "api", "service": "api", "hostPortEnv": "API_PORT"}),
        {"services": {"api": {"ports": ["${API_PORT:-8000}:8000"]}}},
    )

    assert run_workbench_check(root)[0] == 0


def test_several_services_may_share_a_role(tmp_path) -> None:
    root = _app(
        tmp_path,
        _declaring(
            {"role": "api", "service": "api", "hostPortEnv": "API_PORT"},
            {"role": "api", "service": "api2", "hostPortEnv": "API2_PORT"},
            {"role": "web", "service": "web", "hostPortEnv": "WEB_PORT"},
        ),
        _standard(api2={"ports": ["${API2_PORT:-8001}:8000"]}),
    )

    assert run_workbench_check(root)[0] == 0


def test_a_role_this_toolchain_does_not_know_is_information_not_an_error(tmp_path) -> None:
    """Adding a role must not break every app that already shipped one."""
    root = _app(
        tmp_path,
        _declaring({"role": "message-bus", "service": "nats"}),
        _standard(nats={"image": "nats:2"}),
    )

    assert run_workbench_check(root)[0] == 0


def test_an_app_with_no_declaration_at_all_passes(tmp_path) -> None:
    """Upgrading the toolchain must never redden a gate over an unadopted file."""
    root = _app(tmp_path, None, _standard())

    code, output = run_workbench_check(root)

    assert code == 0
    assert "not declared" in output


def test_a_service_that_publishes_nothing_is_a_stale_line_not_a_failure(tmp_path) -> None:
    root = _app(
        tmp_path,
        _declaring({"role": "api", "service": "api", "hostPortEnv": "API_PORT"}),
        {"services": {"api": {}}},
    )

    assert run_workbench_check(root)[0] == 0


# --- what must be red ------------------------------------------------------


def test_a_role_pointing_at_a_service_that_does_not_exist_is_a_lie(tmp_path) -> None:
    root = _app(
        tmp_path,
        _declaring({"role": "web", "service": "frontend"}),
        _standard(),
    )

    code, output = run_workbench_check(root)

    assert code == 1
    assert "frontend" in output


def test_a_hard_coded_host_port_breaks_running_two_projects_at_once(tmp_path) -> None:
    root = _app(
        tmp_path,
        _declaring({"role": "web", "service": "web", "hostPortEnv": "WEB_PORT"}),
        {"services": {"web": {"ports": ["5173:5173"]}}},
    )

    code, output = run_workbench_check(root)

    assert code == 1
    assert "WEB_PORT" in output
    assert "two projects" in output


def test_the_long_form_port_mapping_is_read_too(tmp_path) -> None:
    root = _app(
        tmp_path,
        _declaring({"role": "web", "service": "web", "hostPortEnv": "WEB_PORT"}),
        {"services": {"web": {"ports": [{"published": 5173, "target": 5173}]}}},
    )

    assert run_workbench_check(root)[0] == 1


def test_an_unreadable_declaration_fails_rather_than_being_ignored(tmp_path) -> None:
    root = tmp_path / "app"
    root.mkdir()
    (root / WORKBENCH_FILE).write_text("{ not json", encoding="utf-8")

    assert run_workbench_check(root)[0] == 1


def test_a_version_this_toolchain_cannot_read_says_so(tmp_path) -> None:
    root = _app(tmp_path, {"schemaVersion": 99, "services": []}, _standard())

    code, output = run_workbench_check(root)

    assert code == 1
    assert "99" in output


# --- the escape ------------------------------------------------------------


def test_unmanaged_turns_the_check_off(tmp_path) -> None:
    root = _app(
        tmp_path,
        {"unmanaged": True, "reason": "this app's dev loop is a devcontainer"},
        {"services": {}},
    )

    code, output = run_workbench_check(root)

    assert code == 0
    assert "unmanaged" in output
    assert "devcontainer" in output


def test_unmanaged_without_a_reason_is_refused(tmp_path) -> None:
    """An escape nobody can review is not an escape, it is a hole."""
    root = _app(tmp_path, {"unmanaged": True}, {"services": {}})

    code, output = run_workbench_check(root)

    assert code == 1
    assert "reason" in output


def test_an_unmanaged_app_needs_no_compose_file_at_all(tmp_path) -> None:
    root = tmp_path / "app"
    root.mkdir()
    (root / WORKBENCH_FILE).write_text(
        json.dumps({"unmanaged": True, "reason": "no Docker here"}), encoding="utf-8"
    )

    assert run_workbench_check(root)[0] == 0


# --- the shipped artefacts -------------------------------------------------


def test_the_example_app_declares_a_topology_that_matches_its_compose() -> None:
    assert run_workbench_check(_REPO_ROOT / "apps" / "example")[0] == 0


def test_the_template_seeds_a_declaration_the_app_then_owns() -> None:
    """Overwriting it on upgrade would make it describe the template, not the app."""
    seeded = _REPO_ROOT / "template" / "project" / WORKBENCH_FILE
    copier = yaml.safe_load(
        (_REPO_ROOT / "template" / "copier.yml").read_text(encoding="utf-8")
    )

    assert seeded.is_file()
    assert WORKBENCH_FILE in copier["_skip_if_exists"]


def test_the_declaration_never_TARGETS_the_production_profile() -> None:
    """Dev only. The freedom real deployments need lives in the prod profile.

    Asserted on the parsed value, not on the text: the seeded file mentions the
    production profile precisely in order to forbid it, and a substring test
    would fail on the sentence that states the rule.
    """
    seeded = json.loads(
        (_REPO_ROOT / "template" / "project" / WORKBENCH_FILE).read_text(
            encoding="utf-8"
        )
    )

    assert "prod" not in seeded["compose"]["file"]


def test_a_declaration_pointing_at_the_production_profile_finds_nothing_to_check(
    tmp_path,
) -> None:
    """The check must not become a gate on how anyone deploys.

    Nothing here reads the production profile, so aiming a declaration at one
    finds no compose file to audit rather than quietly starting to police it.
    """
    root = tmp_path / "app"
    root.mkdir()
    (root / WORKBENCH_FILE).write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "compose": {"file": "docker-compose.prod.yml"},
                "services": [{"role": "api", "service": "api"}],
            }
        ),
        encoding="utf-8",
    )
    (root / "docker-compose.prod.yml").write_text(
        yaml.safe_dump({"services": {"api": {"ports": ["8000:8000"]}}}),
        encoding="utf-8",
    )

    code, output = run_workbench_check(root)

    # It reads whatever file it is pointed at — but the SHIPPED declaration
    # never points there, and no rule in this module treats a prod profile
    # specially. The guarantee is the absence of such a rule.
    assert code == 0
    assert "prod" not in output.replace("docker-compose.prod.yml", "")


def test_audit_reads_a_declaration_without_touching_the_filesystem() -> None:
    findings = audit(
        Declaration(services=({"role": "web", "service": "missing"},)),
        {"services": {"web": {}}},
    )

    assert len(findings) == 1
    assert "missing" in findings[0].message


def test_load_returns_nothing_for_an_app_that_has_no_declaration(tmp_path) -> None:
    declared, defects = load(tmp_path)

    assert declared is None
    assert defects == []


# --- the fail-closed paths -------------------------------------------------
#
# Each of these is a way the declaration can be unusable. They matter because
# "cannot tell" must never read as "nothing wrong": a workbench that silently
# skipped a malformed declaration would run on assumptions nobody wrote down.


def test_a_declaration_that_is_not_an_object_is_refused(tmp_path) -> None:
    root = tmp_path / "app"
    root.mkdir()
    (root / WORKBENCH_FILE).write_text("[1, 2, 3]", encoding="utf-8")

    code, output = run_workbench_check(root)

    assert code == 1
    assert "JSON object" in output


def test_a_declaration_without_a_services_list_is_refused(tmp_path) -> None:
    root = _app(tmp_path, {"schemaVersion": 1, "services": "web"}, _standard())

    code, output = run_workbench_check(root)

    assert code == 1
    assert "services" in output


def test_an_entry_with_no_service_name_is_named_rather_than_skipped(tmp_path) -> None:
    root = _app(tmp_path, _declaring({"role": "web"}), _standard())

    code, output = run_workbench_check(root)

    assert code == 1
    assert "no" in output and "service" in output


def test_a_declaration_naming_a_compose_file_that_is_absent_is_refused(tmp_path) -> None:
    root = tmp_path / "app"
    root.mkdir()
    (root / WORKBENCH_FILE).write_text(
        json.dumps({"schemaVersion": 1, "compose": {"file": "gone.yml"}, "services": []}),
        encoding="utf-8",
    )

    code, output = run_workbench_check(root)

    assert code == 1
    assert "gone.yml" in output


def test_an_unparsable_compose_file_is_refused_rather_than_assumed_empty(tmp_path) -> None:
    root = tmp_path / "app"
    root.mkdir()
    (root / WORKBENCH_FILE).write_text(json.dumps(_declaring()), encoding="utf-8")
    (root / "docker-compose.yml").write_text("services: [unclosed", encoding="utf-8")

    code, output = run_workbench_check(root)

    assert code == 1
    assert "unreadable" in output


def test_a_compose_file_with_no_services_block_is_refused(tmp_path) -> None:
    findings = audit(Declaration(services=({"role": "web", "service": "web"},)), {})

    assert len(findings) == 1
    assert "no services" in findings[0].message
