"""The generated state: read, held to its render, and rendered (ADR 0187 decisions 1 and 3).

``build: generated`` is accepted from the same commit as its drift check: the reader reads it
and the generator's two words, ``deployment_generated_files_match_their_render`` refuses a
committed copy that is not the render (and an environment file a unit loads that git or the
build context would carry, and a template answer that disagrees), ``terp verify --only
generated`` runs that rule in every profile, and ``terp deployment render`` writes the render.

A project here is the template's own: its seed declaration set to ``generated``, the
generator's render of it, the template's ``.gitignore`` and ``.dockerignore``, a
``pyproject.toml`` and a frontend lock. Each case then breaks one thing.
"""

from __future__ import annotations

import copy
import json
import pathlib
import shutil
import subprocess

import pytest

import terp.arch as arch
from terp.arch.deployment import (
    Drift,
    SystemPackageTable,
    generated,
    published_table,
    read,
    readable,
    untrue,
)
from terp.arch.deployment import render_check
from terp.arch.deployment.generator import OWNED_PATHS, generate
from terp.arch.deployment.tables import load_system_packages, published_tables
from terp.cli import main
from terp.cli import deployment_render
from terp.cli.deployment_render import run_generated_check, run_render_command
from tests.architecture.deployment_fixtures import REPO_ROOT, seed

_TEMPLATE = REPO_ROOT / "template" / "project"
_NAME = "demo-app"


def _seed_generated(**changes: object) -> dict:
    raw = seed()
    raw["build"] = "generated"
    raw.update(copy.deepcopy(changes))
    return raw


def _write(root: pathlib.Path, files: dict[str, bytes | str]) -> None:
    for name, content in files.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))


def _project(
    tmp_path: pathlib.Path,
    raw: dict | None = None,
    *,
    git: bool = False,
    render: bool = True,
    **files: bytes | str,
) -> pathlib.Path:
    root = tmp_path / "project"
    root.mkdir(parents=True)
    declaration = raw if raw is not None else _seed_generated()
    base = {
        "deployment.json": json.dumps(declaration, indent=2) + "\n",
        "pyproject.toml": f'[project]\nname = "{_NAME}"\nversion = "0.1.0"\n',
        "frontend/package-lock.json": "{}\n",
        ".gitignore": (_TEMPLATE / ".gitignore").read_bytes(),
        ".dockerignore": (_TEMPLATE / ".dockerignore").read_bytes(),
    }
    _write(root, base)
    if render:
        declared, findings = read(declaration, published_table())
        assert findings == [], findings
        rendered, refused = generate(declared, _NAME, tables=published_tables(), frontend_lock=True)
        assert refused == []
        _write(root, rendered)
    if git:
        subprocess.run(["git", "init", "-q", str(root)], check=True)  # noqa: S603, S607
    _write(root, {name.replace("__", "/").replace("_dot_", "."): data for name, data in files.items()})
    return root


def _findings(root: pathlib.Path) -> list[str]:
    return [f"{finding.file}: {finding.message}" for finding in generated(root).drift.findings]


# --------------------------------------------------------------------------- #
# the reader reads the generated state and the two words                       #
# --------------------------------------------------------------------------- #
def test_generated_is_read_now_that_its_drift_check_ships() -> None:
    declared, findings = read(_seed_generated(), published_table())
    assert findings == [] and declared.build == "generated"


def test_a_generator_block_beside_own_is_refused_at_the_block() -> None:
    raw = seed()
    raw["generator"] = {"systemPackages": []}
    declared, findings = read(raw, published_table())
    assert declared is None
    messages = [finding.message for finding in findings]
    assert messages == [
        'generator stands beside build "own": the generator\'s words are read only where '
        'build is "generated" (allowed: no generator block beside own)'
    ], "named at the block, not at build, where the schema states the same refusal"
    assert read({"unmanaged": True, "reason": "x", "generator": {}}, published_table())[1]


def test_a_system_package_resolves_against_the_table_it_is_given(tmp_path) -> None:
    raw = _seed_generated(generator={"systemPackages": ["libpq5"]})
    _declared, findings = read(raw, published_table())
    assert [finding.message for finding in findings] == [
        'generator.systemPackages[0] "libpq5" is not in the system-package table (allowed: a '
        "package of the table: none in this release)"
    ]
    offered = SystemPackageTable(("libpq5", "zlib1g"))
    declared, findings = read(raw, published_table(), offered)
    assert findings == [] and declared.system_packages == ("libpq5",)
    table = tmp_path / "system-package-table.json"
    table.write_text(json.dumps({"packages": {"libpq5": {}}}), encoding="utf-8")
    assert load_system_packages(table).packages == ("libpq5",)
    assert load_system_packages(tmp_path / "absent.json").packages == ()
    root = _project(tmp_path, raw, render=False)
    assert arch.check_deployment_declaration_is_readable(root, system_package_table=table) == []
    assert arch.check_deployment_declaration_is_readable(root, system_package_table=offered) == []
    assert arch.check_deployment_declaration_is_readable(root)


def test_a_mount_names_declared_units_and_a_path_inside_var() -> None:
    mount = {"path": "var/files", "units": ["api", "worker"]}
    _declared, findings = read(seed() | {"volumes": [{"id": "files", "mount": mount}]},
                               published_table())
    assert [finding.message for finding in findings] == [
        'volumes[0].mount.units[1] "worker" is no declared unit (allowed: a declared unit\'s '
        "id: api, db, migrate, web)"
    ]
    for path in ("data", "var/../etc", "/srv/var/files"):
        bad = {"id": "files", "mount": {"path": path, "units": ["api"]}}
        assert read(seed() | {"volumes": [bad]}, published_table())[1], path
    unmounted = _seed_generated(volumes=[{"id": "files"}])
    assert [f.message for f in read(unmounted, published_table())[1]] == [
        "volumes[0].mount is required"
    ]


# --------------------------------------------------------------------------- #
# the truth rule holds a restated mount to the profile                         #
# --------------------------------------------------------------------------- #
def _mounted_project(tmp_path: pathlib.Path, mount: dict, *, api: str, worker: str | None) -> pathlib.Path:
    from tests.architecture.deployment_fixtures import profile, project

    raw = seed()
    raw["units"].append({"id": "worker", "role": "worker", "dependsOn": ["db", "migrate"]})
    raw["volumes"] = [{"id": "files-data", "mount": mount}]
    services = profile()["services"]
    worker_service = dict(services["api"], command=["terp", "jobs", "worker", "--forever"])
    worker_service.pop("build", None)
    worker_service.pop("healthcheck", None)
    worker_service["volumes"] = [worker] if worker else []
    data = profile(api=dict(services["api"], volumes=[api]), worker=worker_service)
    data["volumes"] = {"db-data": None, "files-data": None}
    return project(tmp_path, raw, data)


def test_a_restated_mount_is_the_profile_s(tmp_path) -> None:
    mount = {"path": "var/files", "units": ["api", "worker"]}
    root = _mounted_project(tmp_path / "true", mount, api="files-data:/srv/var/files",
                            worker="files-data:/srv/var/files/")
    assert untrue(root) == []
    wrong_units = _mounted_project(tmp_path / "units", mount, api="files-data:/srv/var/files",
                                   worker=None)
    assert [f.message for f in untrue(wrong_units)] == [
        "volumes[0].mount.units restates ['api', 'worker'], and docker-compose.prod.yml mounts "
        "files-data at var/files on api (allowed: the declared units whose services mount "
        "files-data at var/files: api)"
    ]
    elsewhere = dict(mount, path="var/uploads")
    wrong_path = _mounted_project(tmp_path / "path", elsewhere, api="files-data:/srv/var/files",
                                  worker="files-data:/data")
    assert [f.message for f in untrue(wrong_path)] == [
        'volumes[0].mount.path is "var/uploads", and docker-compose.prod.yml mounts files-data at '
        "/data, var/files on the declared units (allowed: where the profile mounts files-data: "
        "/data, var/files, relative to /srv)"
    ]


# --------------------------------------------------------------------------- #
# the rule: a copy that is not the render is refused                           #
# --------------------------------------------------------------------------- #
def test_the_template_s_own_render_is_silent_but_for_its_notes(tmp_path) -> None:
    result = generated(_project(tmp_path))
    assert result.applies and result.drift.findings == []
    assert set(result.drift.files) == set(OWNED_PATHS)
    assert result.drift.notes == [
        "the git half of the environment-file check is not judged: the project lies in no git "
        "work tree"
    ]


def test_a_render_in_a_git_work_tree_is_judged_by_git_too(tmp_path) -> None:
    if shutil.which("git") is None:
        pytest.skip("git is not on PATH")
    root = _project(tmp_path, git=True)
    assert generated(root).drift.notes == [] and _findings(root) == []
    (root / ".gitignore").write_text("__pycache__/\n", encoding="utf-8")
    assert _findings(root) == [
        ".gitignore: git does not ignore .env, .app.env, .app.migrate.env, .app.api.env, and the "
        "units deployment.json declares load them, so a commit can carry them (allowed: "
        ".gitignore patterns that cover .env, .app.env and each backend unit's .app.<id>.env)"
    ]


def test_a_git_marker_git_cannot_read_is_no_work_tree(tmp_path) -> None:
    if shutil.which("git") is None:
        pytest.skip("git is not on PATH")
    root = _project(tmp_path)
    (root / ".git").mkdir()
    assert generated(root).drift.notes == [
        "the git half of the environment-file check is not judged: the project lies in no git "
        "work tree"
    ]
    assert _findings(root) == []


def test_git_that_cannot_answer_is_a_finding_and_no_git_a_note(tmp_path, monkeypatch) -> None:
    root = _project(tmp_path, git=True)

    class Answer:
        def __init__(self, argv: list[str]) -> None:
            inside = "rev-parse" in argv
            self.returncode = 0 if inside else 128
            self.stdout = "true\n" if inside else ""
            self.stderr = "" if inside else "fatal: bad config line"

    monkeypatch.setattr(render_check.subprocess, "run", lambda argv, **kwargs: Answer(argv))
    assert _findings(root)[0] == (
        ".gitignore: git check-ignore cannot read the ignore rules for .env: fatal: bad config "
        "line (allowed: ignore rules git reads)"
    )
    monkeypatch.setattr(render_check.shutil, "which", lambda name: None)
    assert generated(root).drift.notes == [
        "the git half of the environment-file check is not judged: git is not on PATH"
    ]


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        (
            lambda root: (root / "Dockerfile.prod").write_bytes(
                (root / "Dockerfile.prod").read_bytes().replace(b"USER appuser", b"USER root")
            ),
            "Dockerfile.prod: Dockerfile.prod is not the render of deployment.json (allowed: the "
            "generator's render, never an edit of the file):\n--- Dockerfile.prod (committed)\n"
            "+++ Dockerfile.prod (render)",
        ),
        (
            lambda root: (root / "docker-compose.prod.yml").unlink(),
            "docker-compose.prod.yml: docker-compose.prod.yml is missing, and deployment.json "
            "renders it (allowed: the generator's render)",
        ),
        (
            lambda root: (root / "docker-compose.prod.yml").write_bytes(
                (root / "docker-compose.prod.yml").read_bytes().replace(b"\n", b"\r\n")
            ),
            "docker-compose.prod.yml: docker-compose.prod.yml is not the render of deployment.json",
        ),
    ],
    ids=["edited", "missing", "crlf"],
)
def test_a_generator_owned_file_that_is_not_the_render_is_refused(tmp_path, change, expected) -> None:
    root = _project(tmp_path)
    change(root)
    (finding,) = generated(root).drift.findings
    assert f"{finding.file}: {finding.message}".startswith(expected)
    assert finding.remedy.startswith("Run `uv run terp deployment render`")


def test_a_generator_owned_path_the_render_does_not_produce_is_refused(tmp_path) -> None:
    raw = _seed_generated()
    raw["units"] = [unit for unit in raw["units"] if unit["id"] != "web"]
    root = _project(tmp_path, raw, **{"frontend__Dockerfile.prod": "FROM scratch\n"})
    assert _findings(root) == [
        "frontend/Dockerfile.prod: frontend/Dockerfile.prod exists, and deployment.json renders "
        "nothing for it: no web unit is declared (allowed: no file)"
    ]
    only_db = _seed_generated()
    only_db["units"] = only_db["units"][:1]
    root = _project(tmp_path / "db", only_db, **{"Dockerfile.prod": "FROM scratch\n"})
    assert "Dockerfile.prod exists, and deployment.json renders nothing for it: no unit runs the "\
        "backend image (allowed: no file)" in _findings(root)[0]


def test_what_the_generator_refuses_is_the_finding_word_for_word(tmp_path) -> None:
    raw = _seed_generated()
    raw["units"][2]["dependsOn"] = ["db", "migrate", "web"]
    declared = read(raw, published_table())[0]
    _files, refused = generate(declared, _NAME, tables=published_tables(), frontend_lock=True)
    root = _project(tmp_path, raw, render=False)
    assert generated(root).drift.findings == refused != []
    assert generated(root).drift.files == {}


@pytest.mark.parametrize(
    ("pyproject", "expected"),
    [
        (None, "pyproject.toml: pyproject.toml is missing, and the generator names the compose "
               "project and the images after its project.name"),
        ("[project\n", "pyproject.toml: pyproject.toml cannot be read as TOML"),
        ("[tool.x]\n", "pyproject.toml: pyproject.toml declares no project.name"),
        ('[project]\nname = "Demo_App"\n', 'pyproject.toml: project.name "Demo_App" in '
                                            "pyproject.toml is not a name compose and Docker"),
    ],
    ids=["missing", "unreadable", "no-name", "refused"],
)
def test_the_project_name_is_read_verbatim_or_refused(tmp_path, pyproject, expected) -> None:
    root = _project(tmp_path)
    if pyproject is None:
        (root / "pyproject.toml").unlink()
    else:
        (root / "pyproject.toml").write_text(pyproject, encoding="utf-8")
    assert _findings(root)[0].startswith(expected)


def test_an_environment_file_the_build_context_would_carry_is_refused(tmp_path) -> None:
    root = _project(tmp_path, **{"_dot_dockerignore": ".git\n[unclosed\n**/.env\n"})
    assert _findings(root) == [
        ".dockerignore: .dockerignore line 2 '[unclosed' cannot be read: a character class that "
        "never closes (allowed: a pattern Docker's matcher reads)",
        ".dockerignore: .dockerignore lets .app.env, .app.migrate.env, .app.api.env into the build "
        "context, and the units deployment.json declares load them, so a `COPY . .` bakes them "
        "into an image layer (allowed: patterns that leave .env, .app.env and each backend unit's "
        ".app.<id>.env out of the build context, such as **/.env and **/.app.*.env)",
    ]
    (root / ".dockerignore").unlink()
    assert ".dockerignore lets .env, .app.env" in _findings(root)[0]


@pytest.mark.parametrize(
    ("answers", "findings", "notes"),
    [
        (None, [], []),
        ("_src_path: template\nproject_slug: demo\n", [],
         [".copier-answers.yml records no deploy_build: the template version it was rendered "
          "from does not ask, so the build it records is not compared"]),
        ("deploy_build: generated\n", [], []),
        ("deploy_build: own\n",
         ['.copier-answers.yml: deploy_build is \'own\' in .copier-answers.yml, and deployment.json '
          'says "build": "generated" (allowed: generated, the build deployment.json declares)'],
         []),
        ("a: [unclosed\n", [".copier-answers.yml: .copier-answers.yml cannot be read as YAML"], []),
    ],
    ids=["none", "predates", "agrees", "disagrees", "unreadable"],
)
def test_the_template_answer_agrees_with_the_declaration(tmp_path, answers, findings, notes) -> None:
    root = _project(tmp_path) if answers is None else _project(
        tmp_path, **{"_dot_copier-answers.yml": answers}
    )
    result = generated(root)
    found = [f"{finding.file}: {finding.message}" for finding in result.drift.findings]
    assert len(found) == len(findings) and all(a.startswith(b) for a, b in zip(found, findings))
    assert result.drift.notes[1:] == notes


def test_a_profile_terp_release_will_refuse_is_noted_never_red(tmp_path) -> None:
    raw = _seed_generated()
    raw["units"] = [raw["units"][0], {"id": "worker", "role": "worker", "dependsOn": ["db"]}]
    root = _project(tmp_path, raw)
    result = generated(root)
    assert result.drift.findings == []
    assert result.drift.notes[-1] == (
        "terp release will refuse this profile (ADR 0184 decision 9): it has no migration step "
        "and 0 api units, so no one image runs the upgrade"
    )


@pytest.mark.parametrize(
    ("declaration", "reason"),
    [
        (None, "no deployment.json: nothing is generated here"),
        ("{ nope", "deployment.json cannot be read, which `terp verify --only deployment` reports"),
        ({"unmanaged": True, "reason": "Deployed elsewhere."},
         "deployment.json is unmanaged: Deployed elsewhere."),
        (seed(), 'deployment.json says "build": "own": the build files are the app\'s own'),
    ],
    ids=["undeclared", "unreadable", "unmanaged", "own"],
)
def test_every_other_state_is_silent(tmp_path, declaration, reason) -> None:
    root = tmp_path / "project"
    root.mkdir()
    (root / "Dockerfile.prod").write_text("FROM scratch\n", encoding="utf-8")
    if declaration is not None:
        text = declaration if isinstance(declaration, str) else json.dumps(declaration)
        (root / "deployment.json").write_text(text, encoding="utf-8")
    result = generated(root)
    assert (result.applies, result.reason, result.drift) == (False, reason, Drift())
    assert arch.check_deployment_generated_files_match_their_render(root) == []
    assert run_generated_check(root) == (0, f"{reason} (nothing to compare with a render)")


def test_the_rule_reports_each_finding_against_its_file(tmp_path) -> None:
    root = _project(tmp_path)
    (root / "Dockerfile.prod").write_text("FROM scratch\n", encoding="utf-8")
    (violation,) = arch.check_deployment_generated_files_match_their_render(root)
    assert violation.rule == "deployment_generated_files_match_their_render"
    assert violation.path == "Dockerfile.prod" and violation.line == 0
    assert violation.message.endswith("and commit what it writes, together with deployment.json.")
    assert readable(root)[1] == [], "a drift is never a reason the file cannot be read"


# --------------------------------------------------------------------------- #
# terp verify --only generated                                                  #
# --------------------------------------------------------------------------- #
def test_the_check_is_in_every_profile_after_locks_and_reached_by_its_own_runner(
    tmp_path, capsys
) -> None:
    from terp.cli import verify as verify_module

    for checks in verify_module.PROFILES.values():
        ids = [check.id for check in checks]
        assert ids.index("locks") < ids.index("generated") < ids.index("deploy-safety")
    (check,) = {check for checks in verify_module.PROFILES.values() for check in checks
                if check.id == "generated"}
    assert check.category == "build" and "deployment.json" in check.scope
    assert set(OWNED_PATHS) <= set(check.scope)
    root = _project(tmp_path)
    (root / "Dockerfile.prod").write_text("FROM scratch\n", encoding="utf-8")
    with pytest.raises(SystemExit) as excinfo:
        main(["verify", "--root", str(root), "--only", "generated", "--format", "json"])
    assert excinfo.value.code == 1
    (result,) = json.loads(capsys.readouterr().out)["checks"]
    assert result["id"] == "generated" and result["category"] == "build"
    assert "Dockerfile.prod is not the render of deployment.json" in result["output_tail"]


def test_the_runner_says_what_it_compared_and_what_it_did_not_judge(tmp_path) -> None:
    code, output = run_generated_check(_project(tmp_path))
    assert code == 0
    assert output.splitlines() == [
        "every generator-owned file is the render of deployment.json: Dockerfile.prod, "
        "frontend/Dockerfile.prod, docker-compose.prod.yml",
        "note: the git half of the environment-file check is not judged: the project lies in no "
        "git work tree",
    ]


# --------------------------------------------------------------------------- #
# terp deployment render                                                        #
# --------------------------------------------------------------------------- #
def test_render_writes_the_render_and_removes_what_it_no_longer_renders(tmp_path, capsys) -> None:
    raw = _seed_generated()
    raw["units"] = [unit for unit in raw["units"] if unit["id"] != "web"]
    root = _project(tmp_path, raw, render=False, **{"frontend__Dockerfile.prod": "FROM x\n"})
    (root / "Dockerfile.prod").write_text("stale\n", encoding="utf-8")
    assert run_render_command(root=root) == 0
    out = capsys.readouterr().out
    assert out.splitlines() == [
        "wrote Dockerfile.prod",
        "wrote docker-compose.prod.yml",
        "removed frontend/Dockerfile.prod",
        "commit them together with deployment.json",
    ]
    assert generated(root).drift.findings == []
    assert not list(root.rglob("*.terp-render")), "no staged file is left behind"
    assert run_render_command(root=root) == 0
    assert "every generator-owned file was already the render" in capsys.readouterr().out
    assert run_render_command(root=root, check=True) == 0


def test_render_refuses_every_state_but_generated_and_writes_nothing(tmp_path, capsys) -> None:
    root = _project(tmp_path, seed(), render=False)
    assert run_render_command(root=root) == 1
    assert capsys.readouterr().out.splitlines() == [
        'nothing rendered: deployment.json says "build": "own": the build files are the app\'s own',
        'The generator writes the build files only where deployment.json says "build": '
        '"generated".',
    ]
    assert not (root / "Dockerfile.prod").exists()


def test_render_refuses_what_the_generator_cannot_render(tmp_path, capsys) -> None:
    raw = _seed_generated(compose={"file": "deploy/compose.yml"})
    root = _project(tmp_path, raw, render=False)
    assert run_render_command(root=root) == 1
    out = capsys.readouterr().out
    assert "nothing rendered: the generator cannot render deployment.json as it stands." in out
    assert '- deployment.json: compose.file is "deploy/compose.yml"' in out
    assert not (root / "docker-compose.prod.yml").exists()


def test_render_still_red_says_what_rendering_does_not_fix(tmp_path, capsys) -> None:
    root = _project(tmp_path, render=False, **{"_dot_dockerignore": ".git\n"})
    assert run_render_command(root=root) == 1
    out = capsys.readouterr().out
    assert "still red under `terp verify --only generated`:" in out
    assert "- .dockerignore: .dockerignore lets .env" in out


def test_render_writes_every_file_or_none(tmp_path, monkeypatch) -> None:
    root = _project(tmp_path, render=False)
    committed = {path: f"committed {path}\n".encode() for path in OWNED_PATHS}
    _write(root, committed)
    real = pathlib.Path.write_bytes
    written: list[str] = []

    def failing(self: pathlib.Path, data: bytes) -> int:
        if written:
            raise OSError("disk full")
        written.append(self.name)
        return real(self, data)

    monkeypatch.setattr(pathlib.Path, "write_bytes", failing)
    with pytest.raises(OSError, match="disk full"):
        run_render_command(root=root)
    assert not list(root.rglob("*.terp-render")), "no staged file is left behind"
    assert {path: (root / path).read_bytes() for path in OWNED_PATHS} == committed, (
        "a render that fails part-way leaves every committed file as it was"
    )


def test_main_dispatches_render_and_check(tmp_path, capsys) -> None:
    root = _project(tmp_path)
    for argv in (["deployment", "render", "--root", str(root), "--check"],
                 ["deployment", "render", "--root", str(root)]):
        with pytest.raises(SystemExit) as excinfo:
            main(argv)
        assert excinfo.value.code == 0
    assert "every generator-owned file" in capsys.readouterr().out
    assert deployment_render.RENDER_COMMAND == "uv run terp deployment render"
