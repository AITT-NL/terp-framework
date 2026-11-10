"""The npm trees an app keeps, as the npm checks of ``terp verify`` read them.

An app on Terp has more than one npm tree (``frontend/`` and ``conformance/`` from the template,
a static site's ``site/``, and any of its own), and each npm check runs in one of them. This
says which tree an ``npm`` argument list works in, and whether that tree's ``node_modules`` can
run it on this machine: one never installed, or installed for another platform, is named with
its fix before npm's own stack trace says nothing useful. :mod:`terp.cli.verify` keeps the
names its checks and its tests use.
"""

from __future__ import annotations

import json
import pathlib
import sys


def node_platform() -> tuple[str, str]:
    """This machine as npm names it — ``process.platform`` / ``process.arch``."""
    import platform as _platform

    system = {"win32": "win32", "darwin": "darwin"}.get(sys.platform, "linux")
    machine = _platform.machine().lower()
    arch = {
        "amd64": "x64",
        "x86_64": "x64",
        "aarch64": "arm64",
        "arm64": "arm64",
    }.get(machine, machine)
    return system, arch


def node_libc(system: str) -> str | None:
    """This machine's libc flavour as npm names it, or None where npm ignores it.

    npm gates Linux binaries on ``libc`` as well as ``os``/``cpu``: a x64 Linux
    bundler ships a ``-gnu`` *and* a ``-musl`` binding and installs exactly one.
    Reading only ``os``/``cpu`` therefore reports the flavour this machine is not,
    turning a perfectly healthy tree red.
    """
    if system != "linux":
        return None
    return "musl" if any(pathlib.Path("/lib").glob("ld-musl-*.so.1")) else "glibc"


def argv_workspace(argv: list[str]) -> str:
    """Which directory an ``npm`` argv installs into and reads, relative to the root.

    ``npm --prefix conformance test`` resolves against ``conformance/node_modules``;
    the same command without a prefix uses the directory npm runs in, which for a
    manifest command is the project root. Read out of the argv rather than assumed,
    because an app on Terp has more than one npm tree: the template ships
    ``frontend/`` *and* ``conformance/`` (``terp.cli.verify._terp_frontend_manifests``
    discovers both rather than naming one), and the profile is open at the app end
    (ADR 0106) so a third is the app's business.

    A precondition read against the wrong tree is worse than none. It refuses a
    check whose own tree is installed and healthy — naming a fix that has nothing
    to do with the failure — while passing the tree that is actually missing,
    straight into the raw Node stack the precondition exists to replace.
    """
    for index, token in enumerate(argv):
        if token == "--prefix":
            following = argv[index + 1 : index + 2]
            # A dangling `--prefix` is npm's own argv to complain about, not a
            # precondition failure: fall back to the root so the guard stays quiet
            # and the command reports its own usage error.
            return following[0] if following else "."
        if token.startswith("--prefix="):
            return token.removeprefix("--prefix=") or "."
    return "."


def node_modules_problem(root: pathlib.Path, workspace: str) -> str | None:
    """Explain an unusable ``<workspace>/node_modules``, or None if it looks fine.

    An npm install is platform-specific: the native binaries a bundler needs are
    optional dependencies gated on ``os``/``cpu``, so a tree installed on the
    Windows host has no Linux binary, and running the gate in the container dies
    with a raw Node stack (``Cannot find module '@rolldown/binding-linux-x64-gnu'``)
    that names neither the cause nor the fix. Every Terp failure states the fix, so
    this is detected up front rather than left to the reader to decode.

    The lockfile already records which optional packages belong on which platform,
    so the check is exact and needs no list of native package names to maintain.

    *workspace* is required rather than defaulted to ``frontend``: an implicit
    default is what let every npm check be judged by the frontend tree, and a
    caller that has to name its tree cannot inherit the wrong one silently.
    """
    directory = root / workspace
    if not (directory / "package.json").is_file():
        return None
    # `npm ci` with no prefix is the shape a root-level manifest command has, and
    # `./node_modules`, `npm --prefix . ci` and "the . checks" would all read as a typo.
    root_level = workspace == "."
    label = "node_modules" if root_level else f"{workspace}/node_modules"
    fix = "npm ci" if root_level else f"npm --prefix {workspace} ci"
    subject = "the root npm checks" if root_level else f"the {workspace} checks"
    modules = directory / "node_modules"
    if not modules.is_dir():
        return f"{label} is missing — {subject} cannot run.\n  Fix: {fix}"

    lockfile = directory / "package-lock.json"
    if not lockfile.is_file():
        return None
    try:
        packages = json.loads(lockfile.read_text(encoding="utf-8")).get("packages", {})
    except (OSError, ValueError):
        return None

    # A directory with none of the lockfile's platform-neutral packages in it is not
    # a tree for another platform but no tree at all -- an install that never ran,
    # or a fresh mount point. Calling it "a different platform" sends the reader
    # looking for a second machine that does not exist. Neutral ones only: every
    # platform installs those, so not one of them present means nothing was.
    neutral = [
        name
        for name, entry in packages.items()
        if name.startswith("node_modules/")
        and isinstance(entry, dict)
        and not (entry.get("os") or entry.get("cpu") or entry.get("libc"))
    ]
    if neutral and not any((directory / name).exists() for name in neutral):
        return (
            f"{label} is missing (the directory is there, but holds none of the "
            f"lockfile's packages) — {subject} cannot run.\n  Fix: {fix}"
        )

    system, arch = node_platform()
    libc = node_libc(system)
    missing = [
        name
        for name, entry in packages.items()
        if name.startswith("node_modules/")
        and isinstance(entry, dict)
        # Only packages this platform is *supposed* to have: an entry with no
        # os/cpu/libc constraint is platform-neutral, and one constrained elsewhere
        # is absent by design rather than by a bad install.
        and system in (entry.get("os") or [system])
        and arch in (entry.get("cpu") or [arch])
        and (libc is None or libc in (entry.get("libc") or [libc]))
        and (entry.get("os") or entry.get("cpu") or entry.get("libc"))
        and not (directory / name).exists()
    ]
    if not missing:
        return None
    return (
        f"{label} was installed for a different platform: "
        f"{len(missing)} package(s) this machine ({system}/{arch}) needs are absent, "
        f"e.g. {missing[0].removeprefix('node_modules/')}.\n"
        "  This happens when the tree is installed on the host and the gate runs in "
        "a container (or vice versa); native binaries are per-platform optional "
        "dependencies and do not travel.\n"
        f"  Fix: {fix}   (run it where the gate runs)"
    )


__all__ = ["argv_workspace", "node_libc", "node_modules_problem", "node_platform"]
