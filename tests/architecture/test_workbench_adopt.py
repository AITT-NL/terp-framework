"""``terp workbench adopt``: a declaration moves forward by its diff, and only by its own hand.

``workbench.json`` is seeded once and owned by the app, so a later vocabulary never
reaches an app that already has one unless something carries it there. These hold the
thing that does (ADR 0186): it refuses a version the vocabulary does not define, refuses
a fact it cannot represent, shows the diff, writes only with ``--write``, and fails
``--check`` exactly when it has something to write.
"""

from __future__ import annotations

import json
import pathlib

import pytest
import yaml

from terp.cli import main
from terp.cli.workbench import WORKBENCH_FILE, run_workbench_check
from terp.cli.workbench_adopt import (
    AdoptionRefused,
    latest_version,
    plan,
    run_workbench_adopt,
)


def _declaring(*entries: dict, **extra) -> dict:
    return {"//": ["the app's own note"], "schemaVersion": 1, "services": list(entries), **extra}


def _app(tmp_path: pathlib.Path, declaration: dict | str | None, compose: dict | str | None) -> pathlib.Path:
    root = tmp_path / "app"
    root.mkdir(exist_ok=True)
    if declaration is not None:
        text = declaration if isinstance(declaration, str) else json.dumps(declaration, indent=2) + "\n"
        (root / WORKBENCH_FILE).write_text(text, encoding="utf-8")
    if compose is not None:
        text = compose if isinstance(compose, str) else yaml.safe_dump(compose)
        (root / "docker-compose.yml").write_text(text, encoding="utf-8")
    return root


_WEB = {"role": "web", "service": "web", "hostPortEnv": "WEB_PORT"}


def _web_publishing(host: str) -> dict:
    return {"services": {"web": {"ports": [f"{host}:5173"]}}}


def test_the_newest_version_is_the_vocabulary_s() -> None:
    assert latest_version() == 1


def test_a_version_the_vocabulary_does_not_define_is_refused_and_nothing_is_written(tmp_path, capsys) -> None:
    root = _app(tmp_path, _declaring(_WEB), _web_publishing("${WEB_PORT:-5173}"))
    before = (root / WORKBENCH_FILE).read_bytes()

    assert run_workbench_adopt(root=str(root), schema=2, write=True) == 1

    out = capsys.readouterr().out
    assert "Nothing was written" in out and "schemaVersion 2" in out and "defines 1" in out
    assert (root / WORKBENCH_FILE).read_bytes() == before


def test_a_declaration_that_agrees_has_nothing_to_adopt(tmp_path, capsys) -> None:
    root = _app(tmp_path, _declaring(_WEB), _web_publishing("${WEB_PORT:-5173}"))

    assert run_workbench_adopt(root=str(root), check=True) == 0
    assert "agrees with its compose file" in capsys.readouterr().out


def test_no_declaration_stays_no_declaration(tmp_path, capsys) -> None:
    """Deleting the file is how an app opts out of the check; adoption must not undo it."""
    root = _app(tmp_path, None, _web_publishing("5173"))

    assert run_workbench_adopt(root=str(root), write=True) == 0
    assert "nothing to adopt" in capsys.readouterr().out
    assert not (root / WORKBENCH_FILE).exists()


def test_an_opted_out_declaration_stays_opted_out(tmp_path, capsys) -> None:
    root = _app(tmp_path, {"unmanaged": True, "reason": "Started from a make target."}, None)
    before = (root / WORKBENCH_FILE).read_bytes()

    assert run_workbench_adopt(root=str(root), write=True) == 0
    assert "unmanaged: Started from a make target." in capsys.readouterr().out
    assert (root / WORKBENCH_FILE).read_bytes() == before


def test_a_renamed_port_variable_is_shown_then_written_only_when_asked(tmp_path, capsys) -> None:
    """The compose file's own name, carried into the declaration, by its diff."""
    root = _app(
        tmp_path,
        _declaring(_WEB, {"role": "api", "service": "api", "readinessPath": "/ready"}),
        {"services": {"web": {"ports": ["${FRONT_PORT:-5173}:5173"]}, "api": {}}},
    )
    before = (root / WORKBENCH_FILE).read_text(encoding="utf-8")
    assert run_workbench_check(root)[0] == 1, "the gate sees the lie adoption will settle"

    assert run_workbench_adopt(root=str(root)) == 0
    shown = capsys.readouterr().out
    assert '-      "hostPortEnv": "WEB_PORT"' in shown and '+      "hostPortEnv": "FRONT_PORT"' in shown
    assert "Nothing was written" in shown
    assert (root / WORKBENCH_FILE).read_text(encoding="utf-8") == before

    assert run_workbench_adopt(root=str(root), check=True) == 1
    assert "is not adopted" in capsys.readouterr().out
    assert (root / WORKBENCH_FILE).read_text(encoding="utf-8") == before

    assert run_workbench_adopt(root=str(root), write=True) == 0
    assert '+      "hostPortEnv": "FRONT_PORT"' in capsys.readouterr().out
    written = json.loads((root / WORKBENCH_FILE).read_text(encoding="utf-8"))
    assert list(written) == ["//", "schemaVersion", "services"], "the order and the app's own keys survive"
    assert written["services"][1] == {"role": "api", "service": "api", "readinessPath": "/ready"}
    assert run_workbench_check(root)[0] == 0
    assert run_workbench_adopt(root=str(root), check=True) == 0


@pytest.mark.parametrize(
    ("declaration", "compose", "said"),
    [
        (_declaring(_WEB), _web_publishing("5173"), "fixed host port"),
        (_declaring(_WEB), {"services": {"api": {}}}, "does not define"),
        (
            _declaring(_WEB),
            {"services": {"web": {"ports": ["${A_PORT:-1}:1", "${B_PORT:-2}:2"]}}},
            "A_PORT, B_PORT",
        ),
        (
            _declaring(_WEB, env={"sourceRoot": "APP_HOST_ROOT"}),
            _web_publishing("${WEB_PORT:-5173}"),
            "never reads",
        ),
        (_declaring(_WEB), _web_publishing("${DOCKER_PORT:-5173}"), "DOCKER_"),
        (_declaring(_WEB), "services: [unclosed", "unreadable"),
        (_declaring(_WEB), {"volumes": {}}, "declares no services"),
        ("{ not json", _web_publishing("5173"), "cannot be read"),
        ({"schemaVersion": 7, "services": []}, _web_publishing("5173"), "does not read"),
        (_declaring(_WEB, compose={"file": "gone.yml"}), None, "does not exist"),
    ],
    ids=[
        "a fixed port", "a service gone", "two variables", "a seam not read",
        "a reserved name", "an unparsable compose file", "no services",
        "an unreadable declaration", "a later declaration", "a compose file gone",
    ],
)
def test_a_fact_adoption_cannot_represent_is_refused(tmp_path, capsys, declaration, compose, said) -> None:
    root = _app(tmp_path, declaration, compose)
    before = (root / WORKBENCH_FILE).read_bytes()

    assert run_workbench_adopt(root=str(root), write=True) == 1

    out = capsys.readouterr().out
    assert out.startswith("Nothing was written.") and said in out, out
    assert (root / WORKBENCH_FILE).read_bytes() == before


def test_what_the_compose_file_cannot_settle_is_carried_over(tmp_path) -> None:
    """A service that publishes nothing, an entry with no port, commands, seams that are read."""
    declaration = _declaring(
        {"role": "api", "service": "api", "hostPortEnv": "API_PORT"},
        {"role": "message-bus", "service": "nats", "note": "kept"},
        env={"frameAncestors": "TERP_DEV_FRAME_ANCESTORS"},
        commands={"start": "make dev", "reticulate": "kept"},
    )
    root = _app(
        tmp_path,
        declaration,
        {"services": {"api": {"environment": {"X": "${TERP_DEV_FRAME_ANCESTORS:-}"}}, "nats": None}},
    )

    adoption = plan(root, 1)

    assert adoption is not None and not adoption.changes and adoption.diff() == ""


def test_an_app_that_drives_its_own_loop_needs_no_compose_file(tmp_path) -> None:
    root = _app(tmp_path, {"schemaVersion": 1, "services": [], "commands": {"start": "make dev"}}, None)

    adoption = plan(root, 1)

    assert adoption is not None and not adoption.changes


def test_plan_refuses_with_a_typed_error(tmp_path) -> None:
    root = _app(tmp_path, _declaring(_WEB), _web_publishing("5173"))
    with pytest.raises(AdoptionRefused, match="fixed host port"):
        plan(root, 1)


def test_the_command_line_runs_it_and_will_not_both_write_and_check(tmp_path, capsys) -> None:
    root = _app(tmp_path, _declaring(_WEB), _web_publishing("${WEB_PORT:-5173}"))

    with pytest.raises(SystemExit) as finished:
        main(["workbench", "adopt", "--root", str(root), "--schema", "1", "--check"])
    assert finished.value.code == 0
    assert "agrees" in capsys.readouterr().out

    with pytest.raises(SystemExit) as finished:
        main(["workbench", "adopt", "--root", str(root), "--write", "--check"])
    assert finished.value.code == 2
