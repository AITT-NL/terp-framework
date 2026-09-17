"""The project's own declaration of which roots the gate scans.

An application is not always one Python package, and a repository is not always one
deployable. The scaffolded shape has held two packages since it existed — ``app/`` and
the ``control_plane/`` beside it — and a repository whose work cannot run under the gate
keeps a third: a worker, a publisher, a CLI, a sidecar. ``assert_app_clean("app")``
scanned the first of those and nothing else.

A project says what else it has, once, in its ``pyproject.toml``::

    [tool.terp.arch]
    app_packages = ["control_plane"]
    companions = ["engine"]

``app_packages`` is *more of the application*: code that participates in the Terp
contract — permissions, operations, event and job catalogs, a control plane — and is
held to every rule, exactly as ``app/`` is. ``companions`` ship alongside the
application without being mounted by ``create_app``, and are held to the rules whose
invariant holds for any Python that ships (:data:`~terp.arch.RULE_ROOT_KINDS`).

:func:`declared_roots` turns the declaration into :class:`~terp.arch.ScanRoot` values.
The test gate spreads them beside the app package::

    from terp.arch import assert_app_clean, declared_roots

    assert_app_clean("app", *declared_roots(), budget_path="escape-hatch-budget.json")

and ``terp check`` reads the same table with no flag, so the CLI, ``terp verify`` and
pytest hold the repository to one scope. That matters more than tidiness: the
escape-hatch budget is shared across the scanned roots, so a run that missed a declared
root would count its markers as *absent*, read that as a win to lock in, and fail the
ratchet. One declaration is what keeps that from being a footgun (ADR 0141).

Reading a manifest is the only configuration the harness does, and it stays within what
the harness is: a static analyser that parses files and imports no application code.
"""

from __future__ import annotations

import pathlib
import tomllib

from terp.arch.rules import RootKind, ScanRoot

#: The table an app declares its extra scanned roots in.
ARCH_TABLE = "[tool.terp.arch]"

#: The declaration's keys, and the root kind each one produces. Ordered: more of the
#: application first, then what merely ships beside it.
_KEYS: tuple[tuple[str, RootKind], ...] = (
    ("app_packages", RootKind.APP),
    ("companions", RootKind.COMPANION),
)


class ArchDeclarationError(Exception):
    """The project's ``[tool.terp.arch]`` table cannot be honoured as written.

    Raised rather than ignored: a scope declaration that is silently dropped is a gate
    that quietly scans less than the repository believes, which is the whole defect this
    seam addresses.
    """


def declared_roots(project_root: str | pathlib.Path = ".") -> tuple[ScanRoot, ...]:
    """The roots *project_root* declares **beyond** the app package, in declaration order.

    Empty when the project declares none, or has no ``pyproject.toml`` at all — a
    single-package app is a legitimate shape and owes no configuration. A declared
    directory that does not exist is an error, not an empty scan: a typo would otherwise
    return zero violations from every rule and read as clean.
    """
    root = pathlib.Path(project_root)
    manifest = root / "pyproject.toml"
    if not manifest.is_file():
        return ()
    try:
        declared = tomllib.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ArchDeclarationError(
            f"pyproject.toml is unreadable ({exc}), so whether this project declares "
            f"roots beyond the app package cannot be established; fix it or remove "
            f"{ARCH_TABLE}"
        ) from exc
    table = ((declared.get("tool") or {}).get("terp") or {}).get("arch") or {}
    if not isinstance(table, dict):
        raise ArchDeclarationError(f"{ARCH_TABLE} is not a table")
    unknown = sorted(set(table) - {key for key, _kind in _KEYS})
    if unknown:
        raise ArchDeclarationError(
            f"{ARCH_TABLE} has unknown key(s) {', '.join(unknown)}; the keys are "
            f"{', '.join(repr(key) for key, _kind in _KEYS)}"
        )
    roots: list[ScanRoot] = []
    for key, kind in _KEYS:
        names = table.get(key, [])
        if not isinstance(names, list) or not all(isinstance(name, str) for name in names):
            raise ArchDeclarationError(
                f"{ARCH_TABLE} `{key}` must be a list of directory names, e.g. "
                '["control_plane"]'
            )
        for name in names:
            path = root / name
            if not path.is_dir():
                raise ArchDeclarationError(
                    f"{ARCH_TABLE} `{key}` declares {name!r} but {path} is not a "
                    "directory; a declared root that does not exist would scan nothing "
                    "and report clean"
                )
            roots.append(ScanRoot(path, package=pathlib.Path(name).name, kind=kind))
    return tuple(roots)


__all__ = ["ARCH_TABLE", "ArchDeclarationError", "declared_roots"]
