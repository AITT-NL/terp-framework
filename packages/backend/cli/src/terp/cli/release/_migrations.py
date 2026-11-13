"""``outputs.migrations``: every migration history the backend image brings to head, as data.

A deploy tool lists the destructive steps of a deploy from the signed manifest, so ``sign``
records, for every history ``terp migrate upgrade`` would find in the release's backend image,
each revision with the revisions it follows, and each operation
:func:`terp.arch.destructive_operations` lists for its ``upgrade()``, excused by its marker or
not and ``opaque`` ones included. Nothing is imported: a revision imported is a revision run. It
is read from what the sandbox read of the image (:mod:`._sandbox`) and from the commit's tree.

The histories are the trees :func:`terp.core.migrations.resolve_all_migration_trees` finds,
under the labels it gives them:

* **a capability's**, one for each line ``label = import.path`` or ``label = import.path:attr``
  of a ``[terp.migrations]`` section, in the ``entry_points.txt`` of a ``*.dist-info`` or
  ``*.egg-info`` directory anywhere in the image, as ``importlib.metadata`` finds them on any
  path entry. The distribution must sit directly in a ``site-packages`` or ``dist-packages``
  directory, and its package at ``<that directory>/<import path>/``. Any other directory at
  ``<any directory>/<import path>/`` is refused: the interpreter imports the copy that comes
  first on its path, and a copy under a ``PYTHONPATH`` entry would run in place of the one read;
* **an app module's**, one for each directory ``modules/<name>/`` of the app root the migration
  step passes (``/srv/app``) whose name does not begin with ``_``. Its revisions are
  read from the commit's tree, which the gate read, and the image must hold the same modules
  and the same revision files, byte for byte.

A history's revision files are the names Alembic loads from ``<package>/migrations/versions/``:
its ``_only_source_rev_file``, with ``sourceless`` and ``recursive_version_locations`` off as
``terp migrate`` leaves them. A history whose ``versions/`` holds no revision is listed with
nothing in it, so a unit may name it. Neither reading follows a symbolic link: one where a
reading would pass is refused, because the upgrade would follow it to files no list names.

Each refusal names what was found and what to do instead, and every one is reported at once.
Beyond what is read here: a finder installed as the interpreter starts (a ``.pth`` file's
``import`` line, a ``sitecustomize``), which can map an import path anywhere, and a migration run
by other means than ``terp migrate``.
"""

from __future__ import annotations

import base64
import hashlib
import posixpath
import re
from dataclasses import dataclass
from typing import Any

from terp.arch.deployment.generator import APP_ROOT, MIGRATION_STEP
from terp.cli.release._git import Tree
from terp.cli.release._history import listing
from terp.cli.release._image import Node

#: The app root a deploy's migration step passes (``--app-root /srv/app``), as a path of the
#: image, and the tree's directory the image holds there: the image holds the tree's source
#: roots beneath :data:`APP_ROOT`, as :mod:`._compare` holds it to.
_STEP_ROOT = MIGRATION_STEP[MIGRATION_STEP.index("--app-root") + 1]
IMAGE_APP = _STEP_ROOT.lstrip("/")
TREE_APP = posixpath.relpath(_STEP_ROOT, APP_ROOT)

#: Alembic's ``_only_source_rev_file``, unchanged from 1.13, the framework's floor, to 1.20,
#: matched as Alembic matches it: from the start of the name. So ``_b2_hotfix.py`` is a
#: revision Alembic loads and runs, and ``__init__x.py`` is skipped.
_REVISION_FILE = re.compile(r"(?!\.\#|__init__)(.*\.py)$")

#: The labels a deploy's plan holds, a label naming its history's version table
#: ``alembic_version_<label>``, 63 characters at most; and how many histories a plan holds.
_LABEL = re.compile(r"[a-z0-9_]{1,47}")
MOST_HISTORIES = 64

_SECTION = "terp.migrations"
_SITES = ("site-packages", "dist-packages")
_DISTRIBUTIONS = (".dist-info", ".egg-info")
_ENTRY_POINTS = "entry_points.txt"
_NAME = r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*"
_ENTRY = re.compile(rf"(?P<path>{_NAME})(?::{_NAME})?")


@dataclass(frozen=True)
class _History:
    """One history to list: its label, where it was declared, and its revision files' bytes."""

    label: str
    where: str
    revisions: tuple[tuple[str, bytes], ...]


class _Paths:
    """One side's paths, the image's or the tree's: what each is, and what a directory holds."""

    def __init__(self, kinds: dict[str, str]) -> None:
        self.kinds = kinds
        self._held: dict[str, set[str]] = {}
        for path in kinds:
            self._held.setdefault(posixpath.dirname(path), set()).add(path)

    def kind(self, path: str) -> str | None:
        return self.kinds.get(path)

    def children(self, directory: str) -> list[tuple[str, str]]:
        """Each path directly in *directory*, and what it is."""
        return [(path, self.kinds[path]) for path in sorted(self._held.get(directory, ()))]

    def links_on(self, path: str) -> list[str]:
        """Each directory on the way to *path*, and *path* itself, that is a symbolic link."""
        parts = path.split("/")
        prefixes = ("/".join(parts[:end]) for end in range(1, len(parts) + 1))
        return [prefix for prefix in prefixes if self.kinds.get(prefix) == "link"]


def _tree_paths(tree: Tree) -> _Paths:
    kinds: dict[str, str] = {}
    for path, entry in tree.entries.items():
        kinds[path] = "link" if entry.link else "file"
        parent = posixpath.dirname(path)
        while parent and parent not in kinds:
            kinds[parent] = "dir"
            parent = posixpath.dirname(parent)
    return _Paths(kinds)


def _image_paths(answer: dict[str, Any], findings: list[str]) -> tuple[_Paths, dict[str, bytes], dict[str, str]]:
    """The image's paths, the bytes of the files the sandbox kept, and each file's SHA-256 under
    ``/srv``. A kept file whose bytes are not those of the file the image holds there is refused,
    and read as no path at all."""
    inputs = answer["migrationInputs"]
    srv = {path: Node.from_data(data) for path, data in answer["nodes"].items()}
    nodes = {**srv, **{path: Node.from_data(data) for path, data in inputs["nodes"].items()}}
    files: dict[str, bytes] = {}
    for path, encoded in sorted(inputs["files"].items()):
        data = base64.b64decode(encoded)
        node = nodes.get(path, Node("missing"))
        if node.kind == "file" and hashlib.sha256(data).hexdigest() == node.sha256:
            files[path] = data
            continue
        nodes.pop(path, None)
        findings.append(
            f"the bytes the sandbox kept for /{path} are not those of the file the image holds there, "
            "so sign cannot tell which the upgrade would read: rebuild the image, writing each path "
            "once in each layer"
        )
    return _Paths({path: node.kind for path, node in nodes.items()}), files, {path: node.sha256 for path, node in srv.items()}


def _unreadable(path: str, kind: str) -> str:
    what = "a symbolic link" if kind == "link" else "neither a file nor a directory"
    return (
        f"{path} is {what} where sign reads a migration history: sign reads only files and "
        "directories there, and terp migrate upgrade would read through it to code no list names; "
        "put the file or the directory itself there"
    )


def _revision_files(paths: _Paths, migrations: str) -> tuple[list[str], list[tuple[str, str]]]:
    """The revision files of the history whose ``migrations/`` directory is *migrations*, and
    each path there a reading cannot pass, with what it is."""
    versions = f"{migrations}/versions"
    links = [(path, "link") for path in (migrations, versions) if paths.kind(path) == "link"]
    if links or paths.kind(versions) != "dir":
        return [], links
    found: list[str] = []
    refused: list[tuple[str, str]] = []
    for path, kind in paths.children(versions):
        if kind == "file":
            if _REVISION_FILE.match(posixpath.basename(path)):
                found.append(path)
        elif kind != "dir":  # Alembic resolves a link, and loads what it finds by the target's name
            refused.append((path, kind))
    return found, refused


def _section(text: str) -> list[str]:
    """The lines of an ``entry_points.txt``'s ``[terp.migrations]`` section, as ``importlib.metadata`` reads them."""
    section: str | None = None
    lines: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line.strip("[]")
        elif section == _SECTION:
            lines.append(line)
    return lines


def _named_as_distribution(name: str) -> bool:
    return name.lower().endswith(_DISTRIBUTIONS)


def _capability(
    paths: _Paths, files: dict[str, bytes], declared_in: str, line: str, findings: list[str]
) -> _History | None:
    """The history one line of a ``[terp.migrations]`` section declares, or ``None`` refused."""
    label, _, value = (part.strip() for part in line.partition("="))
    found = _ENTRY.fullmatch(value)
    if found is None:
        findings.append(
            f"/{declared_in} declares the migration history {line!r}, which is not `label = "
            "import.path` or `label = import.path:attr`: declare the entry point in one of those forms"
        )
        return None
    site = posixpath.dirname(posixpath.dirname(declared_in))
    relative = found.group("path").replace(".", "/")
    package = f"{site}/{relative}"
    links = paths.links_on(package)
    if links:
        findings.extend(_unreadable(f"/{link}", "link") for link in links)
        return None
    if paths.kind(package) != "dir":
        findings.append(
            f"the migration history {label!r} that /{declared_in} declares names the package "
            f"{found.group('path')}, and /{package}/ is no directory of the image: an editable "
            "install, a package on a .pth path or a namespace spread over two directories runs "
            "files sign cannot list; install the distribution as a wheel"
        )
        return None
    copies = (
        other for other, kind in paths.kinds.items()
        if kind in ("dir", "link") and other != package and (other == relative or other.endswith(f"/{relative}"))
    )
    for other in sorted(copies):
        findings.append(
            f"/{other} is a second copy of {found.group('path')}, the package of the migration "
            f"history {label!r}: the interpreter imports whichever copy comes first on its path, "
            f"so a copy under a PYTHONPATH entry would run in place of /{package}/, the one sign "
            "read; remove it from the image"
        )
    revisions, refused = _revision_files(paths, f"{package}/migrations")
    findings.extend(_unreadable(f"/{path}", kind) for path, kind in refused)
    return _History(label, f"the entry point in /{declared_in}", tuple((f"/{path}", files[path]) for path in revisions))


def _capabilities(paths: _Paths, files: dict[str, bytes], findings: list[str]) -> list[_History]:
    """Every history an installed distribution declares, as ``importlib.metadata`` would find it."""
    for path in sorted(path for path, kind in paths.kinds.items() if kind == "link"):
        directory, _, name = path.rpartition("/")
        if _named_as_distribution(name) or (name == _ENTRY_POINTS and _named_as_distribution(posixpath.basename(directory))):
            findings.append(_unreadable(f"/{path}", "link"))  # importlib.metadata follows it on any path entry
    histories: list[_History] = []
    for path in sorted(files):
        lines = _section(files[path].decode("utf-8", errors="replace")) if posixpath.basename(path) == _ENTRY_POINTS else []
        if not lines:
            continue
        distribution = posixpath.dirname(path)
        site, _, name = distribution.rpartition("/")
        if posixpath.basename(site) not in _SITES or not _named_as_distribution(name):
            findings.append(
                f"/{path} declares the migration histories {', '.join(lines)} outside a distribution "
                "directory that sits directly in a site-packages or dist-packages directory, so sign "
                "cannot hold a history to the package the distribution installed: install the "
                "distribution as a wheel into the environment the app runs from"
            )
            continue
        for line in lines:
            history = _capability(paths, files, path, line, findings)
            if history is not None:
                histories.append(history)
    return histories


def _modules(paths: _Paths, root: str) -> tuple[dict[str, list[str]], list[tuple[str, str]]]:
    """Each module ``iter_domain_packages`` finds under the app root *root*, with its revision
    files, and each path there a reading cannot pass, with what it is."""
    directory = f"{root}/modules"
    refused = [(link, "link") for link in paths.links_on(directory)]
    modules: dict[str, list[str]] = {}
    if refused or paths.kind(directory) != "dir":
        return modules, refused
    for path, kind in paths.children(directory):
        name = posixpath.basename(path)
        if name.startswith("_") or kind not in ("dir", "link"):
            continue  # skipped by discovery, so it never runs
        if kind == "link":
            refused.append((path, kind))
            continue
        revisions, unreadable = _revision_files(paths, f"{path}/migrations")
        modules[name] = revisions
        refused.extend(unreadable)
    return modules, refused


def _app_modules(tree: Tree, image: _Paths, digests: dict[str, str], findings: list[str]) -> list[_History]:
    """Every module history, read from the tree, with each way the image differs from it."""
    ours, refused = _modules(_tree_paths(tree), TREE_APP)
    findings.extend(_unreadable(path, kind) for path, kind in refused)
    # A link in the image's modules is the tree's, which is refused above, or a difference below.
    theirs = _modules(image, IMAGE_APP)[0]
    for name in sorted(set(ours) | set(theirs)):
        if name not in theirs:
            findings.append(
                f"{TREE_APP}/modules/{name} is a module of the tree, and the image holds no directory "
                f"/{IMAGE_APP}/modules/{name}: rebuild the image from this commit, with the module in "
                "its build context (.dockerignore)"
            )
            continue
        if name not in ours:
            findings.append(
                f"/{IMAGE_APP}/modules/{name} is a module of the image and none of the tree: terp "
                "migrate upgrade would bring it to head from code the gate never read; build the "
                "image from this commit"
            )
            continue
        tree_files = {posixpath.basename(path): path for path in ours[name]}
        image_files = {posixpath.basename(path): path for path in theirs[name]}
        for file_name in sorted(set(tree_files) | set(image_files)):
            if file_name not in image_files:
                findings.append(
                    f"{tree_files[file_name]} is a revision in the tree that the image does not hold: "
                    "the gate read it, and the upgrade would not run it; rebuild the image from this "
                    "commit, with the revision in its build context (.dockerignore)"
                )
            elif file_name not in tree_files:
                findings.append(
                    f"/{image_files[file_name]} is a revision in the image and none of the tree: the "
                    "upgrade would run code the gate never read; build the image from this commit"
                )
            elif digests[image_files[file_name]] != hashlib.sha256(tree.bytes(tree_files[file_name])).hexdigest():
                findings.append(
                    f"/{image_files[file_name]} is not the tree's {tree_files[file_name]}: the upgrade "
                    "would run another revision than the one the gate read; rebuild the image from "
                    "this commit"
                )
    return [
        _History(name, f"the module {TREE_APP}/modules/{name}", tuple((path, tree.bytes(path)) for path in ours[name]))
        for name in sorted(ours)
    ]


def migrations(tree: Tree, answer: dict[str, Any]) -> tuple[list[str], dict[str, Any]]:
    """Every reason the histories of the image the sandbox read (*answer*) cannot be listed, and
    ``outputs.migrations``: per label, ``{"revisions": [{"id", "down"}], "operations": [{"revision",
    "ordinal", "kind", "operation"}]}``."""
    findings: list[str] = []
    image, files, digests = _image_paths(answer, findings)
    histories = _capabilities(image, files, findings) + _app_modules(tree, image, digests, findings)
    if len(histories) > MOST_HISTORIES:
        findings.append(
            f"the image holds {len(histories)} migration histories, more than the {MOST_HISTORIES} a "
            "deploy's plan holds: fold modules that change together into one"
        )
    listed: dict[str, Any] = {}
    declared: dict[str, str] = {}
    for history in histories:
        if history.label in declared:
            findings.append(
                f"two migration histories are labelled {history.label!r}, {declared[history.label]} "
                f"and {history.where}: they would share the version table alembic_version_"
                f"{history.label}, and terp migrate refuses them; rename one"
            )
            continue
        declared[history.label] = history.where
        if _LABEL.fullmatch(history.label) is None:
            findings.append(
                f"the migration history {history.label!r}, {history.where}, has a label outside "
                "^[a-z0-9_]{1,47}$: a deploy reads its version table alembic_version_<label>, and a "
                "table name holds 63 characters; name it with lower-case letters, digits and underscores"
            )
        listed[history.label] = listing(history.label, history.revisions, findings)
    return list(dict.fromkeys(findings)), listed


__all__ = ["IMAGE_APP", "MOST_HISTORIES", "TREE_APP", "migrations"]
