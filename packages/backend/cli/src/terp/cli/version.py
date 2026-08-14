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


def render_upgrade_check() -> str:
    """Report whether the whole lockstep set can move, and to what."""
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
        return f"Up to date: all {len(installed)} terp-* packages are on {current}."

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
    lines += [
        "",
        f"All {len(landing)} packages can move to {target} together:",
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
    return "\n".join(lines)
