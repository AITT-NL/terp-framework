"""What the ``terp maintenance`` tests build: an app's locks, a signed bundle, an advisory set."""

from __future__ import annotations

import hashlib
import json
import pathlib

from terp.cli.release._common import canonical
from terp.cli.release.manifest import sbom
from tests.architecture.osv_fixtures import FakeOSV, affected

#: A lock with the shapes the report must tell apart: the project itself, two packages from the
#: public index, one from a private index, one from git, and one entry with no version.
UV_LOCK = """\
version = 1
requires-python = ">=3.13"

[[package]]
name = "demo"
version = "0.1.0"
source = { editable = "." }

[[package]]
name = "Jinja2"
version = "2.11.2"
source = { registry = "https://pypi.org/simple" }

[[package]]
name = "markupsafe"
version = "2.0.1"
source = { registry = "https://pypi.org/simple" }

[[package]]
name = "internal-lib"
version = "3.1.0"
source = { registry = "https://pkgs.example.com/simple" }

[[package]]
name = "forked"
version = "1.0"
source = { git = "https://example.com/forked.git" }

[[package]]
name = "nameless-version"
source = { registry = "https://pypi.org/simple" }
"""

#: Where npm's public registry serves a tarball, as an npm lock records it.
NPMJS = "https://registry.npmjs.org"


def npm_lock(*entries: tuple[str, dict], direct: tuple[str, ...] = ()) -> str:
    """An npm lock: the workspace's own entry naming *direct*, then *entries*."""
    root = {"name": "web", "dependencies": {name: "*" for name in direct}}
    return json.dumps({"lockfileVersion": 3, "packages": {"": root, **dict(entries)}})


def tarball(name: str, version: str) -> str:
    return f"{NPMJS}/{name}/-/{name.rsplit('/', 1)[-1]}-{version}.tgz"


def write_app(root: pathlib.Path, *, uv: str | None = UV_LOCK, npm: str | None = None) -> pathlib.Path:
    """An app at *root*: its pyproject.toml, *uv* as its uv.lock and *npm* as frontend's lock."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "pyproject.toml").write_text('[project]\nname = "demo"\nversion = "0.1.0"\n', encoding="utf-8")
    if uv is not None:
        (root / "uv.lock").write_text(uv, encoding="utf-8")
    if npm is not None:
        (root / "frontend").mkdir(exist_ok=True)
        (root / "frontend/package.json").write_text('{"name": "web"}', encoding="utf-8")
        (root / "frontend/package-lock.json").write_text(npm, encoding="utf-8")
    return root


def write_bundle(
    directory: pathlib.Path,
    images: dict[str, tuple[list[tuple[str, str]], str, dict]],
    *,
    tamper: str | None = None,
    database: str | None = None,
) -> pathlib.Path:
    """A bundle as ``sign`` writes one: each SBOM, and a manifest recording its digest."""
    directory.mkdir(parents=True)
    outputs: dict = {}
    for name, (packages, ecosystem, vulnerabilities) in images.items():
        data = canonical(sbom(name, "v1.2.0", packages, ecosystem))
        (directory / f"sbom-{name.replace('/', '_')}.cdx.json").write_bytes((b"[]" if name == tamper else data) + b"\n")
        outputs[name] = {"sbom": hashlib.sha256(data).hexdigest(), "tag": "v1.2.0", "vulnerabilities": vulnerabilities}
    manifest = {"schemaVersion": 1, "outputs": {"images": outputs}}
    if database is not None:
        manifest["outputs"]["vulnerabilityDatabase"] = database
    (directory / "release.manifest.json").write_bytes(canonical(manifest) + b"\n")
    return directory


def advisories() -> FakeOSV:
    """The advisory set most tests ask: aliases to group, a withdrawn advisory, one with no fix."""
    database = FakeOSV()
    jinja = [affected("PyPI", "jinja2", {"introduced": "0"}, {"fixed": "3.1.6"})]
    database.add("GHSA-a", ["pkg:pypi/jinja2@2.11.2"], aliases=["CVE-1", "PYSEC-1"], summary="sandbox escape",
                 database_specific={"severity": "HIGH"}, affected=jinja)
    database.add("PYSEC-1", ["pkg:pypi/jinja2@2.11.2"], aliases=["CVE-1"], affected=jinja)
    database.add("PYSEC-2", ["pkg:pypi/jinja2@2.11.2"], aliases=["CVE-2"], affected=[affected("PyPI", "jinja2", {"fixed": "2.11.3"})])
    database.add("GHSA-b", ["pkg:pypi/jinja2@2.11.2"], aliases=["CVE-2"], database_specific={"severity": ""})
    database.add("GHSA-withdrawn", ["pkg:pypi/jinja2@2.11.2"], withdrawn="2026-01-01T00:00:00Z")
    database.add("GHSA-c", ["pkg:npm/lodash@4.17.15"], summary="", affected=[affected("npm", "lodash", {"fixed": "4.18.0"})])
    database.add("GHSA-nofix", ["pkg:npm/%40scope/pkg@1.0.0"], affected=[affected("npm", "@scope/pkg", {"introduced": "0"})])
    database.add("GHSA-only-withdrawn", ["pkg:pypi/markupsafe@2.0.1"], withdrawn="2026-01-01T00:00:00Z")
    database.add("GHSA-private", ["pkg:pypi/internal-lib@3.1.0"], affected=[affected("PyPI", "internal-lib", {"fixed": "3.2"})])
    return database
