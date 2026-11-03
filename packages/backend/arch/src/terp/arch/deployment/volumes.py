"""What a declaration says about volumes, held to the profile (ADR 0184 decision 5, 0187).

A declared volume is a named volume of the resolved profile that some service mounts and
that no declared stateful unit's policy already covers, and the mount it restates is the
profile's: exactly the declared units whose services mount it, at that path inside the
app root.
"""

from __future__ import annotations

import posixpath
from typing import Any

from terp.arch.deployment._generator_text import APP_ROOT
from terp.arch.deployment.model import Declaration, Finding, Volume


def mounters(services: dict[str, dict[str, Any]]) -> dict[str, list[tuple[str, str]]]:
    """Named volume -> every ``(service, container path)`` that mounts it."""
    found: dict[str, list[tuple[str, str]]] = {}
    for name, service in services.items():
        for entry in service.get("volumes") or ():
            if isinstance(entry, dict):
                if entry.get("type", "volume") == "volume" and entry.get("source"):
                    found.setdefault(str(entry["source"]), []).append(
                        (name, str(entry.get("target", "")))
                    )
                continue
            source, _, rest = str(entry).partition(":")
            if (
                rest
                and source
                and not source.startswith(("/", ".", "~", "$"))
                and "/" not in source
            ):
                found.setdefault(source, []).append((name, rest.split(":", 1)[0]))
    return found


def _volume_findings(
    declaration: Declaration,
    profile: dict[str, Any],
    services: dict[str, dict[str, Any]],
    label: str,
) -> list[Finding]:
    named = set(profile.get("volumes") or {}) if isinstance(profile.get("volumes"), dict) else set()
    mounted = mounters(services)
    stateful = {unit.id for unit in declaration.units if unit.stateful}
    findings: list[Finding] = []
    for index, volume in enumerate(declaration.volumes):
        users = sorted({service for service, _target in mounted.get(volume.id, ())})
        where = f'volumes[{index}].id "{volume.id}"'
        if volume.id not in named:
            listed = ", ".join(sorted(named)) or "none"
            findings.append(
                Finding(
                    f"{where} is not a named volume of {label} (allowed: a named volume of the profile: {listed})"
                )
            )
        elif not users:
            findings.append(
                Finding(
                    f"{where} is mounted by no service of {label}, so its backup policy would back up nothing (allowed: a named volume a service mounts)"
                )
            )
        elif set(users) <= stateful:
            findings.append(
                Finding(
                    f"{where} is mounted only by declared stateful units ({', '.join(users)}), whose backup policy already covers it (allowed: a volume no declared stateful unit owns)"
                )
            )
        elif volume.mount is not None:
            findings.extend(_mount_findings(index, volume, mounted, declaration, label))
    return findings


def _relative(target: str) -> str:
    """A container path as a mount restates it: relative to the app root."""
    normal = posixpath.normpath(target)
    return normal.removeprefix(f"{APP_ROOT}/") if normal.startswith(f"{APP_ROOT}/") else normal


def _mount_findings(
    index: int,
    volume: Volume,
    mounted: dict[str, list[tuple[str, str]]],
    declaration: Declaration,
    label: str,
) -> list[Finding]:
    """A restated mount is the profile's: exactly the declared units that mount it, there."""
    assert volume.mount is not None
    ids = {unit.id for unit in declaration.units}
    by_unit = [(service, _relative(target)) for service, target in mounted.get(volume.id, ())]
    by_unit = [(service, path) for service, path in by_unit if service in ids]
    at_path = sorted({service for service, path in by_unit if path == volume.mount.path})
    where = f"volumes[{index}].mount"
    if not at_path:
        paths = ", ".join(sorted({path for _service, path in by_unit})) or "nowhere"
        return [
            Finding(
                f'{where}.path is "{volume.mount.path}", and {label} mounts {volume.id} at '
                f"{paths} on the declared units (allowed: where the profile mounts "
                f"{volume.id}: {paths}, relative to {APP_ROOT})"
            )
        ]
    if sorted(set(volume.mount.units)) != at_path:
        return [
            Finding(
                f"{where}.units restates {sorted(volume.mount.units)}, and {label} mounts "
                f"{volume.id} at {volume.mount.path} on {', '.join(at_path)} (allowed: the "
                f"declared units whose services mount {volume.id} at {volume.mount.path}: "
                f"{', '.join(at_path)})"
            )
        ]
    return []
