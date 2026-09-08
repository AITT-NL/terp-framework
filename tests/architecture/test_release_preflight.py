"""The release refuses a distribution PyPI has no project for.

``tools/check_pypi_projects.py`` exists because trusted publishing can add a
version to a project and cannot create one, and because the upload is a single
twine invocation: the first distribution PyPI refuses stops it with the earlier
ones already published. 0.19.0 released that way — ``terp-cap-egress`` was new,
five siblings were live before the refusal, and the lockstep pins left the
version uninstallable until the rest went up.

What is asserted here is mostly the *refusals*, because a gate that only
answers the happy case would have passed on the release that motivated it.
No network: existence is injected, so these tests state what the tool does
with an answer rather than what PyPI happens to say today.
"""

from __future__ import annotations

import pathlib
import re
import sys

import httpx
import pytest

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

sys.path.insert(0, str(_REPO_ROOT / "tools"))

from check_pypi_projects import (  # noqa: E402
    distribution_names,
    main,
    missing_projects,
    normalize,
    project_exists,
)


def test_every_published_distribution_is_checked() -> None:
    """Discovery must reach the same set the lockstep gate publishes.

    A guard narrower than the release it guards is the failure it exists to
    prevent, one release later: the new capability nobody thought to add here
    is exactly the kind that has no project yet.
    """
    names = distribution_names()

    backend = _REPO_ROOT / "packages" / "backend"
    published = {
        normalize(
            re.search(
                r'^name = "([^"]+)"', manifest.read_text(encoding="utf-8"), re.MULTILINE
            ).group(1)
        )
        for manifest in [
            *backend.glob("*/pyproject.toml"),
            *backend.glob("capabilities/*/pyproject.toml"),
        ]
    }

    assert set(names) == published
    assert len(names) == len(published), "a distribution is checked twice"
    # The kernel and one capability by name: an empty or truncated discovery
    # would satisfy a set comparison against an equally broken expectation.
    assert {"terp-core", "terp-cap-egress"} <= set(names)
    assert len(names) >= 15


def test_a_distribution_with_no_project_is_named_and_refused() -> None:
    absent = {"terp-cap-egress"}
    names = ["terp-core", "terp-cap-egress", "terp-cli"]

    missing = missing_projects(names, exists=lambda name: name not in absent)

    assert missing == ["terp-cap-egress"]


def test_a_release_whose_projects_all_exist_is_not_refused() -> None:
    missing = missing_projects(["terp-core", "terp-cli"], exists=lambda _name: True)

    assert missing == []


def test_every_missing_distribution_is_reported_not_just_the_first() -> None:
    """Several new capabilities in one release need several pending publishers.

    Reporting one at a time would send the operator around the loop once per
    distribution, learning about the next only after re-running the release.
    """
    present = {"terp-core"}
    names = ["terp-core", "terp-cap-egress", "terp-cap-leases"]

    missing = missing_projects(names, exists=lambda name: name in present)

    assert missing == ["terp-cap-egress", "terp-cap-leases"]


def test_the_refusal_exits_nonzero_and_says_how_to_fix_it(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "check_pypi_projects.distribution_names", lambda: ["terp-core", "terp-cap-egress"]
    )
    monkeypatch.setattr(
        "check_pypi_projects.missing_projects", lambda _names: ["terp-cap-egress"]
    )

    assert main() == 1

    stderr = capsys.readouterr().err
    assert "terp-cap-egress" in stderr
    # The two steps that actually unblock it, in the order they must happen.
    assert "pending publisher" in stderr
    assert "gh workflow run release.yml -f package=" in stderr


def test_a_release_with_every_project_present_exits_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("check_pypi_projects.distribution_names", lambda: ["terp-core"])
    monkeypatch.setattr("check_pypi_projects.missing_projects", lambda _names: [])

    assert main() == 0


def test_names_are_normalised_to_the_form_the_index_is_keyed_by() -> None:
    """``terp_cap_jobs_celery`` and ``terp-cap-jobs-celery`` are one project.

    Querying the un-normalised name would 404 on a project that exists, which
    fails a release for a reason that is not true.
    """
    assert normalize("terp_cap_jobs_celery") == "terp-cap-jobs-celery"
    assert normalize("Terp.Cap__Egress") == "terp-cap-egress"
    assert normalize("terp-core") == "terp-core"


def test_an_index_that_cannot_answer_refuses_rather_than_assuming_presence() -> None:
    """Fail closed: a 500 or a timeout is not evidence that the project is there.

    Treating an unhappy index as "present" would restore the original silence
    on exactly the day PyPI is unwell.
    """

    def unhappy_index(_url: str, **_kwargs: object) -> httpx.Response:
        return httpx.Response(500, request=httpx.Request("GET", "https://pypi.org/simple/x/"))

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(httpx, "get", unhappy_index)
        with pytest.raises(httpx.HTTPStatusError):
            project_exists("terp-core")

    def unreachable_index(_url: str, **_kwargs: object) -> httpx.Response:
        raise httpx.ConnectError("no route to host")

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(httpx, "get", unreachable_index)
        with pytest.raises(httpx.ConnectError):
            project_exists("terp-core")


def test_a_404_is_absence_and_a_200_is_presence() -> None:
    """The one status that means "no project", distinguished from the rest."""

    def responder(status: int):
        def get(_url: str, **_kwargs: object) -> httpx.Response:
            return httpx.Response(
                status, request=httpx.Request("GET", "https://pypi.org/simple/x/")
            )

        return get

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(httpx, "get", responder(404))
        assert project_exists("terp-cap-egress") is False

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(httpx, "get", responder(200))
        assert project_exists("terp-core") is True


def test_a_manifest_without_a_name_is_a_refusal_not_a_skip(tmp_path: pathlib.Path) -> None:
    """A manifest the regex cannot read must not silently drop out of the set."""
    (tmp_path / "packages" / "backend" / "broken").mkdir(parents=True)
    (tmp_path / "packages" / "backend" / "broken" / "pyproject.toml").write_text(
        '[project]\nversion = "0.19.0"\n', encoding="utf-8"
    )

    with pytest.raises(ValueError, match="declares no name"):
        distribution_names(tmp_path)
