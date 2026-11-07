"""``terp release sign`` signs only over a green release profile (ADR 0200).

The gate records every check of the release profile beside the release-assurance claim, and
``sign`` reads its document in the version the commit's pinned ``terp-cli`` writes: version 1,
the claim alone, below :data:`gate.STRICT_SINCE`; version 2 from it up, where every check must
have passed; version 3 from :data:`gate.APPLICABLE_SINCE`, where every check also says whether it
had anything to judge, so a lane composed only of such checks is never signed as passed. The
first cases hold :func:`gate.require_passed` to each refusal; the rest run the whole of ``sign``
on a commit that pins the first release whose gate writes version 2, and show that a refusal
comes before the registry, the index or the sandbox is asked anything.
"""

from __future__ import annotations

import json
import pathlib
import re

import pytest

from terp.cli.release import gate, sign
from terp.cli.release._common import ReleaseError
from terp.cli.release.manifest import parse
from terp.cli.verify import PROFILES, assurance_document
from tests.architecture.release_fixtures import REPO_ROOT, TOOLCHAIN, app_files
from tests.architecture.test_release_compare import SCRIPT, SITE, install
from tests.architecture.test_release_sign import Release

STRICT = gate.STRICT_SINCE
APPLICABLE = gate.APPLICABLE_SINCE

#: The checks an API-only app has nothing to judge in (ADR 0202): its frontend and its suite.
API_ONLY = (
    "dependency-audit-npm", "frontend-boundaries", "routes-drift", "api-client", "frontend-typecheck",
    "frontend-tests", "frontend-build", "conformance",
)

#: A version 1 document's verdict: the claim, and nothing of the checks.
CLAIM_ONLY = {"terpReleaseGate": 1, "assurance": {"terp_assurance": 1, "ok": True, "lanes": []}}


def _strict(red: tuple[str, ...] = (), *, app: tuple[str, ...] = (), ok: bool | None = None) -> dict:
    """A version 2 document's two verdicts, as the gate writes them from one run: every check of
    the release profile, then the app's own, each green unless *red* names it."""
    checks = [{"id": check, "ok": check not in red} for check in [*(c.id for c in PROFILES["release"]), *app]]
    recorded = all(check["ok"] for check in checks) if ok is None else ok
    return {
        "terpReleaseGate": 2,
        "profile": {"name": "release", "ok": recorded, "checks": checks},
        "assurance": assurance_document(checks),
    }


def _judged(red: tuple[str, ...] = (), *, inapplicable: tuple[str, ...] = (), app: tuple[str, ...] = ()) -> dict:
    """A version 3 document, as the gate writes it from one run: every check, green unless *red*
    names it, and with nothing to judge where *inapplicable* names it."""
    checks = [
        {"id": check, "ok": check not in red, "applicable": check not in inapplicable}
        for check in [*(c.id for c in PROFILES["release"]), *app]
    ]
    return {
        "terpReleaseGate": 3,
        "profile": {"name": "release", "ok": all(check["ok"] for check in checks), "checks": checks},
        "assurance": assurance_document(checks),
    }


# --------------------------------------------------------------------------- what sign holds a gate to
def test_a_green_profile_whose_claim_holds_passes() -> None:
    gate.require_passed(_strict(), STRICT)
    gate.require_passed(_judged(), APPLICABLE)
    gate.require_passed(_judged(app=("domain-invariants",)), "1.0")
    gate.require_passed(CLAIM_ONLY, TOOLCHAIN)


def test_an_api_only_app_s_claim_names_no_lane_passed_that_judged_nothing() -> None:
    """ADR 0202 decision 4. The suite and the frontend checks had nothing to judge, so the lane
    the suite alone composes is not-run, and a lane with a backend half composes from that half,
    naming only the check that ran: the claim sign reads is the one ``terp verify`` composes."""
    document = _judged(inapplicable=API_ONLY)
    gate.require_passed(document, APPLICABLE)
    lanes = {lane["id"]: lane for lane in document["assurance"]["lanes"]}
    assert lanes["blackbox-conformance"] == {"id": "blackbox-conformance", "status": "not-run", "checks": []}
    assert lanes["terp-standard"] == {"id": "terp-standard", "status": "passed", "checks": ["architecture"]}
    assert lanes["dependency-audit"]["checks"] == ["dependency-audit-python"]


def test_a_claim_composed_as_if_a_check_had_judged_contradicts_its_checks() -> None:
    """What a version 2 gate signed: the suite had nothing to judge, and the claim it composed,
    having dropped that, called its lane passed. Over checks that say so, that claim is not theirs."""
    document = _judged(inapplicable=("conformance",))
    as_if_run = [{**check, "applicable": True} for check in document["profile"]["checks"]]
    document["assurance"] = assurance_document(as_if_run)
    lanes = {lane["id"]: lane["status"] for lane in document["assurance"]["lanes"]}
    assert lanes["blackbox-conformance"] == "passed", "the claim a version 2 gate wrote"
    with pytest.raises(ReleaseError, match="is not the one its checks compose"):
        gate.require_passed(document, APPLICABLE)


@pytest.mark.parametrize(
    "change",
    [
        lambda check: check.pop("applicable"),
        lambda check: check.update(applicable="no"),
        lambda check: check.update(applicable=None),
    ],
)
def test_a_version_3_check_that_does_not_say_whether_it_judged_is_refused(change) -> None:  # type: ignore[no-untyped-def]
    document = _judged()
    change(document["profile"]["checks"][-1])
    with pytest.raises(ReleaseError, match="the gate document holds no verdict of the release profile's checks"):
        gate.require_passed(document, APPLICABLE)


@pytest.mark.parametrize(
    ("red", "app"),
    [
        (("api-contract",), ()),
        (("backend-tests",), ()),
        (("production-readiness", "conformance"), ()),
        (("domain-invariants",), ("domain-invariants",)),
    ],
)
def test_a_red_check_is_refused_by_name_although_the_claim_holds(red: tuple[str, ...], app: tuple[str, ...]) -> None:
    """None of these composes a required lane, so the claim alone would have let each through."""
    document = _strict(red, app=app)
    assert document["assurance"]["ok"] is True
    with pytest.raises(ReleaseError, match=re.escape(f"the release profile the gate ran is red ({', '.join(red)})")) as refused:
        gate.require_passed(document, STRICT)
    assert "`terp verify --only <check>` in a checkout of the commit says why" in str(refused.value)


def test_a_document_that_records_green_over_a_red_check_contradicts_itself() -> None:
    document = _strict(("backend-tests",), ok=True)
    assert document["assurance"]["ok"] is True, "a claim that holds, over a profile recorded green"
    with pytest.raises(ReleaseError, match="contradicts itself: it records the release profile as green and backend-tests red"):
        gate.require_passed(document, STRICT)
    with pytest.raises(ReleaseError, match="contradicts itself: it records the release profile as red and every check of it green"):
        gate.require_passed(_strict(ok=False), STRICT)


@pytest.mark.parametrize(
    "change",
    [
        lambda document: document.pop("profile"),
        lambda document: document.update(profile=["architecture"]),
        lambda document: document["profile"].update(name="full"),
        lambda document: document["profile"].update(ok="yes"),
        lambda document: document["profile"].update(checks=[]),
        lambda document: document["profile"].update(checks="architecture"),
        lambda document: document["profile"]["checks"][0].update(ok="yes"),
        lambda document: document["profile"]["checks"][0].pop("id"),
        lambda document: document["profile"]["checks"].append("conformance"),
    ],
)
def test_a_verdict_sign_cannot_read_is_refused(change) -> None:  # type: ignore[no-untyped-def]
    document = _strict()
    change(document)
    with pytest.raises(ReleaseError, match="the gate document holds no verdict of the release profile's checks"):
        gate.require_passed(document, STRICT)


@pytest.mark.parametrize(
    ("document", "pin"),
    [
        ({**_strict(), "assurance": {**_strict()["assurance"], "ok": False}}, STRICT),
        ({k: v for k, v in _strict().items() if k != "assurance"}, STRICT),
        ({**CLAIM_ONLY, "assurance": {"ok": False}}, TOOLCHAIN),
        ({**CLAIM_ONLY, "assurance": {"ok": "true"}}, TOOLCHAIN),
        ({"terpReleaseGate": 1}, TOOLCHAIN),
    ],
)
def test_a_claim_that_does_not_hold_is_refused_in_either_version(document: dict, pin: str) -> None:
    with pytest.raises(ReleaseError, match="the gate's release-assurance claim does not hold") as refused:
        gate.require_passed(document, pin)
    assert "`terp verify --profile release --format assurance` in a checkout of the commit" in str(refused.value)


@pytest.mark.parametrize(
    ("pin", "writes"),
    [
        (TOOLCHAIN, 1), ("0.36.0", 1), ("0.36.0.9", 1),
        (STRICT, 2), ("0.36.2", 2), ("0.37.0", 2), ("0.38.9", 2),
        (APPLICABLE, 3), ("0.39.1", 3), ("1.0", 3),
    ],
)
def test_the_commit_s_pin_says_which_version_its_gate_writes(pin: str, writes: int) -> None:
    """Version 1 below STRICT_SINCE, version 2 from it up and version 3 from APPLICABLE_SINCE, and
    never another: an older document for a newer pin would skip what the newer gate records, and
    a newer document for an older pin is another toolchain's gate."""
    documents = {1: CLAIM_ONLY, 2: _strict(), 3: _judged()}
    gate.require_passed(documents[writes], pin)
    for other in sorted(set(documents) - {writes}):
        with pytest.raises(ReleaseError, match=re.escape(
            f"the gate document is version {other}, and the commit pins terp-cli {pin}, whose gate "
            f"writes version {writes}: sign reads a commit's gate only as its own toolchain wrote it. "
            "Run `uv run terp release gate` in the commit's checkout"
        )):
            gate.require_passed(documents[other], pin)


@pytest.mark.parametrize("first", [STRICT, APPLICABLE])
def test_the_first_release_whose_gate_writes_a_version_is_one_the_release_notes_open(first: str) -> None:
    """A typo, or a release renumbered before it ships, would put every commit of it on the wrong
    side of the line: sign would read its gate as a version it never writes."""
    changelog = (REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert re.search(rf"^## {re.escape(first)} ", changelog, re.MULTILINE), first


# --------------------------------------------------------------------------- the whole of sign
def _pinning(version: str) -> dict[str, bytes]:
    """The app's files with terp-cli pinned at *version*, in its manifest and its lock."""
    files = app_files()
    old, new = f'name = "terp-cli"\nversion = "{TOOLCHAIN}"', f'name = "terp-cli"\nversion = "{version}"'
    assert old.encode() in files["uv.lock"]
    files["uv.lock"] = files["uv.lock"].replace(old.encode(), new.encode())
    files["pyproject.toml"] = files["pyproject.toml"].replace(f"terp-cli=={TOOLCHAIN}".encode(), f"terp-cli=={version}".encode())
    return files


def _strict_release(tmp_path: pathlib.Path, monkeypatch) -> Release:  # type: ignore[no-untyped-def]
    """A release of a commit that pins terp-cli at STRICT_SINCE, its image installing that terp-cli;
    its gate document is still the fixture's version 1."""
    release = Release(tmp_path, monkeypatch, _pinning(STRICT))
    stale = f"{SITE}/terp_cli-{TOOLCHAIN}.dist-info/"
    for table in ("nodes", "texts"):
        for path in [path for path in release.answer[table] if path.startswith(stale)]:
            del release.answer[table][path]
    install(release.answer, "terp-cli", STRICT,
            {"terp/cli/__init__.py": b"main = None\n", "terp/cli/v1.compat.py": b"", "../../../bin/terp": SCRIPT})
    return release


def _asked_nothing(release: Release, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    def asked(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("sign reached the index or the registry before it judged the gate")

    monkeypatch.setattr(sign, "egress_getter", asked)
    monkeypatch.setattr(sign, "fetch", asked)


def test_sign_signs_a_release_whose_every_check_passed(tmp_path: pathlib.Path, monkeypatch) -> None:
    release = _strict_release(tmp_path, monkeypatch)
    verdict = _strict()
    release.write_gate(**verdict)
    release.sign()
    manifest = parse((tmp_path / "out" / sign.MANIFEST).read_bytes().strip())
    assert manifest["inputs"]["toolchain"]["terpCli"] == STRICT
    assert manifest["collected"]["assurance"] == verdict["assurance"], "collected carries the claim, as it did"
    assert "profile" not in manifest["collected"]


def test_sign_refuses_a_release_whose_contract_check_is_red_although_its_claim_holds(tmp_path: pathlib.Path, monkeypatch) -> None:
    """ADR 0194's open item: the manifest would carry a contract the app no longer serves."""
    release = _strict_release(tmp_path, monkeypatch)
    release.write_gate(**_strict(("api-contract",)))
    assert json.loads(release.gate_doc.read_text())["assurance"]["ok"] is True
    _asked_nothing(release, monkeypatch)
    with pytest.raises(ReleaseError, match=re.escape("the release profile the gate ran is red (api-contract)")):
        release.sign()
    assert release.tasks == [] and not (tmp_path / "out").exists()


def test_sign_refuses_a_gate_document_that_contradicts_itself(tmp_path: pathlib.Path, monkeypatch) -> None:
    release = _strict_release(tmp_path, monkeypatch)
    release.write_gate(**_strict(("backend-tests",), ok=True))
    _asked_nothing(release, monkeypatch)
    with pytest.raises(ReleaseError, match="contradicts itself: it records the release profile as green and backend-tests red"):
        release.sign()
    assert release.tasks == [] and not (tmp_path / "out").exists()


def test_sign_refuses_a_claim_only_gate_for_a_commit_whose_gate_records_every_check(tmp_path: pathlib.Path, monkeypatch) -> None:
    """The downgrade: a version 1 document would be signed over the claim alone."""
    release = _strict_release(tmp_path, monkeypatch)
    assert json.loads(release.gate_doc.read_text())["terpReleaseGate"] == 1
    _asked_nothing(release, monkeypatch)
    with pytest.raises(ReleaseError, match=re.escape(f"version 1, and the commit pins terp-cli {STRICT}, whose gate writes version 2")):
        release.sign()
    assert release.tasks == [] and not (tmp_path / "out").exists()


def test_sign_signs_an_older_commit_over_the_claim_its_gate_wrote(tmp_path: pathlib.Path, monkeypatch) -> None:
    """The fixture's commit pins terp-cli below STRICT_SINCE: its version 1 document is signed over
    the claim, as before, and a version 2 document for it is another toolchain's gate."""
    release = Release(tmp_path, monkeypatch)
    release.sign()
    assert (tmp_path / "out" / sign.ENVELOPE).exists()
    release.write_gate(**_strict())
    _asked_nothing(release, monkeypatch)
    with pytest.raises(ReleaseError, match=re.escape(f"version 2, and the commit pins terp-cli {TOOLCHAIN}, whose gate writes version 1")):
        release.sign()


def test_a_claim_that_its_checks_do_not_compose_contradicts_itself() -> None:
    """ADR 0200 decision 1: the claim is composed from the very checks the document records, so a
    claim borrowed from a green run over a shorter list of checks, or lanes that say failed under
    a claim that holds, was not written by one run of the gate."""
    borrowed = _strict()
    borrowed["profile"]["checks"] = [{"id": "architecture", "ok": True}]
    with pytest.raises(ReleaseError, match="contradicts itself: its release-assurance claim is not the one its checks compose"):
        gate.require_passed(borrowed, STRICT)
    failed_lanes = _strict()
    failed_lanes["assurance"]["lanes"] = [{**lane, "status": "failed"} for lane in failed_lanes["assurance"]["lanes"]]
    with pytest.raises(ReleaseError, match="is not the one its checks compose"):
        gate.require_passed(failed_lanes, STRICT)
    gate.require_passed(_strict(), STRICT)
    gate.require_passed(_strict(app=("domain-invariants",)), STRICT), "an app's own check composes no lane"


@pytest.mark.parametrize("pin", ["0.36.1rc1", "0.36.1.dev0", "0.36.1+local"])
def test_a_pre_release_pin_is_refused_naming_the_lock(pin: str) -> None:
    """The signer cannot tell which gate document a toolchain that is not a release writes, and
    says where the pin comes from rather than only that the number does not compare."""
    with pytest.raises(ReleaseError, match=re.escape(f"the commit's uv.lock pins terp-cli {pin}, which is not a release number")):
        gate.require_passed(_strict(), pin)
