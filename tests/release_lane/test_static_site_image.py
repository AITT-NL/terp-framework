"""The static-site recipe's image on a real Docker engine (ADR 0198).

The generator's tests hold the text of ``site/Dockerfile.prod``. Only an engine shows that the
text is a build, so this builds it. The site is a few files and a lock with no package in it, so
the build fetches nothing but the two pinned base images, and its Dockerfile is the generator's
render for an app that declares the recipe:

* the image builds, runs as ``nginx``, answers ``/healthz`` itself, and its own
  ``HEALTHCHECK`` turns it healthy, which ``docker compose up --wait`` waits for;
* a page is served with the recipe's document headers, its content security policy among them,
  and ``no-cache``; a directory's ``index.html`` is its page, with or without the slash;
* a path with no file is the site's own ``404.html``, with status 404, and so is anything under
  ``/api``: the site proxies nothing;
* ``/assets/`` is immutable;
* a page with an inline ``<style>`` fails the build, which names the file and the tag, so the
  image whose page a browser would have broken is never made.

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
from terp.arch.deployment.generator import SITE_DOCKERFILE, generate
from terp.arch.deployment.tables import published_tables
from tests.release_lane import lane as rl

pytestmark = pytest.mark.release_lane

#: A declaration with one web unit, which names the recipe: its render holds the site's file.
DECLARATION = rl.REPO_ROOT / "tests" / "architecture" / "generator_goldens" / "site-alone" / "deployment.json"

#: The policy the recipe serves every page with (``SITE_NGINX``), as a browser receives it.
POLICY = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
    "font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; "
    "frame-ancestors 'none'; form-action 'self'"
)


def _page(title: str) -> str:
    """A page the policy admits: its style and script are files, and a data block runs as nothing."""
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        f"<title>{title}</title>"
        '<link rel="stylesheet" href="/assets/site.css">'
        '<script type="application/ld+json">{"@type": "WebSite", "name": "lane"}</script>'
        '<script src="/assets/site.js" defer></script>'
        f"</head><body><p>{title}</p></body></html>\n"
    )


#: The site: ``npm run build`` copies ``src/`` to ``dist/``, which is all a build has to do.
SITE = {
    "site/package.json": json.dumps(
        {"name": "lane-site", "private": True, "scripts": {"build": "node build.mjs"}}, indent=2
    ) + "\n",
    "site/package-lock.json": json.dumps(
        {"name": "lane-site", "lockfileVersion": 3, "requires": True, "packages": {"": {"name": "lane-site"}}},
        indent=2,
    ) + "\n",
    "site/build.mjs": 'import { cpSync } from "node:fs";\ncpSync("src", "dist", { recursive: true });\n',
    "site/src/index.html": _page("home"),
    "site/src/docs/index.html": _page("docs"),
    "site/src/404.html": _page("not here"),
    "site/src/assets/site.css": "p { margin: 0; }\n",
    "site/src/assets/site.js": 'document.documentElement.dataset.ready = "yes";\n',
}


@pytest.fixture(scope="module")
def engine() -> None:
    missing = rl.missing_tools()
    if missing:
        rl.unavailable(f"the static-site image needs {', '.join(missing)}")


def _dockerfile() -> bytes:
    """``site/Dockerfile.prod`` as the generator renders it for a declared site."""
    raw = json.loads(DECLARATION.read_text(encoding="utf-8"))
    tables = published_tables()
    declared, findings = reader.read(raw, tables.datastores, tables.system_packages)
    assert findings == [] and declared is not None
    rendered, refused = generate(declared, "lane", tables=tables, frontend_lock=False, site_lock=True)
    assert refused == []
    return rendered[SITE_DOCKERFILE]


def _context(root: pathlib.Path, extra: dict[str, str] | None = None) -> pathlib.Path:
    for path, text in {**SITE, **(extra or {})}.items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    (root / SITE_DOCKERFILE).write_bytes(_dockerfile())
    return root


def _build(context: pathlib.Path, tag: str):  # type: ignore[no-untyped-def]
    return rl.run(
        ["docker", "build", "--progress=plain", "-f", SITE_DOCKERFILE, "-t", tag, "."],
        cwd=context, env={**os.environ, "DOCKER_BUILDKIT": "1"}, check=False,
    )


def _get(port: int, path: str) -> tuple[int, dict[str, str], str]:
    url = f"http://127.0.0.1:{port}{path}"
    try:
        with urllib.request.urlopen(url, timeout=10) as answer:  # noqa: S310 - the test's own loopback container
            return answer.status, dict(answer.headers), answer.read().decode()
    except urllib.error.HTTPError as refused:
        return refused.code, dict(refused.headers), refused.read().decode()


@pytest.fixture(scope="module")
def site(engine: None, tmp_path_factory: pytest.TempPathFactory) -> Iterator[tuple[str, int]]:
    tag, name = f"{rl.prefix()}site:ok", f"{rl.prefix()}site-ok"
    built = _build(_context(tmp_path_factory.mktemp("site")), tag)
    assert built.returncode == 0, built.stdout[-6000:] + built.stderr[-6000:]
    try:
        yield name, rl.publish(name, 8080, [tag], "/healthz")
    finally:
        rl.run(["docker", "rm", "-f", "-v", name], check=False)
        rl.run(["docker", "image", "rm", "-f", tag], check=False)


def test_the_site_image_runs_as_nginx_and_answers_its_health_path(site: tuple[str, int]) -> None:
    name, port = site
    assert rl.run(["docker", "exec", name, "id", "-un"]).stdout.strip() == "nginx"
    assert _get(port, "/healthz")[::2] == (200, "ok\n")
    deadline, status = time.monotonic() + 90, "starting"
    while status == "starting" and time.monotonic() < deadline:
        status = rl.run(["docker", "inspect", "--format", "{{.State.Health.Status}}", name]).stdout.strip()
        time.sleep(1)
    assert status == "healthy", "the image's own HEALTHCHECK is what `docker compose up --wait` reads"


def test_a_page_is_served_with_the_recipe_s_policy(site: tuple[str, int]) -> None:
    _name, port = site
    status, headers, body = _get(port, "/")
    assert status == 200 and "<p>home</p>" in body
    assert headers["Content-Security-Policy"] == POLICY
    assert headers["Cache-Control"] == "no-cache"
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["Referrer-Policy"] == "no-referrer"
    for path in ("/docs/", "/docs"):
        status, headers, body = _get(port, path)
        assert (status, "<p>docs</p>" in body) == (200, True), path
        assert headers["Content-Security-Policy"] == POLICY, path


def test_a_missing_path_and_the_api_are_the_site_s_own_404(site: tuple[str, int]) -> None:
    _name, port = site
    for path in ("/nope", "/api/v1/health", "/api/"):
        status, headers, body = _get(port, path)
        assert (status, "<p>not here</p>" in body) == (404, True), path
        assert headers["Content-Security-Policy"] == POLICY, path


def test_assets_are_immutable(site: tuple[str, int]) -> None:
    _name, port = site
    status, headers, body = _get(port, "/assets/site.css")
    assert (status, body) == (200, SITE["site/src/assets/site.css"])
    assert headers["Cache-Control"] == "public, max-age=31536000, immutable"
    assert _get(port, "/assets/nope.css")[0] == 404


def test_a_page_with_an_inline_style_fails_the_build_by_name(engine: None, tmp_path: pathlib.Path) -> None:
    tag = f"{rl.prefix()}site:refused"
    bad = '<!doctype html><html><head><style>p { color: red; }</style></head><body></body></html>\n'
    try:
        built = _build(_context(tmp_path, {"site/src/guide/bad.html": bad}), tag)
    finally:
        rl.run(["docker", "image", "rm", "-f", tag], check=False)
    said = built.stdout + built.stderr
    assert built.returncode != 0, said[-6000:]
    assert "site/dist/guide/bad.html: <style> is a <style> element" in said, said[-6000:]
    assert 'or build the site under "build": "own"' in said, said[-6000:]
