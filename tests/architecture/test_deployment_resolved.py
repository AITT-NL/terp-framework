"""The resolved deployment a generated release runs, and the profile it is written beside.

:mod:`terp.arch.deployment.resolved` builds terp-spec's ``resolved-deployment`` document from
the plan the profile is written from. Two things hold it here:

* **every golden sample** (``generator_goldens/<name>/``) resolves to exactly its
  ``expected/resolved-deployment.json``, written from the current code with
  ``TERP_WRITE_GOLDENS=1`` and reviewed as a diff, like the profile beside it;
* **the profile and the document say the same**: each sample's rendered profile is read back
  (PyYAML's ``SafeLoader``, which applies the ``<<`` merges) and every field the document
  carries is held to it: the restart policy against the lifecycle, the command, ``init``,
  the variable names, the mounts, the probe and its timing, the start conditions, the
  container port and the image.
"""

from __future__ import annotations

import json
import re
from typing import Any

import pytest
import yaml

from terp.arch.deployment import published_tables, reader, resolved, resolved_check
from terp.arch.deployment._generator_text import MIGRATION_STEP
from terp.arch.deployment.generator import PROFILE, generate
from terp.arch.deployment.resolved import ResolvedDeploymentError, resolved_deployment
from terp.arch.deployment.tables import KindRecipe, Tables
from tests.architecture.deployment_fixtures import seed
from tests.architecture.test_deployment_generator import _GOLDENS, _SAMPLES, _WRITE, _sample

#: The images ``sign`` would have pushed, invented: one per image the profile builds.
IMAGES = {
    "backend": "registry.example.test/example-app-backend@sha256:" + "1a" * 32,
    "frontend": "registry.example.test/example-app-frontend@sha256:" + "2b" * 32,
    "site": "registry.example.test/example-app-site@sha256:" + "3c" * 32,
}

#: A sample the first version of the document refuses, and the words it refuses it with.
_REFUSED = {"store": "is a bundled store"}

_COMPOSE_WAITS = {
    "service_started": "started",
    "service_healthy": "healthy",
    "service_completed_successfully": "completed",
}
_SECONDS = re.compile(r"(\d+)s")


def _as_compose_reads(value: Any) -> Any:
    """A profile value as the process receives it: Compose turns each ``$$`` into ``$``.

    The generator writes every ``$`` of a declared value as ``$$``, so nothing in it is
    interpolated; the resolved deployment carries the value itself.
    """
    if isinstance(value, str):
        return value.replace("$$", "$")
    if isinstance(value, list):
        return [_as_compose_reads(item) for item in value]
    return value


def _tier(declaration: Any, unit: Any) -> str:
    """Which built image a unit runs: the site's, the web tier's, or the backend's."""
    if unit.role == "web":
        return "site" if declaration.recipe(unit.id) else "frontend"
    return "backend"


def _images_for(declaration: Any) -> dict[str, str]:
    """What ``sign`` records in ``outputs.services`` for the units built from the checkout."""
    return {unit.id: IMAGES[_tier(declaration, unit)] for unit in declaration.units if unit.kind is None}


def _resolve(name: str, **options: Any) -> dict[str, Any]:
    meta, declaration, tables = _sample(name)
    return resolved_deployment(
        declaration,
        meta["project"],
        tables=tables,
        images=options.pop("images", _images_for(declaration)),
        frontend_lock=meta["frontendLock"],
        **options,
    )


def _profile(name: str) -> dict[str, Any]:
    meta, declaration, tables = _sample(name)
    files, found = generate(
        declaration,
        meta["project"],
        tables=tables,
        frontend_lock=meta["frontendLock"],
        site_lock=meta.get("siteLock", False),
    )
    assert found == [], found
    return yaml.safe_load(files[PROFILE])


_RESOLVED = [name for name in _SAMPLES if name not in _REFUSED]


@pytest.mark.parametrize("name", _RESOLVED)
def test_a_golden_sample_resolves_to_its_expected_deployment(name: str) -> None:
    text = json.dumps(_resolve(name), indent=2, sort_keys=True) + "\n"
    expected = _GOLDENS / name / "expected" / "resolved-deployment.json"
    if _WRITE:  # the writer is run by hand, and its diff reviewed
        expected.write_text(text, encoding="utf-8")
    assert text == expected.read_text(encoding="utf-8"), (
        f"{name}: the resolved deployment moved; if on purpose, write the goldens "
        "(TERP_WRITE_GOLDENS=1) and review the diff"
    )


@pytest.mark.parametrize("name", _RESOLVED)
def test_what_the_writer_writes_the_checker_refuses_nothing_of(name: str) -> None:
    _, declaration, tables = _sample(name)
    images = sorted(set(_images_for(declaration).values()))
    found = resolved_check.refusals_for(_resolve(name), declaration, table=tables.datastores, images=images)
    assert found == [], f"{name}: {found}"


@pytest.mark.parametrize("name", sorted(_REFUSED))
def test_a_sample_version_1_cannot_say_is_refused_by_name(name: str) -> None:
    with pytest.raises(ResolvedDeploymentError, match=_REFUSED[name]):
        _resolve(name)


def _tier_of(image: str, project: str) -> str:
    matched = re.fullmatch(rf"{re.escape(project)}-(backend|frontend|site)-prod:.*", image)
    assert matched is not None, image
    return matched.group(1)


@pytest.mark.parametrize("name", _RESOLVED)
def test_the_profile_and_the_resolved_deployment_say_the_same(name: str) -> None:
    meta, _, _ = _sample(name)
    document, profile = _resolve(name), _profile(name)
    services = profile["services"]
    assert [service["id"] for service in document["services"]] == list(services)
    for service in document["services"]:
        written = services[service["id"]]
        where = f"{name}: {service['id']}"
        assert written["restart"] == ("no" if service["lifecycle"] == "one-shot" else "unless-stopped"), where
        assert written.get("init", False) is service["init"], where
        if "datastore" in service:
            assert written["image"] == service["image"], where
        else:
            assert IMAGES[_tier_of(written["image"], meta["project"])] == service["image"], where
        if service["id"] == document.get("migration"):
            assert written["command"] == list(MIGRATION_STEP), where
            assert "command" not in service, f"{where}: the executor owns the migration step's argv"
        else:
            assert _as_compose_reads(written.get("command")) == service.get("command"), where
        names = {entry["name"] for entry in service["environment"]}
        withheld = {"DATABASE_URL"} if service["id"] == document.get("migration") else set()
        assert set(written.get("environment", {})) == names | withheld, where
        assert ("env_file" in written) is service["appEnvironment"], where
        named = sorted(
            (mount["source"], mount["target"]) for mount in service["mounts"] if mount["type"] == "volume"
        )
        assert sorted(tuple(entry.split(":", 1)) for entry in written.get("volumes", [])) == named, where
        waits = {ident: _COMPOSE_WAITS[spec["condition"]] for ident, spec in written.get("depends_on", {}).items()}
        assert waits == {entry["unit"]: entry["condition"] for entry in service["after"]}, where
        probe = written.get("healthcheck")
        assert (probe is None) == ("healthcheck" not in service), where
        if probe is not None:
            check = service["healthcheck"]
            test = _as_compose_reads(probe["test"])
            if test[0] == "CMD":
                assert check == {**check, "form": "exec", "argv": test[1:]}, where
            else:
                assert check == {**check, "form": "shell", "script": test[1]}, where
            for field, key in (("interval", "intervalSeconds"), ("timeout", "timeoutSeconds"),
                               ("start_period", "startPeriodSeconds")):
                matched = _SECONDS.fullmatch(probe[field])
                assert matched is not None and int(matched.group(1)) == check[key], where
            assert probe["retries"] == check["retries"], where
        ports = written.get("ports", [])
        if ports:
            assert "serves" in service, where
            assert all(port.rsplit(":", 1)[1] == str(service["serves"]["port"]) for port in ports), where
    assert sorted(document["volumes"]) == document["volumes"]
    assert set(document["volumes"]) == set(profile.get("volumes") or {}), name


def test_every_kind_the_published_table_carries_is_one_the_document_can_say() -> None:
    """The table and the writer ship in one wheel. A kind the table publishes that the resolved
    deployment cannot say (a bundled store, today) would leave every app declaring it unable to
    sign, so it fails here first, where the contract can be extended in the same change."""
    tables = published_tables()
    for entry in tables.datastores.entries:
        raw = seed("generated")
        [unit] = [unit for unit in raw["units"] if "kind" in unit]
        unit.update(role=entry.role, kind=entry.kind, version=entry.version)
        declared, found = reader.read(raw, tables.datastores, tables.system_packages)
        assert found == [] and declared is not None, (entry.kind, found)
        built = {unit.id: IMAGES[_tier(declared, unit)] for unit in declared.units if unit.kind is None}
        document = resolved_deployment(declared, "example-app", tables=tables, images=built, frontend_lock=True)
        assert {"kind": entry.kind, "version": entry.version} in [s.get("datastore") for s in document["services"]]


def test_every_built_service_needs_the_image_sign_verified() -> None:
    _, declaration, _ = _sample("grown")
    images = _images_for(declaration)
    del images["web"]
    with pytest.raises(ResolvedDeploymentError, match=r"web runs an image the release builds, and none"):
        _resolve("grown", images=images)


def test_a_datastore_runs_the_table_s_image_only() -> None:
    _, declaration, _ = _sample("grown")
    images = {**_images_for(declaration), "db": "postgres@sha256:" + "5e" * 32}
    with pytest.raises(ResolvedDeploymentError, match=r"db runs postgres@sha256:5e.*the datastore table pins"):
        _resolve("grown", images=images)


def test_an_anonymous_mount_covers_each_image_volume_no_named_volume_covers() -> None:
    document = _resolve("grown", image_volumes={IMAGES["backend"]: ["/var/cache/example", resolved.FILES_ROOT]})
    by_id = {service["id"]: service for service in document["services"]}
    # The api mounts the files volume at the storage root, so only the other path is anonymous.
    assert by_id["api"]["mounts"] == [
        {"type": "volume", "source": "files-data", "target": "/srv/var/files", "readOnly": False},
        {"type": "anonymous", "target": "/var/cache/example"},
    ]
    # The scheduler mounts nothing, so both image volumes are anonymous: unbacked, and shown.
    assert by_id["scheduler"]["mounts"] == [
        {"type": "anonymous", "target": "/srv/var/files"},
        {"type": "anonymous", "target": "/var/cache/example"},
    ]
    assert "files-data" in document["volumes"]


def _with_recipe_environment(environment: tuple[tuple[str, str], ...]) -> Tables:
    _, _, tables = _sample("grown")
    recipe = tables.recipe("postgres")
    assert recipe is not None
    replaced = KindRecipe(
        kind=recipe.kind,
        title=recipe.title,
        data_path=recipe.data_path,
        healthcheck=recipe.healthcheck,
        environment=environment,
        variable=recipe.variable,
        url=recipe.url,
    )
    return Tables(
        datastores=tables.datastores,
        base_images=tables.base_images,
        system_packages=tables.system_packages,
        recipes=tuple(replaced if entry.kind == "postgres" else entry for entry in tables.recipes),
    )


def test_a_seam_the_document_has_no_source_for_is_refused() -> None:
    meta, declaration, _ = _sample("grown")
    tables = _with_recipe_environment((("POSTGRES_INITDB_ARGS", "${INITDB_ARGS:-}"),))
    with pytest.raises(ResolvedDeploymentError, match=r"POSTGRES_INITDB_ARGS is .* a seam version 1"):
        resolved_deployment(
            declaration, meta["project"], tables=tables, images=_images_for(declaration),
            frontend_lock=meta["frontendLock"],
        )


def test_a_required_variable_of_its_own_name_is_a_secret() -> None:
    meta, declaration, _ = _sample("grown")
    tables = _with_recipe_environment(
        (("POSTGRES_PASSWORD", "${POSTGRES_PASSWORD:?required}"), ("POSTGRES_DB", "app"))
    )
    document = resolved_deployment(
        declaration, meta["project"], tables=tables, images=_images_for(declaration),
        frontend_lock=meta["frontendLock"],
    )
    database = next(service for service in document["services"] if service["id"] == "db")
    assert database["environment"] == [
        {"name": "POSTGRES_DB", "source": "value", "value": "app"},
        {"name": "POSTGRES_PASSWORD", "source": "secret", "key": "POSTGRES_PASSWORD"},
    ]


def test_a_datastore_the_table_does_not_hold_is_refused() -> None:
    meta, declaration, tables = _sample("grown")
    emptied = Tables(
        datastores=type(tables.datastores)(entries=()),
        base_images=tables.base_images,
        system_packages=tables.system_packages,
        recipes=tables.recipes,
    )
    with pytest.raises(ResolvedDeploymentError, match=r"db: no datastore table entry for postgres 17"):
        resolved_deployment(
            declaration, meta["project"], tables=emptied, images=_images_for(declaration),
            frontend_lock=meta["frontendLock"],
        )


def test_a_probe_of_another_form_or_timing_is_refused() -> None:
    with pytest.raises(ResolvedDeploymentError, match="a probe of an unknown form"):
        resolved._healthcheck((("NONE",), ()))
    with pytest.raises(ResolvedDeploymentError, match="a probe timing line it cannot read"):
        resolved._healthcheck((("CMD", "true"), ("interval: soon",)))


def test_the_container_ports_are_the_profile_s() -> None:
    assert resolved.API_CONTAINER_PORT == 8000
    assert resolved.WEB_CONTAINER_PORT == 8080
