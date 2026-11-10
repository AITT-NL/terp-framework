"""The ``static-site`` recipe: a static site the framework builds and serves (ADR 0198).

The goldens hold the recipe's render byte for byte (``generator_goldens/static-site`` and
``site-alone``) and the corpus holds its refusals at the fields the fixtures name. This suite
holds what neither shows:

* **the refusal at build**, run with ``node`` exactly as the image runs it: the script is read
  out of the rendered Dockerfile, so the test runs the bytes a build runs. It refuses a symbolic
  link under ``dist/``, and reads a large page of each shape that once cost it quadratic time
  within a bound;
* **the server's policy**: the template SPA's document headers, its content security policy
  included, character for character, on every location that serves a file, with no ``/api``
  location and no SPA fallback;
* **the escape audit**: the two interpolations the recipe adds and nothing near them;
* **who fronts the api**: a site proxies nothing, so with no web tier the api unit is the way
  in, and several api units behind a site alone are refused as behind nothing;
* **the health path**: the site's own nginx answers ``/healthz``, where the profile probes it,
  and a deploy tool waits on the path the unit declares, so the reader refuses any other;
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
import time
from typing import Any

import pytest

from terp.arch.deployment import reader
from terp.arch.deployment._static_site import (
    SITE_HEALTH_PATH,
    SITE_ROOT,
    STATIC_SITE,
    port_variable,
    site_port,
)
from terp.arch.deployment.generator import (
    PROFILE,
    SITE_DOCKERFILE,
    escape_findings,
    generate,
)
from terp.arch.deployment.tables import published_tables
from tests.architecture import nginx_config

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
    "spaced-url.html": '<a href="java script:go()">x</a>',
    "nested/deep/page.htm": "<button onclick=go()>x</button>",
    # A tag's attributes as the tokenizer reads them: after a "/", "=" starts a name of its own.
    "slash-equals.html": "<img src=x b / = onerror=go()>",
    # A comment ends where a browser ends it, so what follows is read, not skipped to a later
    # "-->": an empty comment closed at once, and one closed by "--!>".
    "abrupt-comment.html": "<!--><script>go()</script><!-- later -->",
    "abrupt-dash-comment.html": "<!---><script>go()</script><!-- later -->",
    "bang-comment.html": "<!-- a --!><script>go()</script><!-- later -->",
    # A value is judged as the browser reads it, every character reference decoded: a number
    # with or without its semicolon, and the names a URL's punctuation and spaces have.
    "decimal-ref.html": '<a href="&#106;avascript:go()">x</a>',
    "decimal-ref-unterminated.html": '<a href="&#106avascript:go()">x</a>',
    "hex-ref.html": '<a href="&#x6A;avascript:go()">x</a>',
    "colon-ref.html": '<a href="javascript&colon;go()">x</a>',
    "tab-ref.html": '<a href="java&Tab;script:go()">x</a>',
    "newline-ref.html": '<a href="java&NewLine;script:go()">x</a>',
    # A srcdoc is a page of its own, read as one.
    "srcdoc.html": '<iframe srcdoc="<script>go()</script>"></iframe>',
    "srcdoc-escaped.html": '<iframe srcdoc="&lt;p onclick=&quot;go()&quot;&gt;x&lt;/p&gt;"></iframe>',
    # Inside SVG and MathML content the check skips no raw text: a browser reads an element's
    # content there as markup, and where an integration point hands it back to HTML the check
    # reads on as markup all the same. An end tag a browser ignores there closes nothing, and
    # one that ends the integration point ends it here too.
    "svg-title.html": '<svg><title><a onclick="go()">x</a></title></svg>',
    "svg-noscript.html": "<svg><noscript><img src=x onerror=go()></noscript></svg>",
    "svg-script.html": "<svg><script>go()</script></svg>",
    "math-textarea.html": "<math><mtext><textarea><b onclick=go()>x</b></textarea></mtext></math>",
    "svg-ignored-close.html": (
        "<svg><foreignObject><div></svg></div></foreignObject>"
        "<title><img src=x onerror=go()></title></svg>"
    ),
    "desc-close.html": "<svg><desc><div></desc></svg></div></desc><xmp><img src=x onerror=go()></xmp>",
    # Inside a <select> or after a <frameset>, where a browser may ignore a raw-text element's
    # start tag and read on as markup, no raw text is skipped.
    "select-xmp.html": "<select><xmp><option onclick=go()>x</option></xmp></select>",
    "frameset-xmp.html": '<frameset><xmp><frame src="https://video.example/1"></xmp></frameset>',
    # A javascript: URL in any attribute that holds one, an SVG animation of it, a refresh.
    "svg-set.html": '<svg><a><set attributeName="href" to="javascript:go()"/><text>x</text></a></svg>',
    "svg-animate.html": '<svg><a><animate attributeName="xlink:href" values="/a;javascript:go()"/></a></svg>',
    "svg-animate-from.html": '<svg><a><animate attributeName="HREF" from="&#106;avascript:go()"/></a></svg>',
    "meta-refresh.html": '<meta http-equiv="refresh" content="0; url=javascript:go()">',
    "srcset.html": '<img srcset="/a.png 1x, javascript:go() 2x">',
    # A script, a stylesheet or a frame from another origin or a data: URL.
    "data-script.html": '<script src="data:text/javascript,go()"></script>',
    "data-style.html": '<link rel="stylesheet" href="data:text/css,p{}">',
    "cdn-script.html": '<script src="https://cdn.example/a.js"></script>',
    "host-script.html": '<script src="//cdn.example/a.js"></script>',
    "backslash-script.html": '<script src="\\\\cdn.example/a.js"></script>',
    "cdn-style.html": '<link rel="alternate stylesheet" href="https://cdn.example/a.css">',
    "svg-script-href.html": '<svg><script href="https://cdn.example/a.js"></script></svg>',
    "frame-elsewhere.html": '<iframe src="https://video.example/embed/1"></iframe>',
    "frame-data.html": '<iframe src="data:text/html,x"></iframe>',
    # An image, media, a drawing, an icon, a manifest or a preload from another origin. An image
    # may be a data: URL, as img-src allows; media may not.
    "cdn-image.html": '<img src="https://cdn.example/a.png" alt="">',
    "cdn-srcset.html": '<img src="/a.png" srcset="/a.png 1x, https://cdn.example/a@2x.png 2x" alt="">',
    "picture-source.html": '<picture><source srcset="https://cdn.example/a.webp"><img src="/a.png" alt=""></picture>',
    "poster.html": '<video src="/a.mp4" poster="https://cdn.example/a.jpg"></video>',
    "input-image.html": '<form action="/search/"><input type="image" src="https://cdn.example/go.png" alt="go"></form>',
    "body-background.html": '<body background="https://cdn.example/bg.png"><p>x</p></body>',
    "svg-image.html": '<svg><image href="https://cdn.example/a.png"/></svg>',
    "svg-image-xlink.svg": (
        '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink">'
        '<image xlink:href="https://cdn.example/a.png"/></svg>'
    ),
    "svg-use.html": '<svg><use href="https://cdn.example/sprite.svg#a"/></svg>',
    "cdn-video.html": '<video src="https://cdn.example/a.mp4"></video>',
    "video-source.html": '<video><source src="https://cdn.example/a.mp4" type="video/mp4"></video>',
    "audio.html": '<audio src="//cdn.example/a.mp3"></audio>',
    "track.html": '<video src="/a.mp4"><track src="https://cdn.example/a.vtt" kind="captions"></video>',
    "data-video.html": '<video src="data:video/mp4;base64,AAAA"></video>',
    "icon-elsewhere.html": '<link rel="icon" href="https://cdn.example/favicon.ico">',
    "manifest.html": '<link rel="manifest" href="https://cdn.example/site.webmanifest">',
    "preload-font.html": '<link rel="preload" href="https://fonts.example/a.woff2" as="font" crossorigin>',
    "preload-fetch.html": '<link rel="preload" href="https://api.example/a.json" as="fetch" crossorigin>',
    "modulepreload.html": '<link rel="modulepreload" href="https://cdn.example/a.js">',
    # What the policy forbids outright, and a form that submits elsewhere.
    "base.html": '<base href="/">',
    "object.html": '<object data="/a.swf"></object>',
    "embed.html": '<embed src="/a.swf">',
    "form-elsewhere.html": '<form action="https://forms.example/post" method="post"><button>go</button></form>',
    "formaction-elsewhere.html": '<form><button formaction="https://forms.example/post">go</button></form>',
    # An XML file is a document too, read as the XML it is: each element and attribute by its
    # namespace, whatever its prefix, and an xml-stylesheet instruction as the load it is.
    "logo.svg": '<svg xmlns="http://www.w3.org/2000/svg"><script>go()</script></svg>',
    "page.xhtml": (
        '<html xmlns="http://www.w3.org/1999/xhtml"><body><textarea><b onclick="go()">x</b>'
        "</textarea></body></html>"
    ),
    "page.xml": (
        '<?xml version="1.0"?><html xmlns="http://www.w3.org/1999/xhtml"><body>'
        "<script>go()</script></body></html>"
    ),
    "feed.rss": '<rss><channel><x:script xmlns:x="http://www.w3.org/1999/xhtml">go()</x:script></channel></rss>',
    "prefixed.svg": '<s:svg xmlns:s="http://www.w3.org/2000/svg"><s:script>go()</s:script></s:svg>',
    "prefixed.xhtml": (
        '<h:html xmlns:h="http://www.w3.org/1999/xhtml"><h:body><h:script>go()</h:script>'
        "</h:body></h:html>"
    ),
    "xlink-prefix.svg": (
        '<svg xmlns="http://www.w3.org/2000/svg" xmlns:l="http://www.w3.org/1999/xlink">'
        '<a l:href="javascript:go()"><text>x</text></a></svg>'
    ),
    "styled.svg": (
        '<?xml-stylesheet type="text/css" href="https://cdn.example/a.css"?>'
        '<svg xmlns="http://www.w3.org/2000/svg"/>'
    ),
    "xslt.xml": '<?xml-stylesheet type="text/xsl" href="https://cdn.example/feed.xsl"?><rss version="2.0"/>',
    # An internal DTD subset, whatever it declares: a browser expands its entities into the
    # page, and the check does not read them.
    "entity.svg": (
        '<!DOCTYPE svg [ <!ENTITY s "<script>go()</script>"> ]>'
        '<svg xmlns="http://www.w3.org/2000/svg">&s;</svg>'
    ),
    "entity-url.svg": (
        '<!DOCTYPE svg [ <!ENTITY j "javascript:go()"> ]>'
        '<svg xmlns="http://www.w3.org/2000/svg"><a href="&j;"><text>x</text></a></svg>'
    ),
    "param-entity.svg": '<!DOCTYPE svg [ <!ENTITY % p "x"> %p; ]><svg xmlns="http://www.w3.org/2000/svg"/>',
    "namespace-entity.svg": '<?xml version="1.0"?><!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN" '
    '"http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd" [ <!ENTITY ns_x "http://ns.example/x/"> ]>'
    '<svg xmlns="http://www.w3.org/2000/svg" xmlns:x="&ns_x;"/>',
}
_PASSES = {
    "index.html": '<!doctype html><link rel="stylesheet" href="/assets/a.css">'
    '<script src="/assets/a.js" type="module"></script><p>home</p>',
    "data-block.html": '<script type="application/ld+json">{"@type": "Article"}</script>',
    "comment.html": "<!-- <script>go()</script> --><p>ok</p>",
    "dashes.html": "<!-- a -- b - <script>go()</script> ---><!----><p>ok</p>",
    "quoted.html": '<p title="a > <script>go()</script>">ok</p>',
    "text.html": "<textarea><style>p{}</style></textarea><noscript><style>p{}</style></noscript>",
    "empty.html": '<script></script><style> </style><p style="">ok</p>',
    "data.html": '<p data-onclick="x">ok</p><a href="/javascript:x">ok</a>',
    "not-html.css": "p { color: red }",
    # A link elsewhere navigates, which the policy leaves alone, and an image may be data.
    "links.html": '<a href="https://other.example/">out</a><a href="mailto:a@example.org">mail</a>'
    '<img src="data:image/png;base64,iVBORw0KGgo=" alt=""><img srcset="/a.png 1x, /b.png 2x" alt="">',
    "own-frame.html": '<iframe src="/embed/map.html" title="map"></iframe>'
    '<form action="/search/"><input name="q"></form>',
    "icon.html": '<svg viewBox="0 0 1 1"><title>Logo &amp; mark</title><a href="/about/">'
    '<path d="M0 0h1v1z"/></a></svg><p>after</p><textarea><b onclick=x></b></textarea>',
    "icon.svg": '<?xml version="1.0"?><!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN" '
    '"http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd">'
    '<svg xmlns="http://www.w3.org/2000/svg" xmlns:x="http://ns.example/x/"><style/><a href="/">'
    "<rect width=\"1\" height=\"1\"/></a><![CDATA[ <b onclick=x> ]]></svg>",
    # Another namespace's element or attribute does nothing a browser renders, and a feed or a
    # sitemap is data.
    "unbound.svg": '<svg xmlns="http://www.w3.org/2000/svg" xmlns:x="http://ns.example/x/">'
    '<x:script>go()</x:script><a x:href="javascript:go()"><text>x</text></a></svg>',
    "feed.xml": '<?xml version="1.0"?><?xml-stylesheet type="text/xsl" href="/feed.xsl"?><rss version="2.0">'
    "<channel><item><description>&lt;script&gt;go()&lt;/script&gt;</description>"
    "<description><![CDATA[<script>go()</script>]]></description></item></channel></rss>",
    "sitemap.xml": '<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
    "<url><loc>https://site.example/</loc></url></urlset>",
    "feed.atom": '<feed xmlns="http://www.w3.org/2005/Atom"><entry><content type="xhtml">'
    '<div xmlns="http://www.w3.org/1999/xhtml"><p>ok</p></div></content></entry></feed>',
    # The site's own media, a data: image, a frame of about:blank, and links that load nothing.
    "own-media.html": '<img src="/a.png" srcset="/a.png 1x, /a@2x.png 2x" alt=""><picture>'
    '<source srcset="/a.webp"><img src="data:image/png;base64,iVBORw0KGgo=" alt=""></picture>'
    '<video src="/a.mp4" poster="data:image/png;base64,iVBORw0KGgo="><track src="/a.vtt"></video>'
    '<audio src="/a.mp3"></audio><svg><image href="/a.png"/><use href="#icon"/>'
    '<use href="/sprite.svg#icon"/></svg><link rel="icon" href="data:image/svg+xml,%3Csvg%3E">'
    '<link rel="preload" href="/assets/a.woff2" as="font" crossorigin>'
    '<link rel="manifest" href="/site.webmanifest"><iframe src="about:blank" title="x"></iframe>',
    "head-links.html": '<link rel="canonical" href="https://site.example/">'
    '<link rel="alternate" type="application/rss+xml" href="https://site.example/feed.xml">'
    '<meta property="og:image" content="https://site.example/og.png">',
    # Raw text in a page's own HTML is text, whatever it spells.
    "xmp-text.html": "<xmp><img src=x onerror=go()></xmp><textarea><svg><script>go()</script></svg></textarea>",
    "page.html.xhtml": '<?xml version="1.0"?><html xmlns="http://www.w3.org/1999/xhtml"><head>'
    '<link rel="stylesheet" href="/assets/a.css"/><script src="/assets/a.js"></script></head>'
    "<body><p>ok</p></body></html>",
    "srcdoc-ok.html": '<iframe srcdoc="&lt;p&gt;hello&lt;/p&gt;"></iframe>',
    "preconnect.html": '<link rel="preconnect" href="https://fonts.example"><link rel="icon" href="/favicon.svg">',
}


def _run_check(
    tmp_path: pathlib.Path,
    pages: dict[str, str] | None,
    links: dict[str, str] | None = None,
    timeout: float | None = None,
) -> subprocess.CompletedProcess[str]:
    """The check the image runs, over *pages* written under ``dist/`` (none: no ``dist/``) and
    *links*, each a symbolic link under ``dist/`` to its target."""
    node = shutil.which("node")
    assert node is not None, "the recipe's refusal is a Node script; run this suite where node is"
    (tmp_path / "check.mjs").write_text(_heredoc(_site_dockerfile(), "TERP_SITE_CHECK"), "ascii")
    for name, text in (pages or {}).items():
        (tmp_path / "dist" / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / "dist" / name).write_text(text, encoding="utf-8")
    for name, target in (links or {}).items():
        (tmp_path / "dist" / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / "dist" / name).symlink_to(target)
    return subprocess.run(
        [node, "check.mjs", "dist"], cwd=tmp_path, capture_output=True, text=True, check=False,
        timeout=timeout,
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
    assert run.stderr.rstrip().endswith('or build the site under "build": "own".')


@pytest.mark.parametrize(
    ("page", "line"),
    [
        ("inline.html", "<script> is an inline script: write it to a file the page loads with src"),
        ("handler.html", '<img src="/a.png" onerror="go()"> carries the event handler onerror: attach '
         "the listener from a script file"),
        ("url.html", '<a href=" JavaScript:go()"> points href at a javascript: URL: link to a page, or '
         "attach the behaviour from a script file"),
        ("colon-ref.html", '<a href="javascript&colon;go()"> points href at a javascript: URL: link to a '
         "page, or attach the behaviour from a script file"),
        ("style-element.html", '<style> is a <style> element: write it to a stylesheet the page loads '
         'with <link rel="stylesheet">'),
        ("style-attribute.html", '<p style="color:red"> carries a style attribute: move the declaration '
         "to a stylesheet the page loads"),
        ("srcdoc-escaped.html", '<iframe srcdoc="&lt;p onclick=&quot;go()&quot;&gt;x&lt;/p&gt;"> carries a '
         'srcdoc whose page holds <p onclick="go()"> carries the event handler onclick: attach the '
         "listener from a script file"),
        ("svg-title.html", '<a onclick="go()"> carries the event handler onclick: attach the listener '
         "from a script file"),
        ("svg-set.html", '<set attributeName="href" to="javascript:go()"/> animates href to a '
         "javascript: URL: remove the animation, or animate it to a page"),
        ("meta-refresh.html", '<meta http-equiv="refresh" content="0; url=javascript:go()"> refreshes '
         "to a javascript: URL: refresh to a page, or remove it"),
        ("cdn-script.html", '<script src="https://cdn.example/a.js"> loads its script from another '
         "origin (https:), which the policy's script-src 'self' refuses: copy the script into the "
         "site's build and load it by its path"),
        ("host-script.html", '<script src="//cdn.example/a.js"> loads its script from another host, '
         "which the policy's script-src 'self' refuses: copy the script into the site's build and "
         "load it by its path"),
        ("data-style.html", '<link rel="stylesheet" href="data:text/css,p{}"> loads a stylesheet from a '
         "data: URL, which the policy's style-src 'self' refuses: copy the stylesheet into the "
         "site's build and link it by its path"),
        ("frame-elsewhere.html", '<iframe src="https://video.example/embed/1"> frames another origin '
         "(https:), which the policy's default-src 'self' refuses: link to the page instead, or frame "
         "one of the site's own"),
        ("base.html", "<base href=\"/\"> sets the page's base URL, which the policy's base-uri 'none' "
         "refuses: remove it and write each URL whole"),
        ("object.html", '<object data="/a.swf"> is an <object> element, which the policy\'s object-src '
         "'none' refuses: remove it"),
        ("embed.html", '<embed src="/a.swf"> is an <embed> element, which the policy\'s object-src '
         "'none' refuses: remove it"),
        ("form-elsewhere.html", '<form action="https://forms.example/post" method="post"> submits a '
         "form to another origin (https:), which the policy's form-action 'self' refuses: a site built "
         'from the recipe has no form that posts, so remove it or build the site under "build": "own"'),
        ("styled.svg", '<?xml-stylesheet type="text/css" href="https://cdn.example/a.css"?> loads a '
         "stylesheet from another origin (https:), which the policy's style-src 'self' refuses: copy the "
         "stylesheet into the site's build and name it by its path"),
        ("xslt.xml", '<?xml-stylesheet type="text/xsl" href="https://cdn.example/feed.xsl"?> loads an '
         "XSLT stylesheet from another origin (https:), which the policy's script-src 'self' refuses: "
         "copy the stylesheet into the site's build and name it by its path"),
        ("param-entity.svg", "<!DOCTYPE> declares an internal subset, whose entities a browser expands "
         "into the page and the check does not read: write each entity's text where it is used and "
         "remove the subset (an SVG or XHTML file needs none)"),
        ("slash-equals.html", "<img src=x b / = onerror=go()> carries the event handler onerror: attach "
         "the listener from a script file"),
        ("desc-close.html", "<img src=x onerror=go()> carries the event handler onerror: attach the "
         "listener from a script file"),
        ("prefixed.svg", "<s:script> is an inline script: write it to a file the page loads with src"),
        ("xlink-prefix.svg", '<a l:href="javascript:go()"> points xlink:href at a javascript: URL: link '
         "to a page, or attach the behaviour from a script file"),
        ("cdn-image.html", '<img src="https://cdn.example/a.png" alt=""> loads an image from another '
         "origin (https:), which the policy's img-src 'self' data: refuses: copy the image into the "
         "site's build and load it by its path"),
        ("data-video.html", '<video src="data:video/mp4;base64,AAAA"> loads media from a data: URL, '
         "which the policy's default-src 'self' refuses: copy the file into the site's build and load "
         "it by its path"),
        ("svg-use.html", '<use href="https://cdn.example/sprite.svg#a"/> uses a drawing from another '
         "origin (https:), which a browser loads into <use> from the page's own origin alone: copy the "
         "drawing into the site's build and use it by its path"),
        ("icon-elsewhere.html", '<link rel="icon" href="https://cdn.example/favicon.ico"> loads an icon '
         "from another origin (https:), which the policy's img-src 'self' data: refuses: copy the icon "
         "into the site's build and link it by its path"),
        ("manifest.html", '<link rel="manifest" href="https://cdn.example/site.webmanifest"> loads its '
         "manifest from another origin (https:), which the policy's default-src 'self' refuses: copy "
         "the manifest into the site's build and link it by its path"),
        ("preload-font.html", '<link rel="preload" href="https://fonts.example/a.woff2" as="font" '
         "crossorigin> loads a font from another origin (https:), which the policy's font-src 'self' "
         "refuses: copy the font into the site's build and load it by its path"),
        ("preload-fetch.html", '<link rel="preload" href="https://api.example/a.json" as="fetch" '
         "crossorigin> fetches from another origin (https:), which the policy's connect-src 'self' "
         "refuses: copy the file into the site's build and fetch it by its path"),
    ],
)
def test_each_refusal_names_the_file_its_tag_and_what_to_change(
    tmp_path: pathlib.Path, page: str, line: str
) -> None:
    run = _run_check(tmp_path, {page: _REFUSED[page]})
    assert run.returncode == 1
    assert run.stderr.splitlines()[0] == f"site/dist/{page}: {line}"


def test_a_site_whose_pages_the_policy_admits_builds(tmp_path: pathlib.Path) -> None:
    run = _run_check(tmp_path, _PASSES)
    assert (run.returncode, run.stderr) == (0, "")


_LINKED = (
    "is a symbolic link, which the image copies as a link and nginx follows wherever it points, "
    "so the check cannot read what it serves: make the build write the file itself"
)


def test_a_symbolic_link_under_dist_is_refused_wherever_it_points(tmp_path: pathlib.Path) -> None:
    """The image copies a link as a link and nginx follows it, so what the path serves is
    whatever it points at in the running image: a page outside dist/, a file of the image, a
    directory. None of it is read, so each is refused, a page that passes beside them is not."""
    (tmp_path / "outside.html").write_text("<script>go()</script>", encoding="utf-8")
    run = _run_check(
        tmp_path, {"index.html": "<p>ok</p>"},
        links={"a.html": "../outside.html", "img/logo.png": "/etc/hostname", "docs": "../elsewhere"},
    )
    assert run.returncode == 1
    refused = [line for line in run.stderr.splitlines() if line.startswith("site/dist/")]
    assert refused == [f"site/dist/{name}: {_LINKED}" for name in ("a.html", "docs", "img/logo.png")]


@pytest.mark.parametrize(("made", "said"), [("link", "is a symbolic link"), ("file", "is not a directory")])
def test_a_dist_that_is_no_directory_is_named_with_its_remedy(
    tmp_path: pathlib.Path, made: str, said: str
) -> None:
    if made == "link":
        (tmp_path / "pages").mkdir()
        (tmp_path / "dist").symlink_to("pages")
    else:
        (tmp_path / "dist").write_text("", encoding="utf-8")
    run = _run_check(tmp_path, None)
    assert run.returncode == 1
    assert run.stderr.strip() == (
        f"site/dist/ {said}: the static-site recipe serves the pages `npm run build` writes there "
        "(terp-framework ADR 0198). Make the site's build write its pages to dist/, or build the "
        'site under "build": "own".'
    )


#: A large page (a third of a megabyte to one and a half) in each shape that once cost the check
#: quadratic time, or would with a naive reading: forty thousand comments, which the check
#: before 0.41.0 read in about twenty seconds by searching the rest of the page for "--!>" from
#: each; SVG fifty thousand deep whose end tags close nothing; SVG scripts whose end tag never
#: comes; raw text whose end tag never comes; and an XML file that binds a new prefix at each of
#: twenty thousand levels.
_LARGE = {
    "comments.html": ("<!-- " + "x" * 26 + " -->") * 40_000,
    "svg-end-tags.html": "<svg>" + "<g>" * 50_000 + "</x>" * 50_000,
    "svg-scripts.html": "<svg>" + '<script src="/a.js">' * 50_000,
    "unclosed.html": "<textarea>" * 100_000,
    "prefixes.svg": '<svg xmlns="http://www.w3.org/2000/svg">'
    + "".join(f'<g xmlns:p{n}="http://ns.example/{n}">' for n in range(20_000))
    + "</g>" * 20_000 + "</svg>",
}


@pytest.mark.parametrize("page", sorted(_LARGE))
def test_the_check_reads_a_large_page_in_time_linear_in_its_size(tmp_path: pathlib.Path, page: str) -> None:
    started = time.monotonic()
    try:
        run = _run_check(tmp_path, {page: _LARGE[page]}, timeout=10)
    except subprocess.TimeoutExpired:
        pytest.fail(f"the check read {page} ({len(_LARGE[page]):,} characters) for more than 10 s")
    assert (run.returncode, run.stderr) == (0, ""), run.stderr
    assert time.monotonic() - started < 10


def test_a_build_that_wrote_no_dist_is_named_with_its_remedy(tmp_path: pathlib.Path) -> None:
    """Not a Node stack trace about ENOENT: the directory the recipe serves, and how to fill it."""
    run = _run_check(tmp_path, None)
    assert run.returncode == 1
    assert run.stderr.strip() == (
        "site/dist/ does not exist: the static-site recipe serves the pages `npm run build` writes "
        "there (terp-framework ADR 0198). Make the site's build write its pages to dist/, or build "
        'the site under "build": "own".'
    )


# --------------------------------------------------------------------------- #
# the server's policy                                                           #
# --------------------------------------------------------------------------- #
def _policy(text: str) -> str:
    """The one policy *text* serves, however many locations repeat it."""
    (line,) = {line.strip() for line in text.splitlines() if "Content-Security-Policy" in line}
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


def test_every_location_that_serves_a_file_carries_the_policy() -> None:
    """``/assets/`` sets ``Cache-Control``, and nginx then drops every header the block would
    have inherited, so the policy written for the pages was not on its responses. An SVG
    there is a document that runs the script it holds when it is opened on its own. Each
    location that answers with a file carries the whole set; the health path answers with
    text of its own."""
    lacking = nginx_config.unheaded_file_locations(_heredoc(_site_dockerfile(), "TERP_SITE_NGINX"))
    assert lacking == {"location /assets/": [], "location /": []}, lacking


def test_the_site_is_served_from_a_root_only_its_build_fills() -> None:
    """The base image's html directory holds pages of its own (a 50x.html with an inline style
    the policy blocks): copied over it, the site would serve them too. So the build is copied
    into a directory of its own, and the server's root is that directory and nothing else."""
    dockerfile = _site_dockerfile()
    nginx = _heredoc(dockerfile, "TERP_SITE_NGINX")
    assert re.findall(r"^\s*root (\S+);$", nginx, re.M) == [SITE_ROOT]
    assert re.findall(r"^COPY --from=build \S+ (\S+)$", dockerfile, re.M) == [SITE_ROOT]
    assert "/usr/share/nginx/html" not in nginx + dockerfile.split("TERP_SITE_NGINX")[-1]


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
# the health path a site unit may declare                                       #
# --------------------------------------------------------------------------- #
def test_a_site_unit_declares_the_health_path_its_image_answers_or_none() -> None:
    """The generator serves and probes ``/healthz`` for the site, whatever the unit says, and a
    deploy tool waits on the ``healthPath`` the unit declares: any other path is the site's 404,
    and the deploy never turns ready. So the reader refuses it, with the path it allows."""
    tables = published_tables()
    raw = _golden()
    index, site = next((i, unit) for i, unit in enumerate(raw["units"]) if unit["id"] == "site")
    for allowed in (None, SITE_HEALTH_PATH):
        if allowed is not None:
            site["healthPath"] = allowed
        files, refused = _render(raw)
        assert refused == [] and "wget -q -O /dev/null http://127.0.0.1:8080/healthz" in files[PROFILE].decode()
    site["healthPath"] = "/health/ready"
    spa = next(unit for unit in raw["units"] if unit["id"] == "web")
    spa["healthPath"] = "/ready"  # the SPA beside it names no recipe: its config is the app's own
    declared, findings = reader.read(raw, tables.datastores, tables.system_packages)
    assert declared is None and [(finding.message, finding.remedy) for finding in findings] == [(
        f'units[{index}].healthPath is "/health/ready", and generator.recipes.site builds the unit '
        'with "static-site", whose image answers its health at /healthz alone (allowed: /healthz, '
        "or no healthPath)",
        'Declare "healthPath": "/healthz" or leave it out: a deploy tool waits on the path a unit '
        "declares, and the recipe's server answers no other.",
    )]


def test_every_recipe_the_schema_allows_says_where_its_image_answers() -> None:
    """The reader's table and the recipe's server cannot drift: the path the reader allows is
    the one the image answers, and a recipe the schema adds has no reading until it has one."""
    words = reader.schema()["else"]["properties"]["generator"]["properties"]["recipes"]
    (allowed,) = [rule["enum"] for pattern, rule in words["patternProperties"].items() if pattern != "^\\$"]
    assert sorted(reader.RECIPE_HEALTH_PATHS) == sorted(allowed) == [STATIC_SITE]
    assert reader.RECIPE_HEALTH_PATHS[STATIC_SITE] == SITE_HEALTH_PATH
    assert f"location = {SITE_HEALTH_PATH} {{" in _heredoc(_site_dockerfile(), "TERP_SITE_NGINX")


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
    run = subprocess.run(
        [sys.executable, "-I", "-c", _signer_render._RENDER, str(tmp_path / "arch"), str(tmp_path), str(tree)],
        capture_output=True, text=True, check=False,
    )
    assert run.returncode == 0, run.stderr
    answer = json.loads(run.stdout)
    assert answer["refused"] == [] and list(answer["files"]) == ["docker-compose.prod.yml"]
    assert answer["owned"] == ["Dockerfile.prod", "frontend/Dockerfile.prod", "docker-compose.prod.yml"]
