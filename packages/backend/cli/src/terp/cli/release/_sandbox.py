"""The sandbox: what ``sign`` reads from data a build or a history could have shaped.

ADR 0187 decision 6 has ``sign`` read the backend image, scan it and scan the commit's history
"in a sandbox that cannot reach the signer and returns data". Each of those is a task run in a
process of its own, ``python -I -m terp.cli.release._sandbox <task>``: its input on standard
input and its answer on standard output, both one JSON document, in a scratch directory of its
own, with the operating system's variables and the docker client's and nothing else. It is
never given the signing key, the signer's command or its environment; it computes, and
``sign`` judges what it returns.

The tasks:

* ``image``: the image's manifest, configuration and filesystem, read from the registry
  (:mod:`._registry`, :mod:`._image`), and the bytecode check: each ``__pycache__`` file under
  ``/srv`` is answered with the SHA-256 of the checked-hash compile of the tree's source, made
  by the interpreter of the image's own base, run from that base image by digest with no
  network, a read-only filesystem and no privilege. The app image is never started;
* ``scan``: the SBOM's packages asked of the vulnerability database (OSV's batch API);
* ``secrets``: gitleaks over the history reachable from the SHA, with gitleaks' own rules and
  the acknowledgements the SHA's tree commits in ``.gitleaksignore``.

A deployment that wants a stronger wall runs ``sign`` where this process cannot reach the
network the signer is on; the boundary here is the process and what it is handed.
"""

from __future__ import annotations

import base64
import json
import pathlib
import re
import subprocess
import sys
import tempfile
import urllib.parse
from collections.abc import Callable
from typing import Any, BinaryIO, TextIO

from terp.cli.release._common import (
    DOCKER_NAMES,
    ReleaseError,
    canonical,
    os_environment,
    output_of,
    require,
    run,
)
from terp.cli.release._image import read_filesystem
from terp.cli.release._registry import Registry, egress_getter

MODULE = "terp.cli.release._sandbox"

#: The two source roots the backend image copies from the tree and compiles, under ``/srv``.
SOURCE_ROOTS = ("app", "control_plane")

#: Bytecode the build compiles under ``/srv``: ``<dir>/__pycache__/<stem>.<tag>.pyc``.
_PYC = re.compile(r"srv/(?P<dir>(?:[^/]+/)*)__pycache__/(?P<stem>[^/.]+)\.(?P<tag>[^/]+)\.pyc")

#: How the base image's interpreter runs: nobody, nothing writable but /tmp, no network.
_SEALED = (
    "--rm", "-i", "--network", "none", "--read-only", "--tmpfs", "/tmp",  # noqa: S108 - in the container
    "--user", "65534:65534", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
    "--pull", "missing",
)

#: The compile, as the image's own interpreter makes it: the file named as ``compileall``
#: named it from ``/srv`` (``app/x.py``), checked-hash, no optimisation beyond the default.
_COMPILE = """\
import base64, hashlib, importlib.util, json, os, py_compile, sys
files = json.load(sys.stdin)
os.makedirs("/tmp/w", exist_ok=True)
os.chdir("/tmp/w")
out = {}
for name, data in sorted(files.items()):
    os.makedirs(os.path.dirname(name) or ".", exist_ok=True)
    with open(name, "wb") as handle:
        handle.write(base64.b64decode(data))
    py_compile.compile(name, cfile="/tmp/out.pyc", doraise=True,
                       invalidation_mode=py_compile.PycInvalidationMode.CHECKED_HASH)
    with open("/tmp/out.pyc", "rb") as handle:
        out[name] = hashlib.sha256(handle.read()).hexdigest()
print(json.dumps({"files": out, "cacheTag": sys.implementation.cache_tag,
                  "magic": importlib.util.MAGIC_NUMBER.hex()}))
"""


def pyc_source(path: str) -> tuple[str, str] | None:
    """``(source relative to /srv, cache tag)`` of a bytecode path under ``/srv``."""
    found = _PYC.fullmatch(path)
    if found is None:
        return None
    return f"{found.group('dir')}{found.group('stem')}.py", found.group("tag")


def _docker(argv: list[str], stdin: bytes | None = None) -> subprocess.CompletedProcess[bytes]:
    return run(argv, env=os_environment(names=DOCKER_NAMES), stdin=stdin)


def compile_in_base(base: str, platform: str, sources: dict[str, bytes]) -> dict[str, Any]:
    """The checked-hash compile of each of *sources*, by the interpreter of the image *base*."""
    payload = json.dumps({name: base64.b64encode(data).decode() for name, data in sources.items()})
    out = require(
        _docker(
            ["docker", "run", *_SEALED, "--platform", platform, "--entrypoint", "python3", base,
             "-I", "-S", "-c", _COMPILE],
            payload.encode(),
        ),
        f"compiling the tree's sources with the interpreter of {base}",
    )
    layers = require(
        _docker(["docker", "image", "inspect", "--format", "{{json .RootFS.Layers}}", base]),
        f"reading the layers of {base}",
    )
    return {**json.loads(out), "diffIds": json.loads(layers)}


def image_task(payload: dict[str, Any]) -> dict[str, Any]:
    """Read one image as data and answer every bytecode file with the base's compile."""
    host = payload["repository"].split("/", 1)[0]
    credentials = tuple(payload["credentials"]) if payload.get("credentials") else None
    registry = Registry(egress_getter(host, http=payload["http"]), http=payload["http"], credentials=credentials)
    digest, manifest, config = registry.image(payload["repository"], payload["digest"], payload["platform"])
    nodes, texts = read_filesystem(registry, payload["repository"], manifest)
    srv = {path: node.as_data() for path, node in sorted(nodes.items()) if path.startswith("srv/")}
    tree = pathlib.Path(payload["tree"])
    sources = {
        source: (tree / source).read_bytes()
        for path in srv
        if path.startswith(tuple(f"srv/{root}/" for root in SOURCE_ROOTS))
        and (found := pyc_source(path))
        and (source := found[0])
        and (tree / source).is_file()
    }
    compiled: dict[str, Any] = {"files": {}, "cacheTag": "", "magic": "", "diffIds": []}
    if sources and payload.get("base"):
        compiled = compile_in_base(payload["base"], payload["platform"], sources)
    return {
        "digest": digest,
        "configDigest": manifest["config"]["digest"],
        "config": config,
        "nodes": srv,
        "texts": {path: body for path, body in sorted(texts.items()) if path.startswith("srv/")},
        "compiled": compiled,
    }


def _egress(url: str, limit: int) -> Any:
    """A declared client for exactly *url*'s host: HTTPS, or HTTP on this machine's loopback."""
    from terp.capabilities.egress import EgressClient, EgressPolicy

    parts = urllib.parse.urlsplit(url)
    local = parts.hostname in ("localhost", "127.0.0.1")
    return EgressClient(
        EgressPolicy(
            allowed_hosts=(parts.hostname or "",),
            timeout_seconds=60.0,
            max_response_bytes=limit,
            allow_private_addresses=local,
            allowed_schemes=("http", "https") if local else ("https",),
        )
    )


def scan_task(payload: dict[str, Any]) -> dict[str, Any]:
    """Each package URL asked of OSV's batch API; the vulnerability ids it answers, per package."""
    from terp.capabilities.egress import EgressFailedError, EgressRefusedError

    url = payload["osv"].rstrip("/") + "/v1/querybatch"
    client = _egress(url, 64 * 1024 * 1024)
    purls = list(payload["purls"])
    found: dict[str, list[str]] = {}
    for start in range(0, len(purls), 500):
        chunk = purls[start : start + 500]
        body = json.dumps({"queries": [{"package": {"purl": purl}} for purl in chunk]}).encode()
        try:
            answer = client.post(url, body=body, headers={"Content-Type": "application/json"})
        except (EgressFailedError, EgressRefusedError) as exc:
            raise ReleaseError("the vulnerability database could not be asked", cause=str(exc.log_context)) from exc
        if answer.status_code != 200:
            raise ReleaseError(f"the vulnerability database answered {answer.status_code}")
        results = json.loads(answer.content).get("results", [])
        if len(results) != len(chunk):
            raise ReleaseError("the vulnerability database answered for other packages than asked")
        for purl, result in zip(chunk, results, strict=True):
            ids = sorted(str(vuln["id"]) for vuln in (result or {}).get("vulns", []))
            if ids:
                found[purl] = ids
    return {"database": payload["osv"], "queried": len(purls), "vulnerable": found}


def secrets_task(payload: dict[str, Any]) -> dict[str, Any]:
    """gitleaks over the history reachable from the SHA, and what it found, redacted."""
    gitleaks = payload["gitleaks"]
    git_dir = require(
        run(["git", "-C", payload["repo"], "rev-parse", "--absolute-git-dir"]), "finding the git directory"
    ).decode().strip()
    version = run([gitleaks, "version"])
    with tempfile.TemporaryDirectory(prefix="terp-secrets-") as scratch:
        report = pathlib.Path(scratch) / "report.json"
        argv = [
            gitleaks, "detect", "--no-banner", "--redact", "--exit-code", "0",
            "--source", git_dir, f"--log-opts={payload['sha']}",
            "--report-format", "json", "--report-path", str(report),
        ]
        if payload.get("ignore") is not None:
            ignore = pathlib.Path(scratch) / ".gitleaksignore"
            ignore.write_text(payload["ignore"], encoding="utf-8")
            argv += ["--gitleaks-ignore-path", str(ignore)]
        require(run(argv), "scanning the history for secrets")
        try:
            found = json.loads(report.read_text(encoding="utf-8") or "[]")
        except (OSError, ValueError) as exc:
            raise ReleaseError("gitleaks wrote no report", cause=str(exc)) from exc
    return {
        "tool": "gitleaks",
        "version": output_of(version) if version.returncode == 0 else "",
        "findings": sorted(
            ({"rule": str(item.get("RuleID", "")), "file": str(item.get("File", "")),
              "commit": str(item.get("Commit", ""))} for item in found),
            key=lambda item: (item["commit"], item["file"], item["rule"]),
        ),
    }


TASKS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "image": image_task,
    "scan": scan_task,
    "secrets": secrets_task,
}


def sandboxed(task: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Run *task* in its own process, handed *payload* and nothing of the signer's."""
    with tempfile.TemporaryDirectory(prefix="terp-sandbox-") as scratch:
        completed = run(
            [sys.executable, "-I", "-m", MODULE, task],
            cwd=scratch,
            env=os_environment(names=DOCKER_NAMES),
            stdin=canonical(payload),
        )
    if completed.returncode != 0:
        raise ReleaseError(f"the sandbox's {task} task refused", cause=output_of(completed)[-4000:])
    try:
        answer = json.loads(completed.stdout)
    except ValueError as exc:
        raise ReleaseError(f"the sandbox's {task} task answered no JSON") from exc
    if not isinstance(answer, dict):
        raise ReleaseError(f"the sandbox's {task} task answered no JSON object")
    return answer


def main(argv: list[str] | None = None, stdin: BinaryIO | None = None, stdout: TextIO | None = None) -> int:
    """The sandbox process: one task, its input on stdin, its answer on stdout."""
    args = sys.argv[1:] if argv is None else argv
    source = stdin if stdin is not None else sys.stdin.buffer
    sink = stdout if stdout is not None else sys.stdout
    if len(args) != 1 or args[0] not in TASKS:
        sys.stderr.write(f"usage: python -m {MODULE} {{{','.join(sorted(TASKS))}}}\n")
        return 2
    try:
        answer = TASKS[args[0]](json.loads(source.read()))
    except ReleaseError as exc:
        sys.stderr.write(f"{exc}\n")
        return 1
    sink.write(canonical(answer).decode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["MODULE", "SOURCE_ROOTS", "TASKS", "compile_in_base", "main", "pyc_source", "sandboxed"]
