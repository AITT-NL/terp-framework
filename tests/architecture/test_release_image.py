"""An image read from a registry as data: every answer held to its digest (ADR 0187 d6).

A registry is a :data:`Getter`; here an in-memory one serves manifests and blobs, answers a
token challenge, redirects a blob the way a blob store does, and lies when a test asks it to.
The layers are real tar archives, with whiteouts, an opaque directory and a hard link.
"""

from __future__ import annotations

import base64
import gzip
import hashlib
import io
import json
import re
import tarfile

import pytest

from terp.cli.release import _image, _registry
from terp.cli.release._common import ReleaseError
from terp.cli.release._registry import Registry, Response

OCI_MANIFEST = "application/vnd.oci.image.manifest.v1+json"
OCI_INDEX = "application/vnd.oci.image.index.v1+json"
GZIP_LAYER = "application/vnd.oci.image.layer.v1.tar+gzip"


def digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def layer(*entries: tuple) -> bytes:  # type: ignore[type-arg]
    """A gzipped tar: (path, bytes) files, (path, None) directories, (path, "->target") links."""
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w") as archive:
        for path, data, *kind in entries:
            info = tarfile.TarInfo(path)
            if data is None:
                info.type = tarfile.DIRTYPE
                archive.addfile(info)
            elif isinstance(data, str):
                info.type = tarfile.LNKTYPE if kind == ["hard"] else tarfile.SYMTYPE
                info.linkname = data
                archive.addfile(info)
            elif kind == ["fifo"]:
                info.type = tarfile.FIFOTYPE
                archive.addfile(info)
            else:
                info.size = len(data)
                archive.addfile(info, io.BytesIO(data))
    return gzip.compress(raw.getvalue(), mtime=0)


class FakeRegistry:
    """An OCI registry in memory, behind one :data:`Getter`."""

    def __init__(self) -> None:
        self.blobs: dict[str, bytes] = {}
        self.manifests: dict[str, tuple[str, bytes]] = {}
        self.tags: dict[str, str] = {}
        self.repo_tags: dict[tuple[str, str], str] = {}
        self.token: str | None = None
        self.redirect = False
        self.requests: list[tuple[str, dict]] = []

    def push_image(self, layers: list[bytes], config: dict | None = None, tag: str | None = None) -> str:
        cfg = json.dumps(config or {"architecture": "amd64", "os": "linux", "rootfs": {"diff_ids": []}}).encode()
        self.blobs[digest(cfg)] = cfg
        for blob in layers:
            self.blobs[digest(blob)] = blob
        manifest = json.dumps({
            "mediaType": OCI_MANIFEST,
            "config": {"digest": digest(cfg)},
            "layers": [{"mediaType": GZIP_LAYER, "digest": digest(blob)} for blob in layers],
        }).encode()
        self.manifests[digest(manifest)] = (OCI_MANIFEST, manifest)
        if tag:
            self.tags[tag] = digest(manifest)
        return digest(manifest)

    def __call__(self, url: str, headers: dict, limit: int) -> Response:
        self.requests.append((url, headers))
        if url.startswith("https://auth.example/"):
            return Response(200, {}, json.dumps({"token": "t0k"}).encode())
        if url.startswith("https://blobs.example/"):
            return Response(200, {}, self.blobs[url.rsplit("/", 1)[1]])
        if self.token and headers.get("Authorization") != f"Bearer {self.token}":
            return Response(401, {"www-authenticate": 'Bearer realm="https://auth.example/token",service="reg"'}, b"")
        found = re.search(r"/v2/(?P<repo>.+)/(?P<kind>manifests|blobs)/(?P<name>[^/]+)$", url)
        assert found is not None, url
        kind, name = found.group("kind"), found.group("name")
        if kind == "manifests":
            name = self.repo_tags.get((found.group("repo"), name)) or self.tags.get(name, name)
            found = self.manifests.get(name)
            return Response(404, {}, b"") if found is None else Response(200, {"content-type": found[0]}, found[1])
        if name not in self.blobs:
            return Response(404, {}, b"")
        if self.redirect:
            return Response(307, {"location": f"https://blobs.example/{name}"}, b"")
        return Response(200, {}, self.blobs[name])


REPO = "registry.example/rel/app"


def test_an_image_is_its_manifest_config_and_layers_each_held_to_a_digest() -> None:
    fake = FakeRegistry()
    pushed = fake.push_image([layer(("srv/app/x.py", b"x = 1\n"))], tag="r1")
    registry = Registry(fake)
    found, manifest, config = registry.image(REPO, pushed, "linux/amd64")
    assert found == pushed and config["os"] == "linux"
    assert registry.manifest(REPO, "r1")[0] == pushed
    nodes, _texts = _image.read_filesystem(registry, REPO, manifest)
    assert nodes["srv/app/x.py"].sha256 == hashlib.sha256(b"x = 1\n").hexdigest()


def test_a_registry_that_answers_other_bytes_is_refused() -> None:
    fake = FakeRegistry()
    pushed = fake.push_image([layer(("a", b"1"))])
    registry = Registry(fake)
    media, body = fake.manifests[pushed]
    fake.manifests[pushed] = (media, body + b" ")
    with pytest.raises(ReleaseError, match="answered sha256:.* for the manifest"):
        registry.manifest(REPO, pushed)
    fake.manifests[pushed] = (media, body)
    blob = json.loads(body)["layers"][0]["digest"]
    fake.blobs[blob] = b"tampered"
    with pytest.raises(ReleaseError, match="answered other bytes for the blob"):
        registry.blob(REPO, blob)
    with pytest.raises(ReleaseError, match="has no blob"):
        registry.blob(REPO, "sha256:" + "0" * 64)
    with pytest.raises(ReleaseError, match="is not a sha256 digest"):
        registry.blob(REPO, "md5:abc")
    with pytest.raises(ReleaseError, match="has no manifest"):
        registry.manifest(REPO, "missing")
    fake.manifests["sha256:" + "9" * 64] = (OCI_MANIFEST, b"not json")
    fake.tags["broken"] = "sha256:" + "9" * 64
    with pytest.raises(ReleaseError, match="is not JSON"):
        registry.manifest(REPO, "broken")


def test_an_index_is_resolved_by_platform_and_anything_else_refused() -> None:
    fake = FakeRegistry()
    amd = fake.push_image([layer(("a", b"1"))])
    index = json.dumps({"mediaType": OCI_INDEX, "manifests": [
        {"digest": amd, "platform": {"os": "linux", "architecture": "amd64"}},
        {"digest": "sha256:" + "8" * 64, "platform": {"os": "linux", "architecture": "arm64"}},
    ]}).encode()
    fake.manifests[digest(index)] = (OCI_INDEX, index)
    registry = Registry(fake)
    assert registry.image(REPO, digest(index), "linux/amd64")[0] == amd
    with pytest.raises(ReleaseError, match="holds 0 images for linux/s390x"):
        registry.image(REPO, digest(index), "linux/s390x")
    other = json.dumps({"mediaType": "application/vnd.oci.artifact.manifest.v1+json"}).encode()
    fake.manifests[digest(other)] = ("x", other)
    with pytest.raises(ReleaseError, match="is a application/vnd.oci.artifact"):
        registry.image(REPO, digest(other), "linux/amd64")


def test_a_token_challenge_and_a_blob_store_redirect_are_followed() -> None:
    fake = FakeRegistry()
    pushed = fake.push_image([layer(("a", b"1"))])
    fake.token, fake.redirect = "t0k", True
    registry = Registry(fake, credentials=("user", "secret"))
    _found, manifest, _config = registry.image(REPO, pushed, "linux/amd64")
    _image.read_filesystem(registry, REPO, manifest)
    [token] = [(url, headers) for url, headers in fake.requests if url.startswith("https://auth.example/")]
    assert "scope=repository%3Arel%2Fapp%3Apull" in token[0]
    assert token[1]["Authorization"] == "Basic " + base64.b64encode(b"user:secret").decode()
    assert any(url.startswith("https://blobs.example/") for url, _ in fake.requests)
    blob_hops = [headers for url, headers in fake.requests if url.startswith("https://blobs.example/")]
    assert all("Authorization" not in headers for headers in blob_hops), "no credential follows a redirect"


def test_the_token_service_and_a_basic_challenge_are_held_to_their_answers() -> None:
    calls: list[tuple[str, dict]] = []

    def basic(url, headers, limit):  # type: ignore[no-untyped-def]
        calls.append((url, headers))
        if headers.get("Authorization", "").startswith("Basic "):
            return Response(404, {}, b"")
        return Response(401, {"www-authenticate": 'Basic realm="reg"'}, b"")

    with pytest.raises(ReleaseError, match="has no manifest"):
        Registry(basic, credentials=("u", "p")).manifest(REPO, "r1")
    assert calls[-1][1]["Authorization"].startswith("Basic ")

    def challenge(realm: str, token_answer: Response):  # type: ignore[no-untyped-def]
        def get(url, headers, limit):  # type: ignore[no-untyped-def]
            if url.startswith(realm.split("?")[0]) and "/v2/" not in url:
                return token_answer
            return Response(401, {"www-authenticate": f'Bearer realm="{realm}"'}, b"")
        return get

    with pytest.raises(ReleaseError, match="which is no HTTPS realm"):
        Registry(challenge("http://auth.example/t", Response(200, {}, b""))).manifest(REPO, "r1")
    with pytest.raises(ReleaseError, match="token service answered 500"):
        Registry(challenge("https://auth.example/t", Response(500, {}, b""))).manifest(REPO, "r1")
    with pytest.raises(ReleaseError, match="answered no token"):
        Registry(challenge("https://auth.example/t", Response(200, {}, b"{}"))).manifest(REPO, "r1")
    with pytest.raises(ReleaseError, match="has no manifest"):
        Registry(challenge("https://auth.example/t", Response(200, {}, b'{"access_token": "a"}'))).manifest(REPO, "r1")


def test_a_reference_names_its_registry() -> None:
    assert _registry.Reference.parse("localhost/x") == _registry.Reference("localhost", "x")
    assert _registry.Reference.parse("127.0.0.1:5000/rel/x").host == "127.0.0.1:5000"
    for wrong in ("x", "library/x", "registry.example"):
        with pytest.raises(ReleaseError, match="names no registry host"):
            _registry.Reference.parse(wrong)


def test_the_egress_getter_is_a_declared_client_per_host(monkeypatch) -> None:
    from terp.capabilities import egress

    made: list = []

    class Client:
        def __init__(self, policy):  # type: ignore[no-untyped-def]
            made.append(policy)

        def get(self, url, headers=None):  # type: ignore[no-untyped-def]
            if "refuse" in url:
                raise egress.EgressRefusedError("no", log_context={"reason": "host_not_allowed"})
            return egress.EgressResponse(200, {"Content-Type": "x"}, b"body")

    monkeypatch.setattr(egress, "EgressClient", Client)
    get = _registry.egress_getter("127.0.0.1:5000", http=True)
    answer = get("http://127.0.0.1:5000/v2/x/manifests/r1", {}, 10)
    assert answer == Response(200, {"content-type": "x"}, b"body")
    get("http://127.0.0.1:5000/v2/x/blobs/y", {}, 10)
    assert len(made) == 1, "one client per host"
    assert made[0].allowed_hosts == ("127.0.0.1",) and made[0].allowed_schemes == ("http",)
    assert made[0].allow_private_addresses is True
    get("https://blobs.example/x", {}, 10)
    assert made[1].allowed_schemes == ("https",) and made[1].allow_private_addresses is False
    with pytest.raises(ReleaseError, match="could not be read at refuse.example"):
        get("https://refuse.example/x", {}, 10)


def test_a_layer_is_read_under_the_layer_s_limit_after_a_manifest(monkeypatch) -> None:
    """The sandbox reads a manifest (4 MB at most), then the layers (1 GB) from one registry. A
    client made for the first request held every later one to the manifest's limit, so the
    signer's first run against a real registry refused the image's 30 MB base layer."""
    from terp.capabilities import egress

    class Client:
        def __init__(self, policy):  # type: ignore[no-untyped-def]
            self.policy = policy

        def get(self, url, headers=None):  # type: ignore[no-untyped-def]
            body = b"x" * (64 if "/blobs/" in url else 8)
            if len(body) > self.policy.max_response_bytes:
                raise egress.EgressFailedError("larger", log_context={"limit": self.policy.max_response_bytes})
            return egress.EgressResponse(200, {}, body)

    monkeypatch.setattr(egress, "EgressClient", Client)
    get = _registry.egress_getter("127.0.0.1:5000", http=True)
    assert get("http://127.0.0.1:5000/v2/x/manifests/r1", {}, 16).body == b"x" * 8
    assert get("http://127.0.0.1:5000/v2/x/blobs/sha256:y", {}, 128).body == b"x" * 64
    with pytest.raises(ReleaseError, match="could not be read"):
        get("http://127.0.0.1:5000/v2/x/blobs/sha256:z", {}, 32)


def test_without_the_egress_capability_no_registry_is_read(monkeypatch) -> None:
    import sys

    monkeypatch.setitem(sys.modules, "terp.capabilities.egress", None)
    with pytest.raises(ReleaseError, match="needs the egress capability"):
        _registry.egress_getter("r.example", http=False)


# --------------------------------------------------------------------------- the layers
def test_layers_apply_as_an_engine_unpacks_them() -> None:
    state: dict = {}
    texts: dict = {}
    record = b"app/x.py,sha256=" + base64.urlsafe_b64encode(hashlib.sha256(b"x").digest()).rstrip(b"=") + b",1\n"
    metadata_path = "srv/.venv/lib/python3.14/site-packages/app-1.dist-info/METADATA"
    for blob in (
        layer(("srv", None), ("srv/keep.txt", b"keep"), ("srv/gone.txt", b"gone"), ("srv/dir/a", b"a"),
              ("srv/opaque/old", b"old"), ("srv/link", "keep.txt"), (metadata_path, b"Name: app\nVersion: 1\n\nbody")),
        layer(("srv/.wh.gone.txt", b""), ("srv/.wh.dir", b""), ("srv/opaque/.wh..wh..opq", b""),
              ("srv/opaque/new", b"new"), ("srv/hard", "srv/keep.txt", "hard"), ("srv/pipe", b"", "fifo"),
              ("srv/hardmeta", metadata_path, "hard"), ("./srv/rec/RECORD", record)),
    ):
        with _image._open(blob, GZIP_LAYER) as archive:
            _image.apply_layer(state, texts, archive)
    assert "srv/gone.txt" not in state and "srv/dir/a" not in state and "srv/opaque/old" not in state
    assert state["srv/opaque/new"].sha256 == hashlib.sha256(b"new").hexdigest()
    assert state["srv/hard"] == state["srv/keep.txt"]
    assert state["srv/link"] == _image.Node("link", target="keep.txt")
    assert state["srv/pipe"].kind == "other" and state["srv"].kind == "dir"
    assert _image.metadata(texts[metadata_path]) == ("app", "1")
    assert texts["srv/hardmeta"] == texts[metadata_path]
    assert _image.Node.from_data(state["srv/keep.txt"].as_data()) == state["srv/keep.txt"]
    assert _image.record(record.decode() + "app/y.py,,\n\napp/z.py,sha256=x,1\n") == [
        ("app/x.py", hashlib.sha256(b"x").hexdigest()), ("app/y.py", ""), ("app/z.py", "")
    ], "a hash a RECORD cannot decode is no hash, never a crash"


def test_an_opaque_root_empties_everything_below_and_a_dangling_hard_link_is_refused() -> None:
    state = {"a": _image.Node("file", "1", 1)}
    texts = {"a": "x"}
    with _image._open(layer((".wh..wh..opq", b""), ("b", b"b")), GZIP_LAYER) as archive:
        _image.apply_layer(state, texts, archive)
    assert set(state) == {"b"} and texts == {}
    with _image._open(layer(("c", "nowhere", "hard")), GZIP_LAYER) as archive, pytest.raises(ReleaseError, match="which no layer holds"):
        _image.apply_layer(state, texts, archive)


def test_an_uncompressed_layer_is_read_and_another_kind_refused() -> None:
    raw = gzip.decompress(layer(("a", b"1")))
    with _image._open(raw, "application/vnd.oci.image.layer.v1.tar") as archive:
        assert [member.name for member in archive] == ["a"]
    with pytest.raises(ReleaseError, match="cannot be read by this signer"):
        _image._open(raw, "application/vnd.oci.image.layer.v1.tar+zstd")


def test_the_final_base_is_named_through_stage_names_when_pinned() -> None:
    pinned = "python@sha256:" + "a" * 64
    text = (
        "# syntax comment\n"
        f"FROM {pinned} AS runtime\n"
        "FROM --platform=linux/amd64 node:26 AS build\n"
        "RUN echo \\\n  continued\n"
        "FROM runtime\n"
    )
    assert _image.final_base(text) == pinned
    assert _image.final_base("FROM python:3.14-slim\n") is None
    assert _image.final_base("ARG BASE\nFROM ${BASE}\n") is None
    assert _image.final_base("RUN nothing\n") is None
