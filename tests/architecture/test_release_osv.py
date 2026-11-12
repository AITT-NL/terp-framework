"""The vulnerability database, asked one way by ``sign`` and ``terp maintenance`` (ADR 0214).

Every request here crosses a real socket, through the declared egress client, to a database
on this machine's loopback (:mod:`tests.architecture.osv_fixtures`), so the gate needs no
network; only the address differs from ``https://api.osv.dev``.
"""

from __future__ import annotations

from typing import Any

import pytest

from terp.cli.release import _common, _osv
from terp.cli.release._common import ReleaseError
from tests.architecture.osv_fixtures import FakeOSV, serving


def test_each_package_is_asked_in_batches_and_a_clean_one_is_left_out() -> None:
    database = FakeOSV()
    database.add("B", ["pkg:pypi/p0@1"])
    database.add("A", ["pkg:pypi/p0@1", "pkg:npm/%40scope/q@2"])
    purls = [f"pkg:pypi/p{i}@1" for i in range(501)] + ["pkg:npm/%40scope/q@2"]
    with serving(database):
        found = _osv.query_batch(database.url + "/", purls)
    assert found == {"pkg:npm/%40scope/q@2": ["A"], "pkg:pypi/p0@1": ["A", "B"]}
    assert [len(batch) for batch in database.batches] == [500, 2]


def test_a_long_list_is_followed_page_by_page_and_never_cut_short() -> None:
    database = FakeOSV(paged={"pkg:pypi/x@1"})
    for advisory_id in ("A", "B", "C"):
        database.add(advisory_id, ["pkg:pypi/x@1"])
    with serving(database):
        assert _osv.query_batch(database.url, ["pkg:pypi/x@1"]) == {"pkg:pypi/x@1": ["A", "B", "C"]}
    assert [batch[0].get("page_token") for batch in database.batches] == [None, "1", "2"]


def test_a_continuation_that_never_ends_is_refused(monkeypatch) -> None:
    database = FakeOSV(paged={"pkg:pypi/x@1"})
    for advisory_id in ("A", "B", "C", "D"):
        database.add(advisory_id, ["pkg:pypi/x@1"])
    monkeypatch.setattr(_osv, "_PAGES", 3)
    with serving(database), pytest.raises(ReleaseError, match="kept answering pkg:pypi/x@1 with another page"):
        _osv.query_batch(database.url, ["pkg:pypi/x@1"])


@pytest.mark.parametrize(
    ("database", "expected"),
    [
        (FakeOSV(status=500), "answered 500"),
        (FakeOSV(body=b"not json"), "answered no JSON$"),
        (FakeOSV(body=b"[]"), "answered no JSON object"),
        (FakeOSV(body=b'{"results": []}'), "for other packages than asked"),
        (FakeOSV(body=b'{"results": {}}'), "for other packages than asked"),
    ],
)
def test_an_answer_that_cannot_be_trusted_is_refused(database: FakeOSV, expected: str) -> None:
    with serving(database), pytest.raises(ReleaseError, match=expected):
        _osv.query_batch(database.url, ["pkg:pypi/x@1"])


def test_a_result_that_is_not_an_object_reads_as_no_advisory() -> None:
    with serving(FakeOSV(body=b'{"results": [null, "x"]}')) as database:
        assert _osv.query_batch(database.url, ["pkg:pypi/x@1", "pkg:pypi/y@1"]) == {}


def test_an_unreachable_database_is_a_refusal_never_a_clean_answer() -> None:
    with serving(FakeOSV()) as database:
        gone = database.url
    with pytest.raises(ReleaseError, match="could not be asked"):
        _osv.query_batch(gone, ["pkg:pypi/x@1"])


def test_a_host_outside_the_client_s_allowlist_is_never_reached() -> None:
    """The client is made for the database's own host: plain HTTP to anything else is refused."""
    with pytest.raises(ReleaseError, match="could not be asked"):
        _osv.query_batch("http://osv.example", ["pkg:pypi/x@1"])


def test_one_advisory_is_read_whole_and_must_be_the_one_asked_for() -> None:
    database = FakeOSV()
    database.add("GHSA-1", [], summary="s", aliases=["CVE-1"])
    database.advisories["WRONG"] = {"id": "OTHER"}
    with serving(database):
        assert _osv.advisory(database.url, "GHSA-1") == {"id": "GHSA-1", "summary": "s", "aliases": ["CVE-1"]}
        with pytest.raises(ReleaseError, match="answered 404"):
            _osv.advisory(database.url, "GHSA-missing")
        with pytest.raises(ReleaseError, match="another advisory than WRONG"):
            _osv.advisory(database.url, "WRONG")
    assert database.fetched == ["GHSA-1", "GHSA-missing", "WRONG"]


def test_the_egress_client_is_https_or_loopback_http() -> None:
    remote = _common.egress_client("https://api.osv.dev/v1/querybatch", 10).policy
    assert remote.allowed_hosts == ("api.osv.dev",) and remote.allowed_schemes == ("https",)
    assert remote.allow_private_addresses is False
    local = _common.egress_client("http://127.0.0.1:9/v1", 10).policy
    assert local.allowed_schemes == ("http", "https") and local.allow_private_addresses is True


def test_without_the_egress_capability_the_database_is_not_asked(monkeypatch) -> None:
    import builtins

    real = builtins.__import__

    def refuse(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "terp.capabilities.egress":
            raise ImportError(name)
        return real(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", refuse)
    with pytest.raises(ReleaseError, match="reaching api.osv.dev needs the egress capability"):
        _common.egress_client("https://api.osv.dev/v1/querybatch", 10)
