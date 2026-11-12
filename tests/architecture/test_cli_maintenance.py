"""``terp maintenance``: the report, what a target holds, and the command (ADR 0214).

The vulnerability database is a real HTTP server on this machine's loopback, asked through the
declared egress client (:mod:`tests.architecture.osv_fixtures`); a release bundle is written with
the signer's own SBOM and canonical form, and a commit is a real git repository. The advisories
are held in ``test_cli_maintenance_advisories``, the platform and the images in
``test_cli_maintenance_sources``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import subprocess
import sys

import pytest

from terp.cli import _build_parser
from terp.cli.maintenance import _packages, _report, run
from terp.cli.maintenance._packages import Package
from terp.cli.maintenance._report import Advisory, Finding, Report
from terp.cli.release._common import ReleaseError, canonical
from tests.architecture.maintenance_fixtures import UV_LOCK, advisories, npm_lock, tarball, write_app, write_bundle
from tests.architecture.osv_fixtures import FakeOSV, serving
from tests.architecture.release_fixtures import committed_app, git

# --- the report -----------------------------------------------------------------------------


def test_a_finding_and_a_source_only_take_their_own_words() -> None:
    with pytest.raises(ValueError, match="not a kind of finding"):
        Finding("outdated", "x", "y")
    with pytest.raises(ValueError, match="not a source"):
        _report.Source("github", True)


def test_every_finding_carries_every_key_and_a_report_lists_them_in_order() -> None:
    report = Report("app", "/app", checked_at="2026-11-12T10:00:00Z", terp_cli="0.43.0")
    report.answered("osv")
    report.unreachable("python-index", "uv failed: offline.", "Check the index.")
    report.findings.append(Finding("known-vulnerability", "b", "r", advisories=(Advisory("A", ("CVE-1",), "s", "HIGH"),)))
    report.findings.append(Finding("platform-behind", "terp-*", "r", installed="1", latest="2"))
    report.not_made("known-vulnerability: a gap")
    report.not_made("known-vulnerability: a gap")
    document = report.as_dict()
    assert document["terp_maintenance"] == 1 and document["terp_cli"] == "0.43.0"
    assert document["target"] == {"kind": "app", "path": "/app", "release": None, "commit": None}
    assert [s["name"] for s in document["sources"]] == ["python-index", "osv"]
    assert document["sources"][0] == {"name": "python-index", "reachable": False, "detail": "uv failed: offline."}
    assert document["not_checked"] == ["known-vulnerability: a gap"], "a gap met twice is named once"
    assert [f["kind"] for f in document["findings"]] == ["platform-behind", "known-vulnerability", "source-unavailable"]
    assert document["findings"][2]["remedy"] == "uv failed: offline. Check the index."
    assert set(document["findings"][0]) == {
        "kind", "subject", "ecosystem", "location", "installed", "latest", "fixed_in", "advisories",
        "new_since_release", "remedy",
    }
    assert document["findings"][1]["advisories"] == [
        {"id": "A", "aliases": ["CVE-1"], "summary": "s", "severity": "HIGH", "url": "https://osv.dev/vulnerability/A"}
    ]
    assert json.loads(report.as_json()) == document


def test_the_text_names_each_finding_and_its_remedy() -> None:
    report = Report("release", "/b", release="v1", checked_at="T")
    report.answered("osv")
    report.unreachable("registry", "down", "Retry.")
    report.findings.append(
        Finding("known-vulnerability", "x", "Move x.", location="image api", installed="1",
                advisories=(Advisory("A", severity="HIGH"), Advisory("B")), new_since_release=True)
    )
    report.findings.append(Finding("base-image-behind", "python:3", "Pin it.", location="Dockerfile.prod", installed="sha256:a", latest="sha256:b"))
    text = report.as_text()
    assert text.startswith("Maintenance report for /b (release v1), T\nAsked: osv, registry (NOT reachable)")
    assert "3 findings:" in text
    assert "  known-vulnerability: x 1 in image api: A (HIGH), B - new since the release was signed\n    Move x." in text
    assert "  base-image-behind: python:3 in Dockerfile.prod: sha256:a -> sha256:b" in text
    assert "  source-unavailable: registry could not be asked" in text
    assert text.endswith("exits 0 whatever it finds.")
    assert "Nothing to maintain: every check ran and found nothing." in Report("tree", "/t", checked_at="T").as_text()
    commit = Report("commit", "/repo", commit="ab" * 20, checked_at="T", not_checked=["known-vulnerability: a gap"])
    assert commit.as_text().startswith(f"Maintenance report for /repo (commit {'ab' * 6}), T")
    assert "Nothing found by the checks that ran. Not every check could run:\n  - known-vulnerability: a gap" in commit.as_text()
    one = Report("app", "/a", checked_at="T", not_checked=["template-behind: no ref"])
    one.findings.append(Finding("template-behind", "template", "Re-render.", installed="v1", latest="2"))
    assert "1 finding:" in one.as_text() and "\nNot checked:\n  - template-behind: no ref\n" in one.as_text()


def test_the_report_names_the_cli_that_wrote_it_or_none(monkeypatch) -> None:
    from importlib import metadata

    monkeypatch.setattr(metadata, "version", lambda name: "9.9.9")
    assert Report("app", "/a").terp_cli == "9.9.9"

    def missing(name: str) -> str:
        raise metadata.PackageNotFoundError(name)

    monkeypatch.setattr(metadata, "version", missing)
    assert Report("app", "/a").terp_cli is None
    assert Report("app", "/a").checked_at.endswith("Z")


# --- what a target holds --------------------------------------------------------------------


def test_only_registry_packages_are_listed_each_with_the_host_it_came_from(tmp_path: pathlib.Path) -> None:
    npm = npm_lock(
        ("node_modules/lodash", {"version": "4.17.15", "resolved": tarball("lodash", "4.17.15")}),
        ("node_modules/@scope/pkg", {"version": "1.0.0"}),
        ("node_modules/a/node_modules/renamed", {"name": "real-name", "version": "2.0.0", "resolved": tarball("real-name", "2.0.0")}),
        ("node_modules/linked", {"link": True, "resolved": "../linked"}),
        ("node_modules/workspace-link", {"version": "1.0.0", "link": True, "resolved": "packages/workspace"}),
        ("node_modules/local", {"version": "1.0.0", "resolved": "file:../local"}),
        ("node_modules/private-fork", {"version": "1.0.0", "resolved": "git+ssh://git@example.com/fork.git#abc"}),
        ("node_modules/tarball", {"version": "2.0.0", "resolved": "https://files.example.com/tarball.tgz"}),
        ("node_modules/mirrored", {"version": "3.0.0", "resolved": "https://npm.example.com/repo/mirrored/-/mirrored-3.0.0.tgz"}),
        ("node_modules/no-version", {"resolved": tarball("x", "1")}),
        ("packages/workspace", {"version": "1.0.0"}),
        ("node_modules/odd", "not an entry"),
        direct=("lodash", "real-name"),
    )
    found = _packages.inventory(write_app(tmp_path, npm=npm))
    assert found.packages == [
        Package("PyPI", "internal-lib", "3.1.0", "uv.lock", registry="pkgs.example.com"),
        Package("PyPI", "jinja2", "2.11.2", "uv.lock", registry="pypi.org"),
        Package("PyPI", "markupsafe", "2.0.1", "uv.lock", registry="pypi.org"),
        Package("npm", "@scope/pkg", "1.0.0", "frontend/package-lock.json", direct=False),
        Package("npm", "lodash", "4.17.15", "frontend/package-lock.json", True, "registry.npmjs.org"),
        Package("npm", "mirrored", "3.0.0", "frontend/package-lock.json", False, "npm.example.com"),
        Package("npm", "real-name", "2.0.0", "frontend/package-lock.json", False, "registry.npmjs.org"),
    ], "a path, a git repository, a URL that is no registry's tarball and the project itself stay here"
    assert (found.unlocked, found.anything) == ([], True)
    assert [package.public for package in found.packages] == [False, True, True, False, True, False, True]
    assert [p.purl for p in found.packages[2:4]] == ["pkg:pypi/markupsafe@2.0.1", "pkg:npm/%40scope/pkg@1.0.0"]


def test_a_manifest_without_its_lock_is_named_and_a_lock_without_its_manifest_is_not_read(tmp_path: pathlib.Path) -> None:
    root = write_app(tmp_path, uv=None)
    (root / "frontend").mkdir()
    (root / "frontend/package.json").write_text("{}", encoding="utf-8")
    (root / "site").mkdir()
    (root / "site/package-lock.json").write_text("not even json", encoding="utf-8")
    found = _packages.inventory(root)
    assert found.packages == [] and found.anything is True
    assert found.unlocked == [
        "known-vulnerability: pyproject.toml has no uv.lock beside it, so none of its packages was asked about "
        "(`uv lock` writes one)",
        "known-vulnerability: frontend/package.json has no package-lock.json beside it, so none of its packages "
        "was asked about (`npm --prefix frontend install` writes one)",
    ]
    assert _packages.inventory(tmp_path / "nothing").anything is False
    assert _packages.npm_locks(root) == []


def test_a_lock_the_release_plan_builds_a_web_image_from_is_read_and_one_left_unlocked_is_named(tmp_path: pathlib.Path) -> None:
    """Under "build": "own" a web image may build anywhere: its lock is the plan's, not a list's."""
    from tests.architecture.release_fixtures import NPM_LOCK
    from tests.architecture.test_release_build import _own_with_webs

    files = _own_with_webs(
        {"web": {"context": "www", "dockerfile": "Dockerfile"}},
        {"www/Dockerfile": b"FROM scratch\n", "www/package.json": b"{}", "www/package-lock.json": json.dumps(NPM_LOCK).encode()},
    )
    root = tmp_path / "app"
    for path, data in files.items():
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_bytes(data)
    assert _packages.npm_locks(root) == ["www/package-lock.json"]
    assert Package("npm", "react", "19.0.0", "www/package-lock.json", False, "registry.npmjs.org") in _packages.inventory(root).packages


def test_a_lock_that_cannot_be_read_is_refused_by_name_never_read_as_empty(tmp_path: pathlib.Path) -> None:
    with pytest.raises(ReleaseError, match="uv.lock is not TOML"):
        _packages.inventory(write_app(tmp_path / "a", uv="not = [toml"))
    with pytest.raises(ReleaseError, match="uv.lock could not be read"):
        (write_app(tmp_path / "b") / "uv.lock").write_bytes(b"\xff\xfe not utf-8")
        _packages.inventory(tmp_path / "b")
    with pytest.raises(ReleaseError, match="frontend/package-lock.json is not JSON"):
        _packages.inventory(write_app(tmp_path / "c", uv=None, npm="{"))


def test_a_uv_source_in_another_shape_is_no_registry_package(tmp_path: pathlib.Path) -> None:
    lock = UV_LOCK.split("[[package]]\nname = \"Jinja2\"")[0] + '[[package]]\nname = "odd"\nversion = "1"\nsource = "pypi"\n'
    assert _packages.inventory(write_app(tmp_path, uv=lock)).packages == []


def test_a_signed_bundle_yields_its_packages_what_was_known_and_where_it_was_asked(tmp_path: pathlib.Path) -> None:
    from terp.cli.release.sign import MANIFEST

    assert _packages.MANIFEST == MANIFEST
    bundle = _packages.bundle_packages(write_bundle(tmp_path / "b", {
        "acme/api": ([("Jinja2", "2.11.2")], "pypi", {"pkg:pypi/jinja2@2.11.2": ["GHSA-1"]}),
        "acme/web": ([("@scope/ui", "1.0.0")], "npm", None),
    }, database="https://osv.mirror.example"))
    assert (bundle.tag, bundle.database) == ("v1.2.0", "https://osv.mirror.example")
    assert bundle.packages == [
        Package("PyPI", "jinja2", "2.11.2", "image acme/api"),
        Package("npm", "@scope/ui", "1.0.0", "image acme/web"),
    ]
    assert bundle.recorded == {"pkg:pypi/jinja2@2.11.2": frozenset({"GHSA-1"})}


def _manifest(directory: pathlib.Path, manifest: object, sboms: dict[str, bytes] | None = None) -> None:
    directory.mkdir()
    (directory / "release.manifest.json").write_bytes(json.dumps(manifest).encode())
    for name, data in (sboms or {}).items():
        (directory / name).write_bytes(data)


_SBOM = b'{"components": []}'
_DIGEST = hashlib.sha256(_SBOM).hexdigest()


@pytest.mark.parametrize(
    ("make", "expected"),
    [
        (lambda d: d.mkdir(), "the bundle holds no readable release.manifest.json"),
        (lambda d: (d.mkdir(), (d / "release.manifest.json").write_text("{")), "release.manifest.json could not be read as JSON"),
        (lambda d: _manifest(d, []), "records no images"),
        (lambda d: _manifest(d, {"outputs": []}), "records no images"),
        (lambda d: _manifest(d, {"outputs": {"images": []}}), "records no images"),
        (lambda d: _manifest(d, {"outputs": {"images": {"api": "x"}}}), "records no SBOM digest for the image api"),
        (lambda d: _manifest(d, {"outputs": {"images": {"api": {}}}}), "records no SBOM digest for the image api"),
        (lambda d: _manifest(d, {"outputs": {"images": {"api": {"sbom": _DIGEST}}}}), "no readable sbom-api.cdx.json"),
        (lambda d: write_bundle(d, {"api": ([("x", "1")], "pypi", {})}, tamper="api"), "not the SBOM the manifest recorded for api"),
        (lambda d: _manifest(d, {"outputs": {"images": {"api": {"sbom": hashlib.sha256(b"{").hexdigest()}}}}, {"sbom-api.cdx.json": b"{"}),
         "sbom-api.cdx.json could not be read as JSON"),
        (lambda d: _manifest(d, {"outputs": {"images": {"api": {"sbom": hashlib.sha256(b"[]").hexdigest()}}}}, {"sbom-api.cdx.json": b"[]"}),
         "sbom-api.cdx.json lists no components"),
        (lambda d: _manifest(d, {"outputs": {"images": {"api": {"sbom": _DIGEST, "vulnerabilities": {"p": "GHSA"}}}}}, {"sbom-api.cdx.json": _SBOM}),
         "vulnerabilities for the image api are not a list of ids"),
    ],
)
def test_a_bundle_that_is_not_one_is_refused_by_name(tmp_path: pathlib.Path, make, expected: str) -> None:
    make(tmp_path / "b")
    with pytest.raises(ReleaseError, match=expected):
        _packages.bundle_packages(tmp_path / "b")


def test_a_component_that_names_no_package_url_is_left_out(tmp_path: pathlib.Path) -> None:
    document = {"components": [{"purl": "pkg:golang/x@1"}, {"purl": "pkg:pypi/noversion"}, {"name": "bare"}, "odd", {"purl": "pkg:pypi/x@1"}]}
    data = canonical(document)
    _manifest(tmp_path / "b", {"outputs": {"images": {"api": {"sbom": hashlib.sha256(data).hexdigest(), "tag": ""}}}},
              {"sbom-api.cdx.json": data + b"\n"})
    bundle = _packages.bundle_packages(tmp_path / "b")
    assert bundle.packages == [Package("PyPI", "x", "1", "image api")]
    assert (bundle.tag, bundle.recorded, bundle.database) == (None, {}, None)


# --- the command ----------------------------------------------------------------------------


def _run(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    code = run(_build_parser().parse_args(argv))
    out, err = capsys.readouterr()
    return code, out, err


def test_the_tree_target_reports_the_locks_of_another_checkout(tmp_path: pathlib.Path, capsys) -> None:
    tree = write_app(tmp_path / "tree", npm=npm_lock(("node_modules/lodash", {"version": "4.17.15", "resolved": tarball("lodash", "4.17.15")})))
    with serving(advisories()) as database:
        code, out, _ = _run(["maintenance", "--tree", str(tree), "--osv", database.url, "--format", "json"], capsys)
    document = json.loads(out)
    assert code == 0
    assert document["target"] == {"kind": "tree", "path": str(tree.resolve()), "release": None, "commit": None}
    assert [(f["kind"], f["subject"]) for f in document["findings"]] == [
        ("known-vulnerability", "internal-lib"), ("known-vulnerability", "jinja2"), ("known-vulnerability", "lodash"),
    ], "a mirror receives the private names too"


def test_a_tree_of_manifests_without_locks_reports_what_it_could_not_read(tmp_path: pathlib.Path, capsys) -> None:
    code, out, _ = _run(["maintenance", "--tree", str(write_app(tmp_path / "t", uv=None)), "--format", "json"], capsys)
    document = json.loads(out)
    assert code == 0 and document["sources"] == [] and document["findings"] == []
    assert document["not_checked"][0].startswith("known-vulnerability: pyproject.toml has no uv.lock beside it")


def test_the_release_target_asks_the_database_sign_recorded(tmp_path: pathlib.Path, capsys) -> None:
    with serving(advisories()) as database:
        directory = write_bundle(tmp_path / "b", {"api": ([("jinja2", "2.11.2"), ("example-app", "0.1.0")], "pypi",
                                                          {"pkg:pypi/jinja2@2.11.2": ["GHSA-a"]})}, database=database.url)
        code, out, _ = _run(["maintenance", "--release", str(directory)], capsys)
    assert code == 0
    assert "(release v1.2.0)" in out and "jinja2 2.11.2 in image api: GHSA-a (HIGH), GHSA-b - new since" in out
    assert {query["package"]["purl"] for query in database.batches[0]} == {"pkg:pypi/jinja2@2.11.2", "pkg:pypi/example-app@0.1.0"}, (
        "a release re-asks exactly what sign asked, of the database it asked"
    )


def _repo(root: pathlib.Path) -> tuple[pathlib.Path, str]:
    """A repository whose commit pins jinja2 2.11.2, and whose working tree no longer does."""
    sha = committed_app(root, {"pyproject.toml": b'[project]\nname = "demo"\nversion = "0.1.0"\n', "uv.lock": UV_LOCK.encode()})
    (root / "uv.lock").write_text(UV_LOCK.replace('version = "2.11.2"', 'version = "3.1.6"'), encoding="utf-8")
    return root, sha


def test_the_commit_target_reads_the_commit_never_the_working_tree(tmp_path: pathlib.Path, monkeypatch, capsys) -> None:
    root, sha = _repo(tmp_path / "repo")
    monkeypatch.chdir(root)
    with serving(advisories()) as database:
        code, out, _ = _run(["maintenance", "--commit", sha, "--osv", database.url, "--format", "json"], capsys)
    document = json.loads(out)
    assert code == 0
    assert document["target"] == {"kind": "commit", "path": str(root.resolve()), "release": None, "commit": sha}
    jinja = next(f for f in document["findings"] if f["subject"] == "jinja2")
    assert jinja["installed"] == "2.11.2", "the committed lock, not the edited working tree"
    assert git(root, "status", "--porcelain") == "M uv.lock", "nothing is written into the checkout"


def test_what_a_commit_cannot_give_exits_2_with_a_reason(tmp_path: pathlib.Path, monkeypatch, capsys) -> None:
    root, sha = _repo(tmp_path / "repo")
    empty = committed_app(tmp_path / "empty", {"README.md": b"hello\n"})
    monkeypatch.chdir(root)
    for argv, expected in (
        (["--commit", sha[:12]], "is not an exact commit"),
        (["--commit", "0" * 40], "finding commit"),
    ):
        code, out, err = _run(["maintenance", *argv], capsys)
        assert (code, out) == (2, "") and expected in err
    monkeypatch.chdir(tmp_path / "empty")
    code, out, err = _run(["maintenance", "--commit", empty], capsys)
    assert (code, out) == (2, "") and f"the commit {empty} holds no lock and no manifest" in err


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (["--tree", "{tmp}/missing"], "is not a directory"),
        (["--tree", "{tmp}/empty"], "holds no lock and no manifest (uv.lock, pyproject.toml, a package.json), so there is nothing to report on"),
        (["--release", "{tmp}/empty"], "no readable release.manifest.json"),
        ([], "holds no pyproject.toml, so it is no app to report on: run it in the app"),
    ],
)
def test_what_cannot_be_reported_on_exits_2_with_a_reason(tmp_path: pathlib.Path, monkeypatch, capsys, argv, expected) -> None:
    (tmp_path / "empty").mkdir()
    monkeypatch.chdir(tmp_path / "empty")
    code, out, err = _run(["maintenance", *(a.format(tmp=tmp_path) for a in argv)], capsys)
    assert (code, out) == (2, "")
    assert err.startswith("terp maintenance: could not report: ") and expected in err


def test_the_app_target_asks_every_part_of_the_app_it_runs_in(tmp_path: pathlib.Path, monkeypatch, capsys) -> None:
    from terp.cli.maintenance import _images, _platform

    asked: list[str] = []
    monkeypatch.setattr(_platform, "python_platform", lambda root, report: asked.append(f"python {root.name}") or "0.42.0")
    monkeypatch.setattr(_platform, "template", lambda root, report, platform: asked.append(f"template {platform}"))
    monkeypatch.setattr(_platform, "npm_platform", lambda root, report: asked.append("npm"))
    monkeypatch.setattr(_images, "base_image_findings", lambda root, report: asked.append("images"))
    root = write_app(tmp_path / "app", uv=None)
    monkeypatch.chdir(root)
    code, out, _ = _run(["maintenance"], capsys)
    assert code == 0 and asked == ["python app", "template 0.42.0", "npm", "images"]
    assert "Nothing found by the checks that ran. Not every check could run:\n  - known-vulnerability: pyproject.toml" in out
    asked.clear()
    monkeypatch.setattr(_platform, "python_platform", lambda root, report: asked.append("python") and None)
    _run(["maintenance"], capsys)
    assert asked == ["python", "npm", "images"], "no platform version, nothing to compare the scaffolding with"


def test_private_names_leave_only_for_a_mirror_or_when_the_person_says_so(tmp_path: pathlib.Path, monkeypatch, capsys) -> None:
    import terp.cli.maintenance as command

    tree = write_app(tmp_path / "tree")
    for flags, sent_private in (([], False), (["--send-private-names"], True)):
        with serving(advisories()) as database:
            monkeypatch.setattr(command, "DEFAULT_OSV", database.url)
            code, out, _ = _run(["maintenance", "--tree", str(tree), "--osv", database.url, "--format", "json", *flags], capsys)
        purls = {query["package"]["purl"] for batch in database.batches for query in batch}
        assert ("pkg:pypi/internal-lib@3.1.0" in purls) is sent_private
        not_checked = json.loads(out)["not_checked"]
        assert bool(not_checked) is not sent_private
    assert not_checked == []
    with serving(advisories()) as database:
        monkeypatch.setattr(command, "DEFAULT_OSV", database.url)
        _run(["maintenance", "--tree", str(tree), "--osv", database.url, "--format", "json"], capsys)
    with serving(advisories()) as mirror:
        _run(["maintenance", "--tree", str(tree), "--osv", mirror.url, "--format", "json"], capsys)
    assert "pkg:pypi/internal-lib@3.1.0" in {q["package"]["purl"] for b in mirror.batches for q in b}, (
        "a mirror the person names receives the private names: it is theirs"
    )


def test_the_entry_point_exits_2_only_when_it_could_not_report(tmp_path: pathlib.Path, capsys) -> None:
    from terp.cli import main

    with pytest.raises(SystemExit) as refused:
        main(["maintenance", "--tree", str(tmp_path / "missing")])
    assert refused.value.code == 2
    own = write_app(tmp_path / "own-only", uv=UV_LOCK.split('[[package]]\nname = "Jinja2"')[0])
    main(["maintenance", "--tree", str(own)])
    assert "Nothing to maintain: every check ran and found nothing." in capsys.readouterr().out


def test_upgrade_still_answers_through_its_own_command(monkeypatch, capsys) -> None:
    from terp.cli import version

    monkeypatch.setattr(version, "render_upgrade_check", lambda fmt="text": f"checked as {fmt}")
    assert _run(["upgrade", "--check", "--format", "json"], capsys)[:2] == (0, "checked as json\n")
    with pytest.raises(SystemExit, match="run `terp upgrade --check`"):
        run(argparse.Namespace(command="upgrade", check=False, format="text"))


def test_the_console_entry_point_reports_across_a_real_process(tmp_path: pathlib.Path) -> None:
    """``terp maintenance`` as a scheduler runs it: its own process, a JSON document on stdout."""
    tree = write_app(tmp_path / "tree")
    source = pathlib.Path(__file__).resolve().parents[2] / "packages" / "backend" / "cli" / "src"
    command = [sys.executable, "-c", f"import sys; sys.path.insert(0, {str(source)!r}); from terp.cli import main; main()"]
    with serving(advisories()) as database:
        completed = subprocess.run(
            [*command, "maintenance", "--tree", str(tree), "--osv", database.url, "--format", "json"],
            capture_output=True, text=True, check=False, timeout=120,
        )
    assert completed.returncode == 0, completed.stderr
    assert [f["subject"] for f in json.loads(completed.stdout)["findings"]] == ["internal-lib", "jinja2"]
    refused = subprocess.run([*command, "maintenance", "--tree", str(tmp_path / "missing")],
                             capture_output=True, text=True, check=False, timeout=120)
    assert refused.returncode == 2 and refused.stdout == ""


def test_a_database_that_answers_nothing_leaves_no_trace_of_a_clean_report(tmp_path: pathlib.Path, capsys) -> None:
    with serving(FakeOSV(status=503)) as database:
        code, out, _ = _run(["maintenance", "--tree", str(write_app(tmp_path / "t")), "--osv", database.url, "--format", "json"], capsys)
    document = json.loads(out)
    assert code == 0 and document["sources"] == [{"name": "osv", "reachable": False, "detail": "the vulnerability database answered 503"}]
    assert [f["kind"] for f in document["findings"]] == ["source-unavailable"]
