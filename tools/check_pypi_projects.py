"""Refuse a tagged release whose distributions PyPI cannot accept yet.

Trusted publishing can upload a new *version* of an existing project, and it
cannot *create* one: PyPI answers a create attempt from an OIDC identity with
``400 Non-user identities cannot create new projects``. A project comes into
being through a pending publisher, registered by hand, and the pending
publisher slot is keyed by ``(owner, repository, workflow, environment)`` —
which every Terp distribution shares, so only one not-yet-existing project can
hold that slot at a time (docs/RELEASING.md, "Bootstrapping brand-new
projects"). None of that is automatable, and none of it is the problem this
script solves.

The problem is *when* the release finds out. The upload is one twine
invocation over every distribution, so it stops at the first one PyPI refuses
— with the earlier ones already published. 0.19.0 released exactly that way:
``terp-cap-egress`` was new, five distributions were live before the refusal,
and the lockstep ``==`` pins made the version uninstallable until the
remainder was published. Every leg is idempotent, so the state was
recoverable, but recovery is not the same as never entering it, and nothing
warned first.

So this asks the index before anything is uploaded: does a project exist for
every distribution this repository publishes? A tag whose answer is "no" is
refused in seconds, naming the projects and the procedure, instead of being
discovered part-way through an irreversible upload.

**It fails closed.** An unreachable or unhappy index refuses the release
rather than assuming the projects are there — the opposite would turn every
network blip into the silence this exists to remove.

**It belongs on the tag path only.** The manual per-package dispatch is
*how* a new project gets created, so guarding that path would wall off the
escape hatch this script tells you to use. ``test_release_workflow`` holds
that shape.
"""

from __future__ import annotations

import pathlib
import re
import sys
from collections.abc import Callable, Iterable

import httpx

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]

#: PEP 503's simple index. Existence is a 200/404 question there, and the
#: answer is authoritative: ``/pypi/<name>/json`` is served through a cache
#: that can still report a just-published version as absent, which would make
#: this gate flap for reasons that have nothing to do with the release.
_INDEX = "https://pypi.org/simple/{name}/"


def normalize(name: str) -> str:
    """The PEP 503 form the index is keyed by (``terp_cap_x`` -> ``terp-cap-x``)."""
    return re.sub(r"[-_.]+", "-", name).lower()


def distribution_names(repo_root: pathlib.Path | None = None) -> list[str]:
    """Every backend distribution this repository publishes, index-normalised.

    Discovered rather than listed, and the same two globs the lockstep gate
    reads (``test_release_versions``): a capability added without touching this
    file must still be checked, or the guard would go quietly narrower than the
    release it guards.
    """
    backend = (repo_root or _REPO_ROOT) / "packages" / "backend"
    manifests = sorted(backend.glob("*/pyproject.toml")) + sorted(
        backend.glob("capabilities/*/pyproject.toml")
    )
    names = []
    for manifest in manifests:
        match = re.search(r'^name = "([^"]+)"', manifest.read_text(encoding="utf-8"), re.MULTILINE)
        if match is None:
            raise ValueError(f"{manifest} declares no name")
        names.append(normalize(match.group(1)))
    return names


def project_exists(name: str, *, timeout: float = 30.0) -> bool:
    """Whether PyPI has a project by this name. Raises if the index cannot say."""
    response = httpx.get(_INDEX.format(name=name), timeout=timeout, follow_redirects=True)
    if response.status_code == httpx.codes.NOT_FOUND:
        return False
    # Any other unhappy answer is not evidence of existence, so it is not
    # treated as any. See the module docstring: this gate fails closed.
    response.raise_for_status()
    return True


def missing_projects(
    names: Iterable[str],
    exists: Callable[[str], bool] = project_exists,
) -> list[str]:
    """The subset PyPI has no project for, in the order given."""
    return [name for name in names if not exists(name)]


def _refusal(missing: list[str]) -> str:
    return "\n".join(
        [
            f"{len(missing)} distribution(s) have no PyPI project, and trusted publishing",
            "cannot create one — this release would publish its siblings and then stop:",
            *(f"  - {name}" for name in missing),
            "",
            "For each, in this order (docs/RELEASING.md):",
            "  1. https://pypi.org/manage/account/publishing/ — add a pending publisher:",
            "     owner AITT-NL, repository terp-framework, workflow release.yml,",
            "     environment release, and the PyPI Project Name above.",
            "  2. gh workflow run release.yml -f package=<path to that distribution>",
            "     which creates the project through the same attested publish path.",
            "  3. Re-run this release. One pending slot exists at a time, so a release",
            "     introducing several new distributions repeats 1-2 for each.",
        ]
    )


def main() -> int:
    names = distribution_names()
    missing = missing_projects(names)
    if missing:
        print(_refusal(missing), file=sys.stderr)
        return 1
    print(f"all {len(names)} distributions have a PyPI project")
    return 0


if __name__ == "__main__":  # pragma: no cover - entry point
    raise SystemExit(main())
