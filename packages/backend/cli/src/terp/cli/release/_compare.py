"""What ``sign`` holds the backend image to: the tree, the lock, the RECORDs and the Dockerfile.

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
  for the image's interpreter and machine, plus the app itself, each installed once;
* every other file under ``/srv/.venv`` is one an installed distribution's ``RECORD`` lists,
  with the SHA-256 it records there; bytecode of such a file, for the image's interpreter; or
  one the environment is made with: ``pyvenv.cfg`` (which must not add the base's own
  site-packages), its marker files, ``lib64``, the interpreter links in ``bin`` (to an
  interpreter outside ``/srv``) and the activation scripts. A ``.pth`` file and a
  ``sitecustomize`` or ``usercustomize`` module are held the same way, so one no ``RECORD``
  lists is refused, and so is any file in ``/srv`` outside the two roots and the environment,
  but the record below;
* ``/srv/authz-surface.json``, the record the app compares the routes it composed with before
  it serves (ADR 0212), is the tree's, and is there when the tree holds one and the image's own
  Dockerfile copies it;
* the configuration that decides what the image runs (entrypoint, command, environment, user,
  working directory, healthcheck, volumes, stop signal, shell) is what its Dockerfile makes of
  the configuration of the base it pins (:mod:`._dockerfile`).

Not compared, and the manifest says so by what it does not claim: a dependency's files beyond
its own ``RECORD``, which the build writes too, so a build that rewrites a ``RECORD`` with the
file it lists is not caught here (holding each to the lock takes the wheel the lock pins); the
content of the bytecode compiled from a dependency; the text of the activation scripts, which
run only when sourced; files outside ``/srv``, which a layer above the base's could still
change; and the web bundle. Those rest on the lock's hashes and on ``build``'s isolation.
"""

from __future__ import annotations

import hashlib
import posixpath
import re
import tomllib
from typing import Any

from terp.arch.deployment import dockerignore
from terp.cli.release._common import ReleaseError
from terp.cli.release._dockerfile import differences, runtime_config
from terp.cli.release._git import Tree
from terp.cli.release._image import Node, metadata, record
from terp.cli.release._locks import marker_environment, normalise, runtime_set
from terp.cli.release._sandbox import SOURCE_ROOTS as ROOTS
from terp.cli.release._sandbox import pyc_source
from terp.core.authz_surface import SURFACE_ARTIFACT

_SITE = re.compile(r"(?P<site>srv/\.venv/lib/python[0-9.]+/site-packages)/[^/]+\.dist-info/METADATA")
_MACHINES = {"amd64": "x86_64", "arm64": "aarch64", "386": "i686", "arm": "armv7l"}

#: The environment ``/srv/.venv`` and what it is made with beside what it installs: the files
#: at its root, the activation scripts in ``bin`` (run only when sourced) and the interpreter
#: links there.
_VENV = "srv/.venv/"
_MADE_WITH = frozenset({"pyvenv.cfg", ".gitignore", ".lock", "CACHEDIR.TAG"})
_ACTIVATION = re.compile(r"activate(?:\.[a-z0-9]+)?|activate_this\.py|deactivate\.bat|pydoc\.bat")
_INTERPRETER = re.compile(r"python(?:3(?:\.[0-9]+)?)?")

#: The record of who can reach what, the one file of ``/srv`` that is neither source nor
#: environment, and the instruction of a Dockerfile that copies it there.
_RECORD = f"srv/{SURFACE_ARTIFACT}"
_COPIES_RECORD = re.compile(r"^[ \t]*COPY[ \t][^\n]*authz-surface\.jso", re.IGNORECASE | re.MULTILINE)


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
    compared = tuple(f"srv/{root}/" for root in ROOTS) + (_VENV,)
    for path, node in sorted(nodes.items()):
        if node.kind != "dir" and path != _RECORD and not path.startswith(compared):
            findings.append(f"/{path} is in /srv outside {', '.join(ROOTS)} and .venv, where sign holds it to nothing")


def _surface_record(tree: Tree, nodes: dict[str, Node], dockerfile: str, findings: list[str]) -> None:
    """Hold the image's record of who can reach what to the tree's (ADR 0212).

    The app compares the routes it composed with ``/srv/authz-surface.json`` before it serves,
    so a record that is not the tree's would have it hold itself to something no reviewer saw.

    An image without the record is not compared when it starts. That is a finding where the
    tree holds the record and the image's own Dockerfile copies it, because something then
    kept it out of the build context, and one line in ``.dockerignore`` would otherwise turn
    the startup check off with every other answer here unchanged. A Dockerfile that does not
    copy it, one rendered before the record was shipped or an app's own, builds an image that
    starts without the comparison, as it did before.
    """
    image, ours = nodes.get(_RECORD), _tree_node(tree, SURFACE_ARTIFACT)
    if image is not None:
        if not _same(image, ours):
            findings.append(f"/{_RECORD} is not the tree's {SURFACE_ARTIFACT}")
    elif ours is not None and _COPIES_RECORD.search(tree.read_text(dockerfile)):
        findings.append(
            f"{SURFACE_ARTIFACT} is in the tree, {dockerfile} copies it, and it is not in the "
            "image, so the app would start without comparing the routes it serves with it: "
            "keep the record in the build context (.dockerignore)"
        )


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


def _distributions(texts: dict[str, str], site: str) -> dict[str, tuple[str, str]]:
    """Each installed distribution's ``.dist-info`` directory: its normalised name and version."""
    found: dict[str, tuple[str, str]] = {}
    for path, body in texts.items():
        if path.startswith(f"{site}/") and path.endswith(".dist-info/METADATA") and path.count("/") == site.count("/") + 2:
            name, version = metadata(body)
            found[posixpath.dirname(path)] = (normalise(name), version)
    return found


def _installed(distributions: dict[str, tuple[str, str]], findings: list[str]) -> dict[str, str]:
    found: dict[str, str] = {}
    for _directory, (name, version) in sorted(distributions.items()):
        if name in found:
            findings.append(f"the image installs {name} more than once ({found[name]} and {version})")
        found[name] = version
    return found


def _wheel(tree: Tree, nodes: dict[str, Node], texts: dict[str, str], site: str, project: str, findings: list[str]) -> set[str]:
    """Hold the app wheel's files to the tree; the paths so held."""
    records = [
        path for path in texts
        if path.startswith(f"{site}/") and path.endswith(".dist-info/RECORD")
        and normalise(posixpath.basename(posixpath.dirname(path)).split("-")[0]) == normalise(project)
    ]
    if len(records) != 1:
        findings.append(f"the image holds {len(records)} installed copies of the app {project}, not one")
        return set()
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
    return {f"{site}/{path}" for path in listed}


def _compiled_from(path: str, tag: str) -> tuple[str, str] | None:
    """``(source, cache tag)`` of bytecode ``compileall`` writes beside a module: ``<dir>/__pycache__/<name>.<tag>.pyc``."""
    directory, _, name = path.rpartition("/__pycache__/")
    if not directory or "/" in name or not name.endswith(".pyc"):
        return None
    stem = name[: -len(".pyc")]
    if tag and stem.endswith(f".{tag}"):
        return f"{directory}/{stem[: -len(tag) - 1]}.py", tag
    module, dot, other = stem.partition(".")
    return (f"{directory}/{module}.py", other) if dot else None


def _listed(texts: dict[str, str], site: str, distributions: dict[str, tuple[str, str]], findings: list[str]) -> dict[str, set[str]]:
    """Every path an installed distribution's ``RECORD`` lists, with the SHA-256 it records ("" none)."""
    listed: dict[str, set[str]] = {}
    for directory in sorted(distributions):
        own = f"{directory}/RECORD"
        if own not in texts:
            findings.append(f"/{directory} has no RECORD, so none of its files can be held to one")
            continue
        for row, digest in record(texts[own]):
            path = posixpath.normpath(posixpath.join(site, row))
            if posixpath.isabs(row) or not path.startswith(_VENV):
                findings.append(f"the RECORD of /{directory} lists {row}, outside the environment")
                continue
            if not digest and path != own and _compiled_from(path, "") is None:
                findings.append(f"the RECORD of /{directory} lists {row} without its SHA-256")
            listed.setdefault(path, set()).add(digest)
    return listed


def _made_with(inside: str, node: Node) -> bool:
    """Whether *inside* (a path in the environment) is one the environment itself is made with."""
    if inside in _MADE_WITH:
        return node.kind == "file"
    if inside == "lib64":
        return node.kind == "link" and node.target == "lib"
    directory, _, name = inside.partition("/")
    if directory != "bin" or "/" in name:
        return False
    if _ACTIVATION.fullmatch(name):
        return node.kind == "file"
    if _INTERPRETER.fullmatch(name) is None or node.kind != "link":
        return False
    if name != "python":
        return node.target == "python"
    target = posixpath.normpath(node.target)
    return target.startswith("/") and not (target == "/srv" or target.startswith("/srv/"))


def _environment(
    nodes: dict[str, Node], texts: dict[str, str], site: str, distributions: dict[str, tuple[str, str]],
    tag: str, compared: set[str], findings: list[str],
) -> None:
    """Hold every file under ``/srv/.venv`` but the app's own (*compared*, held to the tree) to a
    ``RECORD``, the build's bytecode, or how the environment is made."""
    listed = _listed(texts, site, distributions, findings)
    for path, node in sorted(nodes.items()):
        if not path.startswith(_VENV) or node.kind == "dir" or path in compared:
            continue
        compiled = _compiled_from(path, tag)
        if compiled and node.kind == "file" and compiled[0] in listed:
            if compiled[1] != tag:
                findings.append(f"/{path} is bytecode for {compiled[1]}, and the image's interpreter is {tag or 'unknown'}")
            continue
        if path in listed:
            digests = listed[path] - {""}
            if node.kind != "file" or (digests and node.sha256 not in digests):
                findings.append(f"/{path} is not the file its distribution's RECORD lists")
            continue
        if not _made_with(path[len(_VENV) :], node):
            findings.append(f"/{path} is in the environment, and no installed distribution's RECORD lists it")
    configuration = texts.get(f"{_VENV}pyvenv.cfg")
    if configuration is None:
        findings.append("/srv/.venv holds no pyvenv.cfg sign can read, so it is no environment sign compares")
        return
    keys = {key.strip().lower(): value.strip().lower() for key, _, value in (line.partition("=") for line in configuration.splitlines())}
    if keys.get("include-system-site-packages") == "true":
        findings.append("/srv/.venv/pyvenv.cfg adds the base image's own site-packages, which the lock does not install")


def _configuration(tree: Tree, dockerfile: str, config: dict[str, Any], compiled: dict[str, Any], findings: list[str]) -> None:
    """Hold the image's runtime configuration to its Dockerfile, replayed over its base's."""
    base = compiled.get("baseConfig")
    if not isinstance(base, dict):
        findings.append("the configuration of the base the Dockerfile pins was not read, so the image's own cannot be held to it")
        return
    platform = "/".join(str(config[key]) for key in ("os", "architecture", "variant") if config.get(key))
    expected = runtime_config(tree.read_text(dockerfile), dockerfile, base, {"SOURCE_DATE_EPOCH": str(tree.time)}, platform)
    findings.extend(differences(expected, config.get("config") or {}))


def compare_backend(
    tree: Tree, answer: dict[str, Any], project: str, version: str, lock: dict[str, Any], *, dockerfile: str
) -> tuple[list[str], list[tuple[str, str]]]:
    """Every way the backend image differs from the tree, the lock and *dockerfile*, and what it installs."""
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
    _configuration(tree, dockerfile, config, compiled, findings)
    _roots(tree, nodes, findings)
    _surface_record(tree, nodes, dockerfile, findings)
    _bytecode(tree, nodes, compiled, findings)
    site = _site(nodes)
    compared = _wheel(tree, nodes, texts, site, project, findings)
    distributions = _distributions(texts, site)
    installed = _installed(distributions, findings)
    _environment(nodes, texts, site, distributions, str(compiled.get("cacheTag") or ""), compared, findings)
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
