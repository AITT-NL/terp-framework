"""Review routing exists, and covers the surfaces the design document says it does.

``AGENTIC_PLATFORM_DESIGN.md`` asserts CODEOWNERS twice — §10 claim 3 ("editing
core fails CI") and §12.4 ("CODEOWNERS protects core/capabilities/CI") — and the
file was absent from the repository entirely. That is the same class of drift
``test_release_versions`` already guards elsewhere: a control the docs assert and
nothing enforces, which reads as protection right up until someone checks.

So the file is now held the way every other claim here is held. The test does not
assert *who* owns a path — that is a routing decision, and it changes. It asserts
that each protected surface has **an** owner, that the catch-all has one so a new
surface is never unrouted, and that no entry outlived the directory it names.
"""

from __future__ import annotations

import pathlib

import pytest

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_CODEOWNERS = _REPO_ROOT / ".github" / "CODEOWNERS"

#: The surfaces whose change is felt by every consumer at once: the layer-0
#: kernel, the harness that judges consumer code, the published capabilities,
#: the contract the frontend generates from, and the workflows that publish 24
#: distributions. A path here must keep an owner; adding one is a deliberate act.
_PROTECTED = (
    "packages/backend/core",
    "packages/backend/arch",
    "packages/backend/capabilities",
    "packages/frontend/contract",
    ".github",
)


def _entries() -> list[tuple[str, list[str], int]]:
    """``(pattern, owners, line_number)`` for every rule line, comments stripped."""
    rules = []
    for number, raw in enumerate(
        _CODEOWNERS.read_text(encoding="utf-8").splitlines(), start=1
    ):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        pattern, *owners = line.split()
        rules.append((pattern, owners, number))
    return rules


def _covers(pattern: str, path: str) -> bool:
    """Does a CODEOWNERS directory pattern cover ``path`` (repo-relative, no slashes)?"""
    normalised = pattern.strip("/")
    return normalised == path or path.startswith(f"{normalised}/")


def test_the_codeowners_file_the_design_document_claims_actually_exists() -> None:
    assert _CODEOWNERS.is_file(), (
        "AGENTIC_PLATFORM_DESIGN.md §10 and §12.4 both state that CODEOWNERS protects "
        "core/capabilities/CI — write .github/CODEOWNERS rather than letting the claim "
        "survive in prose with nothing behind it"
    )


def test_every_rule_line_names_at_least_one_owner() -> None:
    """A pattern with no owner is worse than no pattern: GitHub treats it as
    *unowning* that path, so it silently removes the routing a broader rule above
    it would otherwise have supplied."""
    unowned = [
        (pattern, number) for pattern, owners, number in _entries() if not owners
    ]
    assert unowned == [], (
        f"these CODEOWNERS patterns name no owner, which unowns the path rather than "
        f"protecting it: {unowned}"
    )


def test_every_owner_is_a_handle() -> None:
    offenders = [
        (owner, number)
        for _, owners, number in _entries()
        for owner in owners
        if not (owner.startswith("@") or "@" in owner[1:])
    ]
    assert offenders == [], (
        f"a CODEOWNERS owner is a @user, a @org/team or an email address — "
        f"anything else is silently ignored by GitHub: {offenders}"
    )


def test_a_catch_all_owner_keeps_a_new_surface_routed() -> None:
    assert any(pattern == "*" for pattern, _, _ in _entries()), (
        "without a `*` rule a directory nobody listed is reviewable by anyone — "
        "the default must route somewhere, then the specific rules narrow it"
    )


@pytest.mark.parametrize("protected", _PROTECTED)
def test_each_protected_surface_has_an_owner(protected: str) -> None:
    owned = [
        pattern
        for pattern, owners, _ in _entries()
        if owners and _covers(pattern, protected)
    ]
    assert owned, (
        f"{protected} is a surface every consumer feels at once and no CODEOWNERS rule "
        f"covers it — add a `/{protected}/` entry rather than relying on the catch-all"
    )


@pytest.mark.parametrize("protected", _PROTECTED)
def test_each_protected_surface_still_exists(protected: str) -> None:
    """The other direction: an entry for a directory that moved is dead routing,
    and dead routing reads exactly like live routing."""
    assert (_REPO_ROOT / protected).is_dir(), (
        f"{protected} is listed as a protected surface but is not a directory — "
        f"either the path moved (update CODEOWNERS and this list together) or the "
        f"surface is gone (drop both)"
    )
