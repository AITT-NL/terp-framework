"""What ``sign`` holds the backend image to: the tree, the lock, the RECORDs, the Dockerfile.

ADR 0187 decision 6. Each case starts from the answer the sandbox gives for a faithful build of
the fixture app, changes one thing an attacker or a mistake could change in the image, and
expects that one finding: the app layer and the tree must agree, the installed set and the lock,
every other file of the environment and the RECORD that lists it, and the image's configuration
and its Dockerfile.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import pathlib
import posixpath

import pytest

from terp.cli.release import _compare
from terp.cli.release._common import ReleaseError
from terp.cli.release._git import Tree
from terp.cli.release._image import Node
from terp.cli.release._locks import read_uv_lock
from tests.architecture.release_fixtures import PROJECT, TOOLCHAIN, app_files, committed_app, git

SITE = "srv/.venv/lib/python3.14/site-packages"
TAG = "cpython-314"
BIN = "srv/.venv/bin"

#: The pinned base's configuration, as the engine that pulled it by digest reads it.
BASE_CONFIG = {
    "Env": ["PATH=/usr/local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin", "LANG=C.UTF-8",
            "PYTHON_VERSION=3.14.8"],
    "Cmd": ["python3"], "Entrypoint": None, "WorkingDir": "", "User": "", "OnBuild": None, "Labels": None,
}

#: What BuildKit makes of the generated Dockerfile.prod over that base, written out by hand rather
#: than replayed, so the replay is held to it.
IMAGE_CONFIG = {
    "Env": ["PATH=/srv/.venv/bin:/usr/local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
            "LANG=C.UTF-8", "PYTHON_VERSION=3.14.8", "PYTHONUNBUFFERED=1", "PYTHONDONTWRITEBYTECODE=1",
            "VIRTUAL_ENV=/srv/.venv"],
    "Cmd": ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--timeout-graceful-shutdown", "8"],  # noqa: S104 - the image's command, as data
    "WorkingDir": "/srv", "User": "appuser", "ExposedPorts": {"8000/tcp": {}}, "ArgsEscaped": True,
}

PYVENV = "home = /usr/local/bin\nimplementation = CPython\nuv = 0.13.4\nversion_info = 3.14.8\ninclude-system-site-packages = false\nprompt = relapp\n"
SCRIPT = b"#!/srv/.venv/bin/python\nimport sys\nfrom terp.cli import main\nsys.exit(main())\n"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _file(data: bytes) -> list:
    return Node("file", _sha(data), len(data)).as_data()


def _row(path: str, data: bytes) -> str:
    return f"{path},sha256={base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b'=').decode()},{len(data)}"


def install(answer: dict, name: str, version: str, files: dict[str, bytes]) -> str:
    """Install one distribution as uv does: its files, its .dist-info, and a RECORD of them all."""
    dist = f"{name.replace('-', '_')}-{version}.dist-info"
    meta = f"Metadata-Version: 2.4\nName: {name}\nVersion: {version}\n\nlong description"
    files = files | {f"{dist}/METADATA": meta.encode(), f"{dist}/INSTALLER": b"uv"}
    for path, data in files.items():
        answer["nodes"][posixpath.normpath(f"{SITE}/{path}")] = _file(data)
    rows = "\n".join([*(_row(path, data) for path, data in files.items()), f"{dist}/RECORD,,"]) + "\n"
    answer["texts"][f"{SITE}/{dist}/METADATA"] = meta
    answer["texts"][f"{SITE}/{dist}/RECORD"] = rows
    answer["nodes"][f"{SITE}/{dist}/RECORD"] = _file(rows.encode())
    return f"{SITE}/{dist}/RECORD"


def faithful(tree: Tree) -> dict:
    """The sandbox's answer for an image built faithfully from *tree*."""
    answer: dict = {
        "nodes": {"srv/app": Node("dir").as_data(), "srv/var/files": Node("dir").as_data()},
        "texts": {},
        "config": {"architecture": "amd64", "os": "linux", "config": copy.deepcopy(IMAGE_CONFIG),
                   "rootfs": {"diff_ids": ["sha256:base1", "sha256:base2", "sha256:app"]}},
        "compiled": {"files": {}, "cacheTag": TAG, "magic": "x", "diffIds": ["sha256:base1", "sha256:base2"],
                     "baseConfig": copy.deepcopy(BASE_CONFIG)},
    }
    wheel: dict[str, bytes] = {"../../../bin/relapp": SCRIPT}
    for path in tree.paths():
        if path.split("/", 1)[0] in ("app", "control_plane"):
            data = tree.bytes(path)
            answer["nodes"][f"srv/{path}"] = _file(data)
            wheel[path] = data
            if path.endswith(".py"):
                directory, name = path.rsplit("/", 1)
                pyc = f"{directory}/__pycache__/{name[:-3]}.{TAG}.pyc"
                answer["nodes"][f"srv/{pyc}"] = Node("file", _sha(b"pyc:" + data), 9).as_data()
                answer["compiled"]["files"][path] = _sha(b"pyc:" + data)
    install(answer, PROJECT, "0.1.0", wheel)
    install(answer, "terp-cli", TOOLCHAIN, {"terp/cli/__init__.py": b"main = None\n", "terp/cli/v1.compat.py": b"",
                                             "../../../bin/terp": SCRIPT})
    record = install(answer, "terp_arch", TOOLCHAIN, {"terp/arch/__init__.py": b"", "terp_arch.pth": b"/srv/.venv/x\n"})
    answer["texts"][record] += f"terp/arch/__pycache__/__init__.{TAG}.pyc,,\n"  # an installer that compiled lists it so
    for source in ("terp/cli/__init__", "terp/cli/v1.compat", "terp/arch/__init__"):
        directory, name = source.rsplit("/", 1)
        answer["nodes"][f"{SITE}/{directory}/__pycache__/{name}.{TAG}.pyc"] = Node("file", "dep", 1).as_data()
    for name in ("pyvenv.cfg", ".gitignore", ".lock", "CACHEDIR.TAG"):
        answer["nodes"][f"srv/.venv/{name}"] = _file(PYVENV.encode() if name == "pyvenv.cfg" else b"*")
    answer["texts"]["srv/.venv/pyvenv.cfg"] = PYVENV
    answer["nodes"]["srv/.venv/lib64"] = Node("link", target="lib").as_data()
    for name in ("activate", "activate.fish", "activate.xsh", "activate_this.py", "deactivate.bat", "pydoc.bat"):
        answer["nodes"][f"{BIN}/{name}"] = _file(b"# activation")
    answer["nodes"][f"{BIN}/python"] = Node("link", target="/usr/local/bin/python3").as_data()
    answer["nodes"][f"{BIN}/python3"] = Node("link", target="python").as_data()
    answer["nodes"][f"{BIN}/python3.14"] = Node("link", target="python").as_data()
    return answer


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
    return _compare.compare_backend(tree, answer, PROJECT, "0.1.0", lock, dockerfile="Dockerfile.prod")[0]


def test_a_faithful_image_has_nothing_to_find_and_installs_the_lock(tree: Tree) -> None:
    answer = faithful(tree)
    answer["nodes"].pop("srv/app/local.db")  # .dockerignore keeps every *.db out of the context
    lock = read_uv_lock(tree.read_text("uv.lock"))
    findings, installed = _compare.compare_backend(tree, answer, PROJECT, "0.1.0", lock, dockerfile="Dockerfile.prod")
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
        (lambda a: a["texts"].update({f"{SITE}/terp_cli-0.33.0.dist-info/METADATA": "Name: terp-cli\nVersion: 0.33.0\n"}),
         "the image installs terp-cli more than once (0.33.0 and 0.34.0)"),
    ],
)
def test_each_way_the_image_differs_from_the_commit_is_found(tree: Tree, change, expected: str) -> None:
    found = _change(tree, change)
    assert any(expected in finding for finding in found), (expected, found)


def test_bytecode_needs_a_base_whose_layers_the_image_begins_with(tree: Tree) -> None:
    found = _change(tree, lambda a: a["compiled"].update(diffIds=[]))
    assert any("is not built on the base its Dockerfile names" in finding for finding in found)


def test_the_interpreter_version_comes_from_the_image(tree: Tree) -> None:
    def no_version(answer: dict) -> None:
        for config in (answer["config"]["config"], answer["compiled"]["baseConfig"]):
            config["Env"].remove("PYTHON_VERSION=3.14.8")
        answer["config"]["architecture"] = "s390x"

    assert _change(tree, no_version) == []


# --------------------------------------------------------------------------- #
# the record the app compares its routes with when it starts (ADR 0212)
# --------------------------------------------------------------------------- #
RECORD = b'{"authz_surface": 1}\n'
COPIES_RECORD = b"COPY authz-surface.jso[n] ./\n"


def _recorded(tmp_path: pathlib.Path, files: dict[str, bytes] | None = None) -> Tree:
    """The app with its record of who can reach what, which the render's Dockerfile copies."""
    root = tmp_path / "recorded"
    committed_app(root, (files or app_files()) | {"authz-surface.json": RECORD})
    return Tree.read(root, git(root, "rev-parse", "HEAD"))


def _shipped(tree: Tree, record: bytes = RECORD) -> dict:
    answer = faithful(tree)
    answer["nodes"]["srv/authz-surface.json"] = _file(record)
    return answer


def test_the_record_an_image_starts_against_is_the_tree_s(tmp_path: pathlib.Path) -> None:
    """The one file of /srv that is neither source nor environment, held to the tree's bytes."""
    tree = _recorded(tmp_path)
    assert COPIES_RECORD in tree.bytes("Dockerfile.prod"), "the render copies the record"
    assert _findings(tree, _shipped(tree)) == []


def test_a_record_that_is_not_the_tree_s_is_a_finding(tmp_path: pathlib.Path) -> None:
    """The app would hold itself to a record no reviewer saw."""
    tree = _recorded(tmp_path)
    assert _findings(tree, _shipped(tree, b'{"authz_surface": 1, "modules": []}\n')) == [
        "/srv/authz-surface.json is not the tree's authz-surface.json"
    ]


def test_a_record_the_tree_does_not_hold_is_a_finding(tree: Tree) -> None:
    found = _change(tree, lambda a: a["nodes"].update({"srv/authz-surface.json": _file(RECORD)}))
    assert found == ["/srv/authz-surface.json is not the tree's authz-surface.json"]


def test_a_record_kept_out_of_the_image_its_dockerfile_copies_it_into_is_a_finding(
    tmp_path: pathlib.Path,
) -> None:
    """One line in .dockerignore would otherwise turn the startup check off, and nothing else."""
    tree = _recorded(tmp_path)
    assert _findings(tree, faithful(tree)) == [
        "authz-surface.json is in the tree, Dockerfile.prod copies it, and it is not in the "
        "image, so the app would start without comparing the routes it serves with it: keep "
        "the record in the build context (.dockerignore)"
    ]


def test_a_dockerfile_that_does_not_copy_the_record_builds_an_image_without_it(
    tmp_path: pathlib.Path,
) -> None:
    """A Dockerfile rendered before the record was shipped, or an app's own.

    Its image starts without the comparison, as it did before: a signer newer than the app
    it reads does not refuse what that app's Dockerfile never claimed to copy.
    """
    files = app_files()
    assert COPIES_RECORD in files["Dockerfile.prod"]
    files["Dockerfile.prod"] = files["Dockerfile.prod"].replace(COPIES_RECORD, b"")
    tree = _recorded(tmp_path, files)
    assert _findings(tree, faithful(tree)) == []


def _planted(path: str, node: Node | None = None):  # type: ignore[no-untyped-def]
    return lambda a: a["nodes"].update({path: (node or Node("file", "5" * 64, 1)).as_data()})


def _record_of(name: str, extra: str):  # type: ignore[no-untyped-def]
    path = f"{SITE}/{name}-{TOOLCHAIN}.dist-info/RECORD"
    return lambda a: a["texts"].update({path: a["texts"][path] + extra})


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        # Code that runs at every interpreter start, planted beside the dependencies.
        (_planted(f"{SITE}/zz-hook.pth"), f"/{SITE}/zz-hook.pth is in the environment, and no installed distribution's RECORD lists it"),
        (_planted(f"{SITE}/sitecustomize.py"), f"/{SITE}/sitecustomize.py is in the environment, and no"),
        (_planted(f"{SITE}/usercustomize.py"), f"/{SITE}/usercustomize.py is in the environment, and no"),
        (_planted(f"{SITE}/sitecustomize.pyc"), f"/{SITE}/sitecustomize.pyc is in the environment, and no"),
        (_planted(f"{SITE}/__pycache__/sitecustomize.{TAG}.pyc"), "sitecustomize.cpython-314.pyc is in the environment, and no"),
        # A command on the PATH, and the interpreter the scripts name.
        (_planted(f"{BIN}/sh"), f"/{BIN}/sh is in the environment, and no"),
        (_planted(f"{BIN}/python", Node("link", target="/srv/app/main.py")), f"/{BIN}/python is in the environment, and no"),
        (_planted(f"{BIN}/python", Node("link", target="/srv")), f"/{BIN}/python is in the environment, and no"),
        (_planted(f"{BIN}/python", Node("link", target="python3")), f"/{BIN}/python is in the environment, and no"),
        (_planted(f"{BIN}/python3", Node("link", target="/opt/python")), f"/{BIN}/python3 is in the environment, and no"),
        (_planted(f"{BIN}/python3.14t", Node("link", target="python")), f"/{BIN}/python3.14t is in the environment, and no"),
        (_planted(f"{BIN}/activate", Node("link", target="/opt/x")), f"/{BIN}/activate is in the environment, and no"),
        (_planted(f"{BIN}/sub/activate"), f"/{BIN}/sub/activate is in the environment, and no"),
        (_planted("srv/.venv/lib64", Node("link", target="/opt")), "/srv/.venv/lib64 is in the environment, and no"),
        (_planted("srv/.venv/.gitignore", Node("link", target="/opt")), "/srv/.venv/.gitignore is in the environment, and no"),
        (_planted("srv/.venv/include/x.h"), "/srv/.venv/include/x.h is in the environment, and no"),
        # A dependency's own files, and its bytecode.
        (_planted(f"{SITE}/terp/cli/__init__.py"), f"/{SITE}/terp/cli/__init__.py is not the file its distribution's RECORD lists"),
        (_planted(f"{SITE}/terp/cli/__init__.py", Node("link", target="/opt/x")), "terp/cli/__init__.py is not the file its"),
        (_planted(f"{BIN}/terp"), f"/{BIN}/terp is not the file its distribution's RECORD lists"),
        (_planted(f"{SITE}/terp/cli/__pycache__/__init__.cpython-313.pyc"),
         "__init__.cpython-313.pyc is bytecode for cpython-313, and the image's interpreter is cpython-314"),
        (_planted(f"{SITE}/terp/cli/__pycache__/ghost.{TAG}.pyc"), "ghost.cpython-314.pyc is in the environment, and no"),
        (_planted(f"{SITE}/terp/cli/__pycache__/__init__.{TAG}.opt-1.pyc"), "is bytecode for cpython-314.opt-1"),
        (_planted(f"{SITE}/terp/cli/__pycache__/README"), "__pycache__/README is in the environment, and no"),
        (_planted(f"{SITE}/terp/cli/__pycache__/__init__.pyc"), "__pycache__/__init__.pyc is in the environment, and no"),
        (_planted(f"{SITE}/terp/cli/__pycache__/sub/__init__.{TAG}.pyc"), "sub/__init__.cpython-314.pyc is in the environment, and no"),
        # What a RECORD may list.
        (_record_of("terp_cli", "evil.pth,,\n"), f"the RECORD of /{SITE}/terp_cli-{TOOLCHAIN}.dist-info lists evil.pth without its SHA-256"),
        (_record_of("terp_cli", "../../../../../etc/x,sha256=AA,1\n"), "lists ../../../../../etc/x, outside the environment"),
        (_record_of("terp_cli", "/etc/x,sha256=AA,1\n"), "lists /etc/x, outside the environment"),
        (lambda a: a["texts"].pop(f"{SITE}/terp_arch-{TOOLCHAIN}.dist-info/RECORD"),
         f"/{SITE}/terp_arch-{TOOLCHAIN}.dist-info has no RECORD, so none of its files can be held to one"),
        # The environment's own configuration.
        (lambda a: a["texts"].update({"srv/.venv/pyvenv.cfg": PYVENV.replace("= false", "= True")}),
         "/srv/.venv/pyvenv.cfg adds the base image's own site-packages"),
        (lambda a: a["texts"].pop("srv/.venv/pyvenv.cfg"), "/srv/.venv holds no pyvenv.cfg sign can read"),
        # A file in /srv that nothing holds.
        (_planted("srv/fastapi.py"), "/srv/fastapi.py is in /srv outside app, control_plane and .venv"),
        (_planted("srv/app", Node("link", target="/opt")), "/srv/app is in /srv outside app, control_plane and .venv"),
    ],
)
def test_every_file_of_the_environment_is_held_to_a_record_or_to_how_it_is_made(tree: Tree, change, expected: str) -> None:
    found = _change(tree, change)
    assert any(expected in finding for finding in found), (expected, found)


def _config(change):  # type: ignore[no-untyped-def]
    return lambda a: change(a["config"]["config"])


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        (_config(lambda c: c["Env"].append("LD_PRELOAD=/srv/.venv/x.so")),
         "the image's environment sets LD_PRELOAD, which its Dockerfile does not"),
        (_config(lambda c: c["Env"].append("PYTHONPATH=/tmp")), "the image's environment sets PYTHONPATH, which"),
        (_config(lambda c: c["Env"].remove("VIRTUAL_ENV=/srv/.venv")),
         "the image's environment does not set VIRTUAL_ENV, which its Dockerfile does"),
        (_config(lambda c: c["Env"].__setitem__(0, "PATH=/tmp:/usr/bin")),
         "the image's environment gives PATH another value than its Dockerfile does"),
        (_config(lambda c: c["Env"].append("LANG=C.UTF-8")), "the image's environment sets a variable more than once"),
        (_config(lambda c: c.update(Cmd=["python", "-c", "x"])), "the image's Cmd is"),
        (_config(lambda c: c.update(Entrypoint=["/bin/sh", "-c"])), 'the image\'s Entrypoint is ["/bin/sh", "-c"], and its Dockerfile makes it null'),
        (_config(lambda c: c.update(User="root")), 'the image\'s User is "root", and its Dockerfile makes it "appuser"'),
        (_config(lambda c: c.update(WorkingDir="/opt")), "the image's WorkingDir is"),
        (_config(lambda c: c.update(Healthcheck={"Test": ["CMD-SHELL", "x"]})), "the image's Healthcheck is"),
        (_config(lambda c: c.update(Volumes={"/srv/.venv": {}})), 'the image\'s Volumes is ["/srv/.venv"]'),
        (_config(lambda c: c.update(StopSignal="SIGKILL")), "the image's StopSignal is"),
        (_config(lambda c: c.update(Shell=["/srv/.venv/bin/x"])), "the image's Shell is"),
        (lambda a: a["compiled"].pop("baseConfig"),
         "the configuration of the base the Dockerfile pins was not read, so the image's own cannot be held to it"),
    ],
)
def test_the_image_s_configuration_is_what_its_dockerfile_makes_of_the_base_s(tree: Tree, change, expected: str) -> None:
    found = _change(tree, change)
    assert any(expected in finding for finding in found), (expected, found)


def test_what_runs_nothing_is_not_held_to_the_dockerfile(tree: Tree) -> None:
    def labelled(answer: dict) -> None:
        answer["config"]["config"].update(Labels={"x": "y"}, ExposedPorts={"9/tcp": {}}, ArgsEscaped=False)
        answer["config"]["config"]["Env"].reverse()

    assert _change(tree, labelled) == []


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
    with pytest.raises(ReleaseError, match="a shape sign cannot compare.*") as raised:
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
    link = subprocess.run(["git", "-C", str(root), "hash-object", "-w", "--stdin"], input=b"main.py",
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
