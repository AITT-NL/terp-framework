"""Is this app on the current Terp: the Python set, the npm set and the scaffolding (ADR 0214).

The Python half is ``terp upgrade --check``'s own answer (:func:`terp.cli.version.upgrade_status`),
read from ``uv`` against the index the app installs from. The npm half asks ``npm view`` the
same question of the registry the app's frontend installs from, run in that workspace so its
``.npmrc`` applies. Neither makes Terp an HTTP client of a package index: each asks the tool
that already resolves against the app's own configuration (``version.py`` says why).

The scaffolding half is local: the template ref copier recorded against the platform the app
runs, the comparison ``terp upgrade --check`` already prints.
"""

from __future__ import annotations

import json
import pathlib
import re
import subprocess

from terp.cli.maintenance._report import Finding, Report
from terp.cli.version import _version_key, scaffold_ref, upgrade_status

#: The manifests that pin ``@terpjs/*``: the frontend's and the conformance suite's.
NPM_MANIFESTS = ("frontend/package.json", "conformance/package.json")

_NPM_TIMEOUT_SECONDS = 120.0


def _upgrade_remedy(target: str, *, whole: bool) -> str:
    if not whole:
        return (
            f"Terp {target} does not yet cover every package (the release is still publishing, or "
            "the index mirrors it partly). Wait, then check again; upgrading now is a mixed install."
        )
    return (
        f"Upgrade every terp-* and @terpjs/* package to {target} together, as one change: "
        "`uv run terp upgrade --check` prints the recipe, and the release notes come first."
    )


def python_platform(root: pathlib.Path, report: Report) -> str | None:
    """The terp-* set against the index; the platform version the app runs, when there is one."""
    status = upgrade_status(root)
    if status.current is None:
        report.unreachable(
            "python-index",
            "no terp-* distribution is installed in this environment",
            "Run it from the app's own environment: `uv run terp maintenance`.",
        )
        return None
    if status.error is not None:
        report.unreachable(
            "python-index",
            status.error,
            "Check the package index this app installs from (uv's own configuration), then run it again.",
        )
        return status.current
    report.answered("python-index")
    if status.target is not None:
        report.findings.append(
            Finding(
                "platform-behind",
                "terp-*",
                _upgrade_remedy(status.target, whole=status.covers_whole_set),
                ecosystem="PyPI",
                location="pyproject.toml",
                installed=status.current,
                latest=status.target,
            )
        )
    return status.current


def template(root: pathlib.Path, report: Report, platform: str) -> None:
    """The scaffolding's template ref against the platform the app runs."""
    ref = scaffold_ref(root)
    if ref is None:
        report.not_made(
            "template-behind: no .copier-answers.yml records the template this app was rendered "
            "from, so there is no scaffolding to compare with the platform"
        )
        return
    match = re.fullmatch(r"v?(\d+(?:\.\d+)*)", ref)
    if match is None:
        report.not_made(
            f"template-behind: the scaffolding was rendered from {ref}, which is not a release tag, "
            "so how far behind it is cannot be read from the ref alone"
        )
        return
    if _version_key(match.group(1)) >= _version_key(platform):
        return
    from terp.cli.version import _copier_update_blocker

    blocker = _copier_update_blocker(root)
    remedy = (
        "Re-render the scaffolding from the template of the installed release: `copier update`, "
        "or the upgrade flow of the tool that scaffolded it. It rewrites every file the template "
        "owns (AGENTS.md among them); review it as one change."
    )
    if blocker is not None:
        remedy = f"A re-render is unavailable here: this app {blocker}."
    report.findings.append(
        Finding(
            "template-behind",
            "template",
            remedy,
            location=".copier-answers.yml",
            installed=ref,
            latest=platform,
        )
    )


#: The template release whose production profile first gave the files capability a writable
#: storage root and a volume (ADR 0218): an older render installs terp-cap-files in an image
#: whose user cannot write ``/srv/var/files``.
FILES_ROOT_TEMPLATE = "0.35.0"

_FILES_ROOT_REMEDY = (
    "Re-render the scaffolding from template {template} or later (`copier update`; it brings the "
    "volume only when the recorded use_files answer is true: `copier update --data use_files=true`), "
    "or add what that production profile has: `&& mkdir -p /srv/var/files && chown appuser "
    "/srv/var/files` on the `RUN useradd` line of Dockerfile.prod, and a "
    "`files-data:/srv/var/files` volume on `api` in docker-compose.prod.yml, with `files-data:` "
    "under its top-level `volumes`. A volume an older image already created is owned by root: "
    "chown it once, `docker compose -f docker-compose.prod.yml run --rm --no-deps --user root api "
    "chown 10001 /srv/var/files`. See: terp guide files."
)


def _installs_files(root: pathlib.Path) -> bool:
    """Whether ``pyproject.toml`` asks for terp-cap-files, in any dependency list it keeps."""
    import tomllib

    try:
        project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    lists: list[object] = []
    body = project.get("project")
    if isinstance(body, dict):
        lists.append(body.get("dependencies"))
        optional = body.get("optional-dependencies")
        lists += list(optional.values()) if isinstance(optional, dict) else []
    groups = project.get("dependency-groups")
    lists += list(groups.values()) if isinstance(groups, dict) else []
    for entries in lists:
        for entry in entries if isinstance(entries, list) else ():
            name = re.match(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)", entry) if isinstance(entry, str) else None
            if name is not None and re.sub(r"[._-]+", "-", name.group(1)).lower() == "terp-cap-files":
                return True
    return False


def _names_files_root(path: pathlib.Path) -> bool | None:
    """Whether a line of *path* that is not a comment names ``var/files``; ``None`` without the file."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    return any("var/files" in line and not line.lstrip().startswith("#") for line in text.splitlines())


def files_storage(root: pathlib.Path, report: Report) -> None:
    """The production defect a re-render is known to fix: no writable files root (ADR 0218).

    An app that installs terp-cap-files and builds its own production image from a render
    older than template 0.35 runs as a user that cannot write ``/srv/var/files``, with no
    volume there: every upload failed, and a process on Terp 0.43 or later refuses to start
    outside ``ENVIRONMENT=local``. Read from the app's own files, so a Dockerfile fixed by
    hand is not reported and one whose re-render dropped the line is. Under ``"build":
    "generated"`` the framework writes the image and its mounts, and nothing here applies.
    """
    if not _installs_files(root):
        return
    try:
        declared = json.loads((root / "deployment.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        declared = None
    if isinstance(declared, dict) and declared.get("build") == "generated":
        return
    ref = scaffold_ref(root)
    release = re.fullmatch(r"v?(\d+(?:\.\d+)*)", ref or "")
    older = release is not None and _version_key(release.group(1)) < _version_key(FILES_ROOT_TEMPLATE)
    image = _names_files_root(root / "Dockerfile.prod")
    volume = _names_files_root(root / "docker-compose.prod.yml")
    missing: list[tuple[str, str]] = []
    if image is False or (image is None and older):
        missing.append(
            (
                "Dockerfile.prod",
                "the production image does not create /srv/var/files owned by the user it runs as, "
                "so the files capability cannot write its storage root: every upload fails, and on "
                "Terp 0.43 or later the process refuses to start outside ENVIRONMENT=local",
            )
        )
    if volume is False or (volume is None and older):
        missing.append(
            (
                "docker-compose.prod.yml",
                "the production profile mounts no volume at /srv/var/files, so the files stored "
                "there go with the container at the next deploy",
            )
        )
    if not missing:
        return
    rendered = f"was rendered from template {ref}" if ref else "records no template ref"
    report.findings.append(
        Finding(
            "template-behind",
            "terp-cap-files",
            f"This app installs terp-cap-files and its scaffolding {rendered}: "
            + "; ".join(sentence for _, sentence in missing)
            + ". "
            + _FILES_ROOT_REMEDY.format(template=FILES_ROOT_TEMPLATE),
            location=missing[0][0],
            installed=ref,
            latest=FILES_ROOT_TEMPLATE,
        )
    )


def _declared(root: pathlib.Path) -> dict[str, tuple[str, str]]:
    """Each ``@terpjs/*`` package a manifest declares: name -> (installed version, manifest)."""
    found: dict[str, tuple[str, str]] = {}
    for manifest in NPM_MANIFESTS:
        try:
            declared = json.loads((root / manifest).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        try:
            lock = json.loads((root / manifest).with_name("package-lock.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            lock = {}
        locked = lock.get("packages", {}) if isinstance(lock, dict) else {}
        for group in ("dependencies", "devDependencies"):
            for name, spec in (declared.get(group) or {}).items() if isinstance(declared, dict) else ():
                if not name.startswith("@terpjs/") or name in found:
                    continue
                entry = locked.get(f"node_modules/{name}") if isinstance(locked, dict) else None
                version = entry.get("version") if isinstance(entry, dict) else None
                version = str(version or re.sub(r"^[\^~=v]+", "", str(spec)))
                found[name] = (version, manifest)
    return found


def _npm_latest(root: pathlib.Path, manifest: str, name: str) -> tuple[str | None, str | None]:
    """``(latest version, error)`` for *name*, asked of the registry the workspace installs from."""
    workspace = (root / manifest).parent
    try:
        completed = subprocess.run(  # noqa: S603 - fixed argv, no shell; the name is a manifest key
            ["npm", "view", name, "version", "--json"],  # noqa: S607 - npm is found on PATH, as npm audit is
            cwd=workspace,
            capture_output=True,
            text=True,
            timeout=_NPM_TIMEOUT_SECONDS,
            check=False,
        )
    except FileNotFoundError:
        return None, "npm is not on PATH"
    except subprocess.TimeoutExpired:
        return None, f"npm did not answer within {int(_NPM_TIMEOUT_SECONDS)}s"
    if completed.returncode != 0:
        detail = (completed.stderr or "").strip().splitlines()
        return None, f"npm view {name} failed: {detail[-1] if detail else 'no output'}"
    try:
        found = json.loads(completed.stdout or "null")
    except ValueError:
        return None, f"npm view {name} answered no JSON"
    if not isinstance(found, str) or not found:
        return None, f"npm view {name} answered no version"
    return found, None


def npm_platform(root: pathlib.Path, report: Report) -> None:
    """The @terpjs/* set against the npm registry; nothing when no manifest declares one."""
    declared = _declared(root)
    if not declared:
        return
    latest: dict[str, str] = {}
    for name, (_version, manifest) in sorted(declared.items()):
        found, error = _npm_latest(root, manifest, name)
        if error is not None:
            report.unreachable(
                "npm-registry",
                error,
                "Check the registry the frontend installs from (its .npmrc), then run it again.",
            )
            return
        latest[name] = str(found)
    report.answered("npm-registry")
    behind = {name: at for name, at in latest.items() if _version_key(at) > _version_key(declared[name][0])}
    if not behind:
        return
    installed = min((declared[name][0] for name in declared), key=_version_key)
    newest = max(latest.values(), key=_version_key)
    whole = all(_version_key(at) == _version_key(newest) for at in latest.values())
    report.findings.append(
        Finding(
            "platform-behind",
            "@terpjs/*",
            _upgrade_remedy(newest, whole=whole),
            ecosystem="npm",
            location=declared[sorted(behind)[0]][1],
            installed=installed,
            latest=newest,
        )
    )


__all__ = ["FILES_ROOT_TEMPLATE", "NPM_MANIFESTS", "files_storage", "npm_platform", "python_platform", "template"]
