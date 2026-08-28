"""``terp verify --only env-seams`` — which seam actually supplies a declared variable.

Compose resolves a service's ``environment:`` mapping over its ``env_file:`` list, so a
variable named in both is supplied by the developer's ``.env`` and the ``.app.env`` Studio
renders never arrives. Nothing fails at that moment: the value is simply wrong, in every
environment, until something uses it — which is why this is a gate and not a warning.

Docker is not required and never will be: the verdict is a read of two checked-in files
(``environment.schema.json`` and the compose profiles). ``docker compose config`` is not
used deliberately — it inlines ``env_file`` into ``environment`` and drops the key, which
erases the exact distinction under test.
"""

from __future__ import annotations

import json
import pathlib
import sys

import pytest

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_CLI_SRC = _REPO_ROOT / "packages" / "backend" / "cli" / "src"
sys.path.insert(0, str(_CLI_SRC))

from terp.cli.envschema import (  # noqa: E402
    declared_variables,
    manifest_findings,
)
from terp.cli.envseams import (  # noqa: E402
    _forwards_app_env,
    _is_loopback,
    _read_env_file,
    _service_environment,
    env_seam_findings,
    run_env_seams_check,
)

_COMPOSE = """\
name: app
x-backend: &backend
  image: app-backend
  env_file:
    - path: .app.env
      required: false
  environment: &backend-env
{environment}
services:
  db:
    image: postgres:17-alpine
    environment:
      POSTGRES_USER: app
  migrate:
    <<: *backend
    command: ["terp", "migrate", "upgrade"]
  api:
    <<: *backend
    environment:
      <<: *backend-env
      WATCHFILES_FORCE_POLLING: "true"
"""


def _project(
    tmp_path: pathlib.Path,
    *,
    declared: dict,
    environment: str = "    ENVIRONMENT: local",
    example: str | None = None,
) -> pathlib.Path:
    """A project whose seams are complete except for what the test is about.

    `.app.env.example` gets one entry per declared name by default, because that is
    what a whole app looks like and these fixtures exist to isolate the shadowing and
    loopback verdicts. Pass *example* to make the example file itself the subject.
    """
    (tmp_path / "environment.schema.json").write_text(
        json.dumps({"type": "object", "properties": declared, "required": []}),
        encoding="utf-8",
    )
    (tmp_path / "docker-compose.yml").write_text(
        _COMPOSE.format(environment=environment), encoding="utf-8"
    )
    (tmp_path / ".app.env.example").write_text(
        "\n".join(f"{name}=" for name in declared) + "\n" if example is None else example,
        encoding="utf-8",
    )
    return tmp_path


# --------------------------------------------------------------------------- #
# the shadowing verdict
# --------------------------------------------------------------------------- #
def test_a_declared_variable_forwarded_through_interpolation_is_refused(
    tmp_path: pathlib.Path,
) -> None:
    root = _project(
        tmp_path,
        declared={"MY_VAR": {"type": "string"}},
        environment="    MY_VAR: ${MY_VAR:-}",
    )
    exit_code, output = run_env_seams_check(root)
    assert exit_code == 1
    assert "MY_VAR" in output
    # The message must name the seam that wins, not merely that something is wrong.
    assert "environment:" in output and "env_file:" in output
    assert ".app.env" in output


def test_a_declared_variable_hardcoded_in_compose_is_refused(
    tmp_path: pathlib.Path,
) -> None:
    """A literal discards `.app.env` as completely as a `${}` forward.

    Scanning only for interpolation would miss the shape apps reach for most: a plain
    `SOME_API_BASE_URL: http://api:8000` written straight into the compose block.
    """
    root = _project(
        tmp_path,
        declared={"MY_VAR": {"type": "string"}},
        environment="    MY_VAR: http://api:8000",
    )
    exit_code, output = run_env_seams_check(root)
    assert exit_code == 1
    assert "hardcoded" in output


def test_one_offence_per_variable_not_one_per_service(tmp_path: pathlib.Path) -> None:
    """A shared backend anchor puts the override on every service that merges it.

    Reporting it once per service would restate one fact N times with the fix recipe
    repeated each time — the noise that buries the finding.
    """
    root = _project(
        tmp_path,
        declared={"MY_VAR": {"type": "string"}},
        environment="    MY_VAR: ${MY_VAR:-}",
    )
    findings = env_seam_findings(root)
    assert len(findings) == 1
    assert set(findings[0].services) == {"api", "migrate"}


def test_an_undeclared_forward_is_allowed(tmp_path: pathlib.Path) -> None:
    """`.env` stays the developer's override knob — do not over-correct.

    OIDC_REDIRECT_URI is the canonical case: the browser resolves it, so a host address
    is right and a `${}` forward is the correct seam. Only a *declared* name is refused.
    """
    root = _project(
        tmp_path,
        declared={"MY_VAR": {"type": "string"}},
        environment="    OIDC_REDIRECT_URI: ${OIDC_REDIRECT_URI:-}",
    )
    assert run_env_seams_check(root)[0] == 0


def test_a_service_that_does_not_forward_app_env_is_not_a_shadow(
    tmp_path: pathlib.Path,
) -> None:
    """Without the `.app.env` seam there is nothing to shadow (the `db` service)."""
    root = _project(tmp_path, declared={"POSTGRES_USER": {"type": "string"}})
    assert run_env_seams_check(root)[0] == 0


# --------------------------------------------------------------------------- #
# the host / container / browser verdict
# --------------------------------------------------------------------------- #
def test_a_container_resolved_variable_set_to_loopback_is_refused(
    tmp_path: pathlib.Path,
) -> None:
    root = _project(
        tmp_path, declared={"API_URL": {"type": "string", "resolvedBy": "container"}}
    )
    (root / ".app.env").write_text("API_URL=http://127.0.0.1:8000\n", encoding="utf-8")
    exit_code, output = run_env_seams_check(root)
    assert exit_code == 1
    assert "loopback" in output
    assert "container itself" in output


def test_a_host_resolved_variable_may_be_loopback(tmp_path: pathlib.Path) -> None:
    """The distinction is the point: a host address is correct for a host-resolved
    variable, and flagging it would make the annotation useless."""
    root = _project(
        tmp_path, declared={"API_URL": {"type": "string", "resolvedBy": "host"}}
    )
    (root / ".app.env").write_text("API_URL=http://127.0.0.1:8000\n", encoding="utf-8")
    assert run_env_seams_check(root)[0] == 0


def test_a_container_resolved_service_name_passes(tmp_path: pathlib.Path) -> None:
    root = _project(
        tmp_path, declared={"API_URL": {"type": "string", "resolvedBy": "container"}}
    )
    (root / ".app.env").write_text("API_URL=http://api:8000\n", encoding="utf-8")
    assert run_env_seams_check(root)[0] == 0


def test_a_correct_app_env_is_not_condemned_by_a_host_address_in_dot_env(
    tmp_path: pathlib.Path,
) -> None:
    """A host address in `.env` alongside a correct `.app.env` is a developer running
    CLIs against the workbench — the legitimate use of that seam, not a defect. Only the
    value that actually lands is judged."""
    root = _project(
        tmp_path, declared={"API_URL": {"type": "string", "resolvedBy": "container"}}
    )
    (root / ".app.env").write_text("API_URL=http://api:8000\n", encoding="utf-8")
    (root / ".env").write_text("API_URL=http://127.0.0.1:8000\n", encoding="utf-8")
    assert run_env_seams_check(root)[0] == 0


def test_a_loopback_default_in_the_manifest_is_refused(tmp_path: pathlib.Path) -> None:
    """The manifest's own default lands when no seam supplies a value."""
    root = _project(
        tmp_path,
        declared={
            "API_URL": {
                "type": "string",
                "resolvedBy": "container",
                "default": "http://localhost:8000",
            }
        },
    )
    assert run_env_seams_check(root)[0] == 1


def test_a_loopback_finding_does_not_offer_the_precedence_recipe(
    tmp_path: pathlib.Path,
) -> None:
    """The two findings have different fixes. Printing "remove it from that
    `environment:` block" for a value that is merely pointed at the wrong host would be
    a confident answer to a question nobody asked — the failure mode this whole check
    exists to stop."""
    root = _project(
        tmp_path, declared={"API_URL": {"type": "string", "resolvedBy": "container"}}
    )
    (root / ".app.env").write_text("API_URL=http://127.0.0.1:8000\n", encoding="utf-8")
    _, output = run_env_seams_check(root)
    assert "loopback" in output
    assert "remove the variable from that" not in output
    assert "terp guide environment" in output


def test_loopback_recognises_the_forms_an_address_takes() -> None:
    assert _is_loopback("http://127.0.0.1:8000")
    assert _is_loopback("http://localhost:8000/path")
    assert _is_loopback("localhost:5432")
    assert _is_loopback("0.0.0.0")  # noqa: S104 - a value to DETECT, not to bind
    assert not _is_loopback("http://api:8000")
    assert not _is_loopback("db:5432")
    assert not _is_loopback("")


# --------------------------------------------------------------------------- #
# staying quiet when there is nothing to say
# --------------------------------------------------------------------------- #
def test_an_app_with_no_manifest_passes(tmp_path: pathlib.Path) -> None:
    """Upgrading the framework must not turn an app's gate red for an unfilled seam."""
    (tmp_path / "docker-compose.yml").write_text(
        _COMPOSE.format(environment="    ENVIRONMENT: local"), encoding="utf-8"
    )
    assert run_env_seams_check(tmp_path)[0] == 0


def test_an_app_declaring_nothing_passes(tmp_path: pathlib.Path) -> None:
    assert run_env_seams_check(_project(tmp_path, declared={}))[0] == 0


def test_an_unusable_manifest_is_this_checks_verdict_after_all(
    tmp_path: pathlib.Path,
) -> None:
    """It used to be Studio's alone, and that put the verdict a deploy away from the edit.

    Studio's reader fails closed on the WHOLE file, so one defect costs the app every
    declaration it has — and an authoring agent found that out by writing a description
    longer than 500 characters, watching the gate stay green, and losing the manifest.
    """
    root = _project(tmp_path, declared={})
    (root / "environment.schema.json").write_text("{not json", encoding="utf-8")
    exit_code, output = run_env_seams_check(root)
    assert exit_code == 1
    assert "is not valid JSON" in output
    assert "terp guide environment" in output


def test_a_clean_app_reports_the_variables_that_do_arrive(
    tmp_path: pathlib.Path,
) -> None:
    root = _project(tmp_path, declared={"MY_VAR": {"type": "string"}})
    exit_code, output = run_env_seams_check(root)
    assert exit_code == 0
    assert "1 declared variable(s) reach the app" in output


# The readers below are deliberately tolerant: this check's verdict is about which seam
# supplies a value, and an app's compose file or manifest being unusual — or unreadable —
# is not that verdict to give. Each tolerance is a branch, so each is proven here.


def test_service_environment_accepts_both_compose_forms() -> None:
    assert _service_environment({"environment": ["A=1", "B=", "BARE"]}) == {
        "A": "1",
        "B": "",
        "BARE": "",
    }
    assert _service_environment({"environment": {"A": None}}) == {"A": ""}
    assert _service_environment({"environment": "not a mapping or list"}) == {}
    assert _service_environment("not a service") == {}


def test_forwards_app_env_is_false_for_a_non_service() -> None:
    assert _forwards_app_env("not a service") is False


def test_declared_variables_tolerate_a_manifest_that_is_not_usable(
    tmp_path: pathlib.Path,
) -> None:
    """This reader no longer gives the verdict — ``manifest_findings`` does, and
    ``run_env_seams_check`` reports it first. So it only has to answer "which names does
    the app mean to declare" without raising on a file the caller has already refused."""
    assert declared_variables(tmp_path) == {}

    (tmp_path / "environment.schema.json").write_text("{ not json", encoding="utf-8")
    assert declared_variables(tmp_path) == {}

    (tmp_path / "environment.schema.json").write_text('{"properties": []}', encoding="utf-8")
    assert declared_variables(tmp_path) == {}

    (tmp_path / "environment.schema.json").write_text(
        '{"properties": {"GOOD": {"type": "string"}, "BAD": "not an object"}}', encoding="utf-8"
    )
    assert list(declared_variables(tmp_path)) == ["GOOD"]


def test_env_file_reading_skips_comments_and_blanks(tmp_path: pathlib.Path) -> None:
    path = tmp_path / ".env"
    path.write_text("# comment\n\nA=1\nNOEQUALS\n", encoding="utf-8")
    assert _read_env_file(path) == {"A": "1"}
    assert _read_env_file(tmp_path / "absent.env") == {}


def test_findings_are_empty_when_the_app_declares_nothing(tmp_path: pathlib.Path) -> None:
    """No manifest means no promise about any seam, so there is nothing that can be
    broken — the same no-op shape an unadopted generator has."""
    assert env_seam_findings(tmp_path) == []


def test_an_unreadable_compose_file_is_skipped_not_fatal(tmp_path: pathlib.Path) -> None:
    """A compose profile this check cannot parse is one it cannot judge. Failing the gate
    on it would make an unrelated YAML error look like a seam defect."""
    (tmp_path / "environment.schema.json").write_text(
        '{"properties": {"API_URL": {"type": "string"}}}', encoding="utf-8"
    )
    (tmp_path / "docker-compose.yml").write_text("services: [ unbalanced\n", encoding="utf-8")
    (tmp_path / ".app.env.example").write_text("API_URL=\n", encoding="utf-8")
    assert env_seam_findings(tmp_path) == []


def test_a_compose_file_without_a_services_mapping_is_skipped(tmp_path: pathlib.Path) -> None:
    (tmp_path / "environment.schema.json").write_text(
        '{"properties": {"API_URL": {"type": "string"}}}', encoding="utf-8"
    )
    (tmp_path / "docker-compose.yml").write_text("services: not-a-mapping\n", encoding="utf-8")
    (tmp_path / ".app.env.example").write_text("API_URL=\n", encoding="utf-8")
    assert env_seam_findings(tmp_path) == []


def test_the_report_groups_findings_by_the_file_they_came_from(tmp_path: pathlib.Path) -> None:
    """Two profiles shadowing the same variable are two findings from two sources. The
    report is grouped by source so the reader knows which file to open."""
    (tmp_path / "environment.schema.json").write_text(
        '{"type": "object", "properties": {"API_URL": {"type": "string"}}}',
        encoding="utf-8",
    )
    for name in ("docker-compose.yml", "docker-compose.prod.yml"):
        (tmp_path / name).write_text(
            "services:\n"
            "  api:\n"
            "    env_file:\n      - .app.env\n"
            "    environment:\n      API_URL: ${API_URL:-}\n",
            encoding="utf-8",
        )
    exit_code, output = run_env_seams_check(tmp_path)
    assert exit_code == 1
    assert "docker-compose.yml" in output
    assert "docker-compose.prod.yml" in output
    assert output.count("API_URL:") >= 2


# --------------------------------------------------------------------------- #
# the manifest's own shape (Studio's reader, mirrored)
# --------------------------------------------------------------------------- #
def _schema(tmp_path: pathlib.Path, raw: str) -> pathlib.Path:
    (tmp_path / "environment.schema.json").write_text(raw, encoding="utf-8")
    return tmp_path


def _defects(tmp_path: pathlib.Path) -> list[str]:
    return [f"{f.subject} {f.detail}".strip() for f in manifest_findings(tmp_path)]


def test_the_incident_an_over_long_description_costs_the_app_its_whole_manifest(
    tmp_path: pathlib.Path,
) -> None:
    """The defect this check was added for, in the shape it actually arrived in.

    An authoring agent explained OIDC_REDIRECT_URI well and wrote past 500 characters.
    `terp verify --profile full` was green; Studio refused the file, and with it the
    app's MariaDB password and every other declaration. The gate must say so, and say
    the same thing Studio would have.
    """
    root = _schema(
        tmp_path,
        json.dumps(
            {
                "type": "object",
                "properties": {
                    "MARIADB_SYNC_PASSWORD": {"type": "string", "format": "secret"},
                    "OIDC_REDIRECT_URI": {
                        "type": "string",
                        "resolvedBy": "browser",
                        "description": "x" * 501,
                    },
                },
                "required": [],
            }
        ),
    )
    exit_code, output = run_env_seams_check(root)
    assert exit_code == 1
    assert "OIDC_REDIRECT_URI.description must be a string of at most 500" in output
    assert "(it is 501)" in output
    # The consequence, not just the rule: the reader is fail-closed on the WHOLE file.
    assert "WHOLE file" in output
    assert "terp guide environment" in output


_UNUSABLE = (
    ("{ not json", "is not valid JSON"),
    ("[]", 'must be a JSON object with "type": "object"'),
    ('{"type": "array", "properties": {}}', 'must be a JSON object with "type"'),
    ('{"type": "object", "properties": []}', '"properties" must be an object'),
    (
        '{"type": "object", "properties": {"my_var": {"type": "string"}}}',
        "is not a valid variable name",
    ),
    (
        '{"type": "object", "properties": {"SECRET_KEY": {"type": "string"}}}',
        "SECRET_KEY is platform-owned",
    ),
    (
        '{"type": "object", "properties": {"VITE_API_URL": {"type": "string"}}}',
        "VITE_API_URL is a frontend build-time variable",
    ),
    (
        '{"type": "object", "properties": {"MY_VAR": "string"}}',
        "MY_VAR must be an object",
    ),
    (
        '{"type": "object", "properties": {"MY_VAR": {"type": 5}}}',
        "MY_VAR.type must be a string of at most 500 characters",
    ),
    (
        '{"type": "object", "properties": {"MY_VAR": {"resolvedBy": "browsers"}}}',
        "MY_VAR.resolvedBy is 'browsers'",
    ),
    (
        '{"type": "object", "properties": {"MY_VAR": {"enum": "one"}}}',
        "MY_VAR.enum must be a list",
    ),
    (
        '{"type": "object", "properties": {"MY_VAR": {"enum": ["ok", 5]}}}',
        "MY_VAR.enum must be a list",
    ),
    (
        '{"type": "object", "properties": {}, "required": "MY_VAR"}',
        '"required" must be a list',
    ),
    (
        '{"type": "object", "properties": {}, "required": [5]}',
        '"required" must be a list',
    ),
    (
        '{"type": "object", "properties": {}, "required": ["MY_VAR"]}',
        'MY_VAR is in "required" but not declared',
    ),
)


@pytest.mark.parametrize(("raw", "expected"), _UNUSABLE)
def test_every_refusal_the_deploy_side_makes_is_named_by_the_gate(
    tmp_path: pathlib.Path, raw: str, expected: str
) -> None:
    """One case per refusal in Terp Studio's own manifest reader.

    The two halves of the platform have no shared package to hold them equal (Studio
    never imports ``terp.*``), so parity is held here, case by case.
    """
    assert any(expected in defect for defect in _defects(_schema(tmp_path, raw)))


def test_the_limits_are_the_ones_the_deploy_side_enforces(tmp_path: pathlib.Path) -> None:
    """Off-by-one on any of these is a manifest that passes here and dies there."""
    over = {f"VAR_{n}": {"type": "string"} for n in range(51)}
    assert any("declares 51 variables" in d for d in _defects(_schema(
        tmp_path, json.dumps({"type": "object", "properties": over})
    )))
    for prop, expected in (
        ({"enum": ["v"] * 51}, "MY_VAR.enum"),
        ({"enum": ["x" * 201]}, "MY_VAR.enum"),
        ({"title": "t" * 501}, "MY_VAR.title"),
    ):
        root = _schema(
            tmp_path, json.dumps({"type": "object", "properties": {"MY_VAR": prop}})
        )
        assert any(expected in d for d in _defects(root)), prop
    # At the limit, all three are fine.
    assert _defects(
        _schema(
            tmp_path,
            json.dumps(
                {
                    "type": "object",
                    "properties": {
                        "MY_VAR": {
                            "title": "t" * 500,
                            "enum": ["x" * 200] * 50,
                            "resolvedBy": "browser",
                        }
                    },
                }
            ),
        )
    ) == []


def test_a_malformed_resolved_by_is_one_offence_not_two(tmp_path: pathlib.Path) -> None:
    """The vocabulary is only judged once the value cleared the shape check.

    Otherwise an over-long or non-string ``resolvedBy`` would be reported twice — as
    the wrong shape and, redundantly, as an unrecognised word.
    """
    root = _schema(
        tmp_path,
        json.dumps(
            {"type": "object", "properties": {"MY_VAR": {"resolvedBy": "c" * 501}}}
        ),
    )
    assert len(_defects(root)) == 1
    assert "must be a string of at most 500" in _defects(root)[0]


def test_a_name_defect_stops_before_the_fields_are_judged(
    tmp_path: pathlib.Path,
) -> None:
    """A property refused on its key is not one whose fields Studio ever reads, so
    pricing the same mistake twice would bury the name that actually has to change."""
    root = _schema(
        tmp_path,
        json.dumps(
            {
                "type": "object",
                "properties": {"DATABASE_URL": {"description": "d" * 501}},
            }
        ),
    )
    assert len(_defects(root)) == 1
    assert "platform-owned" in _defects(root)[0]


def test_a_file_level_defect_reads_as_a_sentence_about_the_file(
    tmp_path: pathlib.Path,
) -> None:
    """A finding with no subject names no variable — the manifest itself is the offence."""
    root = _schema(
        tmp_path,
        json.dumps(
            {
                "type": "object",
                "properties": {f"VAR_{n}": {"type": "string"} for n in range(51)},
            }
        ),
    )
    exit_code, output = run_env_seams_check(root)
    assert exit_code == 1
    assert "declares 51 variables -- at most 50 are allowed" in output


def test_an_absent_manifest_has_no_shape_to_refuse(tmp_path: pathlib.Path) -> None:
    """The same no-op an app that has not adopted the seam gets everywhere else."""
    assert manifest_findings(tmp_path) == []


def test_the_shape_verdict_comes_before_the_seam_verdict(
    tmp_path: pathlib.Path,
) -> None:
    """A manifest Studio refuses declares nothing, so a seam verdict over it would
    answer a question that no longer applies — and would name the wrong fix."""
    root = _project(
        tmp_path,
        declared={"MY_VAR": {"type": "string", "description": "d" * 501}},
        environment="    MY_VAR: ${MY_VAR:-}",
    )
    exit_code, output = run_env_seams_check(root)
    assert exit_code == 1
    assert "MY_VAR.description" in output
    assert "docker-compose.yml" not in output


# --------------------------------------------------------------------------- #
# .app.env.example — the one file in the seam a human maintains
# --------------------------------------------------------------------------- #
_DECLARED = {
    "API_URL": {"type": "string", "resolvedBy": "container"},
    "VENDOR_TOKEN": {"type": "string", "format": "secret"},
}


def _kinds(root: pathlib.Path) -> list[tuple[str, str]]:
    return [
        (finding.variable, finding.detail)
        for finding in env_seam_findings(root)
        if finding.kind == "example"
    ]


def test_a_complete_example_file_is_clean(tmp_path: pathlib.Path) -> None:
    root = _project(
        tmp_path,
        declared=_DECLARED,
        example="# workbench values\nAPI_URL=http://api:8000\nVENDOR_TOKEN=\n",
    )
    assert _kinds(root) == []


def test_a_declared_variable_missing_from_the_example_is_refused(
    tmp_path: pathlib.Path,
) -> None:
    """`terp guide environment` says to add a workbench value here, and until now
    nothing opened the file. A name missing from it means the documented
    `cp .app.env.example .app.env` produces a workbench without configuration the app
    requires — discovered at run time, by whoever copied it."""
    root = _project(tmp_path, declared=_DECLARED, example="API_URL=http://api:8000\n")
    ((variable, detail),) = _kinds(root)
    assert variable == "VENDOR_TOKEN" and "no entry here" in detail


def test_an_undeclared_entry_in_the_example_is_refused(
    tmp_path: pathlib.Path,
) -> None:
    """Studio renders declarations and nothing else, so this value reaches no deployed
    environment. In practice it is a misspelling of a name that IS declared, which is
    the same outage wearing a different hat."""
    root = _project(
        tmp_path,
        declared=_DECLARED,
        example="API_URL=http://api:8000\nVENDOR_TOKEN=\nAPI_UROL=oops\n",
    )
    ((variable, detail),) = _kinds(root)
    assert variable == "API_UROL" and "never renders it" in detail


def test_a_secret_with_a_value_in_the_example_is_refused(
    tmp_path: pathlib.Path,
) -> None:
    """This file is COMMITTED; `.app.env` is not. So the one value rule in it is that a
    `"format": "secret"` declaration carries no value — the name tells a reader what to
    supply, and supplying it here puts the credential in git."""
    root = _project(
        tmp_path,
        declared=_DECLARED,
        example="API_URL=http://api:8000\nVENDOR_TOKEN=sk-live-abc123\n",
    )
    ((variable, detail),) = _kinds(root)
    assert variable == "VENDOR_TOKEN" and "COMMITTED" in detail

    # A secret declared with an empty value is the whole point of the entry.
    clean = _project(
        tmp_path,
        declared=_DECLARED,
        example='API_URL=http://api:8000\nVENDOR_TOKEN=""\n',
    )
    assert _kinds(clean) == []


def test_a_missing_example_file_is_refused_when_variables_are_declared(
    tmp_path: pathlib.Path,
) -> None:
    root = _project(tmp_path, declared=_DECLARED)
    (root / ".app.env.example").unlink()
    ((variable, detail),) = _kinds(root)
    assert variable == "" and "is missing" in detail


def test_an_app_declaring_nothing_is_not_asked_for_an_example(
    tmp_path: pathlib.Path,
) -> None:
    """Fail-open on an unadopted seam: a manifest with no variables has nothing to
    exemplify, so the absent file is not a defect."""
    root = _project(tmp_path, declared={}, example="")
    (root / ".app.env.example").unlink()
    assert env_seam_findings(root) == []


def test_the_example_is_parsed_the_way_compose_parses_it(
    tmp_path: pathlib.Path,
) -> None:
    """A value that reads differently to compose than to its author is the failure a
    looser parser hides. `TOKEN=abc # prod` is three characters to compose."""
    from terp.cli.envseams import parse_dotenv

    values, problems = parse_dotenv("TOKEN=abc # prod\nQUOTED='a # b'\n")
    assert values == {"TOKEN": "abc", "QUOTED": "a # b"} and problems == []

    # An unterminated quote is an error, not a value: compose refuses the file, so a
    # parser that guessed here would report a variable the app never receives.
    values, problems = parse_dotenv('BROKEN="oops\n')
    assert values == {} and "never closed" in problems[0][1]

    # An `export` prefix is accepted, as compose accepts it.
    assert parse_dotenv("export NAME=value\n")[0] == {"NAME": "value"}


def test_an_unparseable_example_line_is_reported_not_guessed(
    tmp_path: pathlib.Path,
) -> None:
    root = _project(
        tmp_path,
        declared={"API_URL": {"type": "string"}},
        example='API_URL="http://api:8000\n',
    )
    details = [detail for _variable, detail in _kinds(root)]
    assert any("never closed" in detail for detail in details)
    # ...and the variable is then ALSO reported as absent, because a line that does not
    # parse supplies nothing. Both statements are true and the app needs both.
    assert any("no entry here" in detail for detail in details)


def test_the_example_findings_get_their_own_fix_recipe(
    tmp_path: pathlib.Path,
) -> None:
    """The three kinds have different fixes; offering the compose precedence recipe for
    a missing example entry would be a confident answer to a question nobody asked."""
    root = _project(tmp_path, declared=_DECLARED, example="API_URL=http://api:8000\n")
    exit_code, output = run_env_seams_check(root)
    assert exit_code == 1
    assert "a human maintains" in output
    assert "Compose resolves `environment:` over `env_file:`" not in output


def test_the_parser_refuses_a_name_no_manifest_could_declare() -> None:
    """The manifest dialect is UPPER_SNAKE, so a lowercase name in the file is a
    value that could never be declared and therefore never delivered."""
    from terp.cli.envseams import parse_dotenv

    values, problems = parse_dotenv("lower_case=1\n")
    assert values == {}
    assert "not a usable variable name" in problems[0][1]


def test_the_parser_refuses_trailing_text_after_a_closing_quote() -> None:
    from terp.cli.envseams import parse_dotenv

    values, problems = parse_dotenv('NAME="value" and more\n')
    assert values == {}
    assert "after the closing quote" in problems[0][1]


def test_an_unreadable_example_file_is_a_finding_not_a_crash(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A directory where the file should be, a permission problem — either way the
    check reports it rather than raising out of the gate."""
    from terp.cli import envseams

    root = _project(tmp_path, declared={"API_URL": {"type": "string"}})

    def _refuse(self, *args, **kwargs):
        raise OSError("is a directory")

    monkeypatch.setattr(pathlib.Path, "read_text", _refuse)
    findings = envseams._example_findings(root, {"API_URL": {"type": "string"}})
    assert findings and "cannot be read" in findings[0].detail
