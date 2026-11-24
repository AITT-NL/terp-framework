"""Where a Compose service's container path is on this machine (for ``terp smoke``).

Split out of ``terp.cli.smoke``: the translation of a bind-mounted container path, with the
Compose interpolation it needs, is a self-contained piece of the smoke plan.
"""

from __future__ import annotations

import pathlib
from collections.abc import Mapping


def _mounts(service: Mapping, environment: Mapping[str, str]) -> list[tuple[str, str]]:
    """``(host, container)`` pairs from a service's short-form bind mounts.

    Interpolated BEFORE splitting: the template's mounts are written
    ``${TERP_DEV_HOST_ROOT:-.}/app:/app/app``, and that default value contains the very
    colon the split is looking for — so resolving first is what keeps the host half from
    being torn in two.
    """
    pairs: list[tuple[str, str]] = []
    for volume in service.get("volumes") or []:
        if not isinstance(volume, str):
            continue
        parts = _interpolate(volume, environment).split(":")
        # A Windows host path carries its own drive colon (`C:\src\app:/app/app`), so the
        # container half is the LAST absolute-looking part, not simply parts[1].
        if len(parts) < 2 or not parts[-1].startswith("/"):
            continue
        pairs.append((":".join(parts[:-1]), parts[-1]))
    return pairs


def _host_path(
    service: Mapping,
    container_path: str,
    root: pathlib.Path,
    environment: Mapping[str, str],
) -> str:
    """Translate a container path through the service's bind mounts."""
    for host, container in _mounts(service, environment):
        if container_path == container or container_path.startswith(f"{container}/"):
            local = pathlib.PurePath(host)
            suffix = container_path[len(container) :].strip("/")
            base = local if local.is_absolute() else root / host
            return str(base / suffix if suffix else base)
    return container_path


def _interpolate(value: str, environment: Mapping[str, str]) -> str:
    """Resolve ``${VAR}`` / ``${VAR:-default}`` the way compose would, from *environment*."""
    out, index = [], 0
    while index < len(value):
        start = value.find("${", index)
        if start == -1:
            out.append(value[index:])
            break
        out.append(value[index:start])
        end = value.find("}", start)
        if end == -1:
            out.append(value[start:])
            break
        body = value[start + 2 : end]
        name, _, default = body.partition(":-")
        name = name.split(":?")[0].split("?")[0]
        out.append(environment.get(name) or default)
        index = end + 1
    return "".join(out)
