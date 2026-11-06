"""Each checker ships its catalog, and neither ships its corpus (ADR 0203).

A catalog entry ships with the checker that enforces it, so a toolchain carries the description
of every rule it reports. The corpus beside each package is test data: deliberate violations,
some carrying credential-shaped literals by construction, so it reaches neither registry.

Held at the packaging configuration, because that is what decides the contents and what a
change would edit: ``terp-arch``'s wheel takes only ``src/terp/arch`` (where the catalog lives)
and its sdist excludes ``corpus``; ``@terpjs/eslint-boundaries`` publishes exactly its sources,
its catalog and its refused surface. An artifact present in the repository and absent from the
package is silent: nothing fails until a consumer reaches for it.
"""

from __future__ import annotations

import json
import tomllib

from tests.architecture.rule_layout import (
    CATALOG_SCHEMA,
    REPO_ROOT,
    RESTRICTED_SURFACE,
    catalog_dir,
    corpus_root,
)

_ARCH = REPO_ROOT / "packages" / "backend" / "arch"
_BOUNDARIES = REPO_ROOT / "packages" / "frontend" / "eslint-boundaries"


def _hatch_targets() -> dict:
    config = tomllib.loads((_ARCH / "pyproject.toml").read_text(encoding="utf-8"))
    return config["tool"]["hatch"]["build"]["targets"]


def test_terp_arch_ships_its_catalog() -> None:
    wheel = _hatch_targets()["wheel"]
    assert wheel["only-include"] == ["src/terp/arch"], (
        "the terp-arch wheel takes only src/terp/arch, which is where the catalog lives"
    )
    shipped = _ARCH / "src" / "terp" / "arch"
    assert catalog_dir("backend").is_relative_to(shipped), "the backend catalog is outside the wheel"
    assert CATALOG_SCHEMA.is_relative_to(shipped), "the catalog schema is outside the wheel"


def test_terp_arch_ships_no_corpus() -> None:
    assert corpus_root("backend").parent == _ARCH, "the backend corpus moved; update this guard"
    assert not corpus_root("backend").is_relative_to(_ARCH / "src"), (
        "the backend corpus is inside the wheel's tree"
    )
    excluded = _hatch_targets().get("sdist", {}).get("exclude", [])
    assert f"/{corpus_root('backend').name}" in excluded, (
        "the terp-arch sdist must exclude the corpus: an sdist takes the whole package "
        "directory unless told otherwise, and the corpus carries deliberate violations"
    )


def test_eslint_boundaries_ships_its_catalog_and_refused_surface_and_no_corpus() -> None:
    manifest = json.loads((_BOUNDARIES / "package.json").read_text(encoding="utf-8"))
    files = manifest.get("files")
    assert files is not None, (
        "without a files list npm publishes the whole package directory, the corpus included"
    )
    assert sorted(files) == sorted(
        [
            "src",
            catalog_dir("frontend").relative_to(_BOUNDARIES).parts[0],
            RESTRICTED_SURFACE.relative_to(_BOUNDARIES).as_posix(),
        ]
    ), f"@terpjs/eslint-boundaries publishes {files}: its sources, its catalog and its refused surface, exactly"
    assert corpus_root("frontend").relative_to(_BOUNDARIES).parts[0] not in files
