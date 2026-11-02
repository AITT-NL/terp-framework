"""The typed model of ``deployment.json``: what a read declaration is (ADR 0184, 0187).

The reader (:mod:`terp.arch.deployment.reader`) builds these from a file the schema admits,
and every other reader of the declaration - the truth rule, the generator, a tool that
drives a deploy - takes them rather than the raw JSON.
"""

from __future__ import annotations

from dataclasses import dataclass

#: The declaration's filename, at the project root.
DEPLOYMENT_FILE = "deployment.json"


@dataclass(frozen=True)
class Finding:
    """One reason the declaration cannot be read or is not true, phrased for its fixer.

    *message* names the field and what is allowed there; *file* is the file it is about.
    """

    message: str
    remedy: str = ""
    file: str = DEPLOYMENT_FILE


@dataclass(frozen=True)
class Backup:
    """A backup policy: how often, and how long each backup is kept (ISO 8601)."""

    every: str
    keep: str


@dataclass(frozen=True)
class Unit:
    """One declared unit: a service of the deployment profile."""

    id: str
    role: str
    kind: str | None = None
    version: str | None = None
    #: ``None`` when the declaration does not restate the profile's command.
    command: tuple[str, ...] | None = None
    health_path: str | None = None
    liveness_path: str | None = None
    migrations: tuple[str, ...] = ()
    env: tuple[str, ...] = ()
    #: ``None`` when the declaration does not restate the start order.
    depends_on: tuple[str, ...] | None = None
    instances: str = "one"
    size: str | None = None
    stateful: bool = False
    backup: Backup | None = None


@dataclass(frozen=True)
class Mount:
    """Where a volume is mounted: a path inside ``var/`` and the declared units that mount it."""

    path: str
    units: tuple[str, ...]


@dataclass(frozen=True)
class Volume:
    """A named volume of the profile that holds state no declared stateful unit owns.

    *mount* is the Terp Standard's ``volumes[].mount``: a restatement under ``own``, which the
    truth rule holds to the profile, and what the generator renders under ``generated``, where
    the schema requires it (ADR 0187).
    """

    id: str
    backup: Backup | None = None
    mount: Mount | None = None


@dataclass(frozen=True)
class Declaration:
    """A ``deployment.json`` in a declared state (``own`` or ``generated``)."""

    build: str
    compose_file: str
    compose_overrides: tuple[str, ...]
    units: tuple[Unit, ...]
    volumes: tuple[Volume, ...] = ()
    #: ``(name, cpu cores, memory in MiB)`` for every declared size.
    sizes: tuple[tuple[str, float, int], ...] = ()
    rollback: str | None = None
    external_database: bool = False
    #: ``generator.systemPackages``: what only a generator reads (ADR 0187), valid only
    #: beside ``generated`` and each name one the system-package table carries.
    system_packages: tuple[str, ...] = ()

    @property
    def profile_files(self) -> tuple[str, ...]:
        """The base profile and its overrides, in the order they are merged."""
        return (self.compose_file, *self.compose_overrides)


@dataclass(frozen=True)
class Unmanaged:
    """``{"unmanaged": true, "reason": "..."}``: a tool cannot drive this deploy."""

    reason: str
