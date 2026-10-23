"""What ``sign`` holds the backend image to: the tree's own files, and the lock's own set.

ADR 0187 decision 6, step 5. From the data the sandbox returned (:mod:`._sandbox`), never from
anything the image would say about itself when run:

* each file under ``/srv/app`` and ``/srv/control_plane`` equals the tree's, and each tree file
  the build context admits under those roots is present: one direction, then presence, so a
  tracked file ``.dockerignore`` keeps out is not a refusal;
* each ``__pycache__`` file there is the checked-hash compile of a tree file, compiled by the
  image's own base interpreter (the sandbox's answer), on an image whose first layers are that
  base's, so the interpreter it ran is the one the image runs;
* each file the app wheel's ``RECORD`` lists, but its ``.dist-info`` and the console scripts the
  installer writes, equals the tree's, and no other file lies in the wheel's package
  directories, a planted bytecode file among them. A wheel that maps files to other paths
  (hatch's ``force-include``, ``sources``, a nested ``packages`` entry) is a shape this cannot
  compare, refused as such, never read as tampering;
* the installed distributions are exactly the lock's runtime set, with its markers evaluated
  for the image's interpreter and machine, plus the app itself.

The dependencies' own files and the web bundle are not compared: they rest on the lock's
hashes and on ``build``'s isolation, and the manifest says so by what it does not claim.
"""

from __future__ import annotations

import hashlib
import posixpath
import re
import tomllib
from typing import Any

from terp.arch.deployment import dockerignore
from terp.cli.release._common import ReleaseError
from terp.cli.release._git import Tree
from terp.cli.release._image import Node, metadata, record
from terp.cli.release._locks import marker_environment, normalise, runtime_set
from terp.cli.release._sandbox import SOURCE_ROOTS as ROOTS
from terp.cli.release._sandbox import pyc_source

_SITE = re.compile(r"(?P<site>srv/\.venv/lib/python[0-9.]+/site-packages)/[^/]+\.dist-info/METADATA")
_MACHINES = {"amd64": "x86_64", "arm64": "aarch64", "386": "i686", "arm": "armv7l"}


def wheel_shape(tree: Tree) -> None:
    """Refuse an app wheel whose files land where the tree does not hold them."""
    try:
        project = tomllib.loads(tree.read_text("pyproject.toml"))
    except (KeyError, tomllib.TOMLDecodeError) as exc:
        raise ReleaseError("pyproject.toml cannot be read, so the app wheel cannot be compared") from exc
    wheel = project.get("tool", {}).get("hatch", {}).get("build", {}).get("targets", {}).get("wheel", {})
    remapping = [key for key in ("force-include", "sources") if wheel.get(key)]
    remapping += [f"packages {entry!r}" for entry in wheel.get("packages", []) if "/" in str(entry)]
    if remapping:
        raise ReleaseError(
            "the app wheel maps files to other paths ("
            + ", ".join(remapping)
            + "), a shape sign cannot compare with the tree: list the packages by their own "
            "top-level names (packages = [\"app\", \"control_plane\"])"
        )


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _tree_node(tree: Tree, path: str) -> Node | None:
    if not tree.has(path):
        return None
    if tree.entries[path].link:
        return Node("link", target=tree.read_text(path))
    data = tree.bytes(path)
    return Node("file", _sha(data), len(data))


def _same(image: Node, ours: Node | None) -> bool:
    if ours is None or image.kind != ours.kind:
        return False
    return image.target == ours.target if image.kind == "link" else image.sha256 == ours.sha256


def _roots(tree: Tree, nodes: dict[str, Node], findings: list[str]) -> None:
    ignored = tree.read_text(".dockerignore") if tree.has(".dockerignore") else ""
    patterns, _unreadable = dockerignore.parse(ignored)
    for root in ROOTS:
        for path, node in sorted(nodes.items()):
            if not path.startswith(f"srv/{root}/") or node.kind == "dir" or "/__pycache__/" in path:
                continue
            ours = path[len("srv/") :]
            if not _same(node, _tree_node(tree, ours)):
                findings.append(f"/{path} is not the tree's {ours}")
        for path in tree.paths(f"{root}/"):
            if not dockerignore.excluded(path, patterns) and f"srv/{path}" not in nodes:
                findings.append(f"{path} is in the tree and the build context, and not in the image")


def _bytecode(tree: Tree, nodes: dict[str, Node], compiled: dict[str, Any], findings: list[str]) -> None:
    for path, node in sorted(nodes.items()):
        if not path.startswith(tuple(f"srv/{root}/" for root in ROOTS)) or "/__pycache__/" not in path:
            continue
        found = pyc_source(path)
        if found is None or node.kind != "file":
            findings.append(f"/{path} is in a __pycache__ directory and is no bytecode a build compiles")
            continue
        source, tag = found
        if not tree.has(source):
            findings.append(f"/{path} is bytecode of {source}, which the tree does not hold")
        elif tag != compiled.get("cacheTag"):
            findings.append(f"/{path} is bytecode for {tag}, and the image's interpreter is {compiled.get('cacheTag') or 'unknown'}")
        elif compiled.get("files", {}).get(source) != node.sha256:
            findings.append(f"/{path} is not the checked-hash compile of the tree's {source}")


def _site(nodes: dict[str, Node]) -> str:
    sites = {found.group("site") for path in nodes if (found := _SITE.fullmatch(path))}
    if len(sites) != 1:
        raise ReleaseError(f"the image holds {len(sites)} environments under /srv/.venv, and sign compares one")
    return sites.pop()


def _installed(nodes: dict[str, Node], texts: dict[str, str], site: str) -> dict[str, str]:
    found: dict[str, str] = {}
    for path, body in texts.items():
        if path.startswith(f"{site}/") and path.endswith(".dist-info/METADATA") and path.count("/") == site.count("/") + 2:
            name, version = metadata(body)
            found[normalise(name)] = version
    return found


def _wheel(tree: Tree, nodes: dict[str, Node], texts: dict[str, str], site: str, project: str, findings: list[str]) -> None:
    records = [
        path for path in texts
        if path.startswith(f"{site}/") and path.endswith(".dist-info/RECORD")
        and normalise(posixpath.basename(posixpath.dirname(path)).split("-")[0]) == normalise(project)
    ]
    if len(records) != 1:
        findings.append(f"the image holds {len(records)} installed copies of the app {project}, not one")
        return
    listed: set[str] = set()
    tops: set[str] = set()
    for path, _digest in record(texts[records[0]]):
        if ".dist-info/" in path or path.startswith("../../../bin/") or path.startswith("../../bin/"):
            continue
        if path.startswith("../") or posixpath.isabs(path):
            findings.append(f"the app wheel installs {path} outside site-packages, which sign cannot compare")
            continue
        listed.add(path)
        tops.add(path.split("/", 1)[0])
        if not _same(nodes.get(f"{site}/{path}", Node("missing")), _tree_node(tree, path)):
            findings.append(f"the installed app file {path} is not the tree's {path}")
    for path, node in sorted(nodes.items()):
        inside = path[len(site) + 1 :] if path.startswith(f"{site}/") else ""
        if inside.split("/", 1)[0] in tops and node.kind != "dir" and inside not in listed and "/" in inside:
            findings.append(f"/{path} lies in the app's installed packages and is no file of its wheel")


def compare_backend(
    tree: Tree, answer: dict[str, Any], project: str, version: str, lock: dict[str, Any]
) -> tuple[list[str], list[tuple[str, str]]]:
    """Every way the backend image differs from the tree and the lock, and what it installs."""
    nodes = {path: Node.from_data(data) for path, data in answer["nodes"].items()}
    texts: dict[str, str] = dict(answer["texts"])
    config = answer["config"]
    findings: list[str] = []
    compiled = answer["compiled"]
    base_layers = list(compiled.get("diffIds", []))
    if any(pyc_source(path) for path in nodes if path.startswith(tuple(f"srv/{root}/" for root in ROOTS))):
        layers = list(config.get("rootfs", {}).get("diff_ids", []))
        if not base_layers or layers[: len(base_layers)] != base_layers:
            findings.append("the image is not built on the base its Dockerfile names, so its bytecode cannot be checked")
    _roots(tree, nodes, findings)
    _bytecode(tree, nodes, compiled, findings)
    site = _site(nodes)
    _wheel(tree, nodes, texts, site, project, findings)
    installed = _installed(nodes, texts, site)
    environment = {key: value for key, _, value in (item.partition("=") for item in config.get("config", {}).get("Env", []))}
    python = environment.get("PYTHON_VERSION") or site.rsplit("python", 1)[1].split("/", 1)[0]
    machine = _MACHINES.get(str(config.get("architecture", "")), str(config.get("architecture", "")))
    expected = dict(runtime_set(lock, project, marker_environment(python, machine)))
    expected[normalise(project)] = version
    for name in sorted(set(expected) | set(installed)):
        if name not in installed:
            findings.append(f"the lock's {name} {expected[name]} is not installed in the image")
        elif name not in expected:
            findings.append(f"the image installs {name} {installed[name]}, which the lock's runtime set does not hold")
        elif installed[name] != expected[name]:
            findings.append(f"the image installs {name} {installed[name]}, and the lock pins {expected[name]}")
    return findings, sorted(installed.items())


__all__ = ["ROOTS", "compare_backend", "wheel_shape"]
