"""What ``sign`` holds the backend image to: the tree's files and the lock's set (ADR 0187 d6).

Each case starts from the answer the sandbox gives for a faithful build of the fixture app,
changes one thing an attacker or a mistake could change in the image, and expects that one
finding: the app layer and the tree must agree, and so must the installed set and the lock.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import pathlib

import pytest

from terp.cli.release import _compare
from terp.cli.release._common import ReleaseError
from terp.cli.release._git import Tree
from terp.cli.release._image import Node
from terp.cli.release._locks import read_uv_lock
from tests.architecture.release_fixtures import PROJECT, TOOLCHAIN, app_files, committed_app, git

SITE = "srv/.venv/lib/python3.14/site-packages"
TAG = "cpython-314"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _record(rows: list[tuple[str, bytes]]) -> str:
    lines = [f"{path},sha256={base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b'=').decode()},{len(data)}"
             for path, data in rows]
    return "\n".join([*lines, f"{PROJECT}-0.1.0.dist-info/RECORD,,", "../../../bin/relapp,sha256=x,1"]) + "\n"


def faithful(tree: Tree) -> dict:
    """The sandbox's answer for an image built faithfully from *tree*."""
    nodes: dict[str, list] = {}
    texts: dict[str, str] = {}
    compiled: dict[str, str] = {}
    wheel_rows: list[tuple[str, bytes]] = []
    for path in tree.paths():
        if path.split("/", 1)[0] in ("app", "control_plane"):
            data = tree.bytes(path)
            nodes[f"srv/{path}"] = Node("file", _sha(data), len(data)).as_data()
            nodes[f"{SITE}/{path}"] = Node("file", _sha(data), len(data)).as_data()
            wheel_rows.append((path, data))
            if path.endswith(".py"):
                directory, name = path.rsplit("/", 1)
                pyc = f"{directory}/__pycache__/{name[:-3]}.{TAG}.pyc"
                nodes[f"srv/{pyc}"] = Node("file", _sha(b"pyc:" + data), 9).as_data()
                compiled[path] = _sha(b"pyc:" + data)
    nodes["srv/app"] = Node("dir").as_data()
    for name, version in ((PROJECT, "0.1.0"), ("terp-cli", TOOLCHAIN), ("terp_arch", TOOLCHAIN)):
        dist = f"{SITE}/{name.replace('-', '_')}-{version}.dist-info"
        texts[f"{dist}/METADATA"] = f"Metadata-Version: 2.4\nName: {name}\nVersion: {version}\n\nlong description"
        nodes[f"{dist}/METADATA"] = Node("file", "m", 1).as_data()
    texts[f"{SITE}/{PROJECT}-0.1.0.dist-info/RECORD"] = _record(wheel_rows)
    nodes[f"{SITE}/terp_cli/__pycache__/x.{TAG}.pyc"] = Node("file", "dep", 1).as_data()
    return {
        "nodes": nodes,
        "texts": texts,
        "config": {"architecture": "amd64", "config": {"Env": ["PATH=/x", "PYTHON_VERSION=3.14.8"]},
                   "rootfs": {"diff_ids": ["sha256:base1", "sha256:base2", "sha256:app"]}},
        "compiled": {"files": compiled, "cacheTag": TAG, "magic": "x", "diffIds": ["sha256:base1", "sha256:base2"]},
    }


@pytest.fixture
def tree(tmp_path: pathlib.Path) -> Tree:
    """The app, with a data file, and a tracked file the build context keeps out (forced past git)."""
    root = tmp_path / "repo"
    committed_app(root, app_files() | {"app/data.txt": b"data\n"})
    (root / "app" / "local.db").write_bytes(b"never in an image")
    git(root, "add", "-f", "app/local.db")
    git(root, "commit", "-q", "-m", "a tracked database the context excludes")
    return Tree.read(root, git(root, "rev-parse", "HEAD"))


def _findings(tree: Tree, answer: dict) -> list[str]:
    lock = read_uv_lock(tree.read_text("uv.lock"))
    return _compare.compare_backend(tree, answer, PROJECT, "0.1.0", lock)[0]


def test_a_faithful_image_has_nothing_to_find_and_installs_the_lock(tree: Tree) -> None:
    answer = faithful(tree)
    answer["nodes"].pop("srv/app/local.db")  # .dockerignore keeps every *.db out of the context
    lock = read_uv_lock(tree.read_text("uv.lock"))
    findings, installed = _compare.compare_backend(tree, answer, PROJECT, "0.1.0", lock)
    assert findings == []
    assert installed == [(PROJECT, "0.1.0"), ("terp-arch", TOOLCHAIN), ("terp-cli", TOOLCHAIN)]


def _change(tree: Tree, change) -> list[str]:  # type: ignore[no-untyped-def]
    answer = faithful(tree)
    answer["nodes"].pop("srv/app/local.db")
    change(answer)
    return _findings(tree, answer)


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        (lambda a: a["nodes"].update({"srv/app/main.py": Node("file", "0" * 64, 1).as_data()}),
         "/srv/app/main.py is not the tree's app/main.py"),
        (lambda a: a["nodes"].update({"srv/app/planted.py": Node("file", "1" * 64, 1).as_data()}),
         "/srv/app/planted.py is not the tree's app/planted.py"),
        (lambda a: a["nodes"].update({"srv/app/main.py": Node("link", target="/etc/passwd").as_data()}),
         "/srv/app/main.py is not the tree's app/main.py"),
        (lambda a: a["nodes"].pop("srv/app/data.txt"),
         "app/data.txt is in the tree and the build context, and not in the image"),
        (lambda a: a["nodes"].update({f"srv/app/__pycache__/main.{TAG}.pyc": Node("file", "2" * 64, 1).as_data()}),
         "is not the checked-hash compile of the tree's app/main.py"),
        (lambda a: a["nodes"].update({f"srv/app/__pycache__/ghost.{TAG}.pyc": Node("file", "2" * 64, 1).as_data()}),
         "is bytecode of app/ghost.py, which the tree does not hold"),
        (lambda a: a["nodes"].update({"srv/app/__pycache__/main.cpython-313.pyc": Node("file", "2" * 64, 1).as_data()}),
         "is bytecode for cpython-313, and the image's interpreter is cpython-314"),
        (lambda a: a["nodes"].update({"srv/app/__pycache__/notes.txt": Node("file", "2" * 64, 1).as_data()}),
         "is in a __pycache__ directory and is no bytecode a build compiles"),
        (lambda a: a["config"]["rootfs"].update(diff_ids=["sha256:other", "sha256:app"]),
         "is not built on the base its Dockerfile names"),
        (lambda a: a["nodes"].update({f"{SITE}/app/main.py": Node("file", "3" * 64, 1).as_data()}),
         "the installed app file app/main.py is not the tree's app/main.py"),
        (lambda a: a["nodes"].update({f"{SITE}/app/__pycache__/main.{TAG}.pyc": Node("file", "4" * 64, 1).as_data()}),
         "lies in the app's installed packages and is no file of its wheel"),
        (lambda a: a["texts"].update({f"{SITE}/{PROJECT}-0.1.0.dist-info/RECORD": a["texts"][f"{SITE}/{PROJECT}-0.1.0.dist-info/RECORD"] + "../../../share/x,,\n"}),
         "installs ../../../share/x outside site-packages"),
        (lambda a: a["texts"].update({f"{SITE}/{PROJECT}-0.2.0.dist-info/RECORD": "x,,\n"}),
         "holds 2 installed copies of the app relapp"),
        (lambda a: a["texts"].pop(f"{SITE}/terp_arch-{TOOLCHAIN}.dist-info/METADATA"),
         "the lock's terp-arch 0.34.0 is not installed in the image"),
        (lambda a: a["texts"].update({f"{SITE}/evil-1.0.dist-info/METADATA": "Name: evil\nVersion: 1.0\n"}),
         "the image installs evil 1.0, which the lock's runtime set does not hold"),
        (lambda a: a["texts"].update({f"{SITE}/terp_cli-{TOOLCHAIN}.dist-info/METADATA": "Name: terp-cli\nVersion: 9.9\n"}),
         "the image installs terp-cli 9.9, and the lock pins 0.34.0"),
    ],
)
def test_each_way_the_image_differs_from_the_commit_is_found(tree: Tree, change, expected: str) -> None:
    found = _change(tree, change)
    assert any(expected in finding for finding in found), (expected, found)


def test_bytecode_needs_a_base_whose_layers_the_image_begins_with(tree: Tree) -> None:
    found = _change(tree, lambda a: a["compiled"].update(diffIds=[]))
    assert any("is not built on the base its Dockerfile names" in finding for finding in found)


def test_the_interpreter_version_comes_from_the_image(tree: Tree) -> None:
    def no_env(answer: dict) -> None:
        answer["config"]["config"]["Env"] = ["PATH=/x"]
        answer["config"]["architecture"] = "s390x"

    assert _change(tree, no_env) == []


def test_an_image_without_one_environment_cannot_be_compared(tree: Tree) -> None:
    answer = faithful(tree)
    answer["texts"] = {path.replace("python3.14", "python3.13"): body for path, body in answer["texts"].items()} | answer["texts"]
    answer["nodes"] |= {path.replace("python3.14", "python3.13"): node for path, node in answer["nodes"].items()}
    with pytest.raises(ReleaseError, match="holds 2 environments under /srv/.venv"):
        _findings(tree, answer)
    answer = copy.deepcopy(faithful(tree))
    answer["nodes"] = {path: node for path, node in answer["nodes"].items() if "site-packages" not in path}
    with pytest.raises(ReleaseError, match="holds 0 environments"):
        _findings(tree, answer)


@pytest.mark.parametrize(
    ("wheel", "expected"),
    [
        ('force-include = { "x" = "y" }', "force-include"),
        ('sources = ["src"]', "sources"),
        ('packages = ["src/app"]', "packages 'src/app'"),
    ],
)
def test_a_wheel_that_maps_files_elsewhere_is_refused_as_uncomparable(tmp_path: pathlib.Path, wheel: str, expected: str) -> None:
    files = app_files()
    files["pyproject.toml"] = files["pyproject.toml"].replace(b'packages = ["app", "control_plane"]', wheel.encode())
    tree = Tree.read(tmp_path / "repo", committed_app(tmp_path / "repo", files))
    with pytest.raises(ReleaseError, match=f"a shape sign cannot compare.*") as raised:
        _compare.wheel_shape(tree)
    assert expected in raised.value.message


def test_a_wheel_with_plain_package_names_is_comparable_and_a_broken_pyproject_is_refused(tmp_path: pathlib.Path) -> None:
    tree = Tree.read(tmp_path / "repo", committed_app(tmp_path / "repo"))
    _compare.wheel_shape(tree)
    files = app_files() | {"pyproject.toml": b"[project"}
    broken = Tree.read(tmp_path / "broken", committed_app(tmp_path / "broken", files))
    with pytest.raises(ReleaseError, match="pyproject.toml cannot be read"):
        _compare.wheel_shape(broken)


def test_a_link_in_the_tree_is_held_to_the_image_s_link(tmp_path: pathlib.Path) -> None:
    import subprocess

    root = tmp_path / "repo"
    committed_app(root)
    link = subprocess.run(["git", "-C", str(root), "hash-object", "-w", "--stdin"], input=b"main.py",  # noqa: S603, S607
                          capture_output=True, check=True).stdout.decode().strip()
    git(root, "update-index", "--add", "--cacheinfo", f"120000,{link},app/alias.py")
    git(root, "commit", "-q", "-m", "a link")
    tree = Tree.read(root, git(root, "rev-parse", "HEAD"))
    answer = faithful(tree)
    answer["nodes"]["srv/app/alias.py"] = Node("link", target="main.py").as_data()
    answer["nodes"].pop(f"srv/app/__pycache__/alias.{TAG}.pyc", None)
    answer["nodes"][f"{SITE}/app/alias.py"] = Node("link", target="main.py").as_data()
    assert _findings(tree, answer) == []
    answer["nodes"]["srv/app/alias.py"] = Node("link", target="/etc/shadow").as_data()
    assert "/srv/app/alias.py is not the tree's app/alias.py" in _findings(tree, answer)
