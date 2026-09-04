"""Everything the frontend entry point imports is live in the dev stack.

``frontend/src/main.tsx`` imports two declarations from **outside** ``src/`` --
the layout contract and the locale set -- and the dev stack mounted only
``src/``. Vite therefore resolved both to the copies baked into the image at
build time, so editing nav groups, shell density, the default theme or the
locale set changed nothing in the running app. No error, no warning, no rebuild:
the stack served last build's declaration and looked healthy doing it.

The failure has a second half that is worse than the first. The boundary lint
reads the declaration from the **checkout** (``activeI18nDeclaration`` resolves
it against the ESLint working directory), while the app reads the one in the
image. Two programs, two files, nothing comparing them -- so a change could pass
every check and be absent from the thing the checks are supposed to describe.

Fixing the mount fixes today. This is what stops tomorrow: any *new* import in
the entry point that reaches outside ``src/`` has to land inside a path the dev
stack mounts, or this fails and names the file. Cheap to satisfy and impossible
to satisfy by accident, which is the shape a control wants when the defect it
prevents is silent.
"""

from __future__ import annotations

import pathlib
import posixpath
import re

import pytest
import yaml

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

#: ``(compose file, web service, entry point)`` for each app the repository ships.
#: The template's entry point is a Jinja file; its import statements are plain
#: TypeScript regardless, which is all this reads.
_APPS = (
    (
        _REPO_ROOT / "template" / "project" / "docker-compose.yml.jinja",
        _REPO_ROOT / "template" / "project" / "frontend" / "src" / "main.tsx.jinja",
        "frontend",
    ),
    (
        _REPO_ROOT / "apps" / "example" / "docker-compose.yml",
        _REPO_ROOT / "apps" / "example" / "frontend" / "src" / "main.tsx",
        "frontend",
    ),
)

_JINJA_IF_BLOCK = re.compile(r"\{%-?\s*if\b.*?%\}.*?\{%-?\s*endif\s*-?%\}", re.DOTALL)

#: A relative import that climbs out of the directory it is written in.
_ESCAPING_IMPORT = re.compile(r"""^\s*import\s[^;]*?from\s+["'](\.\./[^"']+)["']""", re.M)

#: The host side of a bind mount: ``<host>:<container>`` where the host side is a
#: path rather than a named volume. An anonymous volume (one field, no colon) is a
#: mask and never a source, so it is not a mount for this purpose.
_BIND = re.compile(r"^(?P<host>[^:]+):(?P<container>/[^:]+)(?::[a-z,]+)?$")

#: ``${NAME:-default}``. Resolved to its default BEFORE the bind is split, because
#: the ``:-`` carries a colon and would otherwise be read as the field separator --
#: which silently produced "this service mounts nothing" for the one file that uses
#: the interpolation. Taking the default is also what compose itself does when the
#: variable is unset, so the test judges the same path a bare ``docker compose up``
#: would bind.
_INTERPOLATION = re.compile(r"\$\{(?P<name>\w+):-(?P<default>[^}]*)\}")


def _compose(path: pathlib.Path) -> dict:
    text = _JINJA_IF_BLOCK.sub("", path.read_text(encoding="utf-8"))
    assert "{%" not in text, f"{path.name}: unstripped Jinja block"
    return yaml.safe_load(re.sub(r"\{\{.*?\}\}", "x", text))


def _mounted_host_paths(compose: dict, service: str) -> list[str]:
    """Every host path the *service* bind-mounts, normalised and without its prefix.

    ``${TERP_DEV_HOST_ROOT:-.}/frontend`` and ``./frontend`` are the same claim
    about the checkout written two ways, so the interpolation and any leading
    ``./`` are stripped and the answer is a repository-relative path.
    """
    mounts: list[str] = []
    for entry in (compose["services"][service].get("volumes") or []):
        if not isinstance(entry, str):
            source = entry.get("source")
            target = entry.get("target")
            if source and target:
                mounts.append(str(source))
            continue
        match = _BIND.match(_INTERPOLATION.sub(lambda m: m.group("default"), entry))
        if match is None:
            continue  # an anonymous volume: a mask, not a source
        mounts.append(match.group("host").removeprefix("./").rstrip("/"))
    return mounts


@pytest.mark.parametrize("compose_path,entry,frontend_dir", _APPS, ids=lambda value: getattr(value, "name", value))
def test_every_escaping_import_in_the_entry_point_is_mounted(
    compose_path: pathlib.Path, entry: pathlib.Path, frontend_dir: str
) -> None:
    compose = _compose(compose_path)
    mounts = _mounted_host_paths(compose, "web")
    assert mounts, f"{compose_path.name}: the web service bind-mounts nothing"

    source = entry.read_text(encoding="utf-8")
    escaping = _ESCAPING_IMPORT.findall(source)
    # The premise, asserted rather than assumed: if the entry point stops importing
    # anything from outside src/, this test is measuring nothing and should be
    # deleted rather than left passing.
    assert escaping, f"{entry.name} imports nothing from outside src/ — retire this test"

    for specifier in escaping:
        # `../layout-contract.json` from `frontend/src/` is `frontend/layout-contract.json`.
        resolved = posixpath.normpath(f"{frontend_dir}/src/{specifier}")
        covered = any(
            resolved == mount or resolved.startswith(f"{mount}/") for mount in mounts
        )
        assert covered, (
            f"{entry.name} imports {specifier!r}, which resolves to {resolved!r} — "
            f"outside every path the web service mounts ({', '.join(sorted(mounts))}). "
            "Vite will serve the copy baked into the image and editing the file will "
            "do nothing in the running stack, silently. Widen the mount rather than "
            "moving the file: the lint reads it from the checkout, so the two have to "
            "be the same file."
        )
