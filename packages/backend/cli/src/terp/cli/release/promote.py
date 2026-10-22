"""``terp promote``: deploy a signed release without rebuilding it (ADR 0184 d9, ADR 0187 d6).

It accepts only a DSSE envelope, and before it pulls or starts anything it verifies the envelope
against the public keys it is given, then reads the manifest it signs:

* the Terp Standard release the declaration was written against may be any up to this
  toolchain's own with the same ``schemaVersion``; only a newer one is refused, so a rollback
  across a spec-pin move needs no older CLI;
* the carried declaration is read with this toolchain's reader against the manifest's own
  ``datastores`` record, so a datastore version a newer table retired still rolls back;
* ``--require-generated`` refuses a manifest whose ``build`` is not ``generated``;
* a generated profile is audited without being rendered: over its parsed keys and scalars,
  every ``$`` is half of a ``$$`` or one of the generator's fixed interpolations at its place,
  and any YAML tag is refused.

Then it deploys exactly the signed digests: each built image pulled by digest, its id held to
the manifest's, and tagged under the profile's name and the release's ``TERP_RELEASE_TAG``; the
carried profile written out and run by compose with an allowlisted environment, never its own;
``up`` always with ``--no-build --pull never``, so an image that is not there fails instead of
being built from whatever checkout is present or pulled by a bare name. The datastores start
first; every version table is read; the migration step runs exactly once; the other services
start and are waited on. When that fails after the reading, the reading decides the undo: a
database whose version tables are as they were is restore-free to roll back (ADR 0185 decision
6, rule zero), and with ``--undo-to`` the previous release is started again once its own check
passes; otherwise the undo is a restore. A separate ``--rollback`` invocation has no reading and
is restore-based: it is refused unless ``--restored`` says the database was restored.
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import yaml

from terp.arch.deployment import (
    Declaration,
    compose_literal,
    published_tables,
    read,
    resolve_profile,
    services_of,
)
from terp.arch.deployment.datastores import read_table
from terp.arch.deployment.generator import RELEASE_TAG_VARIABLE, escape_findings
from terp.arch.deployment.reader import SPEC_RELEASE
from terp.arch.deployment.tables import Tables
from terp.cli.release import dsse
from terp.cli.release._common import DOCKER_NAMES, ReleaseError, os_environment, output_of, require, run
from terp.cli.release._render import version_key
from terp.cli.release.manifest import parse

#: The interpolations a profile reads from the environment: ``${NAME`` and ``$NAME``.
_NAMES = re.compile(r"\$(?:\{(?P<braced>[A-Za-z_][A-Za-z0-9_]*)|(?P<bare>[A-Za-z_][A-Za-z0-9_]*))")
_VERSION_TABLE = re.compile(r"alembic_version_[a-z0-9_]+")

#: Every version table, read in the release's own image with the migration step's environment.
_READ_VERSIONS = """\
import json, os, re, sqlalchemy as sa
engine = sa.create_engine(os.environ["DATABASE_URL"])
schema = "public" if engine.dialect.name == "postgresql" else None
found = {}
with engine.connect() as connection:
    for name in sorted(sa.inspect(connection).get_table_names(schema=schema)):
        if re.fullmatch(r"alembic_version_[a-z0-9_]+", name):
            table = f'"{schema}"."{name}"' if schema else f'"{name}"'
            found[name] = sorted(row[0] for row in connection.execute(sa.text(f"SELECT version_num FROM {table}")))
print(json.dumps(found, sort_keys=True))
"""


@dataclass(frozen=True)
class Release:
    """A verified manifest, and what deploying it needs."""

    manifest: dict[str, Any]
    keyid: str
    declaration: Declaration
    profile: dict[str, Any]

    @property
    def tag(self) -> str:
        return str(self.manifest["inputs"]["releaseTag"])

    @property
    def files(self) -> list[dict[str, str]]:
        given = self.manifest["inputs"]
        return [given["declaration"], *given["profiles"]]

    def services(self) -> dict[str, dict[str, Any]]:
        return {name: service for name, service in services_of(self.profile).items() if not service.get("profiles")}


def _relative(path: str) -> pathlib.PurePosixPath:
    """A carried file's path, refused unless it stays inside the directory it is written to."""
    found = pathlib.PurePosixPath(path)
    if found.is_absolute() or ".." in found.parts or "\\" in path or ":" in path or not found.parts:
        raise ReleaseError(f"the manifest carries {path!r}, a path outside the directory a release is written to")
    return found


def _tags(text_: str) -> list[str]:
    return [token.value[1] for token in yaml.scan(text_) if isinstance(token, yaml.TagToken)]


def load(envelope: bytes, public_keys: Sequence[bytes], *, require_generated: bool = False) -> Release:
    """The release *envelope* signs, verified and checked before anything is pulled or started."""
    keys = [dsse.load_public_key(pem) for pem in public_keys]
    payload, keyid = dsse.verify(envelope, keys)
    manifest = parse(payload)
    given = manifest["inputs"]
    if version_key(str(given["spec"]["release"])) > version_key(SPEC_RELEASE):
        raise ReleaseError(
            f"the release was declared against Terp Standard {given['spec']['release']}, newer than "
            f"{SPEC_RELEASE}, the release this terp promote reads: update the toolchain"
        )
    if require_generated and given["build"] != "generated":
        raise ReleaseError(f'--require-generated: the release says "build": "{given["build"]}"')
    try:
        table = read_table(given["datastores"])
        raw = json.loads(given["declaration"]["content"])
    except ValueError as exc:
        raise ReleaseError("the carried declaration or datastore record cannot be read", cause=str(exc)) from exc
    declared, findings = read(raw, table)
    if findings:
        raise ReleaseError(
            "the carried deployment.json cannot be read: " + "; ".join(finding.message for finding in findings)
        )
    if not isinstance(declared, Declaration):
        raise ReleaseError("the carried deployment.json declares no units a deploy drives (it is unmanaged)")
    if declared.build != given["build"]:
        raise ReleaseError("the carried deployment.json and the manifest disagree on the build")
    carried = {item["path"]: item["content"] for item in given["profiles"]}
    if list(carried) != list(declared.profile_files):
        raise ReleaseError("the carried profile files are not the ones the declaration names")
    for path in [given["declaration"]["path"], *carried]:
        _relative(path)
    if declared.build == "generated":
        published = published_tables()
        tables = Tables(table, published.base_images, published.system_packages, published.recipes)
        for path, content in carried.items():
            try:
                tagged, parsed = _tags(content), yaml.safe_load(content)
            except yaml.YAMLError as exc:
                raise ReleaseError(f"the carried {path} is not YAML", cause=str(exc)) from exc
            if tagged:
                raise ReleaseError(f"the carried {path} carries a YAML tag, which a generated profile never does")
            escaping = escape_findings(parsed, tables)
            if escaping:
                raise ReleaseError(
                    f"the carried {path} interpolates outside the generator's fixed list:\n"
                    + "\n".join(f"- {finding}" for finding in escaping)
                )
    with tempfile.TemporaryDirectory(prefix="terp-promote-") as scratch:
        for path, content in carried.items():
            target = pathlib.Path(scratch) / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content.encode("utf-8"))
        profile, problems = resolve_profile(pathlib.Path(scratch), declared)
    if problems:
        raise ReleaseError(f"the carried profile cannot be read: {problems[0].message}")
    return Release(manifest, keyid, declared, profile)


def _environment(release: Release, env: Mapping[str, str]) -> dict[str, str]:
    """What compose runs with: the names the profile reads, the engine's, the OS's, the tag."""
    names: set[str] = set()
    for item in release.files[1:]:
        for found in _NAMES.finditer(item["content"].replace("$$", "")):
            names.add(found.group("braced") or found.group("bare"))
    names.discard(RELEASE_TAG_VARIABLE)
    chosen = {name: env[name] for name in sorted(names) if name in env}
    return os_environment({**chosen, RELEASE_TAG_VARIABLE: release.tag}, names=DOCKER_NAMES, source=env)


def _local_name(service: Mapping[str, Any], tag: str) -> str:
    image = str(service.get("image", ""))
    return image.split(":${", 1)[0] + f":{tag}" if ":${" in image else image


def _images(release: Release, env: Mapping[str, str], *, pull: bool) -> None:
    """Every built image under its profile name and tag, held to the signed image id."""
    built = release.manifest["outputs"]["images"]
    names = {}
    for name, service in release.services().items():
        reference = release.manifest["outputs"]["services"].get(name)
        for image in built.values():
            if reference == f"{image['repository']}@{image['digest']}":
                names[_local_name(service, release.tag)] = image
    for local, image in sorted(names.items()):
        signed = f"{image['repository']}@{image['digest']}"
        if pull:
            require(run(["docker", "pull", signed], env=env), f"pulling {signed}, the signed image")
            require(run(["docker", "tag", signed, local], env=env), f"tagging {signed} as {local}")
        found = require(
            run(["docker", "image", "inspect", "--format", "{{.Id}}", local], env=env), f"inspecting {local}"
        ).decode().strip()
        if found != image["imageId"]:
            raise ReleaseError(f"{local} is {found}, not {image['imageId']}, the image the release signs")
    if pull:
        for reference in sorted(set(release.manifest["outputs"]["services"].values()) - {f"{i['repository']}@{i['digest']}" for i in built.values()}):
            require(run(["docker", "pull", reference], env=env), f"pulling {reference}")


def _compose(project: pathlib.Path, release: Release) -> list[str]:
    files: list[str] = []
    for path in release.declaration.profile_files:
        files += ["-f", str(project / path)]
    return ["docker", "compose", "--project-directory", str(project), *files]


def _write(project: pathlib.Path, release: Release) -> None:
    for item in release.files:
        target = project / item["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(item["content"].encode("utf-8"))


def _upgrade_unit(release: Release) -> tuple[str, list[str] | None]:
    """``(service, command)``: the migration step as written, or the one api unit's upgrade."""
    for name, service in sorted(release.services().items()):
        command = service.get("command")
        parts = [compose_literal(str(part)) for part in command] if isinstance(command, list) else []
        if parts[:3] == ["terp", "migrate", "upgrade"]:
            return name, None
    apis = [unit.id for unit in release.declaration.units if unit.role == "api" and unit.kind is None]
    return apis[0], ["terp", "migrate", "upgrade"]


def _check_command(release: Release) -> tuple[str, list[str]]:
    """The rollback check: the migration step's own command with ``upgrade`` as ``check``.

    The command as compose runs it, so ``$$`` is one ``$``; an element that interpolates has no
    one value to run, and the check is then refused rather than guessed.
    """
    service, command = _upgrade_unit(release)
    if command is not None:
        return service, ["terp", "migrate", "check"]
    written = [compose_literal(str(part)) for part in release.services()[service]["command"]]
    if any(part is None for part in written):
        raise ReleaseError(f"{service}'s migration step interpolates, so its own check cannot be run")
    return service, [*(str(part) for part in written[:2]), "check", *(str(part) for part in written[3:])]


def _versions(compose: list[str], service: str, env: Mapping[str, str]) -> dict[str, list[str]]:
    out = require(
        run([*compose, "run", "--rm", "--no-deps", "-T", "--entrypoint", "python", service, "-I", "-c", _READ_VERSIONS], env=env),
        "reading the version tables before the migration step",
    )
    try:
        reading = json.loads(out.decode("utf-8").strip().splitlines()[-1])
    except (ValueError, IndexError) as exc:
        raise ReleaseError("the version tables could not be read") from exc
    if not isinstance(reading, dict) or not all(_VERSION_TABLE.fullmatch(name) for name in reading):
        raise ReleaseError("the version tables were read as something else")
    return reading


def _kinds(release: Release) -> list[str]:
    services = release.services()
    return sorted(unit.id for unit in release.declaration.units if unit.kind is not None and unit.id in services)


def _rest(release: Release) -> list[str]:
    """Every service but the datastores and the migration step: what starts after it."""
    service, command = _upgrade_unit(release)
    step = {service} if command is None else set()
    return sorted(set(release.services()) - set(_kinds(release)) - step)


def _up(compose: list[str], services: list[str], env: Mapping[str, str], *, no_deps: bool = True) -> list[str]:
    """``up`` of *services*: never building, never pulling, waiting until they are healthy."""
    return [*compose, "up", "-d", "--wait", "--no-build", "--pull", "never", *(["--no-deps"] if no_deps else []), *services]


def _migrate_and_start(compose: list[str], release: Release, env: Mapping[str, str], log: list[str]) -> tuple[bool, str]:
    """Run *release*'s migration step exactly once, then start the rest. ``(ok, why)``."""
    service, command = _upgrade_unit(release)
    upgrade = run([*compose, "run", "--rm", "--no-deps", "-T", service, *(command or [])], env=env)
    if upgrade.returncode != 0:
        return False, f"the migration step failed (exit {upgrade.returncode}): {output_of(upgrade)[-2000:]}"
    log.append(f"ran the migration step once, in {service}")
    started = run(_up(compose, _rest(release), env), env=env)
    if started.returncode != 0:
        return False, f"the services did not come up healthy (exit {started.returncode}): {output_of(started)[-2000:]}"
    log.append(f"started {', '.join(_rest(release))}")
    return True, ""


def _undo(project: pathlib.Path, previous: Release, env: Mapping[str, str], log: list[str]) -> None:
    """Start *previous* again on an unchanged database, once its own check passes."""
    environment = _environment(previous, env)
    _images(previous, environment, pull=False)
    _write(project, previous)
    compose = _compose(project, previous)
    service, command = _check_command(previous)
    require(run([*compose, "run", "--rm", "--no-deps", "-T", service, *command], env=environment), f"{previous.tag}'s own migration check")
    require(run(_up(compose, _rest(previous), environment), env=environment), f"starting {previous.tag} again")
    log.append(f"undone: {previous.tag} runs again on the database as it was, without a restore")


def promote(
    envelope: str | os.PathLike[str],
    public_keys: Sequence[str | os.PathLike[str]],
    project_dir: str | os.PathLike[str],
    *,
    require_generated: bool = False,
    undo_to: str | os.PathLike[str] | None = None,
    rollback: bool = False,
    restored: bool = False,
    env: Mapping[str, str] | None = None,
) -> list[str]:
    """Deploy the release *envelope* signs into *project_dir*; what was done, line by line."""
    dsse.require_cryptography()
    keys = [pathlib.Path(key).read_bytes() for key in public_keys]
    release = load(pathlib.Path(envelope).read_bytes(), keys, require_generated=require_generated)
    previous = load(pathlib.Path(undo_to).read_bytes(), keys) if undo_to is not None else None
    if rollback and not restored:
        raise ReleaseError(
            f"a rollback to {release.tag} in an invocation of its own has no reading of the version "
            "tables taken before the release that followed it, so it is restore-based (ADR 0185 "
            "decision 6): restore the backup taken before that release, then promote again with "
            "--rollback --restored"
        )
    environment = _environment(release, env if env is not None else os.environ)
    project = pathlib.Path(project_dir)
    project.mkdir(parents=True, exist_ok=True)
    log = [f"verified {release.tag} (key {release.keyid[:16]})"]
    _images(release, environment, pull=True)
    _write(project, release)
    compose = _compose(project, release)
    if _kinds(release):
        require(run(_up(compose, _kinds(release), environment, no_deps=False), env=environment), "starting the datastores")
        log.append(f"started {', '.join(_kinds(release))}")
    reading = _versions(compose, _upgrade_unit(release)[0], environment)
    journal = project / ".terp" / f"versions-before-{release.tag}.json"
    journal.parent.mkdir(parents=True, exist_ok=True)
    journal.write_text(json.dumps(reading, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    log.append(f"read {len(reading)} version tables before the migration step ({journal})")
    if rollback:
        # Restored, the target's own check must pass on the database before its step runs.
        service, command = _check_command(release)
        require(
            run([*compose, "run", "--rm", "--no-deps", "-T", service, *command], env=environment),
            f"{release.tag}'s own migration check on the restored database",
        )
        log.append(f"{release.tag}'s own migration check passes on the restored database")
    ok, why = _migrate_and_start(compose, release, environment, log)
    if ok:
        log.append(f"promoted {release.tag}")
        return log
    unchanged = _versions(compose, _upgrade_unit(release)[0], environment) == reading
    if not unchanged:
        raise ReleaseError(
            f"{why}\nThe migration step changed the version tables, so going back is restore-based: "
            "restore the backup taken before this promotion, then start the previous release."
        )
    if previous is None:
        raise ReleaseError(
            f"{why}\nThe version tables are as they were before the migration step, so starting the "
            "previous release again is restore-free: promote it with --no-build semantics, or pass "
            "--undo-to <its envelope> to have this command do it."
        )
    _undo(project, previous, env if env is not None else os.environ, log)
    raise ReleaseError(f"{why}\n" + "\n".join(log))


__all__ = ["Release", "load", "promote"]
