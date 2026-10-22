"""Write the signer image's build context: the framework's wheels, hash-locked (ADR 0187).

The signer image (``packages/backend/cli/signer/Dockerfile``) installs ``terp-cli[release]``
and nothing else, every distribution by its hash: the third-party ones as uv's lock pins them
(``uv export``, with their hashes), and the framework's own as built here, each pinned by the
SHA-256 of the wheel this run built. So the image holds exactly what this commit is, and an
index serving another file under one of those names is refused by pip itself.

Usage::

    python tools/signer_context.py DEST    # DEST must not exist yet

DEST then holds ``Dockerfile``, ``terp-arch-releases.json``, ``requirements.txt`` and
``wheels/``; ``docker build DEST`` builds the image. CI does exactly that, and runs it.
"""

from __future__ import annotations

import argparse
import hashlib
import pathlib
import re
import shutil
import subprocess
import sys
from collections.abc import Callable, Sequence

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
SIGNER = REPO_ROOT / "packages" / "backend" / "cli" / "signer"

#: The distributions terp-cli[release] needs from this repository.
PACKAGES = (
    "packages/backend/core",
    "packages/backend/arch",
    "packages/backend/migrations",
    "packages/backend/cli",
    "packages/backend/capabilities/egress",
)

#: Everything terp-cli[release] needs from the index, with its hashes and no framework package.
EXPORT = (
    "uv", "export", "--package", "terp-cli", "--extra", "release", "--no-dev",
    "--no-emit-workspace", "--no-header", "--no-annotate", "--format", "requirements-txt",
)

_WHEEL = re.compile(r"(?P<name>[A-Za-z0-9_.]+)-(?P<version>[^-]+)-py3-none-any\.whl")

Runner = Callable[[Sequence[str]], str]


def _run(argv: Sequence[str]) -> str:
    return subprocess.run(  # noqa: S603 - a fixed argument list
        list(argv), cwd=REPO_ROOT, capture_output=True, text=True, check=True
    ).stdout


def pinned_wheels(wheels: pathlib.Path) -> list[str]:
    """One ``name==version --hash=sha256:...`` line per wheel built under *wheels*."""
    lines: list[str] = []
    for wheel in sorted(wheels.glob("*.whl")):
        found = _WHEEL.fullmatch(wheel.name)
        if found is None:
            raise SystemExit(f"{wheel.name} is not a pure-Python wheel this context pins")
        name = found.group("name").replace("_", "-")
        digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
        lines.append(f"{name}=={found.group('version')} --hash=sha256:{digest}")
    return lines


def write_context(destination: pathlib.Path, run: Runner = _run) -> None:
    """Build the wheels into *destination* and write the rest of the build context there."""
    if destination.exists():
        raise SystemExit(f"{destination} exists; the context is written into a new directory")
    wheels = destination / "wheels"
    wheels.mkdir(parents=True)
    for package in PACKAGES:
        run(("uv", "build", "--wheel", "--out-dir", str(wheels), package))
    exported = run(EXPORT).strip()
    if "--hash=sha256:" not in exported:
        raise SystemExit("uv export answered no hashes; the signer installs nothing unhashed")
    (destination / "requirements.txt").write_text(
        "\n".join([exported, *pinned_wheels(wheels)]) + "\n", encoding="utf-8"
    )
    for name in ("Dockerfile", "terp-arch-releases.json"):
        shutil.copyfile(SIGNER / name, destination / name)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("destination", type=pathlib.Path)
    args = parser.parse_args(argv)
    write_context(args.destination)
    sys.stdout.write(f"wrote the signer's build context to {args.destination}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
