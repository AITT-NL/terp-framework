"""The command line of ``terp release build | gate | sign``.

The parsers are added to ``terp``'s own; each job's module is imported only when it runs. A
refusal prints its sentence (and what a program said, beneath it) on standard error and exits
1; what a job wrote, and where, is its answer on standard output.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from terp.cli._output import emit


def add_parsers(subcommands: Any) -> None:
    """``terp release`` with its jobs."""
    release = subcommands.add_parser(
        "release",
        help="Cut a release in three jobs: build from the pristine tree, gate without credentials, "
        "sign without running the app (ADR 0187)",
    )
    jobs = release.add_subparsers(dest="release_command", required=True)

    build = jobs.add_parser("build", help="Build and push the commit's images from its pristine tree")
    gate = jobs.add_parser("gate", help="Run the release profile and read the schedules from the pushed image")
    sign = jobs.add_parser("sign", help="Check the pushed images against the commit, then sign the manifest")
    for parser in (build, gate, sign):
        parser.add_argument("--sha", required=True, help="The exact commit (full object name)")
        parser.add_argument("--repo", default=".", help="The git repository (default: .)")
    for parser in (build, sign):
        parser.add_argument("--tag", required=True, help="The release tag: the value TERP_RELEASE_TAG takes")
        parser.add_argument("--registry", required=True, help="host[:port][/path] the images are pushed under")
        parser.add_argument(
            "--registry-http",
            action="store_true",
            help="The registry speaks plain HTTP on this machine's loopback (a job-local one)",
        )
    build.add_argument("--platform", default="linux/amd64", help="The one platform built (default: linux/amd64)")
    build.add_argument("--out", default="terp-release-build.json", help="The build document to write")
    gate.add_argument("--build", required=True, help="The build document terp release build wrote")
    gate.add_argument("--out", default="terp-release-gate.json", help="The gate document to write")
    gate.add_argument("--pull-credentials", default=None, help="A docker config.json holding only a pull credential")
    sign.add_argument("--build", required=True, help="The build document")
    sign.add_argument("--gate", required=True, help="The gate document")
    sign.add_argument(
        "--hosts", required=True, choices=("separated", "shared"),
        help="Whether build, gate and sign ran on separate, discarded hosts (recorded in the manifest)",
    )
    sign.add_argument("--out-dir", default=".", help="Where the envelope, the manifest and the SBOMs go")
    sign.add_argument("--signer", default=None, help='The signer, a JSON argument list: ["kms-sign", "--key", "release"]')
    sign.add_argument("--public-key", default=None, help="The public key the signer signs with (PEM)")
    sign.add_argument("--sign-key", default=None, help="A private key file (PEM): refused without --test-key")
    sign.add_argument("--test-key", action="store_true", help="Allow --sign-key: a throwaway key, in a test")
    sign.add_argument("--terp-arch-releases", default=None, help="The signer's terp-arch release table")
    sign.add_argument("--terp-index", default=None, help="The index (or directory) the pinned terp-arch wheel comes from")
    sign.add_argument("--registry-credentials", default=None, help='A JSON file {"username": ..., "password": ...}')
    sign.add_argument("--osv", default=None, help="The vulnerability database (default: https://api.osv.dev)")
    sign.add_argument("--gitleaks", default="gitleaks", help="The gitleaks executable (default: gitleaks on PATH)")



def _signer(value: str | None) -> list[str] | None:
    if value is None:
        return None
    try:
        argv = json.loads(value)
    except ValueError:
        argv = None
    if not isinstance(argv, list) or not argv or not all(isinstance(part, str) for part in argv):
        raise argparse.ArgumentTypeError('--signer is a JSON list of strings, such as ["kms-sign", "--key", "x"]')
    return argv


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
        if args.release_command == "gate":
            from terp.cli.release.gate import gate

            document = gate(args.repo, args.sha, args.build, pull_credentials=args.pull_credentials)
            write_document(args.out, document)
            emit(f"read {len(document['schedules'])} schedules from {document['image']}")
            emit(f"the release-assurance claim {'holds' if document['assurance']['ok'] else 'does NOT hold'}")
            emit(f"wrote {args.out}")
            return 0 if document["assurance"]["ok"] else 1
        from terp.cli.release.sign import sign

        options: dict[str, Any] = {
            key: value for key, value in (
                ("releases", args.terp_arch_releases), ("index", args.terp_index), ("osv", args.osv),
            ) if value is not None
        }
        done = sign(
            args.repo, args.sha, args.tag, args.registry, args.build, args.gate, args.out_dir,
            hosts=args.hosts, signer=_signer(args.signer), public_key=args.public_key,
            sign_key=args.sign_key, test_key=args.test_key, registry_http=args.registry_http,
            registry_credentials=args.registry_credentials, gitleaks=args.gitleaks, **options,
        )
        emit(f"signed {', '.join(done['images'])} with key {done['keyid'][:16]}")
        emit(f"wrote {done['envelope']}")
        return 0
    except (ReleaseError, argparse.ArgumentTypeError) as exc:
        sys.stderr.write(f"{exc}\n")
        return 1


__all__ = ["add_parsers", "run_release"]
