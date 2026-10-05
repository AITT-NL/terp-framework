"""A mask the compose file declares as ``tmpfs`` that a running workbench still holds as a volume.

0.30.0 turned the frontend's ``node_modules`` mask from an anonymous volume into a
``tmpfs``, so that a dependency bump reaches the running dev server. A workbench that
was already up before the upgrade does not get it. When Compose recreates a container
it reattaches the old container's anonymous volumes by target path, and that wins over
the ``tmpfs`` now declared at the same path. The dev server then keeps serving the
first boot's packages from that volume, with every container healthy and the page
answering 200. An upgraded-on-paper workbench and an upgraded one look identical.

Compose owns that reattachment, so the place to undo it is before ``watch`` creates
anything. For every service whose mount at a ``tmpfs`` path is still a volume, the
container is removed, and so is that volume and only that one. Compose then creates
both fresh, with the ``tmpfs``. The volume held nothing but a copy of the image's
packages: the mask exists to hide the checkout's ``node_modules``, never to keep one.
A named volume is never touched, and neither is any other volume of the container.

Best effort, like the failure diagnosis next door: a daemon that is not up, a compose
file Compose cannot read, or a ``ps`` with no containers yet means there is nothing to
undo, and ``watch`` speaks for itself.
"""

from __future__ import annotations

import json
import pathlib
from collections.abc import Callable, Sequence

#: Runs argv, returning ``(exit status, combined output)``.
Capture = Callable[[Sequence[str]], tuple[int, str]]


def _compose(compose_file: pathlib.Path, project_name: str | None) -> list[str]:
    argv = ["docker", "compose", "-f", str(compose_file)]
    if project_name:
        argv += ["-p", project_name]
    return argv


def _json_entries(output: str) -> list[dict]:
    """A JSON array, one object, or newline-delimited objects, as Compose has printed each."""
    stripped = output.strip()
    if not stripped:
        return []
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        entries = []
        for line in stripped.splitlines():
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return [entry for entry in entries if isinstance(entry, dict)]
    items = parsed if isinstance(parsed, list) else [parsed]
    return [entry for entry in items if isinstance(entry, dict)]


def tmpfs_targets(config_output: str) -> dict[str, frozenset[str]]:
    """Per service, the paths ``docker compose config --format json`` declares as ``tmpfs``.

    Both spellings count: a ``volumes`` entry of ``type: tmpfs``, and the service-level
    ``tmpfs:`` list (whose entries may carry ``:options`` after the path).
    """
    try:
        config = json.loads(config_output)
    except json.JSONDecodeError:
        return {}
    services = config.get("services") if isinstance(config, dict) else None
    if not isinstance(services, dict):
        return {}
    found: dict[str, frozenset[str]] = {}
    for name, service in services.items():
        if not isinstance(service, dict):
            continue
        targets = {
            volume["target"]
            for volume in service.get("volumes") or ()
            if isinstance(volume, dict)
            and volume.get("type") == "tmpfs"
            and isinstance(volume.get("target"), str)
        }
        listed = service.get("tmpfs") or ()
        for entry in [listed] if isinstance(listed, str) else listed:
            if isinstance(entry, str) and entry:
                targets.add(entry.split(":", 1)[0])
        if targets:
            found[name] = frozenset(targets)
    return found


def containers(ps_output: str) -> dict[str, str]:
    """Service name to container id, from ``docker compose ps --all --format json``."""
    found: dict[str, str] = {}
    for entry in _json_entries(ps_output):
        service, container = entry.get("Service"), entry.get("ID")
        if isinstance(service, str) and isinstance(container, str) and container:
            found.setdefault(service, container)
    return found


def stale_volumes(inspect_output: str, targets: frozenset[str]) -> tuple[str, ...]:
    """The volumes ``docker inspect`` shows mounted at a path that should be a ``tmpfs``.

    Only a volume counts, never a bind: a bind at that path is somebody's deliberate
    choice, and removing it is not this command's to decide.
    """
    names: list[str] = []
    for container in _json_entries(inspect_output):
        for mount in container.get("Mounts") or ():
            if (
                isinstance(mount, dict)
                and mount.get("Type") == "volume"
                and mount.get("Destination") in targets
                and isinstance(mount.get("Name"), str)
                and mount["Name"] not in names
            ):
                names.append(mount["Name"])
    return tuple(names)


def clear_stale_masks(
    compose_file: pathlib.Path,
    *,
    project_name: str | None = None,
    capture: Capture,
) -> str:
    """Undo a pre-0.30.0 ``node_modules`` volume before ``watch``; what was done, or ``""``."""
    compose = _compose(compose_file, project_name)
    status, config = capture([*compose, "config", "--format", "json"])
    targets = tmpfs_targets(config) if status == 0 else {}
    if not targets:
        return ""
    status, ps_output = capture([*compose, "ps", "--all", "--format", "json"])
    running = containers(ps_output) if status == 0 else {}
    stale: dict[str, tuple[str, ...]] = {}
    for service, paths in sorted(targets.items()):
        container = running.get(service)
        if container is None:
            continue
        status, inspected = capture(["docker", "inspect", container])
        volumes = stale_volumes(inspected, paths) if status == 0 else ()
        if volumes:
            stale[service] = volumes
    if not stale:
        return ""
    services = sorted(stale)
    volumes = [volume for service in services for volume in stale[service]]
    listing = ", ".join(repr(service) for service in services)
    removed, _ = capture([*compose, "rm", "--stop", "--force", *services])
    if removed == 0:
        removed, _ = capture(["docker", "volume", "rm", *volumes])
    if removed != 0:
        renew = [*compose, "up", "-d", "--no-deps", "--force-recreate", "--renew-anon-volumes"]
        return (
            f"terp docker dev: {listing} still mount(s) a volume where the compose file "
            "declares a tmpfs (a workbench from before 0.30.0), so the dev server would keep "
            "serving its old packages. Removing it failed; once, by hand:\n"
            f"  {' '.join([*renew, *services])}\n"
            f"  docker volume rm {' '.join(volumes)}"
        )
    return (
        f"terp docker dev: {listing} still mounted a volume where the compose file declares "
        "a tmpfs (a workbench from before 0.30.0), so the dev server kept serving the packages "
        "it first booted with. Removed the container and that volume; this start creates both "
        "fresh."
    )
