"""The build-state round trip, run for real: copier, the template and ``terp deployment adopt``.

ADR 0187 decision 4 rests on copier reading the build state from the recorded answer on
every update. ``tools/copier_round_trip.py`` proves it with the copier an app uses, against
a template repository of four revisions built from ``template/``: own to generated and back
through updates to the same and to newer revisions, a generated copy, scaffolding that
predates the question, and an app with files. Template acceptance runs the same tool on every pull request; here it
runs in the gate whenever copier can be found (on the PATH, or through ``uvx``), and the
copier-free cases hold what it does when a step goes wrong.
"""

from __future__ import annotations

import pathlib
import shutil
import subprocess
import sys

import pytest

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "tools"))

import copier_round_trip as trip_tool  # noqa: E402


def _copier() -> list[str] | None:
    if shutil.which("copier"):
        return ["copier"]
    if shutil.which("uvx"):
        return ["uvx", "copier"]
    return None


def test_the_round_trip_holds_both_ways_with_copier_itself(tmp_path, capsys) -> None:
    copier = _copier()
    if copier is None or shutil.which("git") is None:
        pytest.skip("copier and git are needed to render the template for real")
    code = trip_tool.main(["--copier", " ".join(copier), "--work", str(tmp_path / "trip")])
    out, err = capsys.readouterr()
    assert code == 0, err
    assert out.splitlines() == [
        "ok  adopt --build generated: deployment.json and the answers file, no build file",
        "ok  copier update to the same revision: nothing",
        "ok  copier update to v2 under generated: the README and the answers file; no build "
        "file, and the removed frontend/Dockerfile.prod is not created again",
        "ok  adopt --build own: deployment.json and the answers file, no build file",
        "ok  copier update to v3 under own: each build file is the last render with v3's "
        "change merged in, and v2's left out",
        "ok  a generated copy has no build file until terp deployment render writes the "
        "template's, byte for byte",
        "ok  scaffolding that predates the question: adopt is refused and writes nothing; "
        "copier update records deploy_build: own; adopt then changes no build file",
        "ok  with use_files: the production profile mounts the files volume the seed "
        "declares, and adopt --build generated changes no build file",
    ]


def test_a_step_that_fails_stops_the_trip_and_says_which(tmp_path, capsys) -> None:
    def refuse(argv, **kwargs):
        return subprocess.CompletedProcess(argv, 1, stdout="", stderr="fatal: no\n")

    assert trip_tool.main(["--work", str(tmp_path), "--terp", "terp"], run=refuse) == 1
    message = capsys.readouterr().err
    assert message.startswith("copier_round_trip: `git -C ")
    assert "init -q` exited 1:\nfatal: no" in message


def test_an_adoption_that_should_be_refused_and_is_not_stops_the_trip(tmp_path) -> None:
    def accept(argv, **kwargs):
        return subprocess.CompletedProcess(argv, 0, stdout="written\n", stderr="")

    trip = trip_tool.Trip(tmp_path, ["copier"], ["terp"], accept)
    with pytest.raises(trip_tool.RoundTripError, match="was not refused:\nwritten"):
        trip.adopt(tmp_path, "generated", refused=True)


def test_the_template_it_rewinds_must_still_ask_the_question(tmp_path) -> None:
    template = tmp_path / "tpl"
    (template / "project").mkdir(parents=True)
    (template / "copier.yml").write_text("project_slug: {type: str}\n", encoding="utf-8")
    with pytest.raises(trip_tool.RoundTripError, match="no longer asks deploy_build"):
        trip_tool._before_the_question(template)
    (template / "copier.yml").write_text(
        "deploy_build: {type: str}\n_exclude: []\n", encoding="utf-8"
    )
    (template / "project" / "deployment.json.jinja").write_text('{"build": "own"}', "utf-8")
    with pytest.raises(trip_tool.RoundTripError, match="no longer takes build"):
        trip_tool._before_the_question(template)


def test_template_acceptance_runs_the_round_trip() -> None:
    import yaml

    workflow = yaml.safe_load((_REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text("utf-8"))
    runs = [str(step.get("run", "")) for step in workflow["jobs"]["template-acceptance"]["steps"]]
    assert any("tools/copier_round_trip.py --copier \"uvx copier\"" in run for run in runs)
