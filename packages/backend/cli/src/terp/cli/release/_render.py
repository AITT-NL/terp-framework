"""The ``terp-arch`` the commit pins: fetched by hash, read as data, its generator run apart.

``sign`` is the operator's newest toolchain, never the version the commit pins, so the app does
not choose its own verifier (ADR 0187 decision 6). Two facts still belong to the pinned
release, and this module gets them without letting that release near the signer:

* **what the app's declaration was written against**: the Terp Standard release its
  ``terp-arch`` mirrors, that schema's SHA-256, and the datastore table its kind units resolve
  in. They are read from the wheel's files as data (a zip archive), never imported;
* **what the generator renders**, in the generated state: the pinned ``terp-arch`` runs in a
  process of its own (``python -I -S``), with nothing on its path but that wheel and PyYAML, over
  the commit's tree written out as files, and answers with the files as bytes.

The wheel comes from a fixed index (or a directory of wheels the operator names) and is refused
unless its SHA-256 is the one the signer's release table carries for that version, a table the
signer image ships for every ``terp-arch`` release from :data:`FLOOR` up. A version the table
does not carry, or one below the floor, is refused by name: the signer is updated before an app
can release on a newer framework (ADR 0187 decision 9, a release-train item).
"""

from __future__ import annotations

import base64
import hashlib
import json
import pathlib
import re
import shutil
import sys
import urllib.parse
import zipfile
from dataclasses import dataclass
from typing import Any

from terp.cli.release._common import ReleaseError, os_environment, read_document, require, run

#: The first ``terp-arch`` release this signer reads: the first that renders a generated app.
FLOOR = "0.35.0"

#: Where the signer image carries its release table, and where it fetches wheels from.
DEFAULT_TABLE = "/etc/terp/terp-arch-releases.json"
DEFAULT_INDEX = "https://pypi.org/simple/"
TABLE_DOCUMENT = "terpArchReleases"

_SPEC_LINE = re.compile(r'^SPEC_RELEASE = "(?P<release>[0-9]+(?:\.[0-9]+)*)"\r?$', re.MULTILINE)
_READER = "terp/arch/deployment/reader.py"
_SCHEMA = "terp/arch/deployment/deployment-declaration.schema.json"
_DATASTORES = "terp/arch/deployment/datastore-table.json"
_WHEEL_LIMIT = 64 * 1024 * 1024


def version_key(version: str) -> tuple[int, ...]:
    """A release number as a tuple to compare; refused when it is not one."""
    if re.fullmatch(r"[0-9]+(?:\.[0-9]+)*", version) is None:
        raise ReleaseError(f"{version!r} is not a release number this signer compares")
    return tuple(int(part) for part in version.split("."))


@dataclass(frozen=True)
class Pinned:
    """The pinned ``terp-arch``: its wheel on disk, and what its files say."""

    version: str
    wheel: pathlib.Path
    spec: str
    schema_sha256: str
    datastores: dict[str, Any]


def table_entry(path: str | pathlib.Path, version: str) -> tuple[str, str]:
    """``(wheel file name, SHA-256)`` the signer's release table carries for *version*."""
    if version_key(version) < version_key(FLOOR):
        raise ReleaseError(
            f"the commit pins terp-arch {version}, below {FLOOR}, the first release this signer "
            "reads: release on a framework version from the floor up"
        )
    table = read_document(path, TABLE_DOCUMENT)
    entry = table.get("releases", {}).get(version)
    if not isinstance(entry, dict) or not isinstance(entry.get("wheel"), str) or not re.fullmatch(
        r"[0-9a-f]{64}", str(entry.get("sha256", ""))
    ):
        raise ReleaseError(
            f"this signer's release table carries no terp-arch {version}: update the signer "
            "image to one that knows the release before releasing on it"
        )
    return entry["wheel"], entry["sha256"]


def _download(index: str, name: str, scratch: pathlib.Path) -> bytes:
    from terp.cli.release._sandbox import _egress

    if pathlib.Path(index).is_dir():
        candidate = pathlib.Path(index) / name
        if not candidate.is_file():
            raise ReleaseError(f"{index} holds no {name}")
        return candidate.read_bytes()
    from terp.capabilities.egress import EgressFailedError, EgressRefusedError

    page = urllib.parse.urljoin(index.rstrip("/") + "/", "terp-arch/")
    try:
        listing = _egress(page, 8 * 1024 * 1024).get(
            page, headers={"Accept": "application/vnd.pypi.simple.v1+json"}
        )
        files = json.loads(listing.content).get("files", []) if listing.status_code == 200 else []
        url = next((item["url"] for item in files if item.get("filename") == name), None)
        if url is None:
            raise ReleaseError(f"the index {index} lists no {name}")
        url = urllib.parse.urljoin(page, url)
        wheel = _egress(url, _WHEEL_LIMIT).get(url)
    except (EgressFailedError, EgressRefusedError) as exc:
        raise ReleaseError(f"the index {index} could not be read", cause=str(exc.log_context)) from exc
    if wheel.status_code != 200:
        raise ReleaseError(f"the index answered {wheel.status_code} for {name}")
    return wheel.content


def fetch(table: str | pathlib.Path, index: str, version: str, scratch: pathlib.Path) -> Pinned:
    """The pinned ``terp-arch`` *version*, hash-checked, and the facts its files hold."""
    name, expected = table_entry(table, version)
    data = _download(index, name, scratch)
    if hashlib.sha256(data).hexdigest() != expected:
        raise ReleaseError(f"{name} is not the wheel this signer's release table pins (its SHA-256 differs)")
    wheel = scratch / name
    wheel.write_bytes(data)
    with zipfile.ZipFile(wheel) as archive:
        try:
            reader = archive.read(_READER).decode("utf-8")
            schema = archive.read(_SCHEMA)
            datastores = json.loads(archive.read(_DATASTORES))
        except (KeyError, ValueError) as exc:
            raise ReleaseError(f"{name} holds no deployment reader this signer can read", cause=str(exc)) from exc
    found = _SPEC_LINE.search(reader)
    if found is None:
        raise ReleaseError(f"{name} names no Terp Standard release its declaration reader mirrors")
    return Pinned(version, wheel, found.group("release"), hashlib.sha256(schema).hexdigest(), datastores)


#: The render, run by the pinned ``terp-arch`` on nothing but itself and PyYAML.
_RENDER = """\
import base64, json, pathlib, sys
sys.path[:0] = [sys.argv[1], sys.argv[2]]
from terp.arch.deployment import Declaration, published_tables, readable
from terp.arch.deployment.generator import FRONTEND_LOCK, OWNED_PATHS, generate
from terp.arch.deployment.render_check import project_name
root = pathlib.Path(sys.argv[3])
declared, found = readable(root)
name, missing = project_name(root)
refused = [finding.message for finding in [*found, *missing]]
files = {}
if not refused and isinstance(declared, Declaration):
    files, refusals = generate(declared, name, tables=published_tables(),
                               frontend_lock=(root / FRONTEND_LOCK).is_file())
    refused = [finding.message for finding in refusals]
print(json.dumps({"owned": list(OWNED_PATHS), "refused": refused,
                  "files": {path: base64.b64encode(data).decode() for path, data in files.items()}}))
"""


def _safe_extract(wheel: pathlib.Path, destination: pathlib.Path) -> None:
    with zipfile.ZipFile(wheel) as archive:
        for member in archive.namelist():
            target = (destination / member).resolve()
            if not target.is_relative_to(destination.resolve()):
                raise ReleaseError(f"{wheel.name} holds {member}, which would land outside it")
        archive.extractall(destination)


def render(pinned: Pinned, tree: pathlib.Path, scratch: pathlib.Path) -> tuple[dict[str, bytes], list[str], list[str]]:
    """``(files, owned paths, refusals)``: what the pinned generator renders of *tree*."""
    import yaml

    arch = scratch / "terp-arch"
    _safe_extract(pinned.wheel, arch)
    library = scratch / "pyyaml"
    shutil.copytree(pathlib.Path(yaml.__file__).parent, library / "yaml")
    out = require(
        run(
            [sys.executable, "-I", "-S", "-c", _RENDER, str(arch), str(library), str(tree)],
            cwd=scratch,
            env=os_environment(),
        ),
        f"rendering with terp-arch {pinned.version}",
    )
    answer = json.loads(out)
    files = {path: base64.b64decode(data) for path, data in answer["files"].items()}
    return files, list(answer["owned"]), list(answer["refused"])


__all__ = [
    "DEFAULT_INDEX",
    "DEFAULT_TABLE",
    "FLOOR",
    "Pinned",
    "TABLE_DOCUMENT",
    "fetch",
    "render",
    "table_entry",
    "version_key",
]
