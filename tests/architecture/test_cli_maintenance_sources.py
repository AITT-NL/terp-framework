"""``terp maintenance``: the platform, the scaffolding and the base images (ADR 0214).

``npm`` is a real program here, a script on ``PATH`` that answers ``npm view`` the way the
registry would, so the process boundary, its exit code and its output are all the real ones.
The Python half is ``terp upgrade --check``'s own answer, held in ``test_cli_version``; here
only what the report makes of each answer is held. A registry is the in-memory OCI registry
``sign``'s tests read images from.
"""

from __future__ import annotations

import dataclasses
import json
import pathlib
import stat
import subprocess
from collections.abc import Callable
from typing import Any

import pytest

from terp.cli.maintenance import _images, _platform
from terp.cli.maintenance._report import Finding, Report, Source
from terp.cli.release._common import ReleaseError
from terp.cli.version import UpgradeStatus
from tests.architecture.test_release_image import FakeRegistry, layer


_CURRENT = UpgradeStatus(
    installed={"terp-core": "0.42.0"}, current="0.42.0", target=None, covers_whole_set=True,
    stragglers={}, rerender_blocker=None, scaffold_ref=None, error=None,
)


def _status(**fields: Any) -> UpgradeStatus:
    return dataclasses.replace(_CURRENT, **fields)


@pytest.mark.parametrize(
    ("status", "platform", "sources", "finding"),
    [
        (_status(current=None, installed={}), None, [Source("python-index", False, "no terp-* distribution is installed in this environment")], "source-unavailable"),
        (_status(error="uv failed: offline"), "0.42.0", [Source("python-index", False, "uv failed: offline")], "source-unavailable"),
        (_status(), "0.42.0", [Source("python-index", True)], None),
        (_status(target="0.43.0"), "0.42.0", [Source("python-index", True)], "platform-behind"),
    ],
)
def test_the_python_set_is_upgrade_check_s_own_answer(monkeypatch, tmp_path, status, platform, sources, finding) -> None:
    monkeypatch.setattr(_platform, "upgrade_status", lambda root: status)
    report = Report("app", str(tmp_path))
    assert _platform.python_platform(tmp_path, report) == platform
    assert report.sources == sources
    assert [f.kind for f in report.findings] == ([finding] if finding else [])


def test_a_newer_python_set_names_both_halves_and_waits_for_a_partial_one(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(_platform, "upgrade_status", lambda root: _status(target="0.43.0"))
    report = Report("app", str(tmp_path))
    _platform.python_platform(tmp_path, report)
    assert report.findings == [
        Finding("platform-behind", "terp-*", report.findings[0].remedy, ecosystem="PyPI", location="pyproject.toml", installed="0.42.0", latest="0.43.0")
    ]
    assert report.findings[0].remedy.startswith("Upgrade every terp-* and @terpjs/* package to 0.43.0 together")
    monkeypatch.setattr(_platform, "upgrade_status", lambda root: _status(target="0.43.0", covers_whole_set=False))
    partial = Report("app", str(tmp_path))
    _platform.python_platform(tmp_path, partial)
    assert partial.findings[0].remedy.startswith("Terp 0.43.0 does not yet cover every package")


def _answers(root: pathlib.Path, commit: str, source: str = "gh:example/template") -> pathlib.Path:
    (root / ".copier-answers.yml").write_text(f"_commit: {commit}\n_src_path: {source}\n", encoding="utf-8")
    return root


def test_the_scaffolding_is_behind_only_when_its_release_is_older_than_the_platform(tmp_path: pathlib.Path) -> None:
    for commit in ("v0.42.0", "0.43.0", "a1b2c3d"):
        report = Report("app", str(tmp_path))
        _platform.template(_answers(tmp_path, commit), report, "0.42.0")
        assert report.findings == [], commit
    (tmp_path / ".copier-answers.yml").unlink()
    _platform.template(tmp_path, Report("app", str(tmp_path)), "0.42.0")


def test_a_behind_scaffolding_offers_the_re_render_or_says_why_it_cannot(tmp_path: pathlib.Path) -> None:
    report = Report("app", str(tmp_path))
    _platform.template(_answers(tmp_path, "v0.40.0"), report, "0.42.0")
    assert report.findings[0] == Finding(
        "template-behind", "template", report.findings[0].remedy, location=".copier-answers.yml", installed="v0.40.0", latest="0.42.0"
    )
    assert report.findings[0].remedy == "A re-render is unavailable here: this app is not a git checkout, which `copier update` needs to apply an update."
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    in_git = Report("app", str(tmp_path))
    _platform.template(tmp_path, in_git, "0.42.0")
    assert in_git.findings[0].remedy.startswith("Re-render the scaffolding from the template of the installed release: `copier update`")


#: A stand-in for npm: answers ``npm view <name> version --json`` from the table in its
#: environment, or fails as npm fails.
_NPM = """\
#!/usr/bin/env python3
import json, os, sys
answers = json.loads(os.environ["FAKE_NPM"])
with open(os.environ["FAKE_NPM_LOG"], "a") as log:
    log.write(json.dumps([os.getcwd(), sys.argv[1:]]) + "\\n")
answer = answers.get(sys.argv[2], answers.get("*"))
if answer is None:
    sys.stderr.write("npm error code E404\\nnpm error 404 Not Found - " + sys.argv[2] + "\\n")
    sys.exit(1)
if answer == "silent-failure":
    sys.exit(1)
sys.stdout.write(answer)
"""


@pytest.fixture
def npm(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> Callable[[dict[str, str]], pathlib.Path]:
    """A real ``npm`` program on PATH; set its answers with ``npm({name: stdout})``."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    script = bin_dir / "npm"
    script.write_text(_NPM, encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    log = tmp_path / "npm.log"
    monkeypatch.setenv("PATH", f"{bin_dir}:/usr/bin:/bin")
    monkeypatch.setenv("FAKE_NPM_LOG", str(log))

    def answer(answers: dict[str, str]) -> pathlib.Path:
        monkeypatch.setenv("FAKE_NPM", json.dumps(answers))
        return log

    return answer


def _frontend(root: pathlib.Path, manifest: str, declared: dict[str, str], locked: dict[str, str] | None = None) -> None:
    path = root / manifest
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"dependencies": declared, "devDependencies": {"vitest": "^3.0.0"}}), encoding="utf-8")
    if locked is not None:
        packages = {f"node_modules/{name}": {"version": version} for name, version in locked.items()}
        path.with_name("package-lock.json").write_text(json.dumps({"packages": packages}), encoding="utf-8")


def test_the_npm_set_is_asked_of_each_workspace_s_own_registry(tmp_path: pathlib.Path, npm) -> None:
    root = tmp_path / "app"
    _frontend(root, "frontend/package.json", {"@terpjs/react-core": "^0.41.0", "@terpjs/contract": "^0.41.0"}, {"@terpjs/react-core": "0.41.1"})
    _frontend(root, "conformance/package.json", {"@terpjs/conformance": "0.41.1", "@terpjs/react-core": "^0.40.0"})
    log = npm({"*": '"0.42.0"'})
    report = Report("app", str(root))
    _platform.npm_platform(root, report)
    assert report.sources == [Source("npm-registry", True)]
    assert report.findings == [
        Finding("platform-behind", "@terpjs/*", report.findings[0].remedy, ecosystem="npm", location="conformance/package.json", installed="0.41.0", latest="0.42.0")
    ]
    asked = [json.loads(line) for line in log.read_text().splitlines()]
    assert [(pathlib.Path(cwd).name, argv) for cwd, argv in asked] == [
        ("conformance", ["view", "@terpjs/conformance", "version", "--json"]),
        ("frontend", ["view", "@terpjs/contract", "version", "--json"]),
        ("frontend", ["view", "@terpjs/react-core", "version", "--json"]),
    ]


def test_a_current_npm_set_says_nothing_and_a_partly_published_one_waits(tmp_path: pathlib.Path, npm) -> None:
    root = tmp_path / "app"
    _frontend(root, "frontend/package.json", {"@terpjs/react-core": "^0.42.0", "@terpjs/contract": "~0.42.0"})
    npm({"*": '"0.42.0"'})
    current = Report("app", str(root))
    _platform.npm_platform(root, current)
    assert current.sources == [Source("npm-registry", True)] and current.findings == []
    npm({"@terpjs/contract": '"0.43.0"', "@terpjs/react-core": '"0.42.0"'})
    partial = Report("app", str(root))
    _platform.npm_platform(root, partial)
    assert partial.findings[0].latest == "0.43.0" and partial.findings[0].remedy.startswith("Terp 0.43.0 does not yet cover")


@pytest.mark.parametrize(
    ("answers", "detail"),
    [
        ({}, "npm view @terpjs/react-core failed: npm error 404 Not Found - @terpjs/react-core"),
        ({"*": "silent-failure"}, "npm view @terpjs/react-core failed: no output"),
        ({"*": "{not json"}, "npm view @terpjs/react-core answered no JSON"),
        ({"*": '["0.42.0"]'}, "npm view @terpjs/react-core answered no version"),
        ({"*": ""}, "npm view @terpjs/react-core answered no version"),
    ],
)
def test_a_registry_that_does_not_answer_is_a_finding_never_a_current_set(tmp_path: pathlib.Path, npm, answers, detail) -> None:
    root = tmp_path / "app"
    _frontend(root, "frontend/package.json", {"@terpjs/react-core": "^0.42.0"})
    npm(answers)
    report = Report("app", str(root))
    _platform.npm_platform(root, report)
    assert report.sources == [Source("npm-registry", False, detail)]
    assert [f.kind for f in report.findings] == ["source-unavailable"]


def test_npm_missing_or_hanging_is_said_in_words(tmp_path: pathlib.Path, monkeypatch) -> None:
    root = tmp_path / "app"
    _frontend(root, "frontend/package.json", {"@terpjs/react-core": "^0.42.0"})
    monkeypatch.setenv("PATH", str(tmp_path / "nothing-here"))
    missing = Report("app", str(root))
    _platform.npm_platform(root, missing)
    assert missing.sources[0].detail == "npm is not on PATH"

    def hang(*args: object, **kwargs: object) -> None:
        raise subprocess.TimeoutExpired("npm", 120)

    monkeypatch.setattr(_platform.subprocess, "run", hang)
    slow = Report("app", str(root))
    _platform.npm_platform(root, slow)
    assert slow.sources[0].detail == "npm did not answer within 120s"


def test_no_terpjs_package_declared_means_npm_is_not_asked(tmp_path: pathlib.Path, monkeypatch) -> None:
    root = tmp_path / "app"
    _frontend(root, "frontend/package.json", {"react": "^19.0.0"})
    (root / "conformance").mkdir()
    (root / "conformance/package.json").write_text("{not json", encoding="utf-8")
    (root / "frontend/package-lock.json").write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(_platform.subprocess, "run", lambda *a, **k: pytest.fail("npm was asked"))
    report = Report("app", str(root))
    _platform.npm_platform(root, report)
    assert report.sources == [] and report.findings == []
    (root / "frontend/package.json").write_text("[]", encoding="utf-8")
    (root / "frontend/package-lock.json").write_text("[]", encoding="utf-8")
    _platform.npm_platform(root, report)
    assert report.sources == []


# --- base images ----------------------------------------------------------------------------

_OLD = "sha256:" + "1" * 64


def _own_app(root: pathlib.Path, build: str = "own") -> pathlib.Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "deployment.json").write_text(json.dumps({"build": build}), encoding="utf-8")
    return root


def _dockerfile(root: pathlib.Path, path: str, text: str) -> None:
    (root / path).parent.mkdir(parents=True, exist_ok=True)
    (root / path).write_text(text, encoding="utf-8")


def test_a_base_is_compared_only_where_its_tag_stands_above_its_pinned_from(tmp_path: pathlib.Path) -> None:
    root = _own_app(tmp_path)
    _dockerfile(root, "Dockerfile.prod", f"""\
# python:3.14-slim
FROM python@{_OLD} AS deps
# a sentence about the next line
FROM python@{_OLD}
# ghcr.io/astral-sh/uv:0.13.7
FROM --platform=$BUILDPLATFORM ghcr.io/astral-sh/uv@{_OLD} AS uv
# node:26-slim
FROM python@{_OLD}
# python:3.14-slim
FROM python:3.14-slim
FROM deps AS app
""")
    _dockerfile(root, "frontend/Dockerfile.prod", f"# nginxinc/nginx-unprivileged:alpine\nfrom nginxinc/nginx-unprivileged@{_OLD}\n")
    assert _images.pinned_bases(root) == [
        ("Dockerfile.prod", "docker.io/library/python", _OLD, "3.14-slim"),
        ("Dockerfile.prod", "ghcr.io/astral-sh/uv", _OLD, "0.13.7"),
        ("frontend/Dockerfile.prod", "docker.io/nginxinc/nginx-unprivileged", _OLD, "alpine"),
    ]


def test_only_an_app_that_writes_its_own_build_files_has_its_bases_asked(tmp_path: pathlib.Path) -> None:
    assert _images.own_build(_own_app(tmp_path / "own")) is True
    assert _images.own_build(_own_app(tmp_path / "generated", "generated")) is False
    assert _images.own_build(tmp_path / "undeclared") is False
    (tmp_path / "list").mkdir()
    (tmp_path / "list/deployment.json").write_text("[]", encoding="utf-8")
    assert _images.own_build(tmp_path / "list") is False
    report = Report("app", str(tmp_path))
    _images.base_image_findings(_own_app(tmp_path / "generated", "generated"), report, getter=lambda *a: pytest.fail("asked"))
    _images.base_image_findings(_own_app(tmp_path / "own"), report, getter=lambda *a: pytest.fail("asked"))
    assert report.sources == [] and report.findings == []


def test_a_moved_tag_is_a_finding_and_a_current_one_is_not(tmp_path: pathlib.Path) -> None:
    registry = FakeRegistry()
    moved = registry.push_image([layer(("a", b"1"))])
    kept = registry.push_image([layer(("b", b"2"))])
    registry.repo_tags[("library/python", "3.14-slim")] = moved
    registry.repo_tags[("astral-sh/uv", "0.13.7")] = kept
    root = _own_app(tmp_path)
    _dockerfile(root, "Dockerfile.prod", f"# python:3.14-slim\nFROM python@{_OLD}\n# python:3.14-slim\nFROM python@{_OLD}\n# ghcr.io/astral-sh/uv:0.13.7\nFROM ghcr.io/astral-sh/uv@{kept}\n")
    report = Report("app", str(root))
    _images.base_image_findings(root, report, getter=registry)
    assert report.sources == [Source("registry", True)]
    assert report.findings == [
        Finding("base-image-behind", "python:3.14-slim", report.findings[0].remedy, location="Dockerfile.prod", installed=_OLD, latest=moved)
    ] * 2
    assert report.findings[0].remedy.startswith(f"The tag python:3.14-slim names {moved} now.")
    asked = [url for url, _headers in registry.requests]
    assert asked == [
        "https://registry-1.docker.io/v2/library/python/manifests/3.14-slim",
        "https://ghcr.io/v2/astral-sh/uv/manifests/0.13.7",
    ], "Docker Hub's images are asked at its API host, once per tag"


def test_a_registry_that_does_not_answer_is_a_finding(tmp_path: pathlib.Path, monkeypatch) -> None:
    root = _own_app(tmp_path)
    _dockerfile(root, "Dockerfile.prod", f"# python:3.14-slim\nFROM python@{_OLD}\n")
    report = Report("app", str(root))
    _images.base_image_findings(root, report, getter=FakeRegistry())
    assert report.sources[0].reachable is False and "has no manifest 3.14-slim" in str(report.sources[0].detail)
    def refuse(host: str, *, http: bool) -> None:
        raise ReleaseError("the registry could not be read at registry-1.docker.io", cause="refused")

    monkeypatch.setattr(_images, "egress_getter", refuse)
    plain = Report("app", str(root))
    _images.base_image_findings(root, plain)
    assert plain.sources[0].detail == "the registry could not be read at registry-1.docker.io: refused"
