"""The ``terp-arch`` a commit pins: fetched by hash, read as data, its generator run apart.

ADR 0187 decision 6, step 3. The wheel here is built from this repository's own ``terp-arch``
source, so the render a test asks of it is the generator's, run for real in a process that has
nothing but that wheel and PyYAML on its path.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import zipfile

import pytest

from terp.arch.deployment.reader import SPEC_RELEASE
from terp.cli.release import _render
from terp.cli.release._common import ReleaseError, write_document
from terp.cli.release._git import Tree
from tests.architecture.release_fixtures import REPO_ROOT, TOOLCHAIN, app_files, committed_app

ARCH = REPO_ROOT / "packages" / "backend" / "arch" / "src"
WHEEL = f"terp_arch-{TOOLCHAIN}-py3-none-any.whl"


def build_wheel(directory: pathlib.Path, drop: str | None = None, replace: dict[str, bytes] | None = None) -> pathlib.Path:
    """A wheel of this repository's terp-arch, the way hatch lays one out."""
    directory.mkdir(parents=True, exist_ok=True)
    wheel = directory / WHEEL
    with zipfile.ZipFile(wheel, "w") as archive:
        for path in sorted((ARCH / "terp" / "arch").rglob("*")):
            name = path.relative_to(ARCH).as_posix()
            if path.is_file() and "__pycache__" not in name and name != drop:
                archive.writestr(name, (replace or {}).get(name, path.read_bytes()))
        archive.writestr(f"terp_arch-{TOOLCHAIN}.dist-info/METADATA", f"Name: terp-arch\nVersion: {TOOLCHAIN}\n")
    return wheel


def table(directory: pathlib.Path, wheel: pathlib.Path, version: str = TOOLCHAIN) -> pathlib.Path:
    path = directory / "releases.json"
    write_document(path, {"terpArchReleases": 1, "releases": {version: {
        "wheel": wheel.name, "sha256": hashlib.sha256(wheel.read_bytes()).hexdigest()}}})
    return path


@pytest.fixture(autouse=True)
def _floor(monkeypatch) -> None:
    """This repository's terp-arch is the release being built, still numbered below the floor."""
    monkeypatch.setattr(_render, "FLOOR", TOOLCHAIN)


def test_a_release_number_compares_as_numbers() -> None:
    assert _render.version_key("0.10.0") > _render.version_key("0.9.9")
    with pytest.raises(ReleaseError, match="is not a release number"):
        _render.version_key("1.0rc1")


def test_the_table_carries_the_wheel_of_each_release_from_the_floor_up(tmp_path: pathlib.Path, monkeypatch) -> None:
    wheel = build_wheel(tmp_path / "index")
    releases = table(tmp_path, wheel)
    assert _render.table_entry(releases, TOOLCHAIN) == (WHEEL, hashlib.sha256(wheel.read_bytes()).hexdigest())
    with pytest.raises(ReleaseError, match="carries no terp-arch 9.9.9: update the signer image"):
        _render.table_entry(releases, "9.9.9")
    write_document(releases, {"terpArchReleases": 1, "releases": {TOOLCHAIN: {"wheel": WHEEL, "sha256": "short"}}})
    with pytest.raises(ReleaseError, match="carries no terp-arch"):
        _render.table_entry(releases, TOOLCHAIN)
    monkeypatch.setattr(_render, "FLOOR", "0.35.0")
    with pytest.raises(ReleaseError, match="below 0.35.0, the first release this signer reads"):
        _render.table_entry(releases, "0.34.9")


def test_the_pinned_wheel_is_hash_checked_and_read_as_data(tmp_path: pathlib.Path) -> None:
    wheel = build_wheel(tmp_path / "index")
    releases = table(tmp_path, wheel)
    pinned = _render.fetch(releases, str(tmp_path / "index"), TOOLCHAIN, tmp_path)
    assert pinned.spec == SPEC_RELEASE
    schema = (ARCH / "terp" / "arch" / "deployment" / "deployment-declaration.schema.json").read_bytes()
    assert pinned.schema_sha256 == hashlib.sha256(schema).hexdigest()
    assert pinned.datastores["kinds"]["postgres"]["role"] == "database"
    build_wheel(tmp_path / "index", replace={"terp/arch/__init__.py": b"# a changed wheel\n"})
    with pytest.raises(ReleaseError, match="is not the wheel this signer's release table pins"):
        _render.fetch(releases, str(tmp_path / "index"), TOOLCHAIN, tmp_path)
    (tmp_path / "empty").mkdir()
    with pytest.raises(ReleaseError, match="holds no terp_arch"):
        _render.fetch(releases, str(tmp_path / "empty"), TOOLCHAIN, tmp_path)


@pytest.mark.parametrize(
    ("drop", "replace", "expected"),
    [
        ("terp/arch/deployment/reader.py", None, "holds no deployment reader"),
        (None, {"terp/arch/deployment/reader.py": b"SPEC = 1\n"}, "names no Terp Standard release"),
    ],
)
def test_a_wheel_without_a_reader_is_refused(tmp_path: pathlib.Path, drop, replace, expected) -> None:
    wheel = build_wheel(tmp_path / "index", drop=drop, replace=replace)
    with pytest.raises(ReleaseError, match=expected):
        _render.fetch(table(tmp_path, wheel), str(tmp_path / "index"), TOOLCHAIN, tmp_path)


class _Index:
    """A simple index behind the egress seam: a PEP 691 listing, then the file."""

    def __init__(self, wheel: bytes, listing_status: int = 200, wheel_status: int = 200, files: list | None = None) -> None:
        self.wheel, self.listing_status, self.wheel_status = wheel, listing_status, wheel_status
        self.files = files if files is not None else [{"filename": WHEEL, "url": f"../../files/{WHEEL}"}]
        self.urls: list[str] = []

    def __call__(self, url: str, limit: int):  # type: ignore[no-untyped-def]
        return self

    def get(self, url, headers=None):  # type: ignore[no-untyped-def]
        from terp.capabilities.egress import EgressResponse

        self.urls.append(url)
        if url.endswith("/terp-arch/"):
            return EgressResponse(self.listing_status, {}, json.dumps({"files": self.files}).encode())
        return EgressResponse(self.wheel_status, {}, self.wheel)


def test_the_wheel_comes_from_the_fixed_index(tmp_path: pathlib.Path, monkeypatch) -> None:
    from terp.cli.release import _sandbox

    wheel = build_wheel(tmp_path / "w")
    releases = table(tmp_path, wheel)
    index = _Index(wheel.read_bytes())
    monkeypatch.setattr(_sandbox, "_egress", index)
    assert _render.fetch(releases, "https://index.example/simple", TOOLCHAIN, tmp_path).spec == SPEC_RELEASE
    assert index.urls == ["https://index.example/simple/terp-arch/", f"https://index.example/files/{WHEEL}"]
    for broken, expected in (
        (_Index(b"", listing_status=404), "lists no"),
        (_Index(b"", files=[]), "lists no"),
        (_Index(b"", wheel_status=403), "answered 403"),
    ):
        monkeypatch.setattr(_sandbox, "_egress", broken)
        with pytest.raises(ReleaseError, match=expected):
            _render.fetch(releases, "https://index.example/simple/", TOOLCHAIN, tmp_path)

    class Down(_Index):
        def get(self, url, headers=None):  # type: ignore[no-untyped-def]
            from terp.capabilities.egress import EgressFailedError

            raise EgressFailedError("down", log_context={"host": "index.example"})

    monkeypatch.setattr(_sandbox, "_egress", Down(b""))
    with pytest.raises(ReleaseError, match="could not be read"):
        _render.fetch(releases, "https://index.example/simple/", TOOLCHAIN, tmp_path)


def _pinned(tmp_path: pathlib.Path) -> _render.Pinned:
    wheel = build_wheel(tmp_path / "index")
    return _render.fetch(table(tmp_path, wheel), str(tmp_path / "index"), TOOLCHAIN, tmp_path)


def test_the_pinned_generator_renders_the_tree_in_a_process_of_its_own(tmp_path: pathlib.Path) -> None:
    sha = committed_app(tmp_path / "repo")
    Tree.read(tmp_path / "repo", sha).materialize(tmp_path / "tree")
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    files, owned, refused = _render.render(_pinned(tmp_path), tmp_path / "tree", scratch)
    assert refused == []
    assert owned == ["Dockerfile.prod", "frontend/Dockerfile.prod", "docker-compose.prod.yml"]
    expected = app_files()
    assert files == {path: expected[path] for path in ("Dockerfile.prod", "docker-compose.prod.yml")}


def test_a_declaration_the_pinned_generator_refuses_answers_its_words(tmp_path: pathlib.Path) -> None:
    files = app_files()
    declaration = json.loads(files["deployment.json"])
    declaration["units"].append({"id": "odd", "role": "custom"})
    files["deployment.json"] = json.dumps(declaration).encode()
    sha = committed_app(tmp_path / "repo", files)
    Tree.read(tmp_path / "repo", sha).materialize(tmp_path / "tree")
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    rendered, _owned, refused = _render.render(_pinned(tmp_path), tmp_path / "tree", scratch)
    assert rendered == {} and any("custom" in message for message in refused), refused


def test_a_wheel_that_would_unpack_outside_itself_is_refused(tmp_path: pathlib.Path) -> None:
    wheel = tmp_path / WHEEL
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("../escape.py", "x")
    with pytest.raises(ReleaseError, match="would land outside it"):
        _render._safe_extract(wheel, tmp_path / "out")
