"""Whether ``copier update`` can re-render this app, here, and from which template.

Split out of ``terp.cli.version`` (``terp --version`` / ``terp upgrade --check``), which reads
these to choose between its two recipes. Every answer here is a LOCAL, certain one: a
re-render is ruled out only on evidence, because ruling it out withholds the recipe that
re-renders and prints the hand-pin one instead.
"""

from __future__ import annotations

import os
import pathlib
import re
import subprocess

#: Copier writes the template ref it rendered from into this file at scaffold time.
_ANSWERS_FILES = (".copier-answers.yml", ".copier-answers.yaml")


def _answers_scalar(root: pathlib.Path, key: str) -> str | None:
    """One top-level scalar from the copier answers file, or ``None``.

    Read with a line scan rather than a YAML parser to keep this module dependency-free
    (the file is generated, and the keys read through here are plain scalars). The split
    takes the FIRST colon, so a Windows ``_src_path`` keeps its drive letter.
    """
    prefix = f"{key}:"
    for name in _ANSWERS_FILES:
        answers = root / name
        try:
            text = answers.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line in text.splitlines():
            if line.startswith(prefix):
                return line.split(":", 1)[1].strip().strip("'\"") or None
    return None


def scaffold_ref(root: pathlib.Path) -> str | None:
    """The template ref this app's scaffolding was rendered from, if it records one.

    ``None`` for an app that was never scaffolded from the template.
    """
    return _answers_scalar(root, "_commit")


#: Reading one ref out of a checkout already on disk, so this guards against a
#: pathological repository rather than budgeting for a network round trip the way
#: ``_UV_TIMEOUT_SECONDS`` does.
_GIT_TIMEOUT_SECONDS = 10


def _git_rc(cwd: pathlib.Path, *args: str) -> int | None:
    """Exit code of a local ``git`` call, or ``None`` when git itself could not run.

    ``None`` means "no answer", never "no". Both callers below are only allowed to rule a
    re-render out on certain evidence, so a git that is missing, refused or slow has to
    leave the recommendation exactly as it found it.
    """
    # The answers-file values ride as argv elements and never as a command line, so a
    # hostile _src_path or ref is an argument git rejects rather than anything it runs.
    argv = ["git", "-C", str(cwd), *args]
    try:
        completed = subprocess.run(  # noqa: S603 — fixed argv, no shell
            argv,
            capture_output=True,
            timeout=_GIT_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return completed.returncode


def _is_git_checkout(root: pathlib.Path) -> bool:
    """Whether *root* sits inside a git work tree, which ``copier update`` needs.

    A ``.git`` entry is proof on its own and costs nothing to look for — it covers the
    ordinary app, which lives at its repository root. Its ABSENCE proves nothing, so that
    case is put to git instead: an app vendored into a subdirectory of a larger repository
    has no ``.git`` of its own and updates perfectly well. Answering from the presence
    check alone would reproduce this command's own bug one level down — a confident wrong
    answer that withholds the recipe the reader needs.
    """
    if (root / ".git").exists():
        return True
    # 128 is git refusing outright: not inside a work tree. Anything else — including no
    # answer at all — leaves the re-render on the table.
    return _git_rc(root, "rev-parse", "--is-inside-work-tree") != 128


def _ref_resolves(source: str, ref: str) -> bool:
    """Whether *ref* is still present in a template checkout at *source*.

    Only ever used to RULE OUT a re-render, so everything it cannot check locally answers
    ``True``: a URL ``_src_path``, a directory that is not there, a git that fails for any
    reason. Reading "could not check" as "missing" would route every network-hosted
    template — the common case, and the one that works — to hand-pinning on no evidence.
    """
    path = pathlib.Path(source)
    if not path.is_dir():
        return True
    # Only a clean "no such ref" (1) proves absence. 128 is git declining the question
    # because `source` is not a repository at all, and a question nobody answered must not
    # be reported as a pruned tag — that would name the wrong obstacle with full
    # confidence, which is the failure this whole check exists to stop making.
    return _git_rc(path, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}") != 1


def _copier_update_blocker(root: pathlib.Path) -> str | None:
    """Why ``copier update`` cannot run here, phrased for the report — or ``None``.

    A recorded ``_commit`` used to be the whole test, and it is only the first of three
    things copier needs. It also needs a git checkout to apply the update to, and a ref
    that still resolves in the template it was rendered from — tags do get pruned, and a
    template pinned to a local path can simply not carry the one recorded here. Both of
    those fail at the recipe's own third step, after it has been followed that far.

    The cost of getting this wrong is asymmetric, which is what makes it worth more than
    a line scan. The two recipes are deliberately mutually exclusive, so a false positive
    does not merely print an unrunnable step: it WITHHOLDS the hand-pin recipe, whose
    step 3 is the one that says to pin every npm manifest rather than only the frontend's.
    A stale ``conformance/package.json`` is precisely what that step exists to prevent.

    Local, certain checks only, and every uncertain answer leaves the re-render on the
    table: a remote ``_src_path`` needs the network, a template directory that is no
    repository cannot be asked, an app below its repository root has no ``.git`` of its
    own, and a git that will not run answers nothing at all. Each of those keeps the
    re-render recipe. Trading this command's false positive for a false negative would
    only move the damage to the other set of apps.
    """
    ref = scaffold_ref(root)
    if ref is None:
        return (
            "records no template answers file, so `copier update` has nothing to "
            "re-render from"
        )
    if not _is_git_checkout(root):
        return "is not a git checkout, which `copier update` needs to apply an update"
    source = _answers_scalar(root, "_src_path")
    if source is not None and not _ref_resolves(source, ref):
        return f"records template ref {ref}, which {source} no longer carries"
    return None


def git_dir_read_only(root: pathlib.Path) -> pathlib.Path | None:
    """The checkout's git directory when this process certainly cannot write it, else ``None``.

    ``copier update`` writes through it -- it stashes, and commits the old render to diff
    against -- so a read-only one fails partway, and ``git stash`` fails without saying so.
    That is not a checkout copier cannot update: a tool that runs an agent in a copy of
    the checkout mounts the git directory read-only on purpose (a writable one lets the
    agent plant config the tool's own git then runs), and runs the update itself. So this
    is not a reason to hand-pin, which moves the packages and leaves the scaffolding
    behind; it is a reason to have the re-render run where it can.

    Certain evidence only: a ``.git`` file is followed to the directory it names, and
    anything unreadable or absent answers ``None``.
    """
    entry = root / ".git"
    if entry.is_file():
        try:
            pointer = entry.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeDecodeError):
            return None
        if not pointer.startswith("gitdir:"):
            return None
        named = pathlib.Path(pointer.split(":", 1)[1].strip())
        entry = named if named.is_absolute() else root / named
    if not entry.is_dir():
        return None
    return None if os.access(entry, os.W_OK) else entry


#: The release of the template an environment re-renders from, when that environment says.
#: The package index answers "which Terp is published", and a tool that scaffolds and
#: updates apps from a template of its own can be a release behind it: following the
#: index then moves the packages to a release whose scaffolding the re-render cannot
#: deliver. Such a tool (Terp Studio is one) sets it where its agents run.
TEMPLATE_VERSION_VARIABLE = "TERP_TEMPLATE_VERSION"


def template_ceiling(environment: dict[str, str] | None = None) -> str | None:
    """The release the environment's template is at (``0.44.0``), or ``None`` if unsaid.

    A value that is not a whole release number (``X.Y.Z``) is ignored rather than trusted:
    this only ever LOWERS the recommendation, a ceiling read wrongly would hold an app back
    silently, and ``0.6`` would compare below ``0.6.0``.
    """
    raw = (os.environ if environment is None else environment).get(TEMPLATE_VERSION_VARIABLE)
    match = re.fullmatch(r"v?(\d+\.\d+\.\d+)", (raw or "").strip())
    return match.group(1) if match else None


def _version_key(version: str) -> tuple[int, ...]:
    """Sort key for a release string — numeric, because ``0.10.0`` sorts *below*
    ``0.9.0`` as text and picking the wrong target would recommend a downgrade."""
    return tuple(int(part) if part.isdigit() else 0 for part in re.split(r"[._-]", version))


def _rerender_offer(
    *,
    include_command: bool,
    blocked_because: str | None,
    elsewhere: str | None = None,
    ceiling: str | None = None,
    platform: str | None = None,
) -> list[str]:
    """How the scaffolding report closes: the command, why it is unavailable, or nothing.

    Suppressed when a recipe above already numbered the re-render as a step — the same
    command printed twice in one report reads as two different things to do, and the
    recipe's copy is the one with the tree-cleaning step before it.

    Replaced outright when something local already rules the re-render out. Offering a
    command that cannot run is worse than offering none, because a reader takes it for
    the way forward and finds out three steps in.

    Qualified where this environment says something about it: a template it re-renders
    from that is behind the packages (*ceiling* below *platform*) would write that
    template's pins, so the offer becomes "update the environment's template first"; and
    a git directory this process cannot write (*elsewhere*) puts the re-render somewhere
    else, which the offer says after the command.
    """
    if blocked_because is not None:
        return ["", f"  A re-render is unavailable here: this app {blocked_because}."]
    if ceiling is not None and platform is not None and _version_key(ceiling) < _version_key(platform):
        return [
            "",
            f"  A re-render here would write the pins of template {ceiling}, the release this "
            f"environment re-renders from ({TEMPLATE_VERSION_VARIABLE}), behind the packages' "
            f"{platform}: update the environment's template first.",
        ]
    if not include_command:
        return []
    offer = [
        "",
        "  Re-render:  copier update  (or the Studio's upgrade flow, which records the",
        "              answers file it needs).",
    ]
    return [*offer, "", f"  NOTE: {elsewhere}"] if elsewhere is not None else offer
