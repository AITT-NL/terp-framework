"""What the release jobs share: the tag, the commit, the documents, the tree, the locks.

ADR 0187 decision 6. A release is cut from an exact SHA and read from git's object store, so
the tree here is always a real repository's; the locks are read as data, never by a resolver.
"""

from __future__ import annotations

import json
import os
import pathlib
import subprocess

import pytest

from terp.cli.release import _common, _git, _locks
from terp.cli.release._common import ReleaseError
from tests.architecture.release_fixtures import PROJECT, TOOLCHAIN, app_files, committed_app, git


# --------------------------------------------------------------------------- the tag, the commit
@pytest.mark.parametrize("tag", ["r1", "v0.35.0", "a" * 128, "0_x-y.z", "_x"])
def test_a_release_tag_is_a_docker_tag(tag: str) -> None:
    assert _common.release_tag(tag) == tag


@pytest.mark.parametrize("tag", ["", "-x", ".x", "a" * 129, "a b", "a:b", "a/b", "a$b"])
def test_anything_else_is_refused_as_a_tag(tag: str) -> None:
    with pytest.raises(ReleaseError, match="is not a release tag"):
        _common.release_tag(tag)


def test_a_commit_is_its_full_object_name() -> None:
    assert _common.commit_id("a" * 40) == "a" * 40
    assert _common.commit_id("b" * 64) == "b" * 64
    for wrong in ("a" * 39, "A" * 40, "main", "HEAD", "a" * 41):
        with pytest.raises(ReleaseError, match="is not an exact commit"):
            _common.commit_id(wrong)


# --------------------------------------------------------------------------- documents and bytes
def test_a_document_is_one_canonical_byte_string() -> None:
    assert _common.canonical({"b": [1, "é"], "a": {"z": True, "y": None}}) == (
        '{"a":{"y":null,"z":true},"b":[1,"é"]}'.encode()
    )
    with pytest.raises(ReleaseError, match=r"a\.b\[1\] holds a float"):
        _common.canonical({"a": {"b": [1, 2.5]}})
    with pytest.raises(ReleaseError, match="the document holds a float"):
        _common.canonical(1.0)
    assert _common.sha256(b"") == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


def test_a_document_is_read_back_only_as_its_own_kind(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "d.json"
    _common.write_document(path, {"kind": 1, "x": "y"})
    assert path.read_bytes() == b'{"kind":1,"x":"y"}\n'
    assert _common.read_document(path, "kind") == {"kind": 1, "x": "y"}
    with pytest.raises(ReleaseError, match="is not a other document of version 1"):
        _common.read_document(path, "other")
    with pytest.raises(ReleaseError, match="is not a kind document of version 2"):
        _common.read_document(path, "kind", 2)
    path.write_text("not json", encoding="utf-8")
    with pytest.raises(ReleaseError, match="is not a readable JSON document"):
        _common.read_document(path, "kind")
    with pytest.raises(ReleaseError, match="is not a readable JSON document"):
        _common.read_document(tmp_path / "missing.json", "kind")


def test_an_error_keeps_its_sentence_apart_from_what_a_program_said() -> None:
    assert str(ReleaseError("it failed")) == "it failed"
    error = ReleaseError("it failed", cause="  the tool said so \n")
    assert error.message == "it failed" and error.cause == "the tool said so"
    assert str(error) == "it failed\n  the tool said so"


# --------------------------------------------------------------------------- running programs
def test_a_program_runs_from_a_fixed_list_and_a_missing_one_is_an_answer(tmp_path: pathlib.Path) -> None:
    import sys

    done = _common.run([sys.executable, "-c", "import sys; print(sys.stdin.read().upper())"], stdin=b"hi")
    assert done.returncode == 0 and done.stdout.strip() == b"HI"
    env = _common.run([sys.executable, "-c", "import os; print(sorted(os.environ).count('ONLY_THIS'))"],
                      env={**_common.os_environment(), "ONLY_THIS": "1"})
    assert env.stdout.strip() == b"1"
    missing = _common.run(["terp-release-no-such-program"])
    assert missing.returncode == _common.NOT_FOUND
    assert b"not found on PATH" in missing.stderr
    assert _common.output_of(missing) == "terp-release-no-such-program: not found on PATH"
    with pytest.raises(ReleaseError, match=r"running it failed \(exit 127\)"):
        _common.require(missing, "running it")
    assert _common.require(done, "x") == done.stdout


def test_the_os_environment_is_the_operating_system_s_names_and_nothing_else(monkeypatch) -> None:
    monkeypatch.setenv("PATH", "/bin")
    monkeypatch.setenv("SECRET_KEY", "x" * 40)
    monkeypatch.setenv("DOCKER_HOST", "tcp://engine")
    chosen = _common.os_environment({"EXTRA": "1"}, names=_common.DOCKER_NAMES)
    assert chosen["PATH"] == "/bin" and chosen["EXTRA"] == "1" and chosen["DOCKER_HOST"] == "tcp://engine"
    assert "SECRET_KEY" not in chosen
    assert "DOCKER_HOST" not in _common.os_environment()


# --------------------------------------------------------------------------- the tree
def test_the_tree_is_the_commit_s_exact_bytes_whatever_the_working_copy_holds(tmp_path: pathlib.Path) -> None:
    files = app_files() | {"bin/run.sh": b"#!/bin/sh\necho hi\r\n", "docs/crlf.txt": b"a\r\nb\r\n"}
    sha = committed_app(tmp_path / "repo", files)
    git(tmp_path / "repo", "update-index", "--chmod=+x", "bin/run.sh")
    git(tmp_path / "repo", "commit", "-q", "-m", "exec")
    sha = git(tmp_path / "repo", "rev-parse", "HEAD")
    (tmp_path / "repo" / "app" / "main.py").write_text("edited in the working copy", encoding="utf-8")
    (tmp_path / "repo" / "untracked.txt").write_text("not committed", encoding="utf-8")
    tree = _git.Tree.read(tmp_path / "repo", sha)
    assert tree.commit == sha and len(tree.tree) == 40 and tree.time > 0
    assert tree.bytes("app/main.py") == files["app/main.py"]
    assert tree.bytes("docs/crlf.txt") == b"a\r\nb\r\n", "no line-ending filter between git and the job"
    assert not tree.has("untracked.txt")
    assert tree.read_text("pyproject.toml").startswith("[project]")
    assert tree.paths("app/") == ["app/__init__.py", "app/main.py", "app/modules/__init__.py"]
    assert tree.entries["bin/run.sh"].executable and not tree.entries["app/main.py"].executable
    out = tmp_path / "out"
    tree.materialize(out)
    assert (out / "docs" / "crlf.txt").read_bytes() == b"a\r\nb\r\n"
    assert (out / "app" / "main.py").read_bytes() == files["app/main.py"]
    if os.name != "nt":
        assert os.access(out / "bin" / "run.sh", os.X_OK)
    assert tree.submodules == ()


def test_a_link_is_a_link_or_a_refusal_and_a_submodule_is_named(tmp_path: pathlib.Path, monkeypatch) -> None:
    root = tmp_path / "repo"
    sha = committed_app(root)
    # A link and a submodule enter the index directly, so the test needs no privilege.
    link = subprocess.run(["git", "-C", str(root), "hash-object", "-w", "--stdin"], input=b"app/main.py",  # noqa: S603, S607
                          capture_output=True, check=True).stdout.decode().strip()
    git(root, "update-index", "--add", "--cacheinfo", f"120000,{link},alias.py")
    git(root, "update-index", "--add", "--cacheinfo", f"160000,{sha},vendor/other")
    git(root, "commit", "-q", "-m", "a link and a submodule")
    sha = git(root, "rev-parse", "HEAD")
    tree = _git.Tree.read(root, sha)
    assert tree.entries["alias.py"].link and tree.read_text("alias.py") == "app/main.py"
    assert tree.submodules == ("vendor/other",)
    assert "vendor/other" not in tree.entries
    made: list[tuple[str, pathlib.Path]] = []
    monkeypatch.setattr(_git.os, "symlink", lambda source, target: made.append((source, target)))
    tree.materialize(tmp_path / "out")
    assert made == [("app/main.py", tmp_path / "out" / "alias.py")]

    def refuse(source, target):  # type: ignore[no-untyped-def]
        raise OSError("a symbolic link needs a privilege here")

    monkeypatch.setattr(_git.os, "symlink", refuse)
    with pytest.raises(ReleaseError, match="alias.py is a symbolic link this host cannot create"):
        tree.materialize(tmp_path / "out2")


def test_a_tree_is_read_from_an_exact_commit_only(tmp_path: pathlib.Path, monkeypatch) -> None:
    root = tmp_path / "repo"
    sha = committed_app(root)
    with pytest.raises(ReleaseError, match="is not an exact commit"):
        _git.Tree.read(root, "HEAD")
    with pytest.raises(ReleaseError, match="finding commit"):
        _git.Tree.read(root, "0" * 40)
    tree_id = git(root, "rev-parse", f"{sha}^{{tree}}")
    with pytest.raises(ReleaseError, match="finding commit"):
        _git.Tree.read(root, tree_id)
    real = _git.run

    def lying(argv, **kwargs):  # type: ignore[no-untyped-def]
        if "rev-parse" in argv:
            return subprocess.CompletedProcess(argv, 0, b"f" * 40 + b"\n", b"")
        return real(argv, **kwargs)

    monkeypatch.setattr(_git, "run", lying)
    with pytest.raises(ReleaseError, match="resolves to f+, not to itself"):
        _git.Tree.read(root, sha)


def test_a_checkout_another_user_owns_is_read_all_the_same(tmp_path: pathlib.Path, monkeypatch) -> None:
    """The signer image runs as its own user, never the owner of the checkout it is handed, and
    git refuses such a repository ("dubious ownership"): the signer's first real run did. The
    operator named the repository and the jobs read it as data, so their git calls say so."""
    root = tmp_path / "repo"
    sha = committed_app(root)
    monkeypatch.setenv("GIT_TEST_ASSUME_DIFFERENT_OWNER", "1")  # git's own switch for the check
    refused = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, check=False)  # noqa: S603, S607
    assert refused.returncode != 0 and b"dubious ownership" in refused.stderr
    assert _git.Tree.read(root, sha).commit == sha


def test_the_batch_reader_refuses_an_answer_for_another_object(monkeypatch) -> None:
    monkeypatch.setattr(_git, "run", lambda argv, **kwargs: subprocess.CompletedProcess(argv, 0, b"abc tree 0\n\n", b""))
    with pytest.raises(ReleaseError, match="git answered abc tree where blob"):
        _git._blobs(["git"], ["def"])
    assert _git._blobs(["git"], []) == {}


def test_head_says_which_commit_is_out_and_whether_it_is_clean(tmp_path: pathlib.Path) -> None:
    root = tmp_path / "repo"
    sha = committed_app(root)
    assert _git.head(root) == (sha, True)
    (root / "new.txt").write_text("x", encoding="utf-8")
    assert _git.head(root) == (sha, False)


# --------------------------------------------------------------------------- the locks
def test_the_uv_lock_says_what_the_commit_pins_and_installs() -> None:
    lock = _locks.read_uv_lock(app_files()["uv.lock"].decode())
    assert _locks.pinned(lock, "terp-cli") == _locks.pinned(lock, "terp-arch") == TOOLCHAIN
    assert _locks.pinned(lock, "missing") is None
    assert _locks.path_sources(lock) == []
    assert _locks.python_sources(lock) == ["https://pypi.org/simple"]
    linux = _locks.marker_environment("3.14.8", "x86_64")
    assert linux["python_version"] == "3.14" and linux["sys_platform"] == "linux"
    assert _locks.runtime_set(lock, PROJECT, linux) == [("terp-arch", TOOLCHAIN), ("terp-cli", TOOLCHAIN)]
    windows = {**linux, "sys_platform": "win32"}
    assert ("colorama", "0.4.6") in _locks.runtime_set(lock, PROJECT, windows)


def test_a_lock_naming_a_path_is_named_and_a_broken_one_is_refused() -> None:
    lock = _locks.read_uv_lock(
        app_files()["uv.lock"].decode()
        + '\n[[package]]\nname = "vendored"\nversion = "1"\nsource = { path = ".terp-dist/wheels/v.whl" }\n'
        + '\n[[package]]\nname = "sibling"\nversion = "1"\nsource = { editable = "../sibling" }\n'
        + '\n[[package]]\nname = "git-dep"\nversion = "1"\nsource = { git = "https://example.invalid/r.git" }\n'
    )
    assert _locks.path_sources(lock) == [
        "vendored (path = '.terp-dist/wheels/v.whl')", "sibling (editable = '../sibling')",
    ]
    assert "git+https://example.invalid/r.git" in _locks.python_sources(lock)
    with pytest.raises(ReleaseError, match="is not TOML"):
        _locks.read_uv_lock("[[package")
    with pytest.raises(ReleaseError, match="holds no"):
        _locks.read_uv_lock("version = 1\n")


def test_the_runtime_set_follows_extras_and_refuses_what_it_cannot_resolve() -> None:
    lock = {
        "package": [
            {"name": "app", "version": "1", "source": {"virtual": "."},
             "dependencies": [{"name": "uvicorn", "extra": ["standard"]}, {"name": "pinned", "version": "2"},
                              {"name": "httptools"}]},
            {"name": "uvicorn", "version": "0.5", "optional-dependencies": {"standard": [{"name": "httptools"}]}},
            {"name": "httptools", "version": "0.7", "dependencies": [{"name": "uvicorn"}]},
            {"name": "pinned", "version": "1"},
            {"name": "pinned", "version": "2"},
        ]
    }
    env = _locks.marker_environment("3.14.8", "x86_64")
    assert _locks.runtime_set(lock, "app", env) == [("httptools", "0.7"), ("pinned", "2"), ("uvicorn", "0.5")]
    with pytest.raises(ReleaseError, match="does not lock the project other itself"):
        _locks.runtime_set(lock, "other", env)
    lock["package"][0]["dependencies"].append({"name": "absent"})
    with pytest.raises(ReleaseError, match="names 'absent' ambiguously or not at all"):
        _locks.runtime_set(lock, "app", env)
    lock["package"][0]["dependencies"][-1] = {"name": "pinned", "marker": "python_version >>> '3'"}
    with pytest.raises(ReleaseError, match="carries a marker this signer cannot read"):
        _locks.runtime_set(lock, "app", env)


def test_markers_need_the_release_extra(monkeypatch) -> None:
    import sys

    monkeypatch.setitem(sys.modules, "packaging.markers", None)
    with pytest.raises(ReleaseError, match=r"needs terp-cli\[release\]"):
        _locks._applies({"marker": "sys_platform == 'linux'"}, {})
    assert _locks._applies({}, {}) is True


def test_the_frontend_lock_says_where_npm_fetches_and_what_it_installs() -> None:
    lock = _locks.read_npm_lock(json.dumps({
        "lockfileVersion": 3,
        "packages": {
            "": {"name": "frontend"},
            "node_modules/react": {"version": "19.0.0", "resolved": "https://registry.npmjs.org/react/-/react-19.0.0.tgz"},
            "node_modules/@terpjs/react-core": {"version": "0.35.0", "resolved": "file:../.terp-dist/npm/x.tgz"},
            "node_modules/linked": {"link": True, "resolved": "../linked"},
            "node_modules/a/node_modules/b": {"name": "b", "version": "1.0.0", "resolved": "http://mirror.example/b.tgz"},
            "node_modules/nameless": {},
        },
    }))
    assert _locks.npm_path_sources(lock) == ["node_modules/@terpjs/react-core", "node_modules/linked"]
    assert _locks.npm_hosts(lock) == ["mirror.example", "registry.npmjs.org"]
    assert _locks.npm_packages(lock) == [("@terpjs/react-core", "0.35.0"), ("b", "1.0.0"), ("react", "19.0.0")]
    with pytest.raises(ReleaseError, match="is not JSON"):
        _locks.read_npm_lock("{")
    with pytest.raises(ReleaseError, match="no packages object"):
        _locks.read_npm_lock("[]")
    assert _locks.normalise("Zope.Interface_x") == "zope-interface-x"
