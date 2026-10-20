"""``deployment.json`` is readable, or refused with the field and what is allowed (ADR 0184).

Most cases break the template's own seed in one way and assert the one message it earns,
naming the field and the values allowed there. The rest assert that something is
ALLOWED, and they matter as much: the risk this rule carries is not that it misses a
broken file but that it quietly becomes a gate on how people deploy.
"""

from __future__ import annotations

import copy
import json
import os
import pathlib

import pytest
import yaml

from terp.arch import check_deployment_declaration_is_readable
from terp.arch.deployment import (
    Declaration,
    Unmanaged,
    published_table,
    read,
    readable,
)
from tests.architecture.deployment_fixtures import profile, project, seed, unit


def _refused(raw: object) -> str:
    declared, findings = read(raw, published_table())
    assert declared is None and findings, "expected the reader to refuse this declaration"
    return "\n".join(f"{finding.message} {finding.remedy}" for finding in findings)


def _readable_messages(root: pathlib.Path) -> str:
    violations = check_deployment_declaration_is_readable(root)
    assert violations, "expected the readable rule to refuse this project"
    return "\n".join(violation.message for violation in violations)


# --- the four states -------------------------------------------------------


def test_an_app_without_a_declaration_is_undeclared_and_passes(tmp_path) -> None:
    """Upgrading the toolchain must never redden a gate over a file it has not adopted."""
    assert readable(project(tmp_path, None)) == (None, [])
    assert check_deployment_declaration_is_readable(project(tmp_path, None)) == []


def test_the_template_seed_is_readable(tmp_path) -> None:
    declared, findings = readable(project(tmp_path, seed()))
    assert findings == [] and isinstance(declared, Declaration)
    assert [entry.id for entry in declared.units] == ["db", "migrate", "api", "web"]
    assert declared.units[0].backup is not None and declared.units[0].stateful


def test_unmanaged_with_a_reason_is_the_one_way_out(tmp_path) -> None:
    raw = {"unmanaged": True, "reason": "deployed by a platform team's own pipeline"}
    declared, findings = readable(project(tmp_path, raw))
    assert findings == [] and declared == Unmanaged(
        reason="deployed by a platform team's own pipeline"
    )


def test_unmanaged_may_carry_its_schema_version_and_annotations() -> None:
    declared, findings = read(
        {"$comment": "why", "schemaVersion": 1, "unmanaged": True, "reason": "a reason"},
        published_table(),
    )
    assert findings == [] and isinstance(declared, Unmanaged)


@pytest.mark.parametrize(
    "raw", [{"unmanaged": True}, {"unmanaged": True, "reason": "   "}], ids=["no-reason", "blank"]
)
def test_unmanaged_without_a_reason_is_a_hole_not_an_escape(raw) -> None:
    assert "reason" in _refused(raw)


def test_unmanaged_false_is_not_a_state() -> None:
    message = _refused({"unmanaged": False, "reason": "x"})
    assert "unmanaged is false (allowed: true, or leave the key out)" in message


def test_unmanaged_beside_build_is_two_states_and_is_refused() -> None:
    message = _refused({"unmanaged": True, "reason": "x", "build": "own"})
    assert "unmanaged stands beside build: a file is in exactly one state" in message
    assert "is not a field of" not in message, "one message for one mistake"


def test_units_without_build_are_not_guessed_into_a_state() -> None:
    raw = seed()
    del raw["build"]
    assert "build is required when units are declared (allowed: generated, own)" in _refused(raw)


def test_generated_is_refused_by_name_until_a_generator_ships() -> None:
    raw = seed()
    raw["build"] = "generated"
    assert "this toolchain cannot honour generated; upgrade, or declare own" in _refused(raw)


# --- the file cannot be read ----------------------------------------------


def test_invalid_json_is_refused_rather_than_ignored(tmp_path) -> None:
    assert "deployment.json is not valid JSON" in _readable_messages(project(tmp_path, "{ nope"))


@pytest.mark.parametrize("raw", [[1, 2], "text", None], ids=["list", "string", "null"])
def test_a_declaration_that_is_not_an_object_is_refused(raw) -> None:
    assert "deployment.json must contain one JSON object" in _refused(raw)


@pytest.mark.parametrize("version", [2, "1", True])
def test_a_schema_version_this_toolchain_does_not_read_says_so(version) -> None:
    raw = seed()
    raw["schemaVersion"] = version
    message = _refused(raw)
    assert (
        f"schemaVersion is {json.dumps(version)}, which this toolchain does not read (allowed: 1)"
        in message
    )


def test_a_missing_schema_version_is_named() -> None:
    raw = seed()
    del raw["schemaVersion"]
    assert "schemaVersion is required (allowed: 1)" in _refused(raw)


def test_an_unknown_key_is_refused_because_a_typo_would_do_nothing() -> None:
    """A misspelt ``stateful`` is otherwise a backup policy that silently never runs."""
    raw = seed()
    unit(raw, "db")["statefull"] = True
    message = _refused(raw)
    assert "units[0].statefull is not a field of units[0]" in message
    assert "stateful" in message.split("allowed:", 1)[1], "the allowed fields are named"


def test_a_dollar_key_is_an_annotation_at_every_level() -> None:
    raw = seed()
    raw["compose"]["$comment"] = "the production profile"
    unit(raw, "api")["$comment"] = "the one the browser reaches through web"
    assert isinstance(read(raw, published_table())[0], Declaration)


def test_an_image_key_is_refused_so_a_declaration_cannot_name_a_registry() -> None:
    raw = seed()
    unit(raw, "api")["image"] = "registry.example.invalid/app:latest"
    message = _refused(raw)
    assert "units[2].image is not a field of a unit: there is no image key" in message
    assert "postgres 17" in message, "the remedy names what the table offers"


@pytest.mark.parametrize(
    ("where", "key"),
    [("top", "approvals"), ("unit", "publishers"), ("compose", "gatePolicy"), ("top", "access")],
)
def test_a_deploy_policy_key_is_refused_with_its_own_message(where, key) -> None:
    """Anyone who can commit to the app could lower a policy kept in this file."""
    raw = seed()
    target = {"top": raw, "unit": unit(raw, "api"), "compose": raw["compose"]}[where]
    target[key] = 2
    message = _refused(raw)
    assert (
        "is deploy policy: it belongs to the deploying tool's environment policy, not to this file"
        in message
    )
    assert "is not a field of" not in message, "one message for one mistake"


def test_a_deploy_policy_word_as_a_value_or_an_id_is_not_a_key() -> None:
    raw = seed()
    raw["$comment"] = "approvals and access live in the environment's policy"
    unit(raw, "web")["role"] = "approvals"
    unit(raw, "web")["id"] = "access"
    assert isinstance(read(raw, published_table())[0], Declaration)


def test_a_command_written_as_a_shell_string_is_refused() -> None:
    raw = seed()
    unit(raw, "migrate")["command"] = "terp migrate upgrade && echo done"
    assert "units[1].command is a shell string (allowed: an argument list of strings" in _refused(
        raw
    )


def test_shell_metacharacters_inside_an_argument_are_data() -> None:
    raw = seed()
    unit(raw, "migrate")["command"] = ["sh", "-c", "terp migrate upgrade && echo $HOME | tee /x"]
    assert isinstance(read(raw, published_table())[0], Declaration)


@pytest.mark.parametrize("hostile", ["migrate\nupgrade", "migrate\x1b[31m", "api\u0085"])
def test_a_control_character_is_refused_wherever_it_hides(hostile) -> None:
    raw = seed()
    unit(raw, "migrate")["command"] = ["terp", hostile]
    assert "units[1].command[1] carries a control character" in _refused(raw)


def test_a_trailing_newline_does_not_slip_past_a_pattern() -> None:
    """Python's ``$`` matches before a final newline; the schema's anchor does not."""
    raw = seed()
    unit(raw, "api")["id"] = "api\n"
    assert "units[2].id carries a control character (U+000A)" in _refused(raw)


def test_an_over_long_string_is_refused_with_its_cap() -> None:
    raw = seed()
    unit(raw, "api")["healthPath"] = "/" + "a" * 300
    assert "units[2].healthPath is 301 characters long (at most 256)" in _refused(raw)


def test_a_client_backup_is_valid_only_for_an_external_database() -> None:
    raw = seed()
    unit(raw, "db")["backup"] = "client"
    message = _refused(raw)
    assert 'units[0].backup is "client", which is valid only on externalDatabase' in message
    assert "must be an object" not in message, "one message for one mistake"


def test_a_backup_on_a_unit_that_holds_no_state_is_refused() -> None:
    raw = seed()
    unit(raw, "db")["stateful"] = False
    assert "units[0].stateful is false (allowed: true)" in _refused(raw)
    del unit(raw, "db")["stateful"]
    assert "units[0].stateful is required beside backup" in _refused(raw)


def test_a_kind_or_version_the_table_does_not_carry_names_the_table() -> None:
    raw = seed()
    unit(raw, "db")["kind"] = "mysql"
    assert (
        'units[0].kind is "mysql", which the datastore table does not carry (allowed: postgres)'
        in _refused(raw)
    )
    unit(raw, "db")["kind"] = "postgres"
    unit(raw, "db")["version"] = "15"
    assert (
        'units[0].version is "15" for kind postgres, which the datastore table does not carry (allowed: 17)'
        in _refused(raw)
    )
    del unit(raw, "db")["version"]
    assert "units[0].version is required beside kind" in _refused(raw)


def test_a_size_that_points_nowhere_states_nothing() -> None:
    raw = seed()
    unit(raw, "api")["size"] = "large"
    assert (
        'units[2].size is "large", which sizes does not declare (allowed: a key of sizes: none)'
        in _refused(raw)
    )
    raw["sizes"] = {"large": {"cpu": 1, "memoryMiB": 1024}}
    assert isinstance(read(raw, published_table())[0], Declaration)


def test_two_units_or_two_volumes_with_one_id_are_refused() -> None:
    raw = seed()
    raw["units"].append(copy.deepcopy(unit(raw, "web")))
    raw["volumes"] = [{"id": "files"}, {"id": "files"}]
    message = _refused(raw)
    assert 'units[4].id "web" is the id of an earlier entry' in message
    assert 'volumes[1].id "files" is the id of an earlier entry' in message


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        (lambda raw: raw.update(build="managed"), 'build is "managed" (allowed: generated, own)'),
        (
            lambda raw: raw.update(rollback={"strategy": "restore"}),
            'rollback.strategy is "restore" (allowed: redeploy-previous-release)',
        ),
        (
            lambda raw: unit(raw, "api").update(instances="two"),
            'units[2].instances is "two" (allowed: many, one)',
        ),
        (
            lambda raw: raw.update(externalDatabase={"backup": "nightly"}),
            'externalDatabase.backup is "nightly" (allowed: "client")',
        ),
        (lambda raw: raw.update(compose={}), "compose.file is required"),
        (
            lambda raw: raw["compose"].update(file="/etc/compose.yml"),
            'compose.file is "/etc/compose.yml", which does not match',
        ),
        (
            lambda raw: raw["compose"].update(overrides=["a.yml", "a.yml"]),
            'compose.overrides lists "a.yml" more than once',
        ),
        (lambda raw: raw.update(units=[]), "units has 0 item(s) (allowed: at least 1)"),
        (
            lambda raw: unit(raw, "api").update(id="API Server"),
            'units[2].id is "API Server", which does not match',
        ),
        (
            lambda raw: unit(raw, "api").update(role=None),
            "units[2].role must be a string, not null",
        ),
        (lambda raw: unit(raw, "api").pop("role"), "units[2].role is required"),
        (
            lambda raw: unit(raw, "api").update(env=["lower_case"]),
            'units[2].env[0] is "lower_case", which does not match',
        ),
        (
            lambda raw: unit(raw, "api").update(migrations="notes"),
            "units[2].migrations must be a list, not a string",
        ),
        (
            lambda raw: unit(raw, "api").update(dependsOn=["db", "db"]),
            'units[2].dependsOn lists "db" more than once',
        ),
        (
            lambda raw: unit(raw, "api").update(healthPath="health"),
            'units[2].healthPath is "health", which does not match',
        ),
        (
            lambda raw: unit(raw, "db").update(stateful="yes"),
            "units[0].stateful must be true or false, not a string",
        ),
        (
            lambda raw: unit(raw, "db")["backup"].update(every="daily"),
            'units[0].backup.every is "daily", which does not match',
        ),
        (lambda raw: unit(raw, "db")["backup"].pop("keep"), "units[0].backup.keep is required"),
        (
            lambda raw: raw.update(sizes={"small": {"cpu": 0, "memoryMiB": 512}}),
            "sizes.small.cpu is 0 (allowed: more than 0)",
        ),
        (
            lambda raw: raw.update(sizes={"small": {"cpu": 0.5, "memoryMiB": 0}}),
            "sizes.small.memoryMiB is 0 (allowed: at least 1)",
        ),
        (
            lambda raw: raw.update(sizes={"Small": {"cpu": 0.5, "memoryMiB": 512}}),
            "sizes.Small is not a field of sizes (allowed: a $-prefixed annotation, a key matching",
        ),
        (
            lambda raw: raw.update(volumes=[{"backup": {"every": "P1D", "keep": "P7D"}}]),
            "volumes[0].id is required",
        ),
        (
            lambda raw: unit(raw, "migrate").update(command=[]),
            "units[1].command has 0 item(s) (allowed: at least 1)",
        ),
        (
            lambda raw: raw.update(environments={"production": {}}),
            "environments is not a field of the declaration (allowed: build, compose",
        ),
    ],
    ids=[
        "build",
        "rollback",
        "instances",
        "external-backup",
        "compose-file",
        "absolute-path",
        "overrides-twice",
        "no-units",
        "unit-id",
        "role-type",
        "role-missing",
        "env-name",
        "migrations-type",
        "depends-twice",
        "health-path",
        "stateful-type",
        "backup-every",
        "backup-keep",
        "cpu",
        "memory",
        "size-name",
        "volume-id",
        "empty-command",
        "environments",
    ],
)
def test_a_broken_declaration_names_the_field_and_what_is_allowed(change, expected) -> None:
    """Every refusal says where, what is wrong, and what would be right."""
    raw = seed()
    change(raw)
    assert expected in _refused(raw)


# --- paths: inside the checkout, never the development file ---------------


def test_a_profile_outside_the_checkout_is_refused(tmp_path) -> None:
    raw = seed()
    raw["compose"]["file"] = "../elsewhere.yml"
    (tmp_path / "elsewhere.yml").write_text(yaml.safe_dump(profile()), encoding="utf-8")
    message = _readable_messages(project(tmp_path, raw))
    assert 'compose.file "../elsewhere.yml" resolves outside the checkout' in message


def test_a_link_that_leaves_the_checkout_is_refused(tmp_path) -> None:
    """Followed, then judged: a link is where a path escape hides from a string check."""
    outside = tmp_path / "outside.yml"
    outside.write_text(yaml.safe_dump(profile()), encoding="utf-8")
    raw = seed()
    raw["compose"]["file"] = "linked.yml"
    root = project(tmp_path, raw)
    try:
        os.symlink(outside, root / "linked.yml")
    except OSError:  # pragma: no cover - a Windows account without the link privilege
        pytest.skip("this account cannot create a symbolic link")
    assert "resolves outside the checkout" in _readable_messages(root)


def test_the_development_compose_file_is_never_the_deploy_profile(tmp_path) -> None:
    raw = seed()
    raw["compose"]["file"] = "docker-compose.yml"
    root = project(tmp_path, raw, files={"docker-compose.yml": yaml.safe_dump(profile())})
    assert (
        'compose.file "docker-compose.yml" is the development compose file'
        in _readable_messages(root)
    )


def test_the_development_file_is_the_one_workbench_json_names(tmp_path) -> None:
    raw = seed()
    raw["compose"]["overrides"] = ["compose.dev.yml"]
    workbench = json.dumps(
        {"schemaVersion": 1, "compose": {"file": "compose.dev.yml"}, "services": []}
    )
    root = project(
        tmp_path, raw, files={"compose.dev.yml": "services: {}\n", "workbench.json": workbench}
    )
    assert (
        'compose.overrides[0] "compose.dev.yml" is the development compose file'
        in _readable_messages(root)
    )


def test_a_profile_of_any_other_name_can_be_declared(tmp_path) -> None:
    """The name of a deploy profile is not a gate: no `.prod.` infix is required."""
    raw = seed()
    raw["compose"]["file"] = "deploy/compose.yml"
    root = project(tmp_path, raw, files={"deploy/compose.yml": yaml.safe_dump(profile())})
    assert check_deployment_declaration_is_readable(root) == []


def test_a_profile_that_is_not_there_is_the_truth_rule_s_to_report(tmp_path) -> None:
    raw = seed()
    raw["compose"]["file"] = "compose.production.yml"
    assert check_deployment_declaration_is_readable(project(tmp_path, raw)) == []


@pytest.mark.parametrize(
    ("build", "what"),
    [
        ({"context": "../.."}, "services.web.build.context '../..'"),
        (
            {"context": ".", "dockerfile": "../../Dockerfile"},
            "services.web.build.dockerfile '../../Dockerfile'",
        ),
        (
            "https://example.invalid/app.git",
            "services.web.build.context 'https://example.invalid/app.git'",
        ),
    ],
    ids=["context", "dockerfile", "remote"],
)
def test_a_build_that_reaches_outside_the_checkout_is_not_the_checkout_s(
    tmp_path, build, what
) -> None:
    web = dict(profile()["services"]["web"], build=build)
    message = _readable_messages(project(tmp_path, seed(), profile(web=web)))
    assert f"docker-compose.prod.yml: {what} resolves outside the checkout" in message
    violation = check_deployment_declaration_is_readable(
        project(tmp_path, seed(), profile(web=web))
    )[0]
    assert violation.path == "docker-compose.prod.yml", (
        "a profile finding is reported in the profile"
    )


def test_a_build_above_the_project_but_inside_the_work_tree_passes(tmp_path) -> None:
    """``apps/example`` builds from the repository root with ``context: ../..``."""
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    root = repo / "apps" / "shop"
    root.mkdir(parents=True)
    api = dict(
        profile()["services"]["api"],
        build={"context": "../..", "dockerfile": "apps/shop/Dockerfile.prod"},
    )
    (root / "deployment.json").write_text(json.dumps(seed()), encoding="utf-8")
    (root / "docker-compose.prod.yml").write_text(
        yaml.safe_dump(profile(api=api)), encoding="utf-8"
    )
    assert check_deployment_declaration_is_readable(root) == []
    (repo / ".git").rmdir()
    assert "services.api.build.context '../..' resolves outside" in _readable_messages(root), (
        "the same climb with no work tree leaves the checkout"
    )


def test_an_unreadable_profile_leads_nowhere_so_it_is_silent_here(tmp_path) -> None:
    assert check_deployment_declaration_is_readable(project(tmp_path, seed(), "services: [")) == []
