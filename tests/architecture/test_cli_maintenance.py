"""``terp maintenance``: the report, the packages it asks about and the advisories (ADR 0214).

The vulnerability database is a real HTTP server on this machine's loopback, asked through the
declared egress client (:mod:`tests.architecture.osv_fixtures`); a release bundle is written
with the signer's own SBOM and canonical form. The platform and image checks are held in
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
from terp.cli.maintenance import _packages, _report, _vulnerabilities, run
from terp.cli.maintenance._packages import Package
from terp.cli.maintenance._report import Advisory, Finding, Report
from terp.cli.release._common import ReleaseError, canonical
from terp.cli.release.manifest import sbom
from tests.architecture.osv_fixtures import FakeOSV, affected, serving

UV_LOCK = """\
version = 1
requires-python = ">=3.13"

[[package]]
name = "demo"
version = "0.1.0"
source = { editable = "." }

[[package]]
name = "Jinja2"
version = "2.11.2"
source = { registry = "https://pypi.org/simple" }

[[package]]
name = "markupsafe"
version = "2.0.1"
source = { registry = "https://pypi.org/simple" }

[[package]]
name = "forked"
version = "1.0"
source = { git = "https://example.com/forked.git" }

[[package]]
name = "nameless-version"
source = { registry = "https://pypi.org/simple" }
"""


def _npm_lock(*entries: tuple[str, dict], direct: tuple[str, ...] = ()) -> str:
    root = {"name": "web", "dependencies": {name: "*" for name in direct}}
    return json.dumps({"lockfileVersion": 3, "packages": {"": root, **dict(entries)}})


def _app(root: pathlib.Path, *, uv: str | None = UV_LOCK, npm: str | None = None) -> pathlib.Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "pyproject.toml").write_text('[project]\nname = "demo"\nversion = "0.1.0"\n', encoding="utf-8")
    if uv is not None:
        (root / "uv.lock").write_text(uv, encoding="utf-8")
    if npm is not None:
        (root / "frontend").mkdir()
        (root / "frontend/package.json").write_text('{"name": "web"}', encoding="utf-8")
        (root / "frontend/package-lock.json").write_text(npm, encoding="utf-8")
    return root


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
    document = report.as_dict()
    assert document["terp_maintenance"] == 1 and document["terp_cli"] == "0.43.0"
    assert document["target"] == {"kind": "app", "path": "/app", "release": None}
    assert [s["name"] for s in document["sources"]] == ["python-index", "osv"]
    assert document["sources"][0] == {"name": "python-index", "reachable": False, "detail": "uv failed: offline."}
    assert [f["kind"] for f in document["findings"]] == ["platform-behind", "known-vulnerability", "source-unavailable"]
    assert document["findings"][2]["remedy"] == "uv failed: offline. Check the index."
    assert set(document["findings"][0]) == {
        "kind", "subject", "ecosystem", "location", "installed", "latest", "fixed_in", "advisories",
        "new_since_release", "remedy",
    }
    assert document["findings"][1]["advisories"] == [
        {"id": "A", "aliases": ["CVE-1"], "summary": "s", "severity": "HIGH", "url": "https://osv.dev/vulnerability/A"}
    ]
    assert document["not_checked"] == []
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
    quiet = Report("tree", "/t", checked_at="T")
    assert "Nothing to maintain" in quiet.as_text() and "Asked" not in quiet.as_text()
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


# --- the packages ---------------------------------------------------------------------------


def test_only_packages_a_registry_serves_are_listed_from_the_locks(tmp_path: pathlib.Path) -> None:
    npm = _npm_lock(
        ("node_modules/lodash", {"version": "4.17.15", "resolved": "https://registry.npmjs.org/lodash/-/x.tgz"}),
        ("node_modules/@scope/pkg", {"version": "1.0.0"}),
        ("node_modules/a/node_modules/renamed", {"name": "real-name", "version": "2.0.0"}),
        ("node_modules/linked", {"link": True, "resolved": "../linked"}),
        ("node_modules/workspace-link", {"version": "1.0.0", "link": True, "resolved": "packages/workspace"}),
        ("node_modules/local", {"version": "1.0.0", "resolved": "file:../local"}),
        ("node_modules/private-fork", {"version": "1.0.0", "resolved": "git+ssh://git@example.com/fork.git#abc"}),
        ("node_modules/tarball", {"version": "2.0.0", "resolved": "https://files.example.com/tarball.tgz"}),
        ("node_modules/mirrored", {"version": "3.0.0", "resolved": "https://npm.example.com/repo/mirrored/-/mirrored-3.0.0.tgz"}),
        ("node_modules/no-version", {"resolved": "https://registry.npmjs.org/x"}),
        ("packages/workspace", {"version": "1.0.0"}),
        ("node_modules/odd", "not an entry"),
        direct=("lodash", "real-name"),
    )
    found = _packages.tree_packages(_app(tmp_path, npm=npm))
    assert found == [
        Package("PyPI", "jinja2", "2.11.2", "uv.lock"),
        Package("PyPI", "markupsafe", "2.0.1", "uv.lock"),
        Package("npm", "@scope/pkg", "1.0.0", "frontend/package-lock.json", direct=False),
        Package("npm", "lodash", "4.17.15", "frontend/package-lock.json", direct=True),
        Package("npm", "mirrored", "3.0.0", "frontend/package-lock.json", direct=False),
        Package("npm", "real-name", "2.0.0", "frontend/package-lock.json", direct=False),
    ], "a path, a git repository or a URL that is no registry's tarball is never listed"
    assert [p.purl for p in found[1:3]] == ["pkg:pypi/markupsafe@2.0.1", "pkg:npm/%40scope/pkg@1.0.0"]


def test_a_lock_without_its_manifest_and_a_manifest_without_its_lock_are_not_read(tmp_path: pathlib.Path) -> None:
    root = _app(tmp_path, uv=None)
    (root / "site").mkdir()
    (root / "site/package-lock.json").write_text("not even json", encoding="utf-8")
    (root / "frontend").mkdir()
    (root / "frontend/package.json").write_text("{}", encoding="utf-8")
    assert _packages.tree_packages(root) == []


def test_a_lock_the_release_plan_builds_a_web_image_from_is_read_too(tmp_path: pathlib.Path, monkeypatch) -> None:
    from terp.cli.release import _plan

    root = _app(tmp_path, uv=None)
    (root / "admin").mkdir()
    (root / "admin/package.json").write_text("{}", encoding="utf-8")
    (root / "admin/package-lock.json").write_text(_npm_lock(("node_modules/x", {"version": "1.0.0"})), encoding="utf-8")
    monkeypatch.setattr(_plan, "web_npm_locks", lambda root, table: ("frontend/package-lock.json", "admin/package-lock.json"))
    assert _packages.npm_locks(root) == ["admin/package-lock.json"]
    assert _packages.tree_packages(root) == [Package("npm", "x", "1.0.0", "admin/package-lock.json", direct=False)]


def test_a_lock_that_is_not_one_is_refused_rather_than_read_as_empty(tmp_path: pathlib.Path) -> None:
    with pytest.raises(ReleaseError, match="uv.lock is not TOML"):
        _packages.tree_packages(_app(tmp_path, uv="not = [toml"))


def _bundle(directory: pathlib.Path, images: dict[str, tuple[list[tuple[str, str]], str, dict]], *, tamper: str | None = None) -> pathlib.Path:
    """A bundle as ``sign`` writes one: the SBOMs and a manifest recording each one's digest."""
    directory.mkdir()
    outputs = {}
    for name, (packages, ecosystem, vulnerabilities) in images.items():
        data = canonical(sbom(name, "v1.2.0", packages, ecosystem))
        (directory / f"sbom-{name.replace('/', '_')}.cdx.json").write_bytes((b"[]" if name == tamper else data) + b"\n")
        outputs[name] = {"sbom": hashlib.sha256(data).hexdigest(), "tag": "v1.2.0", "vulnerabilities": vulnerabilities}
    (directory / "release.manifest.json").write_bytes(canonical({"schemaVersion": 1, "outputs": {"images": outputs}}) + b"\n")
    return directory


def test_a_signed_bundle_yields_its_packages_and_what_was_known_when_it_was_signed(tmp_path: pathlib.Path) -> None:
    from terp.cli.release.sign import MANIFEST

    assert _packages.MANIFEST == MANIFEST
    bundle = _packages.bundle_packages(_bundle(tmp_path / "b", {
        "acme/api": ([("Jinja2", "2.11.2")], "pypi", {"pkg:pypi/jinja2@2.11.2": ["GHSA-1"]}),
        "acme/web": ([("@scope/ui", "1.0.0")], "npm", None),
    }))
    assert bundle.tag == "v1.2.0"
    assert bundle.packages == [
        Package("PyPI", "jinja2", "2.11.2", "image acme/api"),
        Package("npm", "@scope/ui", "1.0.0", "image acme/web"),
    ]
    assert bundle.recorded == {"pkg:pypi/jinja2@2.11.2": frozenset({"GHSA-1"})}


@pytest.mark.parametrize(
    ("make", "expected"),
    [
        (lambda d: d.mkdir(), "release.manifest.json could not be read as JSON"),
        (lambda d: (d.mkdir(), (d / "release.manifest.json").write_text("[]")), "records no images"),
        (lambda d: (d.mkdir(), (d / "release.manifest.json").write_text('{"outputs": {"images": {"api": {}}}}')), "holds no sbom-api.cdx.json"),
        (lambda d: _bundle(d, {"api": ([("x", "1")], "pypi", {})}, tamper="api"), "not the SBOM the manifest recorded for api"),
    ],
)
def test_a_bundle_that_is_not_one_is_refused(tmp_path: pathlib.Path, make, expected: str) -> None:
    make(tmp_path / "b")
    with pytest.raises(ReleaseError, match=expected):
        _packages.bundle_packages(tmp_path / "b")


def test_a_component_that_names_no_package_url_is_left_out(tmp_path: pathlib.Path) -> None:
    directory = _bundle(tmp_path / "b", {"api": ([("x", "1")], "pypi", {})})
    document = {"components": [{"purl": "pkg:golang/x@1"}, {"purl": "pkg:pypi/noversion"}, {"name": "bare"}, {"purl": "pkg:pypi/x@1"}]}
    data = canonical(document)
    (directory / "sbom-api.cdx.json").write_bytes(data + b"\n")
    manifest = {"outputs": {"images": {"api": {"sbom": hashlib.sha256(data).hexdigest()}}}}
    (directory / "release.manifest.json").write_bytes(canonical(manifest))
    bundle = _packages.bundle_packages(directory)
    assert bundle.packages == [Package("PyPI", "x", "1", "image api")] and bundle.tag is None and bundle.recorded == {}


# --- the advisories -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("lower", "higher"),
    [
        ("1.9", "1.10"), ("1.2.0rc1", "1.2.0"), ("1.2.0-beta.1", "1.2.0-rc.1"), ("1.1.9", "1.2.0-beta.1"),
        ("1.0.0-1", "1.0.0-rc1"), ("abc", "0.1"), ("2.11.2", "3.1.6"), ("v1.0", "1.0.1"),
        ("1.0.dev1", "1.0a1"), ("1.0a1", "1.0b1"), ("1.0b2", "1.0rc1"), ("1.0rc1", "1.0"), ("1.0", "1.0.post1"),
        ("1.0.post1", "1.0.post2"), ("1.0.0-alpha.1", "1.0.0-beta"), ("1.0.post1", "1.0.1"),
    ],
)
def test_release_numbers_order_as_both_ecosystems_number_them(lower: str, higher: str) -> None:
    assert _vulnerabilities.version_key(lower) < _vulnerabilities.version_key(higher)


def test_equal_release_numbers_compare_equal() -> None:
    key = _vulnerabilities.version_key
    assert key("1.2") == key("1.2.0") == key("1.2.0+local") == key("V1.2")
    assert key("1.0alpha1") == key("1.0a1") and key("1.0c1") == key("1.0rc1") == key("1.0.preview1")


def test_an_advisory_covers_what_its_ranges_and_versions_say() -> None:
    package = Package("PyPI", "jinja2", "2.11.2", "uv.lock")
    record = {
        "affected": [
            affected("PyPI", "Jinja2", {"introduced": "0"}, {"fixed": "2.10.1"}, {"introduced": "2.11"}, {"fixed": "3.1.6"}),
            affected("PyPI", "jinja2", {"introduced": "3.2"}, {"last_affected": "3.3"}),
            affected("npm", "jinja2", {"introduced": "0"}, {"fixed": "9"}),
            {"package": {"ecosystem": "PyPI", "name": "jinja2"}, "versions": ["4.0.1"]},
            {"package": {"ecosystem": "PyPI", "name": "jinja2"}, "ranges": [{"type": "GIT", "events": [{"fixed": "abc"}]}, "x"]},
            "not an entry",
        ]
    }
    covered = {version: _vulnerabilities.affects(record, package, version) for version in
               ("2.9", "2.10.1", "2.11.2", "3.1.6", "3.2", "3.3", "3.3.1", "4.0.1", "9.0")}
    assert covered == {"2.9": True, "2.10.1": False, "2.11.2": True, "3.1.6": False, "3.2": True, "3.3": True,
                       "3.3.1": False, "4.0.1": True, "9.0": False}
    assert _vulnerabilities.fixes(record, package) == ["3.1.6"], "only a fix above the installed version"
    npm = Package("npm", "@scope/x", "1.0.0", "frontend/package-lock.json")
    exact = {"affected": [affected("npm", "@scope/x", {"fixed": "1.0.1"}), affected("npm", "@scope/X", {"fixed": "1.0.2"})]}
    assert _vulnerabilities.fixes(exact, npm) == ["1.0.1"], "npm names are compared exactly"


def test_the_fix_offered_is_the_lowest_version_no_advisory_still_covers() -> None:
    """A fixed on two release lines, B on one: 2.1 fixes B and is still inside A's 2.x range."""
    database = FakeOSV()
    database.add("A", ["pkg:pypi/lib@1.0"], affected=[affected("PyPI", "lib", {"introduced": "0"}, {"fixed": "1.1"},
                                                              {"introduced": "2.0"}, {"fixed": "2.2"})])
    database.add("B", ["pkg:pypi/lib@1.0"], affected=[affected("PyPI", "lib", {"introduced": "0"}, {"fixed": "2.1"})])
    report = Report("app", "/a")
    with serving(database):
        _vulnerabilities.vulnerability_findings(report, [Package("PyPI", "lib", "1.0", "uv.lock")], database.url)
    assert report.findings[0].fixed_in == "2.2"
    assert report.findings[0].remedy == "Move lib to 2.2 or later: uv lock --upgrade-package lib."


def test_fixes_on_lines_no_one_release_clears_say_so() -> None:
    database = FakeOSV()
    database.add("A", ["pkg:pypi/lib@1.0"], affected=[affected("PyPI", "lib", {"introduced": "0"}, {"fixed": "1.1"},
                                                              {"introduced": "2.0"})])
    database.add("B", ["pkg:pypi/lib@1.0"], affected=[affected("PyPI", "lib", {"introduced": "1.1"}, {"fixed": "2.0"})])
    report = Report("app", "/a")
    with serving(database):
        _vulnerabilities.vulnerability_findings(report, [Package("PyPI", "lib", "1.0", "uv.lock")], database.url)
    assert report.findings[0].fixed_in is None
    assert report.findings[0].remedy.startswith("No one release of lib clears A, B: each is fixed on another release line.")


def _database() -> FakeOSV:
    database = FakeOSV()
    jinja = [affected("PyPI", "jinja2", {"introduced": "0"}, {"fixed": "3.1.6"})]
    database.add("GHSA-a", ["pkg:pypi/jinja2@2.11.2"], aliases=["CVE-1", "PYSEC-1"], summary="sandbox escape",
                 database_specific={"severity": "HIGH"}, affected=jinja)
    database.add("PYSEC-1", ["pkg:pypi/jinja2@2.11.2"], aliases=["CVE-1"], affected=jinja)
    database.add("PYSEC-2", ["pkg:pypi/jinja2@2.11.2"], aliases=["CVE-2"], affected=[affected("PyPI", "jinja2", {"fixed": "2.11.3"})])
    database.add("GHSA-b", ["pkg:pypi/jinja2@2.11.2"], aliases=["CVE-2"], database_specific={"severity": ""})
    database.add("GHSA-withdrawn", ["pkg:pypi/jinja2@2.11.2"], withdrawn="2026-01-01T00:00:00Z")
    database.add("GHSA-c", ["pkg:npm/lodash@4.17.15"], summary="", affected=[affected("npm", "lodash", {"fixed": "4.18.0"})])
    database.add("GHSA-nofix", ["pkg:npm/%40scope/pkg@1.0.0"], affected=[affected("npm", "@scope/pkg", {"introduced": "0"})])
    database.add("GHSA-only-withdrawn", ["pkg:pypi/markupsafe@2.0.1"], withdrawn="2026-01-01T00:00:00Z")
    return database


def test_each_vulnerable_package_is_one_finding_with_one_advisory_per_flaw() -> None:
    packages = [
        Package("PyPI", "jinja2", "2.11.2", "uv.lock"),
        Package("PyPI", "markupsafe", "2.0.1", "uv.lock"),
        Package("npm", "lodash", "4.17.15", "frontend/package-lock.json"),
        Package("npm", "@scope/pkg", "1.0.0", "package-lock.json"),
        Package("PyPI", "clean", "1.0", "uv.lock"),
    ]
    report = Report("app", "/a")
    with serving(_database()) as database:
        _vulnerabilities.vulnerability_findings(report, packages, database.url)
    assert report.sources == [_report.Source("osv", True)]
    found = {finding.subject: finding for finding in report.findings}
    assert sorted(found) == ["@scope/pkg", "jinja2", "lodash"], "a withdrawn advisory and a clean package say nothing"
    jinja = found["jinja2"]
    assert [a.id for a in jinja.advisories] == ["GHSA-a", "GHSA-b"], "a GHSA and a PYSEC for one CVE are one flaw"
    assert jinja.advisories[0] == Advisory("GHSA-a", ("CVE-1", "PYSEC-1"), "sandbox escape", "HIGH")
    assert jinja.advisories[1] == Advisory("GHSA-b", ("CVE-2", "PYSEC-2"), None, None)
    assert (jinja.fixed_in, jinja.ecosystem, jinja.location, jinja.new_since_release) == ("3.1.6", "PyPI", "uv.lock", None)
    assert jinja.remedy == "Move jinja2 to 3.1.6 or later: uv lock --upgrade-package jinja2."
    assert found["lodash"].remedy == "Move lodash to 4.18.0 or later: npm --prefix frontend install lodash@4.18.0."
    assert found["lodash"].advisories[0].summary is None
    assert found["@scope/pkg"].fixed_in is None
    assert found["@scope/pkg"].remedy.startswith("No release of @scope/pkg fixes GHSA-nofix yet.")


def test_a_package_another_one_brought_in_is_updated_in_place_never_installed_by_name() -> None:
    database = FakeOSV()
    database.add("A", ["pkg:npm/minimist@1.2.0"], affected=[affected("npm", "minimist", {"fixed": "1.2.6"})])
    report = Report("app", "/a")
    with serving(database):
        _vulnerabilities.vulnerability_findings(
            report, [Package("npm", "minimist", "1.2.0", "frontend/package-lock.json", direct=False)], database.url
        )
    assert report.findings[0].remedy == (
        "Move minimist to 1.2.6 or later: npm --prefix frontend update minimist (it comes in through another "
        "package: if that one's range keeps it below 1.2.6, update that package, or add an `overrides` entry "
        "for minimist)."
    )


def test_an_advisory_without_a_fix_beside_one_with_a_fix_is_named() -> None:
    database = FakeOSV()
    database.add("A", ["pkg:pypi/x@1.0"], affected=[affected("PyPI", "x", {"fixed": "1.1"})])
    database.add("B", ["pkg:pypi/x@1.0"], affected=[])
    report = Report("app", "/a")
    with serving(database):
        _vulnerabilities.vulnerability_findings(report, [Package("PyPI", "x", "1.0", "uv.lock")], database.url)
    assert report.findings[0].remedy == (
        "Move x to 1.1 or later: uv lock --upgrade-package x. No release of x fixes B yet. Read the advisory "
        "for a workaround, or replace the package; check again when a fix is published."
    )
    database.add("C", ["pkg:pypi/x@1.0"])
    two = Report("app", "/a")
    with serving(database):
        _vulnerabilities.vulnerability_findings(two, [Package("PyPI", "x", "1.0", "uv.lock")], database.url)
    assert "No release of x fixes B, C yet." in two.findings[0].remedy


def test_a_release_says_which_flaws_are_new_since_it_was_signed() -> None:
    packages = [Package("PyPI", "jinja2", "2.11.2", "image api"), Package("npm", "lodash", "4.17.15", "image web")]
    recorded = {"pkg:pypi/jinja2@2.11.2": frozenset({"PYSEC-1", "PYSEC-2"}), "pkg:npm/lodash@4.17.15": frozenset()}
    report = Report("release", "/b")
    with serving(_database()) as database:
        _vulnerabilities.vulnerability_findings(report, packages, database.url, recorded=recorded)
    found = {finding.subject: finding for finding in report.findings}
    assert found["jinja2"].new_since_release is False, "every flaw was recorded under one of its ids"
    assert found["lodash"].new_since_release is True
    assert found["jinja2"].remedy.endswith("uv lock --upgrade-package jinja2, then cut a new release.")
    assert found["lodash"].remedy == (
        "Move lodash to 4.18.0 or later: in the npm workspace image web is built from, npm install "
        "lodash@4.18.0, then cut a new release."
    ), "a bundle names the image, never a workspace it cannot know"


def test_a_database_that_does_not_answer_says_so_and_reports_no_package() -> None:
    with serving(FakeOSV()) as database:
        gone = database.url
    report = Report("app", "/a")
    _vulnerabilities.vulnerability_findings(report, [Package("PyPI", "x", "1", "uv.lock")], gone)
    assert report.sources == [_report.Source("osv", False, report.sources[0].detail)]
    assert report.sources[0].detail.startswith("the vulnerability database could not be asked: ")
    assert [finding.kind for finding in report.findings] == ["source-unavailable"]
    assert "Nothing was learned about any package" in report.findings[0].remedy
    plain = Report("app", "/a")
    with serving(FakeOSV(status=503)) as database:
        _vulnerabilities.vulnerability_findings(plain, [Package("PyPI", "x", "1", "uv.lock")], database.url)
    assert plain.sources[0].detail == "the vulnerability database answered 503"


def test_with_nothing_to_ask_the_database_is_not_asked() -> None:
    report = Report("tree", "/t")
    _vulnerabilities.vulnerability_findings(report, [], "http://127.0.0.1:9")
    assert report.sources == [] and report.findings == []


# --- the command ----------------------------------------------------------------------------


def _run(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    code = run(_build_parser().parse_args(argv))
    out, err = capsys.readouterr()
    return code, out, err


def test_the_tree_target_reports_the_locks_of_another_checkout(tmp_path: pathlib.Path, capsys) -> None:
    tree = _app(tmp_path / "tree", npm=_npm_lock(("node_modules/lodash", {"version": "4.17.15"})))
    with serving(_database()) as database:
        code, out, _ = _run(["maintenance", "--tree", str(tree), "--osv", database.url, "--format", "json"], capsys)
    document = json.loads(out)
    assert code == 0
    assert document["target"] == {"kind": "tree", "path": str(tree.resolve()), "release": None}
    assert [(f["kind"], f["subject"]) for f in document["findings"]] == [("known-vulnerability", "jinja2"), ("known-vulnerability", "lodash")]


def test_the_release_target_reports_a_bundle(tmp_path: pathlib.Path, capsys) -> None:
    directory = _bundle(tmp_path / "b", {"api": ([("jinja2", "2.11.2")], "pypi", {"pkg:pypi/jinja2@2.11.2": ["GHSA-a"]})})
    with serving(_database()) as database:
        code, out, _ = _run(["maintenance", "--release", str(directory), "--osv", database.url], capsys)
    assert code == 0
    assert "(release v1.2.0)" in out and "jinja2 2.11.2 in image api: GHSA-a (HIGH), GHSA-b - new since" in out


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (["--tree", "{tmp}/missing"], "is not a directory"),
        (["--tree", "{tmp}"], "holds no uv.lock and no npm lock beside its package.json, so there is nothing to report on"),
        (["--release", "{tmp}"], "could not be read as JSON"),
        (["--root", "{tmp}"], "holds no pyproject.toml"),
    ],
)
def test_what_cannot_be_reported_on_exits_2_with_a_reason(tmp_path: pathlib.Path, capsys, argv, expected) -> None:
    code, out, err = _run(["maintenance", *(a.format(tmp=tmp_path) for a in argv)], capsys)
    assert (code, out) == (2, "")
    assert err.startswith("terp maintenance: could not report: ") and expected in err


def test_the_app_target_asks_every_source_in_turn(tmp_path: pathlib.Path, monkeypatch, capsys) -> None:
    from terp.cli.maintenance import _images, _platform

    asked: list[str] = []
    monkeypatch.setattr(_platform, "python_platform", lambda root, report: asked.append("python") or "0.42.0")
    monkeypatch.setattr(_platform, "template", lambda root, report, platform: asked.append(f"template {platform}"))
    monkeypatch.setattr(_platform, "npm_platform", lambda root, report: asked.append("npm"))
    monkeypatch.setattr(_images, "base_image_findings", lambda root, report: asked.append("images"))
    root = _app(tmp_path, uv=None)
    code, out, _ = _run(["maintenance", "--root", str(root)], capsys)
    assert code == 0 and asked == ["python", "template 0.42.0", "npm", "images"]
    assert "Nothing found by the checks that ran. Not every check could run:\n  - known-vulnerability: the app holds no uv.lock" in out
    (root / "uv.lock").write_text(UV_LOCK, encoding="utf-8")
    with serving(FakeOSV()) as database:
        code, out, _ = _run(["maintenance", "--root", str(root), "--osv", database.url, "--format", "json"], capsys)
    assert json.loads(out)["not_checked"] == [] and json.loads(out)["sources"][0]["name"] == "osv"
    asked.clear()
    asked.clear()
    monkeypatch.setattr(_platform, "python_platform", lambda root, report: asked.append("python") and None)
    _run(["maintenance", "--root", str(root)], capsys)
    assert asked == ["python", "npm", "images"], "no platform version, nothing to compare the scaffolding with"


def test_the_entry_point_exits_2_only_when_it_could_not_report(tmp_path: pathlib.Path, capsys) -> None:
    from terp.cli import main

    with pytest.raises(SystemExit) as refused:
        main(["maintenance", "--tree", str(tmp_path / "missing")])
    assert refused.value.code == 2
    main(["maintenance", "--tree", str(_app(tmp_path / "own-only", uv=UV_LOCK.split("[[package]]\nname = \"Jinja2\"")[0]))])
    assert "Nothing to maintain: every check ran and found nothing." in capsys.readouterr().out


def test_upgrade_still_answers_through_its_own_command(monkeypatch, capsys) -> None:
    from terp.cli import version

    monkeypatch.setattr(version, "render_upgrade_check", lambda fmt="text": f"checked as {fmt}")
    assert _run(["upgrade", "--check", "--format", "json"], capsys)[:2] == (0, "checked as json\n")
    with pytest.raises(SystemExit, match="run `terp upgrade --check`"):
        run(argparse.Namespace(command="upgrade", check=False, format="text"))


def test_the_console_entry_point_reports_across_a_real_process(tmp_path: pathlib.Path) -> None:
    """``terp maintenance`` as a scheduler runs it: its own process, a JSON document on stdout."""
    tree = _app(tmp_path / "tree")
    source = pathlib.Path(__file__).resolve().parents[2] / "packages" / "backend" / "cli" / "src"
    with serving(_database()) as database:
        completed = subprocess.run(
            [sys.executable, "-c", f"import sys; sys.path.insert(0, {str(source)!r}); from terp.cli import main; main()",
             "maintenance", "--tree", str(tree), "--osv", database.url, "--format", "json"],
            capture_output=True, text=True, check=False, timeout=120,
        )
    assert completed.returncode == 0, completed.stderr
    assert [f["subject"] for f in json.loads(completed.stdout)["findings"]] == ["jinja2"]
    refused = subprocess.run(
        [sys.executable, "-c", f"import sys; sys.path.insert(0, {str(source)!r}); from terp.cli import main; main()",
         "maintenance", "--tree", str(tmp_path / "missing")],
        capture_output=True, text=True, check=False, timeout=120,
    )
    assert refused.returncode == 2 and refused.stdout == ""
