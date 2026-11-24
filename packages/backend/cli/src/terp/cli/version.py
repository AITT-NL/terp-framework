"""``terp --version`` — what platform is this app actually running on?

An app cannot reason about an upgrade it cannot see. Before this existed the
CLI had no answer to "which Terp is installed here": the version lived only in
each distribution's metadata, so the only way to find out was to read a lock
file. That silence has a sharper edge than mere inconvenience — Terp ships as a
**lockstep set** of distributions pinned by hand across two manifests, so the
natural failure is a *forgotten* pin producing an install where one package is a
release behind the rest. Nothing detected that, and a mixed install fails in
whatever way the skipped release happened to change.

So this reports the whole set, not a single number: every installed ``terp-*``
distribution is discovered from the environment (never a hand-maintained list
here, which would rot into the same problem it diagnoses) and a disagreement is
called out by name, with the fix.
"""

from __future__ import annotations

import json
import pathlib
import re
import subprocess
from dataclasses import dataclass
from importlib import metadata

from terp.cli.rerender import (
    _copier_update_blocker,
    TEMPLATE_VERSION_VARIABLE,
    git_dir_read_only,
    scaffold_ref,
    template_ceiling,
)
from terp.cli.upgrade_recipes import hand_pin_recipe, rerender_recipe

#: Distribution-name prefix every platform package shares (``terp-core``,
#: ``terp-cap-auth``, …). Normalized names use ``-``; metadata may report either.
_PREFIX = "terp-"

#: The distribution whose version *is* the platform version when present. It is
#: the one package every app has, so it is the least surprising answer to
#: "which Terp?" when the set is consistent.
_ANCHOR = "terp-core"

#: Shares the ``terp-`` prefix but is **not** part of the lockstep set: the Terp
#: Standard is released from its own repository on its own cadence and pinned
#: here deliberately (ADR 0082/0086). Reporting it as a missed pin would be a
#: false alarm on every single install — and a check that cries wolf gets
#: ignored exactly when it is right.
_INDEPENDENTLY_VERSIONED = frozenset({"terp-spec"})


def installed_terp_versions() -> dict[str, str]:
    """Every installed ``terp-*`` distribution mapped to its version.

    Discovered from the live environment rather than declared, so a capability
    adopted after this code was written is still reported — and so this function
    cannot drift out of step with the set it is meant to police.
    """
    found: dict[str, str] = {}
    for dist in metadata.distributions():
        name = dist.metadata["Name"]
        if not name:  # a malformed dist on the path is not worth crashing over
            continue
        normalized = name.lower().replace("_", "-")
        if normalized.startswith(_PREFIX) and normalized not in _INDEPENDENTLY_VERSIONED:
            found[normalized] = dist.version
    return dict(sorted(found.items()))


def platform_version(versions: dict[str, str] | None = None) -> str | None:
    """The single version this install is on, or ``None`` if nothing is installed.

    With a disagreeing set this still answers — the anchor's version, or the most
    common one — because "0.5.4, and three packages disagree" is a more useful
    thing to say than "it's complicated".
    """
    versions = installed_terp_versions() if versions is None else versions
    if not versions:
        return None
    if _ANCHOR in versions:
        return versions[_ANCHOR]
    return max(set(versions.values()), key=list(versions.values()).count)


def render_version(*, fmt: str = "text") -> str:
    """Render the platform version, naming any distribution that disagrees."""
    versions = installed_terp_versions()
    version = platform_version(versions)
    consistent = len(set(versions.values())) <= 1

    if fmt == "json":
        return json.dumps(
            {
                "version": version,
                "consistent": consistent,
                "distributions": versions,
            },
            indent=2,
        )

    if not versions:
        # The platform's own checkout, or an app whose environment is not synced.
        return "terp (not installed — no terp-* distribution found in this environment)"

    lines = [f"terp {version}"]
    if not consistent:
        odd = {
            name: found for name, found in versions.items() if found != version
        }
        lines += [
            "",
            f"WARNING: mixed install — {len(odd)} of {len(versions)} packages are not "
            f"on {version}.",
            "Terp is versioned in lockstep, so this is a pin that was missed, not a",
            "supported combination. It fails in whatever way the skipped release changed.",
            "",
        ]
        for name, found in sorted(odd.items()):
            lines.append(f"  {name:<32} {found}")
        lines += [
            "",
            f"Fix: pin every terp-* dependency to =={version} in pyproject.toml",
            "(including the dev group), then `uv sync --refresh`.",
        ]
    return "\n".join(lines)


# --- upgrade check ----------------------------------------------------------
#
# "Is there a newer Terp?" is a question about a package index, and Terp itself
# deliberately does not become an HTTP client to answer it. A network call inside
# a tool whose whole pitch is deterministic, offline, fail-closed answers needs
# timeouts, proxy handling, index auth and an offline story — every one of which
# is a new way for `terp` to hang or to lie. `uv` already resolves against the
# exact index this app installs from, with that configuration already in place.
#
# What Terp adds is the part uv cannot know: the **lockstep**. `uv pip list
# --outdated` reports fifteen independent packages; only Terp knows they move
# together, and that a release which covers some of them but not all is a trap
# rather than an upgrade.

_UV_OUTDATED_COMMAND = ("uv", "pip", "list", "--outdated", "--format", "json")
_UV_TIMEOUT_SECONDS = 120.0


def _uv_outdated() -> tuple[list[dict[str, str]] | None, str | None]:
    """Ask ``uv`` what is outdated: ``(packages, error)`` — exactly one is set.

    Every failure is returned as a sentence rather than raised: this command is
    run *because* an environment is in question, so an unreachable index must
    produce an explanation, never a traceback.
    """
    try:
        completed = subprocess.run(  # noqa: S603 — fixed argv, no shell, no user input
            _UV_OUTDATED_COMMAND,
            capture_output=True,
            text=True,
            timeout=_UV_TIMEOUT_SECONDS,
            check=False,
        )
    except FileNotFoundError:
        return None, (
            "uv is not on PATH. Terp reads uv rather than reaching the index itself, "
            "so install uv (https://docs.astral.sh/uv/) or check versions manually."
        )
    except subprocess.TimeoutExpired:
        return None, (
            f"uv did not answer within {int(_UV_TIMEOUT_SECONDS)}s — the package index "
            "is unreachable or slow (offline, proxy, or a blocked mirror)."
        )
    if completed.returncode != 0:
        detail = (completed.stderr or "").strip().splitlines()
        return None, f"uv failed: {detail[-1] if detail else 'no output'}"
    try:
        return json.loads(completed.stdout or "[]"), None
    except json.JSONDecodeError:
        return None, "uv's --format json output could not be parsed."


def _terp_upgrades(packages: list[dict[str, str]]) -> dict[str, str]:
    """The ``terp-*`` entries of a uv outdated report: name -> latest version."""
    upgrades: dict[str, str] = {}
    for package in packages:
        name = (package.get("name") or "").lower().replace("_", "-")
        latest = package.get("latest_version") or ""
        if name.startswith(_PREFIX) and name not in _INDEPENDENTLY_VERSIONED and latest:
            upgrades[name] = latest
    return upgrades


def _version_key(version: str) -> tuple[int, ...]:
    """Sort key for a release string — numeric, because ``0.10.0`` sorts *below*
    ``0.9.0`` as text and picking the wrong target would recommend a downgrade."""
    return tuple(int(part) if part.isdigit() else 0 for part in re.split(r"[._-]", version))


#: The scaffolding files copier seeds once and never overwrites — ``_skip_if_exists`` in
#: ``template/copier.yml``. Everything else the template owns *is* rewritten by a
#: re-render, and that is the half a reader actually needs: the report used to name three
#: template-owned files as though they were the list, so someone weighing whether a
#: re-render would deliver a fix to, say, the Compose file had no way to tell from it.
#:
#: Some are authored (``theme.css``) and some are app-generated (``routes.gen.d.ts``), so
#: what the report can honestly say about the set is not that it carries hand-written
#: content but that copier seeds it once and it is the app's afterwards.
#:
#: Duplicated here because the template does not ship inside this wheel, so the CLI cannot
#: read ``copier.yml`` at runtime. Held against it by
#: ``test_the_app_owned_scaffold_list_matches_copier`` — the same treatment the theme
#: bootstrap's three duplicated facts get, so this list cannot rot into a wrong answer.
_APP_OWNED_SCAFFOLD_FILES = (
    "control_plane/app_operations.py",
    "deployment.json",
    "environment.schema.json",
    "escape-hatch-budget.json",
    "frontend/escape-hatch-budget.json",
    "frontend/layout-contract.json",
    "frontend/src/house-style.css",
    "frontend/src/routes.gen.d.ts",
    "frontend/src/theme.css",
    "workbench.json",
)


#: The production build files the framework's generator owns where deployment.json says
#: ``"build": "generated"`` (``terp.arch.deployment.generator.OWNED_PATHS``, ADR 0187).
_GENERATOR_OWNED_FILES = ("Dockerfile.prod", "frontend/Dockerfile.prod", "site/Dockerfile.prod", "conformance/Dockerfile.prod", "docker-compose.prod.yml")


def _is_generated(root: pathlib.Path) -> bool:
    """Whether the app's ``deployment.json`` says ``"build": "generated"``; ``False`` unreadable.

    Read as plain JSON, not through the reader: this only decides which recipe to print,
    and ``terp verify`` is where a declaration that cannot be read is reported.
    """
    try:
        declared = json.loads((root / "deployment.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(declared, dict) and declared.get("build") == "generated"


def _scaffold_lines(
    root: pathlib.Path,
    platform: str,
    *,
    include_command: bool = True,
    blocked_because: str | None = None,
) -> list[str]:
    """Report how far the app's *scaffolding* is behind its *packages*.

    The two move independently and only one of them is gated. Package drift already fails
    closed (``terp verify --only platform-install`` reads every ``@terpjs/*`` manifest and
    its installed ``node_modules``); the template ref is checked by nothing, so an app can
    run current libraries against scaffolding many releases old and stay green throughout.
    That is not hypothetical: the observable symptom is a stale ``AGENTS.md`` briefing every
    agent from a narrower layout contract than the one actually shipping, and workarounds
    for restrictions a later release lifted.

    Deliberately a report and not a gate. Scaffolding legitimately lags — an app need not
    re-render on every release — so a failure on any gap would be noise. This says how far
    behind it is and leaves the judgement where the rest of this command leaves it.
    """
    ref = scaffold_ref(root)
    if ref is None:
        return []
    match = re.fullmatch(r"v?(\d+(?:\.\d+)*)", ref)
    if match is None:
        # A raw commit sha, or a branch: report it without inventing a comparison.
        return [
            "",
            f"Scaffolding: rendered from template {ref} (not a release tag, so how far "
            "behind\nit is cannot be read from the ref alone).",
        ]
    rendered = match.group(1)
    if _version_key(rendered) >= _version_key(platform):
        return ["", f"Scaffolding: rendered from template {ref}, level with the packages."]
    return [
        "",
        f"Scaffolding: rendered from template {ref}, while the packages are on "
        f"{platform}.",
        "A re-render rewrites EVERY file the template owns — main.tsx, index.html,",
        "AGENTS.md, the Dockerfiles, docker-compose.yml, the CI workflows — so any fix a",
        "release made to one of them may still be waiting here. WHICH of them actually",
        "differ is not something this can say: it compares two version numbers, and a",
        "file no release has touched since is already current. Nothing gates any of it,",
        "so it stays green either way — and the two that cost the most when they are",
        "behind are AGENTS.md, which briefs every agent working here, and",
        "docker-compose.yml, which can serve a dev stack that disagrees with the",
        "checkout the boundary lint reads.",
        "These are seeded once and then the app's, so a re-render leaves them alone:",
        *(f"  {name}" for name in _APP_OWNED_SCAFFOLD_FILES),
        *(
            [
                'And deployment.json says "build": "generated", so these are the framework',
                "generator's: a re-render leaves them alone too, and `uv run terp deployment",
                "render` writes them from the release that is installed:",
                *(f"  {name}" for name in _GENERATOR_OWNED_FILES),
            ]
            if _is_generated(root)
            else []
        ),
        *_rerender_offer(include_command=include_command, blocked_because=blocked_because),
    ]


def _rerender_offer(*, include_command: bool, blocked_because: str | None) -> list[str]:
    """How the scaffolding report closes: the command, why it is unavailable, or nothing.

    Suppressed when a recipe above already numbered the re-render as a step — the same
    command printed twice in one report reads as two different things to do, and the
    recipe's copy is the one with the tree-cleaning step before it.

    Replaced outright when something local already rules the re-render out. Offering a
    command that cannot run is worse than offering none, because a reader takes it for
    the way forward and finds out three steps in.
    """
    if blocked_because is not None:
        return ["", f"  A re-render is unavailable here: this app {blocked_because}."]
    if not include_command:
        return []
    return [
        "",
        "  Re-render:  copier update  (or the Studio's upgrade flow, which records the",
        "              answers file it needs).",
    ]


@dataclass(frozen=True)
class UpgradeStatus:
    """The upgrade question as data, before anybody renders a sentence about it.

    Every field here was already computed by ``render_upgrade_check`` and then spent on
    prose. That made ``terp upgrade --check`` the one reporting command in the CLI with
    no machine-readable mode, against ``inspect``, ``guide --list``, ``check`` and
    ``verify``, which all have one — so any tool asking "is this app on a current
    platform?" had to answer it by reimplementing the question rather than by asking.

    ``covers_whole_set`` is the distinction a version number cannot carry on its own:
    "internally consistent at X" and "X, and the release does not cover every package"
    are different answers, and only the second is a reason to wait.

    ``target`` is what the package index publishes, and two facts about THIS environment
    qualify it without changing it: ``template_ceiling``, the release of the template it
    re-renders from when it says (``TERP_TEMPLATE_VERSION``), and ``rerender_elsewhere``,
    why ``copier update`` cannot run in this process although the app can be re-rendered.
    """

    installed: dict[str, str]
    current: str | None
    target: str | None
    covers_whole_set: bool
    stragglers: dict[str, str]
    rerender_blocker: str | None
    scaffold_ref: str | None
    error: str | None
    template_ceiling: str | None = None
    rerender_elsewhere: str | None = None

    def as_dict(self) -> dict[str, object]:
        """A JSON-safe rendering (``terp upgrade --check --format json``)."""
        return {
            "installed": dict(sorted(self.installed.items())),
            "current": self.current,
            "target": self.target,
            "covers_whole_set": self.covers_whole_set,
            "stragglers": dict(sorted(self.stragglers.items())),
            "rerender_blocker": self.rerender_blocker,
            "scaffold_ref": self.scaffold_ref,
            "error": self.error,
            "template_ceiling": self.template_ceiling,
            "rerender_elsewhere": self.rerender_elsewhere,
        }


def upgrade_status(root: pathlib.Path | None = None) -> UpgradeStatus:
    """Answer the upgrade question for *root* without rendering anything.

    Reads uv rather than the package index directly: Terp deliberately ships no HTTP
    client for this, so the answer resolves against exactly the index the app's own
    install uses.
    """
    project_root = pathlib.Path(".") if root is None else root
    installed = installed_terp_versions()
    current = platform_version(installed)
    if not installed or current is None:
        return UpgradeStatus(
            installed=installed,
            current=None,
            target=None,
            covers_whole_set=False,
            stragglers={},
            rerender_blocker=None,
            scaffold_ref=scaffold_ref(project_root),
            error="no terp-* distribution is installed in this environment",
        )

    packages, error = _uv_outdated()
    if error is not None:
        return UpgradeStatus(
            installed=installed,
            current=current,
            target=None,
            covers_whole_set=False,
            stragglers={},
            rerender_blocker=None,
            scaffold_ref=scaffold_ref(project_root),
            error=error,
        )

    upgrades = _terp_upgrades(packages or [])
    if not upgrades:
        return UpgradeStatus(
            installed=installed,
            current=current,
            target=None,
            covers_whole_set=True,
            stragglers={},
            rerender_blocker=_copier_update_blocker(project_root),
            scaffold_ref=scaffold_ref(project_root),
            error=None,
            template_ceiling=template_ceiling(),
            rerender_elsewhere=_rerender_elsewhere(project_root),
        )

    # The lockstep question: after this upgrade, does every package land on the
    # same version? A package whose newest release is older than the target is
    # not "already fine" — it means the release does not cover the whole set.
    landing = {name: upgrades.get(name, found) for name, found in installed.items()}
    target = max(landing.values(), key=_version_key)
    stragglers = {name: at for name, at in landing.items() if at != target}
    return UpgradeStatus(
        installed=installed,
        current=current,
        target=target,
        covers_whole_set=not stragglers,
        stragglers=stragglers,
        rerender_blocker=_copier_update_blocker(project_root),
        scaffold_ref=scaffold_ref(project_root),
        error=None,
        template_ceiling=template_ceiling(),
        rerender_elsewhere=_rerender_elsewhere(project_root),
    )


def _rerender_elsewhere(root: pathlib.Path) -> str | None:
    """Why the re-render has to run outside this process, or ``None`` (see ``git_dir_read_only``)."""
    git_dir = git_dir_read_only(root)
    if git_dir is None:
        return None
    return (
        f"this checkout's git directory ({git_dir}) is read-only to this process, and "
        "`copier update` writes through it, so it cannot run here. Have it run where "
        "the git directory is writable: in Terp Studio, ask the person to start Studio's "
        "upgrade, which runs it outside this copy. Do not pin the packages by hand instead: "
        "that moves the packages and leaves the scaffolding behind."
    )


def render_upgrade_check(root: pathlib.Path | None = None, *, fmt: str = "text") -> str:
    """Report whether the whole lockstep set can move, and to what."""
    project_root = pathlib.Path(".") if root is None else root
    status = upgrade_status(project_root)
    if fmt == "json":
        return json.dumps(status.as_dict(), indent=2)

    installed, current = status.installed, status.current
    if status.error is not None and current is None:
        return (
            "No terp-* distribution is installed in this environment, so there is "
            "nothing to upgrade.\nRun this from the app's environment "
            "(`uv run terp upgrade --check`)."
        )

    if status.error is not None:
        return (
            f"Could not check for a newer Terp: {status.error}\n\n"
            f"This app is on {current}. Terp does not reach the package index itself "
            "— it reads uv,\nwhich resolves against the same index your install uses."
        )

    if status.target is None:
        # The most valuable place to say this: packages current, so nothing else in the
        # toolchain will mention the scaffolding again.
        return "\n".join(
            [f"Up to date: all {len(installed)} terp-* distributions are on {current}."]
            + _scaffold_lines(
                project_root,
                current,
                blocked_because=status.rerender_blocker,
            )
        )

    target = status.target
    landing = {**installed, **status.stragglers}
    stragglers = status.stragglers

    lines = [f"Terp {target} is available (this app is on {current})."]
    ceiling = status.template_ceiling
    if ceiling is not None and _version_key(target) > _version_key(ceiling):
        # The index is ahead of the template this environment re-renders from. Recommending
        # the index's release moved the packages to it while the re-render could deliver
        # only the template's, and that pair is a version skew nothing then reports.
        lines += [
            "",
            f"The template this environment re-renders from is {ceiling} "
            f"({TEMPLATE_VERSION_VARIABLE}), so upgrading",
            f"to {target} would put the packages on {target} and the scaffolding on "
            f"{ceiling}. Update the environment's",
            "template first (in Terp Studio, that is an update of Studio itself).",
        ]
        if _version_key(ceiling) <= _version_key(current):
            return "\n".join(lines)
        lines.append(f"Until then, the recipe below goes as far as {ceiling}.")
        target, stragglers = ceiling, {}
    if stragglers:
        lines += [
            "",
            f"WARNING: {target} does not cover the whole set — {len(stragglers)} of "
            f"{len(landing)} packages\nwould stay behind. Terp releases in lockstep, so "
            "upgrading now produces exactly the\nmixed install `terp --version` warns "
            "about. Either the release is still publishing,\nor your index has a stale "
            "mirror. Wait, then re-check.",
            "",
        ]
        for name, at in sorted(stragglers.items()):
            lines.append(f"  {name:<32} newest available {at}")
        return "\n".join(lines)

    # Step 1 must be possible *before* step 2. The notes for `target` ship inside
    # the `target` wheel, so the installed copy (`uv run terp guide changelog`)
    # ends at `current` and structurally cannot describe the release it is meant
    # to help judge. `uvx --from terp-cli==target` resolves an ephemeral CLI from
    # the same index (terp-cli pins terp-core exactly, so the right CHANGELOG
    # comes with it) without touching this app's environment or its pins.
    # Which recipe depends on whether copier can run here at all: an app the
    # template rendered re-renders and gets its pins written for it, and an app with
    # no answers file writes them by hand. Printing both, or the hand-pin one to an
    # app that could re-render, is what produced two needless installs and a stash
    # halfway through.
    blocker = status.rerender_blocker
    generated = _is_generated(project_root)
    conformance = (project_root / "conformance" / "package.json").is_file()
    if blocker is None and status.rerender_elsewhere is not None:
        lines += ["", f"NOTE: {status.rerender_elsewhere}"]
    if blocker is None:
        lines += rerender_recipe(
            target, current, len(landing), generated=generated, conformance=conformance
        )
    else:
        lines += hand_pin_recipe(
            target, current, len(landing), blocker, generated=generated, conformance=conformance
        )
    # Suppressed on both paths: the re-render recipe numbers the command as a step, and
    # the hand-pin recipe has just said why it is unavailable. Either way, printing it
    # again below reads as a second, different thing to do.
    lines += _scaffold_lines(project_root, target, include_command=False)
    return "\n".join(lines)
