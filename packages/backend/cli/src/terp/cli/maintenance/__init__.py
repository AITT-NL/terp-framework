"""``terp maintenance`` and ``terp upgrade``: what an app should maintain, as a report (ADR 0214).

``terp upgrade --check`` answers one question, whether a newer Terp is out, and prints the
recipe. ``terp maintenance`` answers every question a scheduled check asks of an app: the
platform and its scaffolding (that same answer), each locked package against the published
advisories, and the base images an app pins itself. It reads the app and asks the package
indexes, the vulnerability database and the image registries. It changes nothing, and it is
not a gate: it exits 0 whatever it finds, and 2 only when it could not report at all.

It runs wherever its caller schedules it: cron, any CI, or a workbench. Nothing in it reads a
code host's API, and the vulnerability database is OSV, through the client ``terp release
sign`` asks it with, so a report and a signed manifest cannot disagree about where they asked.

Three targets:

* the app at ``--root`` (the default): everything above;
* ``--tree DIR``: the locks of another checkout of the app, such as the commit a release was
  built from, read by the environment at ``--root``; known vulnerabilities only;
* ``--release DIR``: a signed release bundle, its SBOMs re-asked; known vulnerabilities only,
  each saying whether it is new since the release was signed.
"""

from __future__ import annotations

import argparse
import pathlib
import sys
from typing import Any

from terp.cli._output import emit
from terp.cli.release._common import ReleaseError
from terp.cli.release._osv import DEFAULT_OSV

#: Exit codes: the report was written (whatever it found), or it could not be.
REPORTED, UNREPORTED = 0, 2


def add_parsers(subcommands: Any) -> None:
    """Register ``terp upgrade`` and ``terp maintenance``."""
    upgrade_parser = subcommands.add_parser(
        "upgrade",
        help="Check whether a newer Terp release is available for the whole set",
    )
    upgrade_parser.add_argument(
        "--check",
        action="store_true",
        help="Report the available release and the bump recipe (the only mode: "
        "Terp reports, it does not edit your manifests)",
    )
    upgrade_parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Output format: text (the recipe) or json (the same facts as data — "
        "installed, current, target, covers_whole_set, stragglers, rerender_blocker)",
    )

    parser = subcommands.add_parser(
        "maintenance",
        help="Report what this app should maintain: a newer platform, a behind scaffolding, "
        "known vulnerabilities in its locks, moved base images. A report, never a gate",
    )
    parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="text (for a person) or json (the terp_maintenance document a scheduler stores)",
    )
    parser.add_argument("--root", default=".", help="The app (default: the current directory)")
    target = parser.add_mutually_exclusive_group()
    target.add_argument(
        "--tree",
        metavar="DIR",
        help="Report the known vulnerabilities in the locks of another checkout of the app instead",
    )
    target.add_argument(
        "--release",
        metavar="DIR",
        help="Report the known vulnerabilities of a signed release bundle (terp release sign's output) instead",
    )
    parser.add_argument(
        "--osv",
        default=DEFAULT_OSV,
        metavar="URL",
        help=f"The vulnerability database's API (default: {DEFAULT_OSV}); a mirror answers the same API",
    )


def _build_report(args: argparse.Namespace) -> Any:
    from terp.cli.maintenance import _images, _packages, _platform, _report, _vulnerabilities

    if args.release is not None:
        bundle_dir = pathlib.Path(args.release).resolve()
        bundle = _packages.bundle_packages(bundle_dir)
        report = _report.Report("release", str(bundle_dir), release=bundle.tag)
        _vulnerabilities.vulnerability_findings(report, bundle.packages, args.osv, recorded=bundle.recorded)
        return report
    if args.tree is not None:
        tree = pathlib.Path(args.tree).resolve()
        if not tree.is_dir():
            raise ReleaseError(f"--tree {args.tree} is not a directory")
        report = _report.Report("tree", str(tree))
        _vulnerabilities.vulnerability_findings(report, _packages.tree_packages(tree), args.osv)
        return report
    root = pathlib.Path(args.root).resolve()
    if not (root / "pyproject.toml").is_file():
        raise ReleaseError(f"{root} holds no pyproject.toml, so it is no app to report on (pass --root)")
    report = _report.Report("app", str(root))
    platform = _platform.python_platform(root, report)
    if platform is not None:
        _platform.template(root, report, platform)
    _platform.npm_platform(root, report)
    _vulnerabilities.vulnerability_findings(report, _packages.tree_packages(root), args.osv)
    _images.base_image_findings(root, report)
    return report


def run(args: argparse.Namespace) -> int:
    """``terp upgrade`` or ``terp maintenance``: the exit code."""
    if args.command == "upgrade":
        from terp.cli.version import render_upgrade_check

        if not args.check:
            raise SystemExit(
                "terp upgrade: run `terp upgrade --check`. Terp reports what is "
                "available and how to bump; it does not edit your manifests, because "
                "a lockstep bump spans pyproject.toml and frontend/package.json and "
                "must be reviewed as one change."
            )
        emit(render_upgrade_check(fmt=args.format))
        return REPORTED
    try:
        report = _build_report(args)
    except ReleaseError as exc:
        sys.stderr.write(f"terp maintenance: could not report: {exc}\n")
        return UNREPORTED
    emit(report.as_json() if args.format == "json" else report.as_text())
    return REPORTED


__all__ = ["REPORTED", "UNREPORTED", "add_parsers", "run"]
