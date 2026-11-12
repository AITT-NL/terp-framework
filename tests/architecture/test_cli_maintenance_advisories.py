"""``terp maintenance``: versions, advisory ranges, the fix it offers, and what it sends (ADR 0214).

Every request crosses a real socket to a database on this machine's loopback, through the
declared egress client (:mod:`tests.architecture.osv_fixtures`).
"""

from __future__ import annotations

import pathlib

from packaging.version import Version

from terp.cli.maintenance import _report, _vulnerabilities
from terp.cli.maintenance._packages import Package
from terp.cli.maintenance._report import Advisory, Report
from tests.architecture.maintenance_fixtures import advisories
from tests.architecture.osv_fixtures import FakeOSV, affected, serving

key = _vulnerabilities.version_key

# --- versions -------------------------------------------------------------------------------

#: Every form PEP 440 orders, shuffled: the key must order them exactly as ``packaging`` does.
_PEP440 = ["1.0.post1", "1!0.1", "1.0rc1", "1.0a1.dev1", "1.0", "1.1", "2.0.0", "1.0.dev1", "1.0b1", "1.0a2",
           "1.0-1", "1.0rev2", "1.0.1", "1.0r", "1.0.post1.dev1", "v1.2", "1.0a1", "1.0.0+local", "1.0alpha3",
           "1.0c2", "1.0.preview3", "0.9", "1.0.dev2", "1.0b1.post1"]


def test_pypi_versions_order_exactly_as_packaging_orders_them() -> None:
    assert [str(Version(v)) for v in sorted(_PEP440, key=lambda v: key(v, "PyPI"))] == [
        str(v) for v in sorted(Version(v) for v in _PEP440)
    ]


def test_npm_versions_order_as_semver_orders_them() -> None:
    ordered = ["1.0.0-alpha", "1.0.0-alpha.1", "1.0.0-alpha.beta", "1.0.0-beta", "1.0.0-beta.2", "1.0.0-beta.11",
               "1.0.0-rc.1", "1.0.0", "1.2.3", "1.10.0", "2.0.0"]
    assert sorted(reversed(ordered), key=lambda v: key(v, "npm")) == ordered
    assert key("1.0.0+build.5", "npm") == key("1.0.0", "npm") and key("v1.2", "npm") == key("1.2.0", "npm")


def test_a_version_neither_order_reads_sorts_below_every_release() -> None:
    assert key("not a version", "PyPI") < key("0.0.1", "PyPI") and key("x.y", "npm") < key("0.0.0-0", "npm")


# --- ranges ---------------------------------------------------------------------------------


def _jinja(version: str = "2.11.2") -> Package:
    return Package("PyPI", "jinja2", version, "uv.lock", registry="pypi.org")


def test_an_advisory_covers_what_its_ranges_and_versions_say() -> None:
    record = {
        "affected": [
            affected("PyPI", "Jinja2", {"fixed": "3.1.6"}, {"introduced": "2.11"}, {"fixed": "2.10.1"}, {"introduced": "0"}),
            affected("PyPI", "jinja2", {"introduced": "3.2"}, {"last_affected": "3.3"}),
            affected("PyPI", "jinja2", {"introduced": "5.0"}, {"limit": "5.5"}),
            affected("npm", "jinja2", {"introduced": "0"}, {"fixed": "9"}),
            {"package": {"ecosystem": "PyPI", "name": "jinja2"}, "versions": ["4.0.1"]},
            {"package": {"ecosystem": "PyPI", "name": "jinja2"}, "ranges": [{"type": "GIT", "events": [{"fixed": "abc"}]}, "x"]},
            {"package": "jinja2"},
            "not an entry",
        ]
    }
    covered = {version: _vulnerabilities.affects(record, _jinja(), version) for version in
               ("2.9", "2.10.1", "2.11.2", "3.1.6", "3.2", "3.3", "3.3.1", "4.0.1", "5.2", "5.5", "9.0")}
    assert covered == {"2.9": True, "2.10.1": False, "2.11.2": True, "3.1.6": False, "3.2": True, "3.3": True,
                       "3.3.1": False, "4.0.1": True, "5.2": True, "5.5": False, "9.0": False}, (
        "events read in version order whatever order they are listed in, and a limit caps the range"
    )
    assert _vulnerabilities.fixes(record, _jinja()) == ["3.1.6"], "only a fix above the installed version"
    npm = Package("npm", "@scope/x", "1.0.0", "frontend/package-lock.json")
    exact = {"affected": [affected("npm", "@scope/x", {"fixed": "1.0.1"}), affected("npm", "@scope/X", {"fixed": "1.0.2"})]}
    assert _vulnerabilities.fixes(exact, npm) == ["1.0.1"], "npm names are compared exactly"
    pre = Package("npm", "x", "2.0.0-rc.1", "frontend/package-lock.json")
    assert _vulnerabilities.fixes({"affected": [affected("npm", "x", {"fixed": "2.0.0-rc.2"})]}, pre) == ["2.0.0-rc.2"]


def _finding_of(database: FakeOSV, package: Package) -> _report.Finding:
    report = Report("app", "/a")
    with serving(database):
        _vulnerabilities.vulnerability_findings(report, [package], database.url)
    return report.findings[0]


def test_the_fix_offered_is_the_lowest_version_no_advisory_still_covers() -> None:
    """A fixed on two release lines, B on one: 2.1 fixes B and is still inside A's 2.x range."""
    database = FakeOSV()
    database.add("A", ["pkg:pypi/lib@1.0"], affected=[affected("PyPI", "lib", {"introduced": "0"}, {"fixed": "1.1"},
                                                              {"introduced": "2.0"}, {"fixed": "2.2"})])
    database.add("B", ["pkg:pypi/lib@1.0"], affected=[affected("PyPI", "lib", {"introduced": "0"}, {"fixed": "2.1"})])
    found = _finding_of(database, Package("PyPI", "lib", "1.0", "uv.lock", registry="pypi.org"))
    assert (found.fixed_in, found.remedy) == ("2.2", "Move lib to 2.2 or later: uv lock --upgrade-package lib.")


def test_a_fix_released_as_a_post_release_is_offered() -> None:
    database = FakeOSV()
    database.add("A", ["pkg:pypi/lib@1.0"], affected=[affected("PyPI", "lib", {"introduced": "0"}, {"fixed": "1.0.post1"})])
    assert _finding_of(database, Package("PyPI", "lib", "1.0", "uv.lock", registry="pypi.org")).fixed_in == "1.0.post1"


def test_fixes_on_lines_no_one_release_clears_say_so() -> None:
    database = FakeOSV()
    database.add("A", ["pkg:pypi/lib@1.0"], affected=[affected("PyPI", "lib", {"introduced": "0"}, {"fixed": "1.1"},
                                                              {"introduced": "2.0"})])
    database.add("B", ["pkg:pypi/lib@1.0"], affected=[affected("PyPI", "lib", {"introduced": "1.1"}, {"fixed": "2.0"})])
    found = _finding_of(database, Package("PyPI", "lib", "1.0", "uv.lock", registry="pypi.org"))
    assert found.fixed_in is None
    assert found.remedy.startswith("No one release of lib clears A, B: each is fixed on another release line.")


def test_an_advisory_without_a_fix_beside_one_with_a_fix_is_named() -> None:
    database = FakeOSV()
    database.add("A", ["pkg:pypi/x@1.0"], affected=[affected("PyPI", "x", {"fixed": "1.1"})])
    database.add("B", ["pkg:pypi/x@1.0"], affected=[])
    x = Package("PyPI", "x", "1.0", "uv.lock", registry="pypi.org")
    assert _finding_of(database, x).remedy == (
        "Move x to 1.1 or later: uv lock --upgrade-package x. No release of x fixes B yet. Read the advisory "
        "for a workaround, or replace the package; check again when a fix is published."
    )
    database.add("C", ["pkg:pypi/x@1.0"])
    assert "No release of x fixes B, C yet." in _finding_of(database, x).remedy


# --- findings -------------------------------------------------------------------------------


def test_each_vulnerable_package_is_one_finding_with_one_advisory_per_flaw() -> None:
    packages = [
        _jinja(),
        Package("PyPI", "markupsafe", "2.0.1", "uv.lock", registry="pypi.org"),
        Package("npm", "lodash", "4.17.15", "frontend/package-lock.json", True, "registry.npmjs.org"),
        Package("npm", "@scope/pkg", "1.0.0", "package-lock.json", True, "registry.npmjs.org"),
        Package("PyPI", "clean", "1.0", "uv.lock", registry="pypi.org"),
    ]
    report = Report("app", "/a")
    with serving(advisories()) as database:
        _vulnerabilities.vulnerability_findings(report, packages, database.url)
    assert report.sources == [_report.Source("osv", True)] and report.not_checked == []
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
    found = _finding_of(database, Package("npm", "minimist", "1.2.0", "frontend/package-lock.json", False, "registry.npmjs.org"))
    assert found.remedy == (
        "Move minimist to 1.2.6 or later: npm --prefix frontend update minimist (it comes in through another "
        "package: if that one's range keeps it below 1.2.6, update that package, or add an `overrides` entry "
        "for minimist)."
    )


def test_a_release_says_which_flaws_are_new_since_it_was_signed() -> None:
    packages = [Package("PyPI", "jinja2", "2.11.2", "image api"), Package("npm", "lodash", "4.17.15", "image web")]
    recorded = {"pkg:pypi/jinja2@2.11.2": frozenset({"PYSEC-1", "PYSEC-2"}), "pkg:npm/lodash@4.17.15": frozenset()}
    report = Report("release", "/b")
    with serving(advisories()) as database:
        _vulnerabilities.vulnerability_findings(report, packages, database.url, recorded=recorded, only_public=False)
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
    _vulnerabilities.vulnerability_findings(report, [_jinja()], gone)
    assert report.sources == [_report.Source("osv", False, report.sources[0].detail)]
    assert str(report.sources[0].detail).startswith("the vulnerability database could not be asked: ")
    assert [finding.kind for finding in report.findings] == ["source-unavailable"]
    assert "Nothing was learned about any package" in report.findings[0].remedy


def test_an_advisory_that_cannot_be_read_after_the_batch_answered_is_no_partial_answer() -> None:
    """The batch names GHSA-gone, its record answers 404: nothing is reported about any package."""
    database = advisories()
    database.matches.setdefault("pkg:pypi/jinja2@2.11.2", []).append("GHSA-gone")
    report = Report("app", "/a")
    with serving(database):
        _vulnerabilities.vulnerability_findings(report, [_jinja(), Package("npm", "lodash", "4.17.15", "frontend/package-lock.json", True, "registry.npmjs.org")], database.url)
    assert [finding.kind for finding in report.findings] == ["source-unavailable"]
    assert report.sources[0].detail == "the vulnerability database answered 404"


def test_with_nothing_to_ask_the_database_is_not_asked() -> None:
    report = Report("tree", "/t")
    _vulnerabilities.vulnerability_findings(report, [], "http://127.0.0.1:9")
    assert report.sources == [] and report.findings == [] and report.not_checked == []


# --- what is sent ---------------------------------------------------------------------------


def test_a_private_index_s_names_stay_here_and_are_named_as_not_checked() -> None:
    private = [
        Package("PyPI", "internal-lib", "3.1.0", "uv.lock", registry="pkgs.example.com"),
        Package("npm", "@acme-internal/ui", "1.0.0", "frontend/package-lock.json", True, "npm.example.com"),
        Package("npm", "unresolved", "1.0.0", "frontend/package-lock.json", True),
    ]
    report = Report("app", "/a")
    with serving(advisories()) as database:
        _vulnerabilities.vulnerability_findings(report, [_jinja(), *private], database.url)
    assert [query["package"]["purl"] for batch in database.batches for query in batch] == ["pkg:pypi/jinja2@2.11.2"]
    assert report.not_checked == [
        "known-vulnerability: 3 packages from an index that is not public (npm.example.com, pkgs.example.com) "
        "were not sent to the vulnerability database, so their names stay on this machine: point --osv at a "
        "mirror inside your network, or pass --send-private-names if those names may leave it"
    ]
    alone = Report("app", "/a")
    _vulnerabilities.vulnerability_findings(alone, private[2:], "http://127.0.0.1:9")
    assert alone.sources == [] and alone.not_checked[0].startswith(
        "known-vulnerability: 1 package from an index that is not public (an index the lock does not name) was not sent"
    ), "nothing left to ask, and nothing asked"


def test_without_the_egress_client_the_database_is_not_asked_and_the_report_says_how_to_add_it(monkeypatch) -> None:
    import importlib.util

    from terp.cli import version

    real = importlib.util.find_spec
    monkeypatch.setattr(importlib.util, "find_spec", lambda name, *a: None if name == "terp.capabilities.egress" else real(name, *a))
    monkeypatch.setattr(version, "installed_terp_versions", lambda: {"terp-cli": "0.43.0"})
    report = Report("app", "/a")
    _vulnerabilities.vulnerability_findings(report, [_jinja()], "http://127.0.0.1:9")
    assert report.sources == [] and report.findings == []
    assert report.not_checked == [
        "known-vulnerability: terp-cap-egress is not installed in this environment, so the vulnerability database "
        "was not asked: add it to the development group (`uv add --dev terp-cap-egress==0.43.0`)"
    ]

    def gone(name: str, *args: object) -> None:
        raise ModuleNotFoundError(name)

    monkeypatch.setattr(importlib.util, "find_spec", gone)
    monkeypatch.setattr(version, "installed_terp_versions", lambda: {})
    bare = Report("app", "/a")
    _vulnerabilities.vulnerability_findings(bare, [_jinja()], "http://127.0.0.1:9")
    assert bare.not_checked[0].endswith("(`uv add --dev terp-cap-egress`)")


def test_the_live_shape_of_a_real_advisory_is_read(tmp_path: pathlib.Path) -> None:
    """One record as api.osv.dev writes it (GHSA-cpwx-vrp4-4pq7, trimmed): ranges, aliases, severity."""
    database = FakeOSV()
    database.add(
        "GHSA-cpwx-vrp4-4pq7", ["pkg:pypi/jinja2@2.11.2"], aliases=["CVE-2025-27516"],
        summary="Jinja2 vulnerable to sandbox breakout through attr filter selecting format method",
        database_specific={"severity": "MODERATE", "cwe_ids": ["CWE-1336"]},
        affected=[{"package": {"ecosystem": "PyPI", "name": "jinja2", "purl": "pkg:pypi/jinja2"},
                   "ranges": [{"type": "ECOSYSTEM", "events": [{"introduced": "0"}, {"fixed": "3.1.6"}]}],
                   "versions": ["2.0", "2.11.2", "3.1.5"]}],
    )
    found = _finding_of(database, _jinja())
    assert (found.fixed_in, found.advisories[0].severity, found.advisories[0].aliases) == ("3.1.6", "MODERATE", ("CVE-2025-27516",))
