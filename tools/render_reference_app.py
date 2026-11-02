"""Render the public-safe reference app: the template, a pinned set of answers, an overlay.

The reference app (``apps/reference``) is what every lane runs in place of a real client
application — this repository's CI and any downstream test lane. It is not
committed as a rendered tree, for the reason template acceptance renders rather than
copies: a committed render is a second definition of the template, frozen at the commit
it was taken from, and its version pins with it. So it is produced the way a client
repository is, every time:

1. ``copier copy`` of ``template/`` with ``apps/reference/answers.yml``;
2. the template's ``pyproject.toml`` grown by the distributions and the companion root the
   app adds (:func:`extend_pyproject`), each new pin taken from the template's own
   lockstep pin rather than written down a second time;
3. ``apps/reference/overlay/`` copied over the render: the module, the companion, their
   tests, and the files a client app owns or has changed.

Usage::

    python tools/render_reference_app.py DEST           # DEST must not exist yet
    python tools/render_reference_app.py --record-baseline

An overlay file that replaces one the template still owns (``app/main.py``, the compose
files, ...) is a copy that goes stale when the template changes, which is the upgrade
every client app meets as a ``copier update`` conflict. ``template-baseline.json``
records the digest of each such template source; the gate fails when one moves, naming
the file to carry the change into, and ``--record-baseline`` writes the new digests once
that is done. The digests are of files in this repository, so the check needs no copier.

Rendering needs Python 3.13+ and copier and nothing else, so a lane outside this
repository's environment runs it from a bare checkout of the framework commit it tests.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
import shlex
import shutil
import subprocess
import sys
from collections.abc import Callable, Sequence

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
TEMPLATE = REPO_ROOT / "template"
TEMPLATE_PROJECT = TEMPLATE / "project"
REFERENCE = REPO_ROOT / "apps" / "reference"
ANSWERS = REFERENCE / "answers.yml"
OVERLAY = REFERENCE / "overlay"
BASELINE = REFERENCE / "template-baseline.json"

#: The distributions the reference app adds to what the template's answers already
#: install: the durable outbox its worker drains, the scheduler process, the mail relay
#: and the declared egress client. Each is pinned to the template's own terp-core pin.
ADDED_DISTRIBUTIONS = (
    "terp-cap-egress",
    "terp-cap-mail",
    "terp-cap-outbox",
    "terp-cap-scheduler-apscheduler",
)

#: The second deployable shipped beside ``app/``: declared as a companion scan root, built
#: into the wheel the production image installs, and fenced off from the app by
#: import-linter contracts (ADR 0141, ``terp guide package-boundaries``).
COMPANION = "monitor"

#: Runs the ``package-boundaries`` check ``terp verify`` turns on once contracts exist.
IMPORT_LINTER = "import-linter>=2.1"

IMPORT_LINTER_CONTRACTS = f"""
# The companion and the app never import each other: {COMPANION}/ ships beside app/ and is
# not mounted by create_app. `terp verify` runs these as its `package-boundaries` check
# (`terp guide package-boundaries`).
[tool.importlinter]
root_packages = ["app", "control_plane", "{COMPANION}"]

[[tool.importlinter.contracts]]
name = "the companion never imports the app"
type = "forbidden"
source_modules = ["{COMPANION}"]
forbidden_modules = ["app", "control_plane"]

[[tool.importlinter.contracts]]
name = "the app never imports the companion"
type = "forbidden"
source_modules = ["app", "control_plane"]
forbidden_modules = ["{COMPANION}"]
"""

Runner = Callable[..., object]


class RenderError(RuntimeError):
    """The template no longer has the shape this renderer edits; say where, and stop."""


def _replace_once(text: str, old: str, new: str, *, what: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RenderError(
            f"pyproject.toml: expected exactly one {what} ({old.strip()!r}), found "
            f"{count}. The template changed shape; update {pathlib.Path(__file__).name} "
            "to match it."
        )
    return text.replace(old, new, 1)


def extend_pyproject(text: str) -> str:
    """Grow the rendered ``pyproject.toml`` by what the reference app adds.

    Edits at named anchors and refuses when an anchor is missing or repeated, so a
    template change that moves one fails here, by name, instead of rendering an app with
    half its declarations.
    """
    pin = re.search(r'^\s*"terp-core==([^"]+)",$', text, re.MULTILINE)
    if pin is None:
        raise RenderError("pyproject.toml: no terp-core pin to take the release from")
    version = pin.group(1)
    audit = re.search(r'^\s*"terp-cap-audit==[^"]+",\n', text, re.MULTILINE)
    if audit is None:
        raise RenderError("pyproject.toml: no terp-cap-audit line to add dependencies after")
    added = "".join(f'    "{name}=={version}",\n' for name in ADDED_DISTRIBUTIONS)
    text = (
        text[: audit.end()]
        + "    # The reference app's additions (apps/reference): its worker, scheduler,\n"
        + "    # mail relay and declared egress client.\n"
        + added
        + text[audit.end() :]
    )
    dev = re.search(r'^(dev = \[.*)\]$', text, re.MULTILINE)
    if dev is None:
        raise RenderError("pyproject.toml: no single-line `dev = [...]` dependency group")
    text = text[: dev.start()] + f'{dev.group(1)}, "{IMPORT_LINTER}"]' + text[dev.end() :]
    text = _replace_once(
        text,
        '\napp_packages = ["control_plane"]\n',
        f'\napp_packages = ["control_plane"]\ncompanions = ["{COMPANION}"]\n',
        what="[tool.terp.arch] app_packages",
    )
    text = _replace_once(
        text,
        'known_first_party = ["app", "control_plane"]',
        f'known_first_party = ["app", "control_plane", "{COMPANION}"]',
        what="[tool.deptry] known_first_party",
    )
    text = _replace_once(
        text,
        'packages = ["app", "control_plane"]',
        f'packages = ["app", "control_plane", "{COMPANION}"]',
        what="[tool.hatch.build.targets.wheel] packages",
    )
    if "[tool.importlinter]" in text:
        raise RenderError("pyproject.toml: the template already declares [tool.importlinter]")
    return text.rstrip("\n") + "\n" + IMPORT_LINTER_CONTRACTS


def overlay_files() -> list[str]:
    """Every file the overlay lays over a render, as a POSIX path relative to it."""
    return sorted(
        path.relative_to(OVERLAY).as_posix()
        for path in OVERLAY.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    )


def apply_overlay(dest: pathlib.Path) -> list[str]:
    """Copy the overlay over the rendered app at *dest*; return what was written."""
    written = overlay_files()
    for relative in written:
        target = dest / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(OVERLAY / relative, target)
    return written


def template_source(relative: str) -> pathlib.Path | None:
    """The template file that renders to *relative*, if the template renders it at all."""
    for candidate in (TEMPLATE_PROJECT / relative, TEMPLATE_PROJECT / f"{relative}.jinja"):
        if candidate.is_file():
            return candidate
    return None


def _skipped_if_exists() -> set[str]:
    """The files copier seeds once and never rewrites: the app's from the first render."""
    # Imported here, not at the top: rendering needs only the standard library and copier,
    # so another lane can run this from a bare checkout. Only the baseline reads YAML.
    import yaml  # noqa: PLC0415 - see above

    config = yaml.safe_load((TEMPLATE / "copier.yml").read_text(encoding="utf-8"))
    return set(config.get("_skip_if_exists", ()))


def replaced_template_files() -> list[str]:
    """Overlay files that replace a file the template still owns and may change."""
    skipped = _skipped_if_exists()
    return [
        relative
        for relative in overlay_files()
        if relative not in skipped and template_source(relative) is not None
    ]


def _digest(path: pathlib.Path) -> str:
    """A line-ending-proof digest, so a Windows checkout reads the same as CI's."""
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def template_digests() -> dict[str, str]:
    """The current digest of the template source behind every replaced file."""
    digests: dict[str, str] = {}
    for relative in replaced_template_files():
        source = template_source(relative)
        assert source is not None  # replaced_template_files only returns rendered files
        digests[relative] = _digest(source)
    return digests


def record_baseline() -> dict[str, str]:
    """Write the current digests to ``template-baseline.json`` and return them."""
    digests = template_digests()
    document = {
        "//": (
            "The template source each overlay file replaces, by digest. When the gate "
            "says one moved, carry the template's change into the overlay copy (or "
            "decide it does not apply), then run "
            "`python tools/render_reference_app.py --record-baseline`."
        ),
        "files": digests,
    }
    BASELINE.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8", newline="\n")
    return digests


def render(
    dest: pathlib.Path,
    *,
    copier: Sequence[str] = ("uvx", "copier"),
    run: Runner = subprocess.run,
) -> list[str]:
    """Render the reference app into *dest*, which must not exist yet."""
    if dest.exists():
        raise RenderError(f"{dest} already exists; render into a fresh directory")
    run(
        [
            *copier,
            "copy",
            "--defaults",
            "--trust",
            "--data-file",
            str(ANSWERS),
            str(TEMPLATE),
            str(dest),
        ],
        check=True,
    )
    pyproject = dest / "pyproject.toml"
    pyproject.write_text(
        extend_pyproject(pyproject.read_text(encoding="utf-8")),
        encoding="utf-8",
        newline="\n",
    )
    return apply_overlay(dest)


def main(argv: Sequence[str] | None = None, *, run: Runner = subprocess.run) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("dest", nargs="?", type=pathlib.Path, help="Directory to render into")
    parser.add_argument(
        "--copier",
        default="uvx copier",
        help="How to invoke copier (default: 'uvx copier')",
    )
    parser.add_argument(
        "--record-baseline",
        action="store_true",
        help="Record the digests of the template files the overlay replaces, then exit",
    )
    args = parser.parse_args(argv)
    if args.record_baseline:
        for relative in record_baseline():
            print(f"recorded {relative}")
        return 0
    if args.dest is None:
        parser.error("DEST is required unless --record-baseline is given")
    try:
        written = render(args.dest, copier=shlex.split(args.copier), run=run)
    except RenderError as exc:
        print(f"render_reference_app: {exc}", file=sys.stderr)
        return 1
    print(f"rendered the reference app into {args.dest} ({len(written)} overlay files)")
    return 0


if __name__ == "__main__":  # pragma: no cover - entry point
    raise SystemExit(main())
