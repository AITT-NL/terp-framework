"""The two visual baseline sets cover the same specimens.

`playwright.config.ts` splits baselines by platform on purpose: font rasterisation
differs between Windows and Linux by more than any tolerance that would still catch a
real change, so each platform records and compares its own set. What the split does not
supply is a reason the two sets should contain the *same specimens* — and they did not.
Sixteen specimens were recorded on linux and never on win32, and nothing noticed,
because CI runs only the linux lane.

An unrecorded baseline is not a test that fails; it is a test that silently records
itself on first run. So the divergence can only grow, invisibly, until a maintainer runs
the other lane and meets sixteen failures that look exactly like regressions on a change
that caused none of them.

This is a structural check and deliberately not a browser lane: it reads two directory
listings. `PENDING-BASELINES.json` records what is already missing, as a ratchet — it
only shrinks, nothing new may join it, and an entry whose baseline now exists fails
rather than remaining a permanent excuse. Whether win32 stays a supported lane is a
separate, explicit decision (either add a windows leg to the frontend workflow, or
delete that half); until it is taken, the debt is at least counted and greppable
instead of invisible.
"""

from __future__ import annotations

import json
import pathlib

import pytest

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_SCREENSHOTS = _REPO_ROOT / "apps" / "workbench" / "visual" / "__screenshots__"
_PENDING = _REPO_ROOT / "apps" / "workbench" / "visual" / "PENDING-BASELINES.json"

#: The platforms `snapshotPathTemplate` writes a directory for. Node's `process.platform`
#: spelling, which is what Playwright interpolates — "win32" is 64-bit Windows too.
_PLATFORMS = ("linux", "win32")


def _recorded(platform: str) -> set[str]:
    return {path.name for path in (_SCREENSHOTS / platform).glob("*.png")}


def _pending() -> dict[str, list[str]]:
    data = json.loads(_PENDING.read_text(encoding="utf-8"))
    return {platform: list(data.get(platform, ())) for platform in _PLATFORMS}


@pytest.mark.parametrize("platform", _PLATFORMS)
def test_each_platform_records_baselines(platform: str) -> None:
    """Discovery that quietly finds nothing is a hole with no symptoms: a renamed or
    moved directory would otherwise make every assertion below trivially true."""
    assert len(_recorded(platform)) > 100, (
        f"{platform} records {len(_recorded(platform))} baselines — the specimen suite is "
        f"far larger than that, so the directory moved or the path template changed"
    )


@pytest.mark.parametrize("platform", _PLATFORMS)
def test_no_new_specimen_is_recorded_on_one_platform_only(platform: str) -> None:
    others: set[str] = set()
    for other in _PLATFORMS:
        if other != platform:
            others |= _recorded(other)
    missing = sorted(others - _recorded(platform) - set(_pending()[platform]))
    assert missing == [], (
        f"these specimens have a baseline on another platform and none on {platform}: "
        f"{missing} — record them with `npm run visual:update` on {platform}, because an "
        f"unrecorded baseline does not fail there, it silently records itself and the "
        f"specimen is then compared against nothing"
    )


@pytest.mark.parametrize("platform", _PLATFORMS)
def test_the_pending_list_only_shrinks(platform: str) -> None:
    """An entry that outlived its debt fails too — otherwise the ratchet quietly becomes
    a list of specimens nobody has to record, which is the state it exists to end."""
    settled = sorted(set(_pending()[platform]) & _recorded(platform))
    assert settled == [], (
        f"PENDING-BASELINES.json still lists these as unrecorded on {platform} and they "
        f"are recorded: {settled} — delete the entries; the ratchet only shrinks"
    )


@pytest.mark.parametrize("platform", _PLATFORMS)
def test_the_pending_list_names_real_specimens(platform: str) -> None:
    others: set[str] = set()
    for other in _PLATFORMS:
        if other != platform:
            others |= _recorded(other)
    unknown = sorted(set(_pending()[platform]) - others)
    assert unknown == [], (
        f"PENDING-BASELINES.json lists these for {platform} and no other platform records "
        f"them either: {unknown} — the specimen was renamed or removed, so drop the entry "
        f"rather than leaving a debt against something that no longer exists"
    )


@pytest.mark.parametrize("platform", _PLATFORMS)
def test_the_pending_list_is_sorted_and_unique(platform: str) -> None:
    entries = _pending()[platform]
    assert entries == sorted(set(entries)), (
        f"PENDING-BASELINES.json['{platform}'] must be sorted and duplicate-free, so a "
        f"shrinking diff reads as one deleted line rather than a reshuffle"
    )
