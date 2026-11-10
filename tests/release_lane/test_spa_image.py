"""The generated SPA image on a real Docker engine (ADR 0062, ADR 0187).

The generator's tests hold the text of ``frontend/Dockerfile.prod``. Only an engine shows what
the image serves, so this builds the render for an app with an SPA. The frontend is a few files
and a lock with no package in it, so the build fetches nothing but the two pinned base images,
and the server configuration is the template's own ``frontend/nginx.conf``:

* the image runs as ``nginx``, and its own ``HEALTHCHECK`` turns it healthy;
* only the bundle is served: ``/50x.html`` is the SPA's document, as any path it has no file
  for is, and never the base image's page, which carries an inline style the policy blocks;
* no response names an nginx version, neither the ``Server`` header nor an error page nginx
  writes itself, with the template's ``nginx.conf`` and with one that predates
  ``server_tokens off``: the image sets it at http level on its own.

Selected with ``-m release_lane``, with the rest of the lane; skipped without an engine, and
failed instead where ``TERP_REQUIRE_RELEASE_LANE`` is set.
"""

from __future__ import annotations

import json
import os
import pathlib
import time
import urllib.error
import urllib.request
from collections.abc import Iterator

import pytest

from terp.arch.deployment import reader
from terp.arch.deployment.generator import FRONTEND_DOCKERFILE, generate
from terp.arch.deployment.tables import published_tables
from tests.release_lane import lane as rl

pytestmark = pytest.mark.release_lane

#: A declaration whose render holds the SPA's file: a web unit that names no recipe.
DECLARATION = rl.REPO_ROOT / "tests" / "architecture" / "generator_goldens" / "static-site" / "deployment.json"

#: The template's server configuration, which the image serves as an envsubst template.
NGINX_CONF = rl.REPO_ROOT / "template" / "project" / "frontend" / "nginx.conf"

#: What only the bundle's own document says.
MARKER = "<p>lane spa</p>"

#: The frontend: ``npm run build`` copies ``src/`` to ``dist/``, which is all a build has to do.
FRONTEND = {
    "frontend/package.json": json.dumps(
        {"name": "lane-spa", "private": True, "scripts": {"build": "node build.mjs"}}, indent=2
    ) + "\n",
    "frontend/package-lock.json": json.dumps(
        {"name": "lane-spa", "lockfileVersion": 3, "requires": True, "packages": {"": {"name": "lane-spa"}}},
        indent=2,
    ) + "\n",
    "frontend/build.mjs": 'import { cpSync } from "node:fs";\ncpSync("src", "dist", { recursive: true });\n',
    "frontend/src/index.html": (
        '<!doctype html><html lang="en"><head><meta charset="utf-8"><title>spa</title>'
        f'<script src="/assets/app.js" defer></script></head><body>{MARKER}</body></html>\n'
    ),
    "frontend/src/assets/app.js": 'document.documentElement.dataset.ready = "yes";\n',
}


@pytest.fixture(scope="module")
def engine() -> None:
    missing = rl.missing_tools()
    if missing:
        rl.unavailable(f"the SPA image needs {', '.join(missing)}")


def _dockerfile() -> bytes:
    """``frontend/Dockerfile.prod`` as the generator renders it for an app with an SPA."""
    raw = json.loads(DECLARATION.read_text(encoding="utf-8"))
    tables = published_tables()
    declared, findings = reader.read(raw, tables.datastores, tables.system_packages)
    assert findings == [] and declared is not None
    rendered, refused = generate(declared, "lane", tables=tables, frontend_lock=True, site_lock=True)
    assert refused == []
    return rendered[FRONTEND_DOCKERFILE]


def _predating() -> str:
    """The template's ``nginx.conf`` as an app holds it from before ``server_tokens off``."""
    text = NGINX_CONF.read_text(encoding="utf-8")
    kept = [line for line in text.splitlines(keepends=True) if "server_tokens" not in line]
    assert len(kept) == len(text.splitlines()) - 1, "the template names server_tokens once"
    return "".join(kept)


def _image(root: pathlib.Path, tag: str, nginx_conf: str) -> None:
    for path, text in {**FRONTEND, "frontend/nginx.conf": nginx_conf}.items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    (root / FRONTEND_DOCKERFILE).write_bytes(_dockerfile())
    built = rl.run(
        ["docker", "build", "--progress=plain", "-f", FRONTEND_DOCKERFILE, "-t", tag, "."],
        cwd=root, env={**os.environ, "DOCKER_BUILDKIT": "1"}, check=False,
    )
    assert built.returncode == 0, built.stdout[-6000:] + built.stderr[-6000:]


def _get(port: int, path: str) -> tuple[int, dict[str, str], str]:
    url = f"http://127.0.0.1:{port}{path}"
    try:
        with urllib.request.urlopen(url, timeout=10) as answer:  # noqa: S310 - the test's own loopback container
            return answer.status, dict(answer.headers), answer.read().decode()
    except urllib.error.HTTPError as refused:
        return refused.code, dict(refused.headers), refused.read().decode()


@pytest.fixture(scope="module", params=["template", "predating"])
def spa(
    request: pytest.FixtureRequest, engine: None, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[tuple[str, int]]:
    kind = str(request.param)
    tag, name = f"{rl.prefix()}spa:{kind}", f"{rl.prefix()}spa-{kind}"
    config = NGINX_CONF.read_text(encoding="utf-8") if kind == "template" else _predating()
    _image(tmp_path_factory.mktemp(f"spa-{kind}"), tag, config)
    try:
        # Nothing listens on the upstream, so /api/ answers with nginx's own 502 page.
        yield name, rl.publish(name, 8080, ["-e", "API_UPSTREAM=127.0.0.1:9", tag], "/")
    finally:
        rl.run(["docker", "rm", "-f", "-v", name], check=False)
        rl.run(["docker", "image", "rm", "-f", tag], check=False)


def test_the_spa_image_runs_as_nginx_and_turns_healthy(spa: tuple[str, int]) -> None:
    name, _port = spa
    assert rl.run(["docker", "exec", name, "id", "-un"]).stdout.strip() == "nginx"
    deadline, status = time.monotonic() + 90, "starting"
    while status == "starting" and time.monotonic() < deadline:
        status = rl.run(["docker", "inspect", "--format", "{{.State.Health.Status}}", name]).stdout.strip()
        time.sleep(1)
    assert status == "healthy", "the image's own HEALTHCHECK is what `docker compose up --wait` reads"


def test_only_the_bundle_is_served(spa: tuple[str, int]) -> None:
    """The base image's ``50x.html`` is gone, so its path is one the bundle has no file for."""
    name, port = spa
    for path in ("/", "/50x.html", "/some/client/route"):
        status, headers, body = _get(port, path)
        assert (status, MARKER in body) == (200, True), (path, body[:300])
        assert "Content-Security-Policy" in headers, path
    listed = rl.run(["docker", "exec", name, "ls", "-A", "/usr/share/nginx/html"]).stdout.split()
    assert sorted(listed) == ["assets", "index.html"], "the bundle, and nothing the base image put there"


def test_no_response_names_an_nginx_version(spa: tuple[str, int]) -> None:
    """``server_tokens off`` is the image's own, so a config that predates it names none
    either: not in the ``Server`` header, and not on an error page nginx writes itself."""
    _name, port = spa
    for path in ("/", "/api/v1/health"):
        status, headers, body = _get(port, path)
        assert headers["Server"] == "nginx", (path, headers["Server"])
        assert "nginx/" not in body, (path, body[:300])
    status, _headers, body = _get(port, "/api/v1/health")
    assert status == 502 and "<center>nginx</center>" in body, (status, body[:300])
