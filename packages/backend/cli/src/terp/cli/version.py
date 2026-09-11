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
from importlib import metadata

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
    "environment.schema.json",
    "escape-hatch-budget.json",
    "frontend/layout-contract.json",
    "frontend/src/house-style.css",
    "frontend/src/routes.gen.d.ts",
    "frontend/src/theme.css",
    "workbench.json",
)


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


def _rerender_recipe(target: str, current: str, count: int) -> list[str]:
    """The upgrade for an app the template rendered: re-render first, sync once.

    The order used to be the other way round and could not be followed as printed.
    Steps 2 to 4 were "edit the pins, uv sync, npm install", and the re-render came
    after them — but ``copier update`` refuses a dirty tree, so the recipe's own
    earlier steps made its last step impossible, and whoever followed it had to stash
    halfway through.

    Worse, those pin edits were work the re-render does. The template owns
    ``pyproject.toml``, ``frontend/package.json`` and ``conformance/package.json``, so
    a re-render writes every one of those pins itself. The old recipe even warned that
    "a recipe that names only one is how the other goes stale" — which is an admission
    that the hand-pinning step was a footgun, for a job already done one step later.

    So: read, clean the tree, re-render, resolve, sync once, confirm, verify.
    """
    return [
        "",
        f"All {count} terp-* distributions can move to {target} together, and the",
        "@terpjs/* packages move with them. Re-render FIRST — the template owns",
        "pyproject.toml and both npm manifests, so the re-render writes every pin",
        "itself, and it refuses to run on a tree with uncommitted changes:",
        "",
        f"  1. Read what changed:  uvx --from terp-cli=={target} terp guide changelog",
        f"     (the {target} notes; the copy installed here ends at {current}).",
        "  2. Commit or discard what you have. A re-render on a dirty tree is refused,",
        "     and its own diff is much easier to review on its own.",
        "  3. copier update          (or the Studio's upgrade flow, which records the",
        "     answers file it needs). This rewrites EVERY file the template owns and",
        "     writes the terp-* and @terpjs/* pins for you.",
        "  4. Resolve what it reports. Two conflicts are structural rather than bad luck,",
        "     because the template owns the file and your app also writes to it:",
        "       pyproject.toml            keep your dependencies, take the terp-* pins.",
        "       control_plane/operations.py  the capability folding is the template's;",
        "                                 your own operations belong in",
        "                                 control_plane/app_operations.py, which no",
        "                                 re-render touches (ADR 0130).",
        "  5. uv sync --refresh && npm --prefix frontend install",
        "     (once, now that the manifests are final — not before the re-render.)",
        "  6. uv run terp --version          (confirm the set agrees)",
        "  7. uv run terp verify --profile full",
        "",
        "  Running the dev stack in containers?",
        "  Rebuild it rather than reloading into it: the images bake the terp packages",
        "  in while the source is bind-mounted, so correct new code reloads against old",
        "  libraries and dies on an import nowhere near its cause. `terp docker dev`",
        "  rebuilds on a pyproject.toml change; a plain `docker compose up` does not,",
        "  and `terp verify` now refuses the skew either way.",
        "",
        "A green gate proves the upgrade did not break this app. It cannot prove the",
        "release did not change something this app should adopt — step 1 is the only",
        "thing that answers that.",
    ]


def _hand_pin_recipe(target: str, current: str, count: int, reason: str) -> list[str]:
    """The upgrade for an app that cannot re-render: every pin by hand.

    The pins the template would have written have to be written here instead. Kept in
    full for exactly that case and printed nowhere else — an app the template can update
    is told to re-render, because doing both is what produced two needless installs.

    *reason* says which way the re-render is unavailable, because "no answers file" is
    only one of them and a recipe that names the wrong obstacle sends a reader to fix
    something that is not broken.
    """
    return [
        "",
        f"All {count} terp-* distributions can move to {target} together, and the",
        "@terpjs/* packages with them.",
        f"This app {reason};",
        "the pins have to be written by hand:",
        "",
        f"  1. Read what changed:  uvx --from terp-cli=={target} terp guide changelog",
        f"     (the {target} notes; the copy installed here ends at {current}).",
        f"  2. Pin every terp-* dependency to =={target} in pyproject.toml",
        "     (including the dev group — a forgotten pin is a mixed install).",
        f"  3. Pin every @terpjs/* package to ^{target} in EVERY manifest that",
        "     declares one — frontend/package.json AND conformance/package.json",
        "     (a recipe that names only one is how the other goes stale).",
        "  4. uv sync --refresh && npm --prefix frontend install",
        "  5. uv run terp --version          (confirm the set agrees)",
        "  6. uv run terp verify --profile full",
        "",
        "A green gate proves the upgrade did not break this app. It cannot prove the",
        "release did not change something this app should adopt — step 1 is the only",
        "thing that answers that.",
    ]


def render_upgrade_check(root: pathlib.Path | None = None) -> str:
    """Report whether the whole lockstep set can move, and to what."""
    project_root = pathlib.Path(".") if root is None else root
    installed = installed_terp_versions()
    current = platform_version(installed)
    if not installed or current is None:
        return (
            "No terp-* distribution is installed in this environment, so there is "
            "nothing to upgrade.\nRun this from the app's environment "
            "(`uv run terp upgrade --check`)."
        )

    packages, error = _uv_outdated()
    if error is not None:
        return (
            f"Could not check for a newer Terp: {error}\n\n"
            f"This app is on {current}. Terp does not reach the package index itself "
            "— it reads uv,\nwhich resolves against the same index your install uses."
        )

    upgrades = _terp_upgrades(packages or [])
    if not upgrades:
        # The most valuable place to say this: packages current, so nothing else in the
        # toolchain will mention the scaffolding again.
        return "\n".join(
            [f"Up to date: all {len(installed)} terp-* distributions are on {current}."]
            + _scaffold_lines(
                project_root,
                current,
                blocked_because=_copier_update_blocker(project_root),
            )
        )

    # The lockstep question: after this upgrade, does every package land on the
    # same version? A package whose newest release is older than the target is
    # not "already fine" — it means the release does not cover the whole set.
    landing = {name: upgrades.get(name, found) for name, found in installed.items()}
    target = max(landing.values(), key=_version_key)
    stragglers = {name: at for name, at in landing.items() if at != target}

    lines = [f"Terp {target} is available (this app is on {current})."]
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
    blocker = _copier_update_blocker(project_root)
    if blocker is None:
        lines += _rerender_recipe(target, current, len(landing))
    else:
        lines += _hand_pin_recipe(target, current, len(landing), blocker)
    # Suppressed on both paths: the re-render recipe numbers the command as a step, and
    # the hand-pin recipe has just said why it is unavailable. Either way, printing it
    # again below reads as a second, different thing to do.
    lines += _scaffold_lines(project_root, target, include_command=False)
    return "\n".join(lines)
