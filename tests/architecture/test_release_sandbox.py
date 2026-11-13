"""The sandbox ``sign`` reads untrusted data in, and what each task answers (ADR 0187 d6).

The tasks run in a process of their own, handed their input and nothing of the signer's; here
each is also called in this process with its programs and its network stood in for, so every
path is held, and once for real across the process boundary.
"""

from __future__ import annotations

import io
import json
import pathlib
import runpy
import subprocess
import sys

import pytest

from terp.cli.release import _sandbox
from terp.cli.release._common import ReleaseError
from tests.architecture.release_fixtures import Runs
from tests.architecture.test_release_image import FakeRegistry, layer

BASE = "python@sha256:" + "a" * 64


def test_bytecode_names_its_source_under_srv() -> None:
    assert _sandbox.pyc_source("srv/app/sub/__pycache__/x.cpython-314.pyc") == ("app/sub/x.py", "cpython-314")
    assert _sandbox.pyc_source("srv/app/__pycache__/x.cpython-314.opt-1.pyc") == ("app/x.py", "cpython-314.opt-1")
    assert _sandbox.pyc_source("srv/app/x.py") is None


def test_the_compile_runs_in_the_base_image_sealed(monkeypatch) -> None:
    runs = (
        Runs()
        .on("docker", "run", out=json.dumps({"files": {"app/x.py": "ab"}, "cacheTag": "cpython-314", "magic": "2b0e0d0a"}).encode())
        .on("docker", "image", "inspect", out=b'{"layers":["sha256:l1"],"config":{"Env":["PATH=/usr/bin"],"Cmd":["python3"]}}')
    )
    monkeypatch.setattr(_sandbox, "run", runs)
    answer = _sandbox.compile_in_base(BASE, "linux/amd64", {"app/x.py": b"x = 1\n"})
    assert answer == {"files": {"app/x.py": "ab"}, "cacheTag": "cpython-314", "magic": "2b0e0d0a", "diffIds": ["sha256:l1"],
                      "baseConfig": {"Env": ["PATH=/usr/bin"], "Cmd": ["python3"]}}
    [inspect] = runs.ran("docker", "image", "inspect")
    assert inspect[-1] == BASE and "{{json .Config}}" in inspect[inspect.index("--format") + 1]
    [run] = runs.ran("docker", "run")
    assert run[run.index("--network") + 1] == "none" and "--read-only" in run
    assert run[run.index("--user") + 1] == "65534:65534" and "no-new-privileges" in run
    assert run[run.index("--entrypoint") + 1] == "python3" and run[run.index("--entrypoint") + 2] == BASE
    assert run[-4:-1] == ["-I", "-S", "-c"]


def test_the_compile_script_is_compileall_s_own_compile(tmp_path: pathlib.Path) -> None:
    """The script, run by this interpreter, gives the bytes ``compileall`` gives from /srv."""
    import base64
    import hashlib
    import py_compile

    source = b"def f():\n    return 41 + 1\n"
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "x.py").write_bytes(source)
    expected = tmp_path / "expected.pyc"
    subprocess.run(
        [sys.executable, "-c", "import py_compile, sys; py_compile.compile('app/x.py', cfile=sys.argv[1], doraise=True, "
         "invalidation_mode=py_compile.PycInvalidationMode.CHECKED_HASH)", str(expected)],
        cwd=tmp_path, check=True,
    )
    script = _sandbox._COMPILE.replace('"/tmp/w"', repr(str(tmp_path / "w"))).replace('"/tmp/out.pyc"', repr(str(tmp_path / "out.pyc")))
    out = subprocess.run(
        [sys.executable, "-I", "-S", "-c", script],
        input=json.dumps({"app/x.py": base64.b64encode(source).decode()}).encode(), capture_output=True, check=True,
    )
    answer = json.loads(out.stdout)
    assert answer["files"]["app/x.py"] == hashlib.sha256(expected.read_bytes()).hexdigest()
    assert answer["cacheTag"] == sys.implementation.cache_tag
    assert py_compile is not None


def _tree(tmp_path: pathlib.Path) -> pathlib.Path:
    tree = tmp_path / "tree"
    (tree / "app").mkdir(parents=True)
    (tree / "app" / "x.py").write_bytes(b"x = 1\n")
    return tree


def test_the_image_task_reads_the_image_and_compiles_its_bytecode_sources(tmp_path: pathlib.Path, monkeypatch) -> None:
    fake = FakeRegistry()
    pushed = fake.push_image([layer(
        ("srv/app/x.py", b"x = 1\n"), ("srv/app/__pycache__/x.cpython-314.pyc", b"pyc"),
        ("srv/app/__pycache__/gone.cpython-314.pyc", b"pyc"), ("srv/.venv/lib/python3.14/site-packages/d/__pycache__/m.cpython-314.pyc", b"dep"),
        ("usr/bin/python3", b"elf"),
    )])
    monkeypatch.setattr(_sandbox, "egress_getter", lambda host, http: fake)
    compiled: list = []
    monkeypatch.setattr(_sandbox, "compile_in_base", lambda base, platform, sources: compiled.append(sources) or {"files": {"app/x.py": "h"}})
    payload = {"repository": "registry.example/rel/app", "digest": pushed, "platform": "linux/amd64",
               "http": False, "credentials": ["u", "p"], "tree": str(_tree(tmp_path)), "base": BASE}
    answer = _sandbox.image_task(payload)
    assert answer["digest"] == pushed and "srv/app/x.py" in answer["nodes"]
    assert "usr/bin/python3" not in answer["nodes"], "only /srv is handed back"
    assert compiled == [{"app/x.py": b"x = 1\n"}], "a source the tree holds, under the two roots only"
    assert answer["compiled"] == {"files": {"app/x.py": "h"}}
    no_base = _sandbox.image_task({**payload, "base": None, "credentials": None})
    assert no_base["compiled"] == {"files": {}, "cacheTag": "", "magic": "", "diffIds": []}
    no_bytecode = fake.push_image([layer(("srv/.venv/pyvenv.cfg", b"home = /usr/local/bin\n"))])
    answer = _sandbox.image_task({**payload, "digest": no_bytecode})
    assert compiled[-1] == {}, "the base is read for its configuration even with nothing to compile"
    assert answer["texts"] == {"srv/.venv/pyvenv.cfg": "home = /usr/local/bin\n"}


def test_the_image_task_hands_back_what_the_migration_reading_reads_from_the_whole_image(tmp_path: pathlib.Path, monkeypatch) -> None:
    import base64

    site = "usr/local/lib/python3.14/site-packages"
    metadata = "srv/.venv/lib/python3.14/site-packages/d-1.dist-info/METADATA"
    fake = FakeRegistry()
    pushed = fake.push_image([layer(
        (f"{site}/x-1.dist-info/entry_points.txt", b"[terp.migrations]\nx = x\n"),
        (f"{site}/x/migrations/versions/a1.py", b"revision = 'a1'\n"),
        (metadata, b"Name: d\nVersion: 1\n"), ("usr/bin/python3", b"elf"),
    )])
    monkeypatch.setattr(_sandbox, "egress_getter", lambda host, http: fake)
    answer = _sandbox.image_task({"repository": "registry.example/rel/app", "digest": pushed, "platform": "linux/amd64",
                                  "http": False, "credentials": None, "tree": str(_tree(tmp_path)), "base": None})
    assert list(answer["nodes"]) == [metadata] and answer["texts"] == {metadata: "Name: d\nVersion: 1\n"}, "unchanged: /srv only"
    inputs = answer["migrationInputs"]
    assert inputs["files"] == {
        f"{site}/x-1.dist-info/entry_points.txt": base64.b64encode(b"[terp.migrations]\nx = x\n").decode(),
        f"{site}/x/migrations/versions/a1.py": base64.b64encode(b"revision = 'a1'\n").decode(),
    }
    assert {"usr", "usr/bin", f"{site}/x/migrations/versions", "srv/.venv/lib/python3.14/site-packages/d-1.dist-info"} <= set(inputs["nodes"])
    files = {path for path, data in inputs["nodes"].items() if data[0] == "file"}
    assert files == set(inputs["files"]), "a file is handed back as a node only where its bytes are kept"
    assert all(data[0] == "dir" for path, data in inputs["nodes"].items() if path not in files)


def _image_task(tmp_path: pathlib.Path, monkeypatch, *layers: bytes) -> dict:
    fake = FakeRegistry()
    pushed = fake.push_image(list(layers))
    monkeypatch.setattr(_sandbox, "egress_getter", lambda host, http: fake)
    return _sandbox.image_task({"repository": "registry.example/rel/app", "digest": pushed, "platform": "linux/amd64",
                                "http": False, "credentials": None, "tree": str(_tree(tmp_path)), "base": None})


def _revision(rev: str, down: str | None, body: str) -> bytes:
    return f"revision = {rev!r}\ndown_revision = {down!r}\nfrom alembic import op\n\ndef upgrade():\n{body}\n".encode()


@pytest.mark.parametrize("below", [False, True], ids=["link-in-its-layer", "link-in-a-layer-below"])
def test_an_entry_written_through_a_link_is_refused_where_the_listing_reads(tmp_path: pathlib.Path, monkeypatch, below: bool) -> None:
    """An engine follows a link on an entry's way and writes the file where the link points: here
    a revision into a capability's versions/, which sign filed under the link's own path and never
    listed."""
    versions = "usr/local/lib/python3.14/site-packages/cap/migrations/versions"
    lower = [("usr/local/lib/python3.14/site-packages/cap-1.0.dist-info/entry_points.txt", b"[terp.migrations]\ncap = cap\n"),
             ("usr/local/lib/python3.14/site-packages/cap/__init__.py", b""), (versions, None),
             (f"{versions}/a1_base.py", _revision("a1", None, "    pass")), ("opt/trick", f"/{versions}")]
    upper = [("opt/trick/b2_evil.py", _revision("b2", "a1", "    op.drop_table('invoice')"))]
    layers = (layer(*lower), layer(*upper)) if below else (layer(*lower, *upper),)
    with pytest.raises(ReleaseError, match="the layer writes opt/trick/b2_evil.py through opt/trick, a symbolic link"):
        _image_task(tmp_path, monkeypatch, *layers)


def test_an_entry_written_through_a_link_is_refused_where_the_comparison_reads(tmp_path: pathlib.Path, monkeypatch) -> None:
    """The same over /srv: a file that lands in the app's sources through a link elsewhere was
    never held to the tree."""
    versions = "srv/app/modules/notes/migrations/versions"
    lower = layer(("srv/app/modules/notes/__init__.py", b""), (versions, None), (f"{versions}/a1_base.py", _revision("a1", None, "    pass")))
    upper = layer(("opt/t", f"/{versions}"), ("opt/t/b2_evil.py", _revision("b2", "a1", "    op.drop_table('invoice')")))
    with pytest.raises(ReleaseError, match="the layer writes opt/t/b2_evil.py through opt/t, a symbolic link"):
        _image_task(tmp_path, monkeypatch, lower, upper)


def test_the_scan_asks_the_shared_vulnerability_client_and_names_the_database(monkeypatch) -> None:
    from terp.cli.release import _osv

    asked: list = []
    monkeypatch.setattr(_osv, "query_batch", lambda osv, purls, **_: asked.append((osv, purls)) or {"pkg:pypi/x@1": ["A"]})
    answer = _sandbox.scan_task({"osv": "https://osv.example/", "purls": ["pkg:pypi/x@1", "pkg:pypi/y@2"]})
    assert answer == {"database": "https://osv.example/", "queried": 2, "vulnerable": {"pkg:pypi/x@1": ["A"]}}
    assert asked == [("https://osv.example/", ["pkg:pypi/x@1", "pkg:pypi/y@2"])]


def test_the_secret_scan_is_gitleaks_over_the_git_directory_with_the_tree_s_acknowledgements(tmp_path: pathlib.Path, monkeypatch) -> None:
    from terp.cli.release._common import run as real
    from tests.architecture.release_fixtures import committed_app

    repo = tmp_path / "repo"
    sha = committed_app(repo)
    seen: list = []

    def detect(argv, stdin):  # type: ignore[no-untyped-def]
        seen.append(argv)
        report = pathlib.Path(argv[argv.index("--report-path") + 1])
        ignore = argv[argv.index("--gitleaks-ignore-path") + 1] if "--gitleaks-ignore-path" in argv else None
        seen.append(pathlib.Path(ignore).read_text(encoding="utf-8") if ignore else None)
        report.write_text(json.dumps([{"RuleID": "aws", "File": "a.py", "Commit": "c1", "Secret": "REDACTED"}]))
        return 0, b"", b""

    runs = Runs(real=real).on("fake-gitleaks", "version", out=b"8.30.1\n").on("fake-gitleaks", "detect", then=detect)
    monkeypatch.setattr(_sandbox, "run", runs)
    answer = _sandbox.secrets_task({"gitleaks": "fake-gitleaks", "repo": str(repo), "sha": sha, "ignore": "abc:a.py:aws:1\n"})
    assert answer == {"tool": "gitleaks", "version": "8.30.1",
                      "findings": [{"rule": "aws", "file": "a.py", "commit": "c1"}]}
    argv = seen[0]
    assert argv[argv.index("--source") + 1].replace("\\", "/").endswith("/.git"), "the git directory: no working tree, no tree config"
    assert f"--log-opts={sha}" in argv and "--redact" in argv
    assert seen[1] == "abc:a.py:aws:1\n"
    def clean(argv, stdin):  # type: ignore[no-untyped-def]
        pathlib.Path(argv[argv.index("--report-path") + 1]).write_text("[]")
        return 0, b"", b""

    runs = Runs(real=real).on("fake-gitleaks", "version", code=1).on("fake-gitleaks", "detect", then=clean)
    monkeypatch.setattr(_sandbox, "run", runs)
    assert _sandbox.secrets_task({"gitleaks": "fake-gitleaks", "repo": str(repo), "sha": sha, "ignore": None}) == {
        "tool": "gitleaks", "version": "", "findings": []}

    def broken(argv, stdin):  # type: ignore[no-untyped-def]
        pathlib.Path(argv[argv.index("--report-path") + 1]).write_text("{not json")
        return 0, b"", b""

    monkeypatch.setattr(_sandbox, "run", Runs(real=real).on("fake-gitleaks", "version").on("fake-gitleaks", "detect", then=broken))
    with pytest.raises(ReleaseError, match="gitleaks wrote no report"):
        _sandbox.secrets_task({"gitleaks": "fake-gitleaks", "repo": str(repo), "sha": sha, "ignore": None})
    monkeypatch.setattr(_sandbox, "run", real)
    with pytest.raises(ReleaseError, match="scanning the history for secrets failed"):
        _sandbox.secrets_task({"gitleaks": "terp-no-such-gitleaks", "repo": str(repo), "sha": sha, "ignore": None})


def test_the_secret_scan_reads_a_checkout_another_user_owns(tmp_path: pathlib.Path, monkeypatch) -> None:
    """git refuses a repository another user owns, and so does gitleaks, which runs git: the
    scan's own git call and gitleaks are both told the named repository is safe."""
    from terp.cli.release._common import run as real
    from tests.architecture.release_fixtures import committed_app

    repo = tmp_path / "repo"
    sha = committed_app(repo)
    monkeypatch.setenv("GIT_TEST_ASSUME_DIFFERENT_OWNER", "1")  # git's own switch for the check

    def clean(argv, stdin):  # type: ignore[no-untyped-def]
        pathlib.Path(argv[argv.index("--report-path") + 1]).write_text("[]")
        return 0, b"", b""

    runs = Runs(real=real).on("fake-gitleaks", "version").on("fake-gitleaks", "detect", then=clean)
    monkeypatch.setattr(_sandbox, "run", runs)
    assert _sandbox.secrets_task({"gitleaks": "fake-gitleaks", "repo": str(repo), "sha": sha, "ignore": None})["findings"] == []
    (scan_env,) = [env for call, env in zip(runs.calls, runs.envs, strict=True) if call[1] == "detect"]
    assert scan_env is not None
    assert (scan_env["GIT_CONFIG_COUNT"], scan_env["GIT_CONFIG_KEY_0"], scan_env["GIT_CONFIG_VALUE_0"]) == (
        "1", "safe.directory", "*")
    assert scan_env["GIT_TEST_ASSUME_DIFFERENT_OWNER"] == "1", "the rest of the environment is the task's own"


def test_a_task_runs_in_its_own_process_handed_its_input_alone(monkeypatch) -> None:
    seen: dict = {}

    def child(argv, *, cwd=None, env=None, stdin=None):  # type: ignore[no-untyped-def]
        seen.update(argv=argv, env=env, stdin=stdin, cwd=cwd)
        return subprocess.CompletedProcess(argv, 0, b'{"ok":true}', b"")

    monkeypatch.setenv("TERP_SIGN_SECRET", "never handed over")
    monkeypatch.setattr(_sandbox, "run", child)
    assert _sandbox.sandboxed("scan", {"osv": "x", "purls": []}) == {"ok": True}
    assert seen["argv"][1:] == ["-I", "-m", _sandbox.MODULE, "scan"]
    assert "TERP_SIGN_SECRET" not in seen["env"]
    assert json.loads(seen["stdin"]) == {"osv": "x", "purls": []}
    for out, expected in ((b"not json", "answered no JSON"), (b"[1]", "answered no JSON object")):
        monkeypatch.setattr(_sandbox, "run", lambda argv, out=out, **kwargs: subprocess.CompletedProcess(argv, 0, out, b""))
        with pytest.raises(ReleaseError, match=expected):
            _sandbox.sandboxed("scan", {})


def test_a_task_that_refuses_across_the_process_boundary_says_why() -> None:
    with pytest.raises(ReleaseError, match="the sandbox's scan task refused") as raised:
        _sandbox.sandboxed("scan", {"osv": "http://127.0.0.1:9", "purls": ["pkg:pypi/x@1"]})
    assert "could not be asked" in raised.value.cause


def test_the_sandbox_process_runs_one_task(monkeypatch) -> None:
    out = io.StringIO()
    monkeypatch.setitem(_sandbox.TASKS, "echo", lambda payload: {"got": payload})
    assert _sandbox.main(["echo"], io.BytesIO(b'{"a": 1}'), out) == 0
    assert json.loads(out.getvalue()) == {"got": {"a": 1}}
    monkeypatch.setitem(_sandbox.TASKS, "refuse", lambda payload: (_ for _ in ()).throw(ReleaseError("no")))
    assert _sandbox.main(["refuse"], io.BytesIO(b"{}"), io.StringIO()) == 1
    assert _sandbox.main([], io.BytesIO(b""), io.StringIO()) == 2
    assert _sandbox.main(["nope"], io.BytesIO(b""), io.StringIO()) == 2
    monkeypatch.setattr(sys, "argv", ["x", "echo"])
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(b'{"b": 2}')))
    monkeypatch.setattr(sys, "stdout", io.StringIO())
    monkeypatch.delitem(sys.modules, _sandbox.MODULE)
    with pytest.raises(SystemExit) as exited:
        runpy.run_module(_sandbox.MODULE, run_name="__main__")
    assert exited.value.code == 2, "a fresh module has only its own tasks: echo is not one"
