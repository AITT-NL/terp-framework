"""The palette reaches ``<html>`` before the first paint, in every app the repo ships.

A person's theme is their own choice, so it lives in ``localStorage`` and only script
can read it -- and the app's own bundle cannot do it in time. The document body is
empty until React commits, so the browser has already painted a canvas from the token
sheet's ``:root`` (the light palette) by the time ``ThemeProvider`` applies the stored
one: a viewer who chose a dark palette got a white flash on every reload. Not the
viewer who follows their platform -- the sheet's ``prefers-color-scheme`` block covers
that one before paint, with no script at all -- which is why the defect reads as
intermittent until you notice it tracks an *explicit* choice.

``frontend/public/theme-bootstrap.js`` closes it, and every property that makes it
work is invisible in review:

* **Blocking.** ``defer``, ``async`` or ``type="module"`` all run the script after the
  document is parsed, which is the wrong side of the paint it exists to beat. The
  regression is a one-word edit and looks like a modernisation.
* **Own origin.** Production serves ``script-src 'self'`` with no ``'unsafe-inline'``
  while the dev server permits inline script for Vite's own preamble, so the usual
  inline ``<script>`` in ``<head>`` works in development and is silently refused in
  production. Nobody reads that console.
* **In the head, before the entry point.** A tag that lands after the module script
  is not a bootstrap.

And the script duplicates three facts it cannot import -- the storage key, the theme
names and which of them are dark. Each is checked here against its source, so a sixth
theme cannot ship without this file learning about it.
"""

from __future__ import annotations

import pathlib
import re

import pytest

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

_TEMPLATE_FRONTEND = _REPO_ROOT / "template" / "project" / "frontend"
_EXAMPLE_FRONTEND = _REPO_ROOT / "apps" / "example" / "frontend"

#: ``(index.html, public/theme-bootstrap.js)`` per app. The template's document is a
#: Jinja file; the parts this reads are plain HTML either way.
_APPS = (
    (
        _TEMPLATE_FRONTEND / "index.html.jinja",
        _TEMPLATE_FRONTEND / "public" / "theme-bootstrap.js",
    ),
    (
        _EXAMPLE_FRONTEND / "index.html",
        _EXAMPLE_FRONTEND / "public" / "theme-bootstrap.js",
    ),
)

_BOOTSTRAP_TAG = re.compile(r"<script\b[^>]*\bsrc=\"/theme-bootstrap\.js\"[^>]*>")
_MODULE_TAG = re.compile(r"<script\b[^>]*\btype=\"module\"[^>]*>")

#: A quoted string array in the bootstrap: ``var NAME = ["a", "b"];``
def _array(source: str, name: str) -> list[str]:
    match = re.search(rf"var\s+{name}\s*=\s*\[(.*?)\]\s*;", source, re.DOTALL)
    assert match, f"the bootstrap should declare {name}"
    return re.findall(r'"([^"]+)"', match.group(1))


def _bootstrap() -> str:
    return _APPS[0][1].read_text(encoding="utf-8")


@pytest.mark.parametrize("index_html,script", _APPS, ids=("template", "example"))
def test_every_app_serves_the_bootstrap_blocking_from_its_own_head(
    index_html: pathlib.Path, script: pathlib.Path
) -> None:
    assert script.is_file(), f"{script} is the asset the tag below points at"
    document = index_html.read_text(encoding="utf-8")

    tag = _BOOTSTRAP_TAG.search(document)
    assert tag, f"{index_html} must serve /theme-bootstrap.js"

    # Blocking. Each of these three attributes moves the script to after the parse, and
    # the flash comes back with no other symptom.
    for attribute in ("defer", "async", 'type="module"'):
        assert attribute not in tag.group(0), (
            f"{index_html}: the bootstrap must be a blocking classic script; "
            f"{attribute} runs it after the document is parsed, which is after the "
            "first paint"
        )

    # In the head, and before the entry point. Written as two independent positions
    # rather than one, because a tag inside <body> before the module script would
    # satisfy an ordering check alone and still paint first.
    head = document.index("</head>")
    assert tag.start() < head, f"{index_html}: the bootstrap belongs in the document head"
    entry = _MODULE_TAG.search(document)
    assert entry, f"{index_html} should load a module entry point"
    assert tag.start() < entry.start(), (
        f"{index_html}: the bootstrap must precede the app's own bundle"
    )


def test_the_apps_ship_the_same_bootstrap() -> None:
    # Byte-identical, like the changelog mirrors: the example app is the reference an
    # app is generated to resemble, so a fix applied to one copy and not the other
    # leaves the two disagreeing about a defect that is invisible in both.
    template, example = _APPS[0][1], _APPS[1][1]
    assert template.read_bytes() == example.read_bytes(), (
        f"{example} must be a byte-identical copy of {template}"
    )


def test_the_bootstrap_reads_the_key_the_provider_writes() -> None:
    # One typo here and the script reads an empty box on every load: no error, no
    # attribute, and the flash is back exactly as it was.
    theme_tsx = (
        _REPO_ROOT
        / "packages"
        / "frontend"
        / "react-core"
        / "src"
        / "theme.tsx"
    ).read_text(encoding="utf-8")
    declared = re.search(r'THEME_STORAGE_KEY\s*=\s*"([^"]+)"', theme_tsx)
    assert declared, "theme.tsx should declare THEME_STORAGE_KEY"
    read = re.search(r'var\s+STORAGE_KEY\s*=\s*"([^"]+)"\s*;', _bootstrap())
    assert read, "the bootstrap should declare STORAGE_KEY"
    assert read.group(1) == declared.group(1), (
        "the bootstrap must read the key ThemeProvider persists under"
    )


def test_the_bootstrap_validates_against_the_shipped_theme_list() -> None:
    # The script refuses to stamp a name it does not know, because an unknown
    # ``data-theme`` selects no palette block AND suppresses the platform default with
    # it. That check is only as good as the list, and the list is published elsewhere.
    themes_ts = (
        _REPO_ROOT
        / "packages"
        / "frontend"
        / "react-core"
        / "src"
        / "themes.ts"
    ).read_text(encoding="utf-8")
    published = re.search(r"THEMES:\s*readonly\s+Theme\[\]\s*=\s*\[(.*?)\]", themes_ts, re.DOTALL)
    assert published, "themes.ts should declare THEMES"
    assert sorted(_array(_bootstrap(), "THEMES")) == sorted(
        re.findall(r'"([^"]+)"', published.group(1))
    ), "the bootstrap's theme list must be the list the provider validates against"


def test_the_bootstrap_knows_which_palettes_are_dark() -> None:
    # The appearance half. ``color-scheme`` is what the browser paints the canvas and
    # the native scrollbars from, and it is declared per theme in the token sheet --
    # which the entry point IMPORTS, so in a dev server it arrives with the bundle and
    # the attribute alone has no palette to paint from. The script therefore says the
    # appearance itself, and this holds its list to the sheet's own blocks: a sixth
    # theme, or a palette that changes appearance, fails here rather than shipping a
    # white flash to half its viewers.
    tokens_css = (
        _REPO_ROOT
        / "packages"
        / "frontend"
        / "contract"
        / "src"
        / "tokens.css"
    ).read_text(encoding="utf-8")
    dark_blocks = {
        name
        for name, body in re.findall(
            r"\[data-theme='(\w+)'\]\s*\{(.*?)\}", tokens_css, re.DOTALL
        )
        if "color-scheme: dark" in body
    }
    assert dark_blocks, "the token sheet should declare color-scheme per theme"
    assert set(_array(_bootstrap(), "DARK")) == dark_blocks, (
        "the bootstrap's dark list must be the themes the token sheet paints dark"
    )


def test_the_provider_gives_the_inline_bridge_back() -> None:
    # The bootstrap declares ``color-scheme`` inline, and an inline value outranks
    # every rule in every layer -- so keeping it would pin the native chrome to
    # whatever was stored at load: pick a light palette after loading on a dark one and
    # the scrollbars, the caret and the select popup stay dark on a page that is not.
    # ThemeProvider removes it in the effect that applies the attribute. Held here as
    # well as in the unit test next to the component, because the two halves live in
    # different repositories' worth of context and only one of them is obviously a pair.
    theme_tsx = (
        _REPO_ROOT
        / "packages"
        / "frontend"
        / "react-core"
        / "src"
        / "theme.tsx"
    ).read_text(encoding="utf-8")
    assert 'root.style.removeProperty("color-scheme")' in theme_tsx, (
        "ThemeProvider must hand the bootstrap's inline color-scheme back to the sheet"
    )
