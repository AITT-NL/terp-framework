"""The command line of ``terp release build | gate``.

The parsers are added to ``terp``'s own; each job's module is imported only when it runs. A
refusal prints its sentence (and what a program said, beneath it) on standard error and exits
1; what a job wrote, and where, is its answer on standard output.
"""

from __future__ import annotations

import argparse
import sys
from typing import Any

from terp.cli._output import emit


def add_parsers(subcommands: Any) -> None:
    """``terp release`` with its jobs."""
    release = subcommands.add_parser(
        "release",
        help="Cut a release: build from the pristine tree, gate without credentials (ADR 0187)",
    )
    jobs = release.add_subparsers(dest="release_command", required=True)

    build = jobs.add_parser("build", help="Build and push the commit's images from its pristine tree")
    gate = jobs.add_parser("gate", help="Run the release profile and read the schedules from the pushed image")
    for parser in (build, gate):
        parser.add_argument("--sha", required=True, help="The exact commit (full object name)")
        parser.add_argument("--repo", default=".", help="The git repository (default: .)")
    build.add_argument("--tag", required=True, help="The release tag: the value TERP_RELEASE_TAG takes")
    build.add_argument("--registry", required=True, help="host[:port][/path] the images are pushed under")
    build.add_argument(
        "--registry-http",
        action="store_true",
        help="The registry speaks plain HTTP on this machine's loopback (a job-local one)",
    )
    build.add_argument("--platform", default="linux/amd64", help="The one platform built (default: linux/amd64)")
    build.add_argument("--out", default="terp-release-build.json", help="The build document to write")
    gate.add_argument("--build", required=True, help="The build document terp release build wrote")
    gate.add_argument("--out", default="terp-release-gate.json", help="The gate document to write")
    gate.add_argument("--pull-credentials", default=None, help="A docker config.json holding only a pull credential")


def run_release(args: argparse.Namespace) -> int:
    """Run the job *args* names; its exit code."""
    from terp.cli.release._common import ReleaseError, write_document

    try:
        if args.release_command == "build":
            from terp.cli.release.build import build

            document = build(args.repo, args.sha, args.tag, args.registry, platform=args.platform, registry_http=args.registry_http)
            write_document(args.out, document)
            for image in document["images"]:
                emit(f"pushed {image['repository']}:{image['tag']} as {image['digest']}")
            emit(f"wrote {args.out}")
            return 0
        from terp.cli.release.gate import gate

        document = gate(args.repo, args.sha, args.build, pull_credentials=args.pull_credentials)
        write_document(args.out, document)
        emit(f"read {len(document['schedules'])} schedules from {document['image']}")
        emit(f"the release-assurance claim {'holds' if document['assurance']['ok'] else 'does NOT hold'}")
        emit(f"wrote {args.out}")
        return 0 if document["assurance"]["ok"] else 1
    except ReleaseError as exc:
        sys.stderr.write(f"{exc}\n")
        return 1


__all__ = ["add_parsers", "run_release"]
