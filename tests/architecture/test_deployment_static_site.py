"""The ``static-site`` recipe: a static site the framework builds and serves (ADR 0198).

The goldens hold the recipe's render byte for byte (``generator_goldens/static-site`` and
``site-alone``) and the corpus holds its refusals at the fields the fixtures name. This suite
holds what neither shows:

* **the refusal at build**, run with ``node`` exactly as the image runs it: the script is read
  out of the rendered Dockerfile, so the test runs the bytes a build runs;
* **the server's policy**: the template SPA's document headers, its content security policy
  included, character for character, with no ``/api`` location and no SPA fallback;
* **the escape audit**: the two interpolations the recipe adds and nothing near them;
* **who fronts the api**: a site proxies nothing, so with no web tier the api unit is the way
  in, and several api units behind a site alone are refused as behind nothing;
* **the signer's render**: it hands a pinned generator the site's lock only where that
  generator reads one, so a commit that pins an earlier ``terp-arch`` renders as it did.
"""

from __future__ import annotations

import copy
import importlib
import json
import pathlib
import re
import shutil
import subprocess
import sys
from typing import Any

import pytest

from terp.arch.deployment import reader
from terp.arch.deployment._static_site import SITE_HEALTH_PATH, port_variable, site_port
from terp.arch.deployment.generator import (
    PROFILE,
    SITE_DOCKERFILE,
    escape_findings,
    generate,
)
from terp.arch.deployment.tables import published_tables

#: The signer's render module (``terp.cli.release`` exports a function of the same name).
_signer_render = importlib.import_module("terp.cli.release._render")

_REPO = pathlib.Path(__file__).resolve().parents[2]
_GOLDEN = pathlib.Path(__file__).with_name("generator_goldens") / "static-site"
_SPA_NGINX = _REPO / "template" / "project" / "frontend" / "nginx.conf"


def _declaration(raw: dict[str, Any]) -> reader.Declaration:
    tables = published_tables()
    declared, findings = reader.read(raw, tables.datastores, tables.system_packages)
    assert findings == [] and isinstance(declared, reader.Declaration), findings
    return declared


def _golden() -> dict[str, Any]:
    return json.loads((_GOLDEN / "deployment.json").read_text(encoding="utf-8"))


def _render(raw: dict[str, Any], **locks: bool) -> tuple[dict[str, bytes], list[str]]:
    files, found = generate(
        _declaration(raw), "demo", tables=published_tables(),
        frontend_lock=locks.get("frontend", True), site_lock=locks.get("site", True),
    )
    return files, [finding.message for finding in found]


def _heredoc(dockerfile: str, delimiter: str) -> str:
    found = re.search(rf'<<"{delimiter}" \S+\n(.*?)\n{delimiter}\n', dockerfile, re.S)
    assert found is not None, f"the Dockerfile carries no {delimiter} heredoc"
    return found.group(1) + "\n"


def _site_dockerfile() -> str:
    files, refused = _render(_golden())
    assert refused == []
    return files[SITE_DOCKERFILE].decode("ascii")


# --------------------------------------------------------------------------- #
# the refusal at build, run as the image runs it                                #
# --------------------------------------------------------------------------- #
_REFUSED = {
    "inline.html": "<p>ok</p><script>track()</script>",
    "module.html": '<script type="module">import "/a.js"</script>',
    "importmap.html": '<script type="importmap">{"imports": {}}</script>',
    "style-element.html": "<svg><style>.a{fill:red}</style></svg>",
    "style-attribute.html": '<p style="color:red">x</p>',
    "handler.html": '<img src="/a.png" onerror="go()">',
    "url.html": '<a href=" JavaScript:go()">x</a>',
    "nested/deep/page.htm": "<button onclick=go()>x</button>",
}
_PASSES = {
    "index.html": '<!doctype html><link rel="stylesheet" href="/assets/a.css">'
    '<script src="/assets/a.js" type="module"></script><p>home</p>',
    "data-block.html": '<script type="application/ld+json">{"@type": "Article"}</script>',
    "comment.html": "<!-- <script>go()</script> --><p>ok</p>",
    "quoted.html": '<p title="a > <script>go()</script>">ok</p>',
    "text.html": "<textarea><style>p{}</style></textarea><noscript><style>p{}</style></noscript>",
    "empty.html": '<script></script><style> </style><p style="">ok</p>',
    "data.html": '<p data-onclick="x">ok</p><a href="/javascript:x">ok</a>',
    "not-html.css": "p { color: red }",
}


def _run_check(tmp_path: pathlib.Path, pages: dict[str, str]) -> subprocess.CompletedProcess[str]:
    node = shutil.which("node")
    assert node is not None, "the recipe's refusal is a Node script; run this suite where node is"
    (tmp_path / "check.mjs").write_text(_heredoc(_site_dockerfile(), "TERP_SITE_CHECK"), "ascii")
    for name, text in pages.items():
        (tmp_path / "dist" / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / "dist" / name).write_text(text, encoding="utf-8")
    return subprocess.run(  # noqa: S603 - node runs the recipe's own script over a test tree
        [node, "check.mjs", "dist"], cwd=tmp_path, capture_output=True, text=True, check=False
    )


def test_the_build_refuses_each_page_the_policy_would_break_naming_its_first_tag(
    tmp_path: pathlib.Path,
) -> None:
    run = _run_check(tmp_path, {**_REFUSED, **_PASSES})
    assert run.returncode == 1
    refused = [line for line in run.stderr.splitlines() if line.startswith("site/dist/")]
    assert sorted(line.split(":", 1)[0] for line in refused) == sorted(
        f"site/dist/{name}" for name in _REFUSED
    ), "each refused page once, and no page that passes"
    assert "site/dist/inline.html: <script> is an inline script" in refused
    assert "site/dist/handler.html: <img src=\"/a.png\" onerror=\"go()\"> carries the event " \
        "handler onerror" in refused
    assert 'site/dist/url.html: <a href=" JavaScript:go()"> points href at javascript:' in refused
    assert run.stderr.rstrip().endswith('or build the site under "build": "own".')


def test_a_site_whose_pages_the_policy_admits_builds(tmp_path: pathlib.Path) -> None:
    run = _run_check(tmp_path, _PASSES)
    assert (run.returncode, run.stderr) == (0, "")


# --------------------------------------------------------------------------- #
# the server's policy                                                           #
# --------------------------------------------------------------------------- #
def _policy(text: str) -> str:
    (line,) = [line.strip() for line in text.splitlines() if "Content-Security-Policy" in line]
    return line


def test_the_site_serves_the_template_spa_s_policy_and_proxies_nothing() -> None:
    nginx = _heredoc(_site_dockerfile(), "TERP_SITE_NGINX")
    spa = _SPA_NGINX.read_text(encoding="utf-8")
    assert _policy(nginx) == _policy(spa), "the recipe's policy is the template SPA's, exactly"
    for header in ("X-Content-Type-Options", "Referrer-Policy", "Cross-Origin-Opener-Policy",
                   "Permissions-Policy"):
        spa_line = next(line.strip() for line in spa.splitlines()
                        if f"add_header {header}" in line and "/assets/" not in line)
        assert spa_line in nginx, header
    assert "'unsafe-inline'" not in nginx and "proxy_pass" not in nginx and "/api" not in nginx
    assert "try_files $uri $uri/index.html =404;" in nginx, "real pages, no SPA fallback"
    assert "try_files $uri /index.html" not in nginx
    assert f"location = {SITE_HEALTH_PATH} {{" in nginx and "error_page 404 /404.html;" in nginx
    assert 'add_header Cache-Control "public, max-age=31536000, immutable";' in nginx


# --------------------------------------------------------------------------- #
# the escape audit and the port each site takes                                 #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("unit", "variable"),
    [("site", "WEB_PORT_SITE"), ("9site", "WEB_PORT_9SITE"), ("public.site", "WEB_PORT_PUBLIC_SITE"),
     ("my-site_2", "WEB_PORT_MY_SITE_2")],
)
def test_a_site_is_published_on_a_variable_compose_reads(unit: str, variable: str) -> None:
    assert port_variable(unit) == variable
    assert site_port(unit) == f"${{{variable}:-23101}}:8080"


def test_the_escape_audit_takes_the_site_s_scalars_and_nothing_near_them() -> None:
    tables = published_tables()
    files, _refused = _render(_golden())
    assert escape_findings(__import__("yaml").safe_load(files[PROFILE]), tables) == []
    image = "demo-site-prod:${TERP_RELEASE_TAG:?TERP_RELEASE_TAG is required, one new image tag per release}"
    assert escape_findings({"services": {"site": {"image": image}}}, tables) == []
    for profile in (
        {"services": {"site": {"ports": ["${WEB_PORT_SITE:-80}:8080"]}}},
        {"services": {"site": {"ports": ["${web_port_site:-23101}:8080"]}}},
        {"services": {"site": {"ports": ["${WEB_PORT_SITE:-23101}:80"]}}},
        {"services": {"site": {"image": "demo-site-prod:${TAG}"}}},
        {"services": {"site": {"image": "demo-docs-prod:" + image.split(":", 1)[1]}}},
    ):
        assert escape_findings(profile, tables), profile


# --------------------------------------------------------------------------- #
# who fronts the api                                                            #
# --------------------------------------------------------------------------- #
def test_several_apis_behind_a_site_alone_are_refused_as_behind_nothing() -> None:
    raw = _golden()
    raw["units"] = [unit for unit in raw["units"] if unit["id"] != "web"] + [
        {"id": "admin-api", "role": "api", "healthPath": "/health/ready",
         "livenessPath": "/health/live", "dependsOn": ["db", "migrate"]}
    ]
    files, refused = _render(raw)
    assert files == {} and any("2 api units (api, admin-api) and no web unit" in m for m in refused)


def test_a_site_is_rendered_only_for_the_unit_its_recipe_names() -> None:
    raw = _golden()
    del raw["generator"]
    files, refused = _render(copy.deepcopy(raw))
    assert files == {} and any("a second web unit without a recipe" in m for m in refused), (
        "without its recipe the site is a second web tier, refused as one"
    )


# --------------------------------------------------------------------------- #
# the signer's render, against a generator from before the site                 #
# --------------------------------------------------------------------------- #
_OLD_GENERATOR = '''
OWNED_PATHS = ("Dockerfile.prod", "frontend/Dockerfile.prod", "docker-compose.prod.yml")
FRONTEND_LOCK = "frontend/package-lock.json"


def generate(declaration, name, *, tables, frontend_lock):
    return {"docker-compose.prod.yml": b"rendered"}, []
'''


def test_the_signer_hands_the_site_lock_only_to_a_generator_that_reads_one(
    tmp_path: pathlib.Path,
) -> None:
    """A commit that pins terp-arch 0.39.0 renders with that release's generator, whose
    ``generate`` takes no ``site_lock``: the script reads the pinned signature, so the call is
    the one that release answers, and the render is what it was."""
    package = tmp_path / "arch" / "terp" / "arch" / "deployment"
    package.mkdir(parents=True)
    for parent in (tmp_path / "arch" / "terp", tmp_path / "arch" / "terp" / "arch"):
        (parent / "__init__.py").write_text("", encoding="utf-8")
    (package / "__init__.py").write_text(
        "class Declaration: ...\n"
        "def published_tables():\n    return None\n"
        "def readable(root):\n    return Declaration(), []\n",
        encoding="utf-8",
    )
    (package / "generator.py").write_text(_OLD_GENERATOR, encoding="utf-8")
    (package / "render_check.py").write_text(
        "def project_name(root):\n    return 'demo', []\n", encoding="utf-8"
    )
    tree = tmp_path / "tree"
    (tree / "site").mkdir(parents=True)
    (tree / "site" / "package-lock.json").write_text("{}", encoding="utf-8")
    run = subprocess.run(  # noqa: S603 - the signer's own script, as the signer runs it
        [sys.executable, "-I", "-c", _signer_render._RENDER, str(tmp_path / "arch"), str(tmp_path), str(tree)],
        capture_output=True, text=True, check=False,
    )
    assert run.returncode == 0, run.stderr
    answer = json.loads(run.stdout)
    assert answer["refused"] == [] and list(answer["files"]) == ["docker-compose.prod.yml"]
    assert answer["owned"] == ["Dockerfile.prod", "frontend/Dockerfile.prod", "docker-compose.prod.yml"]
