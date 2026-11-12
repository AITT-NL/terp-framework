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

Four targets:

* the app in the current directory (the default): everything above. The platform half reads
  the environment the command runs in, so it runs in the app: ``uv run --frozen terp
  maintenance``;
* ``--commit SHA``: a commit of this repository, read the way ``terp release sign`` reads one
  (every file of the commit through git, never the working tree) and planned the way a
  release is; known vulnerabilities only. This is how a scheduler audits what an environment
  runs: the commit its release was built from;
* ``--tree DIR``: the locks of another checkout on disk; known vulnerabilities only;
* ``--release DIR``: a signed release bundle, its SBOMs re-asked of the database ``sign``
  recorded; known vulnerabilities only, each saying whether it is new since the release was
  signed.

By default only a package a public registry serves is sent to the database; the rest are named
in ``not_checked``. ``--send-private-names``, or ``--osv`` naming a mirror, sends them too.
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
    target = parser.add_mutually_exclusive_group()
    target.add_argument(
        "--commit",
        metavar="SHA",
        help="Report the known vulnerabilities of a commit of this repository instead, read as a "
        "release reads it (what an environment runs: the commit its release was built from)",
    )
    target.add_argument(
        "--tree",
        metavar="DIR",
        help="Report the known vulnerabilities in the locks of another checkout instead",
    )
    target.add_argument(
        "--release",
        metavar="DIR",
        help="Report the known vulnerabilities of a signed release bundle (terp release sign's output) instead",
    )
    parser.add_argument(
        "--osv",
        default=None,
        metavar="URL",
        help=f"The vulnerability database's API (default: {DEFAULT_OSV}, or for --release the one sign "
        "recorded); a mirror answers the same API and also receives the names of private packages",
    )
    parser.add_argument(
        "--send-private-names",
        action="store_true",
        help="Also send the names of packages from an index that is not public to the default database",
    )


def _audit(report: Any, root: pathlib.Path, osv: str, *, only_public: bool) -> None:
    """The known-vulnerability half for the locks at *root*, and each manifest left unlocked."""
    from terp.cli.maintenance import _packages, _vulnerabilities

    found = _packages.inventory(root)
    for sentence in found.unlocked:
        report.not_made(sentence)
    _vulnerabilities.vulnerability_findings(report, found.packages, osv, only_public=only_public)


def _nothing_to_read(root: pathlib.Path, what: str) -> None:
    from terp.cli.maintenance import _packages

    if not _packages.inventory(root).anything:
        raise ReleaseError(
            f"{what} holds no lock and no manifest (uv.lock, pyproject.toml, a package.json), so "
            "there is nothing to report on"
        )


def _build_report(args: argparse.Namespace) -> Any:
    import tempfile

    from terp.cli.maintenance import _images, _packages, _platform, _report, _vulnerabilities

    mirror = args.osv is not None and args.osv.rstrip("/") != DEFAULT_OSV
    only_public = not (args.send_private_names or mirror)
    if args.release is not None:
        bundle_dir = pathlib.Path(args.release).resolve()
        bundle = _packages.bundle_packages(bundle_dir)
        report = _report.Report("release", str(bundle_dir), release=bundle.tag)
        # A release re-asks what sign asked, of the database it asked: nothing new leaves.
        osv = args.osv or bundle.database or DEFAULT_OSV
        _vulnerabilities.vulnerability_findings(
            report, bundle.packages, osv, recorded=bundle.recorded, only_public=False
        )
        return report
    osv = args.osv or DEFAULT_OSV
    if args.tree is not None:
        tree = pathlib.Path(args.tree).resolve()
        if not tree.is_dir():
            raise ReleaseError(f"--tree {args.tree} is not a directory")
        _nothing_to_read(tree, f"--tree {args.tree}")
        report = _report.Report("tree", str(tree))
        _audit(report, tree, osv, only_public=only_public)
        return report
    here = pathlib.Path.cwd()
    if args.commit is not None:
        from terp.cli.release._git import Tree

        commit = Tree.read(here, args.commit)
        with tempfile.TemporaryDirectory(prefix="terp-maintenance-") as scratch:
            root = pathlib.Path(scratch) / "tree"
            commit.materialize(root)
            _nothing_to_read(root, f"the commit {args.commit}")
            report = _report.Report("commit", str(here), commit=args.commit)
            _audit(report, root, osv, only_public=only_public)
        return report
    if not (here / "pyproject.toml").is_file():
        raise ReleaseError(f"{here} holds no pyproject.toml, so it is no app to report on: run it in the app")
    report = _report.Report("app", str(here))
    platform = _platform.python_platform(here, report)
    if platform is not None:
        _platform.template(here, report, platform)
    _platform.npm_platform(here, report)
    _audit(report, here, osv, only_public=only_public)
    _images.base_image_findings(here, report)
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
