"""The public-safe reference app renders, stays current with the template, and is in CI.

``apps/reference`` is the stand-in for a real client application in every lane: this
repository's CI and any downstream test lane. It is produced, never
committed as a render, by ``tools/render_reference_app.py``: the template with pinned
answers, a ``pyproject.toml`` grown at named anchors, and an overlay. The app's own suite
runs in ``template-acceptance``; what is held here is what needs no copier and no
Docker, so it fails at the commit that breaks it:

* the overlay's copies of template-owned files are re-read whenever the template moves
  (``template-baseline.json``) -- the ``copier update`` conflict a client app would meet;
* every anchor the renderer edits still exists in the template it renders;
* the renderer refuses, by name, every shape it does not understand;
* the CI lane that runs the app is still there.
"""

from __future__ import annotations

import json
import pathlib
import re
import shutil
import sys

import pytest
import yaml

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "tools"))

import render_reference_app as reference  # noqa: E402

_TEMPLATE_PYPROJECT = reference.TEMPLATE_PROJECT / "pyproject.toml.jinja"
_FRAMEWORK_CI = _REPO_ROOT / ".github" / "workflows" / "ci.yml"


def _template_pyproject() -> str:
    """The template's pyproject, close enough to a render for the anchors to be judged.

    The Jinja tags sit on lines of their own, and the anchors the renderer edits are
    plain lines between them, so the source text carries every anchor a render would.
    """
    return _TEMPLATE_PYPROJECT.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# The overlay stays current with the template                                 #
# --------------------------------------------------------------------------- #


def test_every_template_file_the_overlay_replaces_is_at_its_recorded_digest() -> None:
    recorded = json.loads(reference.BASELINE.read_text(encoding="utf-8"))["files"]
    current = reference.template_digests()
    moved = sorted(name for name in current if recorded.get(name) != current[name])
    unrecorded_extra = sorted(set(recorded) - set(current))
    assert not moved and not unrecorded_extra, (
        "the template changed a file the reference app keeps its own copy of: "
        f"{moved or unrecorded_extra}. Carry the change into apps/reference/overlay/<file> "
        "(or decide it does not apply to the reference app), then run "
        "`python tools/render_reference_app.py --record-baseline`."
    )


def test_the_baseline_covers_the_files_a_client_app_changes_first() -> None:
    # The composition root, the control plane and both compose profiles are the files a
    # grown app always edits. If one dropped out of the baseline, a template change to it
    # would stop reaching the reference app with nothing saying so.
    replaced = set(reference.replaced_template_files())
    assert {
        "app/main.py",
        "control_plane/__init__.py",
        "docker-compose.yml",
        "docker-compose.prod.yml",
    } <= replaced
    # And the files copier hands to the app on the first render are not in it: an
    # upgrade never rewrites them, so there is nothing to carry.
    assert not replaced & {"workbench.json", "environment.schema.json", "deployment.json"}


def test_a_line_ending_is_not_a_template_change(tmp_path: pathlib.Path) -> None:
    unix, windows = tmp_path / "unix", tmp_path / "windows"
    unix.write_bytes(b"one\ntwo\n")
    windows.write_bytes(b"one\r\ntwo\r\n")
    assert reference._digest(unix) == reference._digest(windows)


def test_template_source_finds_plain_and_jinja_sources_and_nothing_else() -> None:
    assert reference.template_source("control_plane/__init__.py") == (
        reference.TEMPLATE_PROJECT / "control_plane" / "__init__.py"
    )
    assert reference.template_source("app/main.py") == (
        reference.TEMPLATE_PROJECT / "app" / "main.py.jinja"
    )
    assert reference.template_source("monitor/watch.py") is None


def test_record_baseline_writes_what_the_check_reads(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    baseline = tmp_path / "template-baseline.json"
    monkeypatch.setattr(reference, "BASELINE", baseline)
    assert reference.main(["--record-baseline"]) == 0
    assert json.loads(baseline.read_text(encoding="utf-8"))["files"] == reference.template_digests()


# --------------------------------------------------------------------------- #
# The renderer                                                                 #
# --------------------------------------------------------------------------- #


def test_the_template_carries_every_anchor_the_renderer_edits() -> None:
    grown = reference.extend_pyproject(_template_pyproject())
    version = re.search(r'"terp-core==([^"]+)"', grown).group(1)
    for name in reference.ADDED_DISTRIBUTIONS:
        assert f'"{name}=={version}",' in grown
    assert f'companions = ["{reference.COMPANION}"]' in grown
    assert f'packages = ["app", "control_plane", "{reference.COMPANION}"]' in grown
    assert f'known_first_party = ["app", "control_plane", "{reference.COMPANION}"]' in grown
    assert f'"{reference.IMPORT_LINTER}"]' in grown
    assert grown.rstrip().endswith('forbidden_modules = ["monitor"]')


@pytest.mark.parametrize(
    ("damage", "message"),
    [
        (lambda text: text.replace('"terp-core==', '"terp-kernel=='), "no terp-core pin"),
        (lambda text: text.replace('"terp-cap-audit==', '"terp-cap-trail=='), "terp-cap-audit"),
        (lambda text: text.replace("\ndev = [", "\ndevelopment = ["), "dependency group"),
        (lambda text: text.replace('app_packages = ["control_plane"]', "app_packages = []"), "app_packages"),
        (
            lambda text: text.replace(
                'packages = ["app", "control_plane"]',
                'packages = ["app", "control_plane"]\n# packages = ["app", "control_plane"]',
            ),
            "found 2",
        ),
        (lambda text: text + "\n[tool.importlinter]\n", "already declares"),
    ],
    ids=["no-pin", "no-audit-line", "no-dev-group", "no-app-packages", "ambiguous", "importlinter"],
)
def test_a_template_of_another_shape_is_refused_by_name(damage, message) -> None:
    with pytest.raises(reference.RenderError, match=message):
        reference.extend_pyproject(damage(_template_pyproject()))


def _fake_copier(rendered_pyproject: str):
    """A runner that does what `copier copy` does to DEST, as far as the renderer reads it."""
    calls: list[list[str]] = []

    def _run(command: list[str], *, check: bool) -> None:
        assert check
        calls.append(command)
        dest = pathlib.Path(command[-1])
        dest.mkdir(parents=True)
        (dest / "pyproject.toml").write_text(rendered_pyproject, encoding="utf-8")

    return calls, _run


def test_render_runs_copier_with_the_pinned_answers_then_grows_and_overlays(
    tmp_path: pathlib.Path,
) -> None:
    calls, run = _fake_copier(_template_pyproject())
    dest = tmp_path / "app"
    written = reference.render(dest, copier=["copier"], run=run)

    assert calls == [
        [
            "copier",
            "copy",
            "--defaults",
            "--trust",
            "--data-file",
            str(reference.ANSWERS),
            str(reference.TEMPLATE),
            str(dest),
        ]
    ]
    assert 'companions = ["monitor"]' in (dest / "pyproject.toml").read_text(encoding="utf-8")
    assert written == reference.overlay_files()
    for relative in written:
        assert (dest / relative).read_bytes() == (reference.OVERLAY / relative).read_bytes()


def test_render_refuses_a_directory_that_exists(tmp_path: pathlib.Path) -> None:
    with pytest.raises(reference.RenderError, match="already exists"):
        reference.render(tmp_path, run=lambda *args, **kwargs: None)


def test_the_answers_are_ones_the_template_asks_for() -> None:
    questions = yaml.safe_load((reference.TEMPLATE / "copier.yml").read_text(encoding="utf-8"))
    answers = yaml.safe_load(reference.ANSWERS.read_text(encoding="utf-8"))
    assert set(answers) <= {key for key in questions if not key.startswith("_")}
    # File storage is the one toggle the app's own code depends on.
    assert answers["use_files"] is True


def test_main_renders_and_reports(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture) -> None:
    _calls, run = _fake_copier(_template_pyproject())
    assert reference.main([str(tmp_path / "app"), "--copier", "copier"], run=run) == 0
    assert "rendered the reference app" in capsys.readouterr().out


def test_main_names_a_template_it_cannot_grow(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture
) -> None:
    _calls, run = _fake_copier("[project]\nname = 'not-the-template'\n")
    assert reference.main([str(tmp_path / "app")], run=run) == 1
    assert "no terp-core pin" in capsys.readouterr().err


def test_main_needs_a_destination() -> None:
    with pytest.raises(SystemExit) as raised:
        reference.main([])
    assert raised.value.code == 2


def test_the_overlay_carries_no_build_output(tmp_path: pathlib.Path, monkeypatch) -> None:
    # A stray __pycache__ from running the overlay's code in place must not be copied
    # into a render as if it were source.
    overlay = tmp_path / "overlay"
    shutil.copytree(reference.OVERLAY, overlay)
    (overlay / "app" / "__pycache__").mkdir(parents=True)
    (overlay / "app" / "__pycache__" / "main.cpython-314.pyc").write_bytes(b"\0")
    monkeypatch.setattr(reference, "OVERLAY", overlay)
    assert not any("__pycache__" in name for name in reference.overlay_files())


# --------------------------------------------------------------------------- #
# The lane                                                                     #
# --------------------------------------------------------------------------- #


def _acceptance() -> dict:
    workflow = yaml.safe_load(_FRAMEWORK_CI.read_text(encoding="utf-8"))
    return workflow["jobs"]["template-acceptance"]


def test_template_acceptance_renders_and_runs_the_reference_app() -> None:
    job = _acceptance()
    assert {"variant": "reference", "copier-args": ""} in job["strategy"]["matrix"]["include"]
    steps = [str(step.get("run", "")) for step in job["steps"]]
    joined = "\n".join(steps)
    # Rendered by the tool every lane uses, not restated in the workflow.
    assert "tools/render_reference_app.py /tmp/acceptance-app" in joined
    # Its deploy declaration by name (ADR 0184), then the whole quick profile, so the
    # check list stays `terp verify`'s own.
    assert "terp verify --only deployment" in joined
    assert "terp verify --profile quick" in joined
    assert (reference.OVERLAY / "deployment.json").is_file(), "the reference app is declared"
    # And the stack itself, through the app's own procedure rather than a copy of it.
    assert "scripts/check_stack.py --workbench" in joined


def test_the_stack_check_starts_every_service_the_app_adds() -> None:
    # The check is the overlay's own file; the services it starts are the ones the
    # reference app exists to carry beside the template's API.
    script = (reference.OVERLAY / "scripts" / "check_stack.py").read_text(encoding="utf-8")
    assert 'WORKBENCH_SERVICES = ("api", "worker", "scheduler", "monitor", "mailcatcher")' in script
    compose = yaml.safe_load((reference.OVERLAY / "docker-compose.yml").read_text(encoding="utf-8"))
    prod = yaml.safe_load((reference.OVERLAY / "docker-compose.prod.yml").read_text(encoding="utf-8"))
    for service in ("worker", "scheduler", "monitor"):
        # On the backend image in both profiles, so a deploy pins them with the API.
        assert compose["services"][service]["image"] == compose["services"]["api"]["image"]
        assert prod["services"][service]["image"] == prod["services"]["api"]["image"]
        # And nothing waits on them: none of them may turn readiness red.
        for other in (*compose["services"].values(), *prod["services"].values()):
            assert service not in (other.get("depends_on") or {}), f"something depends on {service}"
    assert "healthcheck" not in prod["services"]["scheduler"]
    assert "mailcatcher" not in prod["services"], "the production relay is a real, encrypted one"
