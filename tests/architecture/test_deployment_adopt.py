"""``terp deployment adopt``: a state change is two recorded facts written together (ADR 0187).

``"build"`` in ``deployment.json`` and ``deploy_build`` in ``.copier-answers.yml`` move as
one; ``--build generated`` renders and, in a template-shaped app at its template version,
changes no build file; ``--build own`` goes back with no file change, or declares an
undeclared app from its production profile; ``--unmanaged`` writes the opt-out. Every
refusal writes nothing. The copier half of the story - that copier honours the recorded
answer on every update - is ``tools/copier_round_trip.py``, run for real by
``test_copier_round_trip.py`` and by template acceptance.

A project here starts as the template's own: the seed declaration, the generator's render
of it (which is the template's three files), the template's ignore files, a project name, a
frontend lock and an answers file recording ``deploy_build: own``.
"""

from __future__ import annotations

import json
import pathlib
import shutil
import subprocess

import pytest
import yaml

from terp.arch.deployment import OWNED_PATHS, generate, generated, published_table, published_tables, read
from terp.cli import deployment_adopt, main
from terp.cli.deployment_adopt import (
    AdoptionRefused,
    plan_generated,
    plan_own,
    plan_unmanaged,
    run_adopt_command,
)
from terp.cli.deployment_declare import COMMENT, DeclareRefused, derive
from tests.architecture.deployment_fixtures import POSTGRES, REPO_ROOT, seed

_TEMPLATE = REPO_ROOT / "template" / "project"
_NAME = "demo-app"
_ANSWERS = (
    "# Managed by Copier.\n"
    "_commit: v0.35.0\n"
    "_src_path: gh:example/template\n"
    "deploy_build: own\n"
    "project_slug: demo-app\n"
)


def _rendered(raw: dict) -> dict[str, bytes]:
    declared, findings = read({**raw, "build": "generated"}, published_table())
    assert findings == [], findings
    files, refused = generate(declared, _NAME, tables=published_tables(), frontend_lock=True)
    assert refused == [], refused
    return files


def _app(
    tmp_path: pathlib.Path,
    raw: dict | None = None,
    *,
    answers: str | None = _ANSWERS,
    **files: str | bytes,
) -> pathlib.Path:
    """A template-shaped app: the seed (or *raw*), its render, the ignores, a lock, answers."""
    root = tmp_path / "app"
    root.mkdir(parents=True)
    declaration = raw if raw is not None else seed()
    base: dict[str, str | bytes] = {
        "deployment.json": json.dumps(declaration, indent=2) + "\n",
        "pyproject.toml": f'[project]\nname = "{_NAME}"\nversion = "0.1.0"\n',
        "frontend/package-lock.json": "{}\n",
        ".gitignore": (_TEMPLATE / ".gitignore").read_bytes(),
        ".dockerignore": (_TEMPLATE / ".dockerignore").read_bytes(),
        **_rendered(seed()),
    }
    if answers is not None:
        base[".copier-answers.yml"] = answers
    for name, content in {**base, **files}.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))
    return root


def _build_files(root: pathlib.Path) -> dict[str, bytes | None]:
    return {
        path: (root / path).read_bytes() if (root / path).is_file() else None
        for path in OWNED_PATHS
    }


def _state(root: pathlib.Path) -> tuple[str | None, str]:
    answers = root / ".copier-answers.yml"
    recorded = yaml.safe_load(answers.read_text(encoding="utf-8")) if answers.is_file() else {}
    declared = json.loads((root / "deployment.json").read_text(encoding="utf-8"))
    return recorded.get("deploy_build"), declared.get("build", "unmanaged")


def _refusal(plan, root: pathlib.Path, *args: str) -> str:
    with pytest.raises(AdoptionRefused) as excinfo:
        plan(root, *args)
    return str(excinfo.value)


# --------------------------------------------------------------------------- #
# --build generated                                                             #
# --------------------------------------------------------------------------- #
def test_a_template_shaped_app_adopts_generated_and_no_build_file_changes(tmp_path, capsys) -> None:
    root = _app(tmp_path)
    before = _build_files(root)
    declaration = (root / "deployment.json").read_text(encoding="utf-8")
    assert run_adopt_command(root=root, build="generated") == 0
    out = capsys.readouterr().out
    assert _build_files(root) == before, "the template's three files are the seed's render"
    assert _state(root) == ("generated", "generated")
    assert (root / "deployment.json").read_text(encoding="utf-8") == declaration.replace(
        '"build": "own"', '"build": "generated"'
    ), "only build changes, in place, the file's own formatting kept"
    answers = (root / ".copier-answers.yml").read_text(encoding="utf-8")
    assert answers == _ANSWERS.replace("deploy_build: own", "deploy_build: generated")
    assert "No build file changed: Dockerfile.prod, frontend/Dockerfile.prod, " in out
    assert "-deploy_build: own\n+deploy_build: generated" in out
    assert '-  "build": "own",\n+  "build": "generated",' in out
    assert "Wrote .copier-answers.yml, deployment.json. Commit them together." in out
    assert "`uv run terp deployment render`; `copier update` leaves the build files to it." in out
    result = generated(root)
    assert result.applies and result.drift.findings == []
    assert run_adopt_command(root=root, build="generated") == 0
    assert capsys.readouterr().out.splitlines()[-1] == (
        "Nothing to write: the app is in that state already."
    )


def test_adopting_generated_renders_and_removes_what_the_declaration_does_not_produce(
    tmp_path, capsys
) -> None:
    raw = seed()
    raw["units"] = [unit for unit in raw["units"] if unit["id"] != "web"]
    root = _app(tmp_path, raw, **{"frontend/Dockerfile.prod": "FROM stale\n", "Dockerfile.prod": "x\n"})
    assert run_adopt_command(root=root, build="generated") == 0
    out = capsys.readouterr().out
    assert "removed frontend/Dockerfile.prod" in out
    assert (
        "Build files changed: Dockerfile.prod, frontend/Dockerfile.prod, docker-compose.prod.yml."
        in out
    )
    assert not (root / "frontend/Dockerfile.prod").exists()
    assert generated(root).drift.findings == []


def test_a_dry_run_prints_the_diff_and_writes_nothing(tmp_path, capsys) -> None:
    root = _app(tmp_path)
    before = {path.name: path.read_bytes() for path in root.iterdir() if path.is_file()}
    assert run_adopt_command(root=root, build="generated", dry_run=True) == 0
    assert capsys.readouterr().out.rstrip().endswith("Nothing was written (--dry-run).")
    assert {path.name: path.read_bytes() for path in root.iterdir() if path.is_file()} == before


def test_an_app_without_an_answers_file_changes_its_declaration_only(tmp_path) -> None:
    root = _app(tmp_path, answers=None)
    plan = plan_generated(root)
    assert list(plan.changes) == ["deployment.json"]


def test_a_build_written_in_a_form_the_edit_cannot_find_is_written_whole(tmp_path) -> None:
    raw = seed()
    root = _app(tmp_path, raw)
    text = (root / "deployment.json").read_text(encoding="utf-8")
    (root / "deployment.json").write_text(
        text.replace('"build": "own"', '"build": "\\u006fwn"'), encoding="utf-8"
    )
    _before, after = plan_generated(root).changes["deployment.json"]
    assert after == (json.dumps({**raw, "build": "generated"}, indent=2) + "\n").encode("utf-8")


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        (lambda root: (root / "deployment.json").unlink(),
         "There is no deployment.json: declare the app first with `uv run terp deployment "
         "adopt --build own`"),
        (lambda root: (root / "deployment.json").write_text("{ nope", encoding="utf-8"),
         "deployment.json cannot be read, so it cannot be rewritten"),
        (lambda root: (root / "deployment.json").write_text(
            json.dumps({"unmanaged": True, "reason": "Deployed by hand."}), encoding="utf-8"),
         "deployment.json declares the app unmanaged (Deployed by hand.)"),
        (lambda root: (root / "docker-compose.prod.yml").write_text(
            (root / "docker-compose.prod.yml").read_text(encoding="utf-8").replace(
                "      migrate:" + chr(10) + "        condition: service_completed_successfully"
                + chr(10), ""),
            encoding="utf-8"),
         "units[2].dependsOn restates ['db', 'migrate']"),
        (lambda root: (root / ".copier-answers.yml").write_text(
            "_commit: v0.34.0\nproject_slug: demo-app\n", encoding="utf-8"),
         ".copier-answers.yml records no deploy_build: this app's scaffolding comes from a "
         "template version that does not ask it"),
        (lambda root: (root / ".copier-answers.yml").write_text("a: [unclosed\n", encoding="utf-8"),
         ".copier-answers.yml cannot be read as YAML"),
        (lambda root: (root / ".copier-answers.yml").write_text("- a list\n", encoding="utf-8"),
         ".copier-answers.yml holds no answers."),
        (lambda root: (root / ".copier-answers.yml").write_text(
            "{deploy_build: own, project_slug: demo-app}\n", encoding="utf-8"),
         "deploy_build in .copier-answers.yml is not written as one plain line"),
        (lambda root: (root / "pyproject.toml").unlink(),
         "The generator names the deployment after the project:"),
        (lambda root: (root / "pyproject.toml").write_text(
            '[project]\nname = "Demo_App"\n', encoding="utf-8"),
         'project.name "Demo_App" in pyproject.toml is not a name compose and Docker accept'),
        (lambda root: (root / "frontend/package-lock.json").unlink(),
         "and the checkout has no frontend/package-lock.json"),
        (lambda root: (root / ".dockerignore").write_text(".git\n", encoding="utf-8"),
         "An environment file the units load would reach git or an image:"),
    ],
    ids=[
        "undeclared", "unreadable", "unmanaged", "untrue", "predates-the-question",
        "answers-unreadable", "answers-not-a-mapping", "answer-not-a-plain-line",
        "no-project-name", "project-name-refused", "no-frontend-lock", "env-file-leaks",
    ],
)
def test_adopting_generated_is_refused_and_writes_nothing(tmp_path, capsys, change, expected) -> None:
    root = _app(tmp_path)
    change(root)
    before = {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}
    assert run_adopt_command(root=root, build="generated") == 1
    out = capsys.readouterr().out
    assert out.startswith("Nothing was written. ")
    assert expected in out, out
    assert {path: path.read_bytes() for path in root.rglob("*") if path.is_file()} == before


def test_an_untrue_declaration_is_refused_before_it_is_rendered(tmp_path) -> None:
    raw = seed()
    raw["units"][1]["command"] = ["terp", "migrate", "upgrade", "--app-root", "/srv/app"]
    root = _app(tmp_path, raw)
    profile = root / "docker-compose.prod.yml"
    profile.write_text(
        profile.read_text(encoding="utf-8").replace(
            '["terp", "migrate", "upgrade", "--app-root", "/srv/app"]', '["true"]'
        ),
        encoding="utf-8",
    )
    message = _refusal(plan_generated, root)
    assert "says what its profile does not" in message and "units[1].command restates" in message


def test_a_declaration_the_generated_state_cannot_read_is_refused(tmp_path) -> None:
    from tests.architecture.deployment_fixtures import project

    raw = seed()
    raw["volumes"] = [{"id": "files-data"}]
    profile = yaml.safe_load(_rendered(seed())["docker-compose.prod.yml"].decode("ascii"))
    profile["services"]["api"]["volumes"] = ["files-data:/srv/var/files"]
    profile["volumes"]["files-data"] = None
    root = project(tmp_path, raw, profile)
    message = _refusal(plan_generated, root)
    assert 'deployment.json cannot say "build": "generated" as it stands:' in message
    assert "volumes[0].mount is required" in message


def test_what_the_generator_cannot_render_keeps_the_app_own(tmp_path) -> None:
    raw = seed()
    raw["units"][1]["command"] = ["terp", "migrate", "upgrade", "--app-root", "/srv/app"]
    root = _app(tmp_path, raw)
    message = _refusal(plan_generated, root)
    assert 'The generator cannot render deployment.json faithfully, so the app stays "own":' in message
    assert "the generator owns the migration step" in message


def test_adopt_says_so_if_the_generated_check_is_still_red(tmp_path, capsys, monkeypatch) -> None:
    """A safety net: adoption is checked again from the files it wrote."""
    from terp.arch.deployment import Drift, Finding, Generated

    root = _app(tmp_path)
    red = Generated(True, "", Drift(findings=[Finding("still not the render", file="x")]))
    monkeypatch.setattr(deployment_adopt, "generated", lambda project_root: red)
    assert run_adopt_command(root=root, build="generated") == 1
    assert "still red under `terp verify --only generated`:\n  - x: still not the render" in (
        capsys.readouterr().out
    )


def test_adoption_in_a_git_work_tree_is_judged_by_git_too(tmp_path) -> None:
    if shutil.which("git") is None:
        pytest.skip("git is not on PATH")
    root = _app(tmp_path)
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    (root / ".gitignore").write_text("__pycache__/\n", encoding="utf-8")
    assert "git does not ignore .env" in _refusal(plan_generated, root)


# --------------------------------------------------------------------------- #
# --build own                                                                   #
# --------------------------------------------------------------------------- #
def test_back_to_own_changes_no_file_but_the_two_facts(tmp_path, capsys) -> None:
    root = _app(tmp_path)
    assert run_adopt_command(root=root, build="generated") == 0
    before = _build_files(root)
    assert run_adopt_command(root=root, build="own") == 0
    out = capsys.readouterr().out
    assert _build_files(root) == before
    assert _state(root) == ("own", "own")
    assert "Adopting \"build\": \"own\": the build files are the app's from here on." in out
    assert (root / ".copier-answers.yml").read_text(encoding="utf-8") == _ANSWERS
    assert run_adopt_command(root=root, build="own") == 0
    assert "Nothing to write" in capsys.readouterr().out


def test_own_puts_back_an_answer_that_disagrees(tmp_path) -> None:
    root = _app(tmp_path, answers=_ANSWERS.replace("deploy_build: own", "deploy_build: generated"))
    assert list(plan_own(root).changes) == [".copier-answers.yml"]


def test_own_leaves_answers_that_predate_the_question(tmp_path) -> None:
    root = _app(tmp_path, seed("generated"), answers="_commit: v0.34.0\nproject_slug: demo-app\n")
    assert list(plan_own(root).changes) == ["deployment.json"]


def test_an_undeclared_app_is_declared_from_its_profile(tmp_path, capsys) -> None:
    root = _app(tmp_path)
    (root / "deployment.json").unlink()
    before = _build_files(root)
    assert run_adopt_command(root=root, build="own") == 0
    out = capsys.readouterr().out
    written = json.loads((root / "deployment.json").read_text(encoding="utf-8"))
    expected = seed()
    del expected["units"][0]["backup"]
    assert written == {**expected, "$comment": COMMENT}, (
        "the template's own profile reads back as the template's seed, but for the backup "
        "policy a profile cannot state"
    )
    assert _build_files(root) == before
    assert "note: db is stateful and declares no backup policy; add one" in out
    assert "--- /dev/null\n+++ b/deployment.json" in out
    assert run_adopt_command(root=root, build="generated") == 0, "and it renders"
    assert _build_files(root) == before


def test_an_opt_out_is_replaced_by_the_profile_s_declaration(tmp_path) -> None:
    root = _app(tmp_path)
    (root / "deployment.json").write_text(
        json.dumps({"unmanaged": True, "reason": "Deployed by hand."}), encoding="utf-8"
    )
    _before, after = plan_own(root).changes["deployment.json"]
    assert json.loads(after)["build"] == "own"


def _derive(tmp_path: pathlib.Path, profile: str, **files: str) -> tuple[dict, str | None, list[str]]:
    root = tmp_path / "derive"
    root.mkdir(parents=True, exist_ok=True)
    (root / "docker-compose.prod.yml").write_text(profile, encoding="utf-8")
    for name, text in files.items():
        (root / name).write_text(text, encoding="utf-8")
    found = derive(root, published_table())
    return found.raw, found.profile, found.notes


_GROWN = """\
name: demo-prod
services:
  db:
    image: postgres:17-alpine
    volumes: ["db-data:/var/lib/postgresql/data"]
  migrate:
    image: demo-backend-prod
    command: ["terp", "migrate", "upgrade", "--app-root", "/srv/app"]
    restart: "no"
    depends_on: {db: {condition: service_healthy}}
  api:
    image: demo-backend-prod
    build: {context: ., dockerfile: Dockerfile.prod}
    depends_on: [db, migrate]
    volumes: ["files-data:/srv/var/files"]
  worker:
    image: demo-backend-prod
    command: "terp jobs worker --forever"
    volumes: ["files-data:/srv/var/files/"]
  scheduler:
    image: demo-backend-prod
    command: ["terp", "jobs", "scheduler", "--poll-seconds", "5"]
  monitor:
    image: demo-backend-prod
    command: ["python", "-m", "monitor"]
  report_job:
    image: demo-backend-prod
    command: ["python", "-m", "report"]
  echo:
    image: demo-backend-prod
    command: ["sh", "-c", "echo $${HOME} ${HOME}"]
  web:
    image: demo-frontend-prod
    build: {context: frontend}
    command: ["nginx", "-g", "daemon off;"]
  debug:
    image: demo-backend-prod
    profiles: [debug]
  scratch:
    image: demo-backend-prod
    command: ["sleep", "infinity"]
    volumes: ["tmp-data:/tmp/a", "tmp-data:/srv/var/b"]
volumes:
  db-data:
  files-data:
  tmp-data:
  unused:
"""


def test_what_each_service_becomes_is_read_from_the_profile(tmp_path) -> None:
    raw, pinned, notes = _derive(tmp_path, _GROWN)
    assert [(unit["id"], unit["role"]) for unit in raw["units"]] == [
        ("db", "database"),
        ("migrate", "one-shot"),
        ("api", "api"),
        ("worker", "worker"),
        ("scheduler", "scheduler"),
        ("monitor", "monitor"),
        ("echo", "echo"),
        ("web", "web"),
        ("scratch", "scratch"),
    ]
    units = {unit["id"]: unit for unit in raw["units"]}
    assert units["db"] == {"id": "db", "role": "database", "kind": "postgres", "version": "17",
                           "stateful": True}
    assert "command" not in units["migrate"] and "command" not in units["worker"], (
        "a command the generator renders by default for the role is not restated"
    )
    assert units["scheduler"]["command"] == ["terp", "jobs", "scheduler", "--poll-seconds", "5"]
    assert units["monitor"]["command"] == ["python", "-m", "monitor"]
    assert units["web"]["command"] == ["nginx", "-g", "daemon off;"]
    assert "command" not in units["echo"]
    assert units["api"]["dependsOn"] == ["db", "migrate"]
    assert units["api"]["healthPath"] == "/health/ready"
    assert raw["volumes"] == [
        {"id": "files-data", "mount": {"path": "var/files", "units": ["api", "worker"]}},
        {"id": "tmp-data"},
    ]
    assert pinned is not None and f"image: {POSTGRES.image}\n" in pinned
    assert "postgres:17-alpine" not in pinned
    assert notes == [
        "db is stateful and declares no backup policy; add one",
        "report_job is not declared: what it does cannot be read from the profile, and its "
        "name is not a role word (lower-case letters, digits and -); declare it yourself",
        "echo's command interpolates a variable, so it is not restated",
        "debug is not declared: it runs only under a compose profile",
        "volume files-data declares no backup policy; add one if it holds state",
        "volume tmp-data's mount is not restated: the declared units mount it at /tmp/a, "
        "var/b, not at one path inside var/",
        "volume tmp-data declares no backup policy; add one if it holds state",
    ]


def test_a_pinned_profile_is_written_with_the_declaration(tmp_path, capsys) -> None:
    root = tmp_path / "app"
    root.mkdir()
    (root / "docker-compose.prod.yml").write_text(
        "services:\n  db:\n    image: 'postgres:17'  # the database\n", encoding="utf-8"
    )
    assert run_adopt_command(root=root, build="own") == 0
    out = capsys.readouterr().out
    assert (root / "docker-compose.prod.yml").read_text(encoding="utf-8") == (
        f"services:\n  db:\n    image: {POSTGRES.image}  # the database\n"
    )
    assert "Build files changed: docker-compose.prod.yml." in out
    assert "note: docker-compose.prod.yml now pins each datastore to the datastore table's digest" in out


def test_a_datastore_that_cannot_be_pinned_in_place_is_refused(tmp_path) -> None:
    """A tag the line edit cannot reach (a flow mapping) leaves the profile running a tag, so
    the truth rule refuses the kind unit, and with it the whole adoption, before any write."""
    root = tmp_path / "app"
    root.mkdir()
    (root / "docker-compose.prod.yml").write_text(
        "services:\n  db: {image: 'postgres:17'}\n", encoding="utf-8"
    )
    with pytest.raises(DeclareRefused) as excinfo:
        derive(root, published_table())
    assert "the declaration read from the profile would not hold against it" in str(excinfo.value)
    assert f"and the datastore table pins {POSTGRES.image}" in str(excinfo.value)
    assert not (root / "deployment.json").exists()


@pytest.mark.parametrize(
    ("profile", "expected"),
    [
        (None, 'docker-compose.prod.yml" does not exist'),
        ("services: [\n", "docker-compose.prod.yml is not readable YAML"),
        ("services:\n  cache:\n    image: redis:7\n  db:\n    image: postgres:17\n",
         'service "cache" runs redis:7, which no service of docker-compose.prod.yml builds from '
         "the checkout and the datastore table does not carry (postgres 17)"),
        ("services:\n  db:\n    image: postgres:16\n",
         'service "db" runs postgres:16, whose version the datastore table does not carry '
         "(allowed: postgres 17"),
        ("services:\n  db:\n    image: postgres@sha256:" + "0" * 64 + "\n",
         "whose version the datastore table does not carry"),
        ("services:\n  db:\n    image: postgres\n", "whose version the datastore table does not carry"),
        ("services:\n  side:\n    image: x\n    profiles: [debug]\n",
         "docker-compose.prod.yml runs no service a declaration could name."),
        ("services:\n  api:\n    build: .\n    image: x\n    command: ['']\n",
         "the declaration read from the profile would not hold against it"),
    ],
    ids=["no-profile", "unreadable", "foreign-image", "version-not-carried", "unknown-digest",
         "no-tag", "nothing-to-declare", "unreadable-result"],
)
def test_a_profile_a_declaration_cannot_state_is_refused(tmp_path, profile, expected) -> None:
    root = tmp_path / "app"
    root.mkdir()
    if profile is not None:
        (root / "docker-compose.prod.yml").write_text(profile, encoding="utf-8")
    with pytest.raises(DeclareRefused) as excinfo:
        derive(root, published_table())
    assert expected in str(excinfo.value)
    assert _refusal(plan_own, root).startswith(str(excinfo.value)[:40])


def test_a_declaration_its_own_truth_rule_refuses_is_never_written(tmp_path) -> None:
    """The truth rule is the last word: a derivation it would refuse is refused instead."""
    root = tmp_path / "app"
    root.mkdir()
    (root / "docker-compose.prod.yml").write_text(
        "services:\n  api:\n    image: x\n    build: {context: ../outside}\n", encoding="utf-8"
    )
    (root / ".git").mkdir()
    with pytest.raises(DeclareRefused) as excinfo:
        derive(root, published_table())
    assert "build.context '../outside' resolves outside the checkout" in str(excinfo.value)


# --------------------------------------------------------------------------- #
# --unmanaged                                                                   #
# --------------------------------------------------------------------------- #
def test_the_opt_out_is_written_and_the_template_takes_the_build_files_back(tmp_path) -> None:
    root = _app(tmp_path)
    assert run_adopt_command(root=root, build="generated") == 0
    before = _build_files(root)
    assert run_adopt_command(root=root, unmanaged="  Deployed by the platform team.  ") == 0
    assert json.loads((root / "deployment.json").read_text(encoding="utf-8")) == {
        "schemaVersion": 1,
        "unmanaged": True,
        "reason": "Deployed by the platform team.",
    }
    assert _state(root) == ("own", "unmanaged")
    assert _build_files(root) == before
    assert generated(root).applies is False
    assert plan_unmanaged(root, "Deployed by the platform team.").changes == {}


def test_an_opt_out_needs_a_reason(tmp_path, capsys) -> None:
    root = _app(tmp_path)
    assert run_adopt_command(root=root, unmanaged="   ") == 1
    assert "Nothing was written. The opt-out cannot carry that reason:" in capsys.readouterr().out


# --------------------------------------------------------------------------- #
# the command                                                                   #
# --------------------------------------------------------------------------- #
def test_main_dispatches_adopt(tmp_path, capsys) -> None:
    root = _app(tmp_path)
    for argv, code in (
        (["deployment", "adopt", "--build", "generated", "--root", str(root), "--dry-run"], 0),
        (["deployment", "adopt", "--build", "generated", "--root", str(root)], 0),
        (["deployment", "adopt", "--build", "own", "--root", str(root)], 0),
        (["deployment", "adopt", "--unmanaged", "", "--root", str(root)], 1),
    ):
        with pytest.raises(SystemExit) as excinfo:
            main(argv)
        assert excinfo.value.code == code, argv
    assert _state(root) == ("own", "own")
    with pytest.raises(SystemExit) as excinfo:
        main(["deployment", "adopt", "--root", str(root)])
    assert excinfo.value.code == 2, "a state is required: --build or --unmanaged"
    capsys.readouterr()
