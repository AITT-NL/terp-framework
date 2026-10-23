"""The generator renders a generated app's build files, and the template is its render (ADR 0187).

``terp.arch.deployment.generate`` is a pure function of the typed declaration, the project
name, whether the checkout holds ``frontend/package-lock.json``, and the framework release's
tables. What is held here:

* **the seed renders the template's own three files**, byte for byte, with the slug left as
  the template's placeholder - so the template and the generator cannot drift;
* **every golden sample** (``generator_goldens/<name>/``: a ``deployment.json``, its
  ``sample.json`` and the exact expected profile) renders exactly that, and the Dockerfiles it
  renders are the template's; **every refusal sample** (``generator_goldens/refusals.json``)
  is refused with its own message and names ``own`` as the way out;
* **properties over every sample**: byte-identical renders across processes and hash seeds;
  every plain scalar reads back as a string under YAML 1.1 and 1.2; every declared value
  reaches compose as a literal; the truth rule, deploy-safety and the escape audit pass; the
  production profile's invariants hold; every ``FROM`` is a table digest; ASCII, LF, one
  final newline, no trailing whitespace;
* **the generator imports the standard library and the reader's own modules only**, and does
  no I/O;
* **the Docker lane**: ``docker compose config`` over the ``hostile-values`` render gives
  every value back literally (skipped where no Docker engine answers).

Every sample is read through :func:`terp.arch.deployment.read`, the reader every caller uses,
so a golden is also a declaration the reader accepts. A refusal sample is built straight into
the typed model instead, because some of them are what the reader refuses first (a version the
table does not carry), and the generator must still refuse them on its own.

Set ``TERP_WRITE_GOLDENS=1`` to write each sample's expected files from the current render,
then review the diff: a golden that moves is a change every generated app meets.
"""

from __future__ import annotations

import ast
import copy
import dataclasses
import hashlib
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys

import pytest
import yaml

from terp.arch.deployment import generator, reader
from terp.arch.deployment.datastores import read_table
from terp.arch.deployment.generator import (
    APP_ROOT,
    BACKEND_DOCKERFILE,
    FRONTEND_DOCKERFILE,
    MOUNT_PATH,
    OWNED_PATHS,
    PROFILE,
    escape_findings,
    fixed_interpolations,
    generate,
    plain_safe,
    scalar,
)
from terp.arch.deployment.profile import compose_literal, truth_findings
from terp.arch.deployment.tables import (
    BASE_IMAGE_NAMES,
    BASE_IMAGE_SOURCES,
    KindRecipe,
    TableError,
    Tables,
    published_tables,
    read_base_images,
    read_system_packages,
)
from terp.cli.deploy_safety import audit
from tests.architecture.deployment_fixtures import answer_files
from tests.architecture.deployment_fixtures import seed as template_seed

_REPO = pathlib.Path(__file__).resolve().parents[2]
_GOLDENS = pathlib.Path(__file__).with_name("generator_goldens")
_TEMPLATE = _REPO / "template" / "project"
_TEMPLATE_FILES = {
    BACKEND_DOCKERFILE: _TEMPLATE / "Dockerfile.prod",
    FRONTEND_DOCKERFILE: _TEMPLATE / "frontend" / "Dockerfile.prod",
    PROFILE: _TEMPLATE / "docker-compose.prod.yml.jinja",
}
#: A project name that stands for the template's placeholder: valid, and nowhere else.
_SLUG = "terp-template-slug"
_PLACEHOLDER = "{{ project_slug }}"
_SAMPLES = sorted(path.name for path in _GOLDENS.iterdir() if path.is_dir())
_REFUSALS = json.loads((_GOLDENS / "refusals.json").read_text(encoding="utf-8"))["refusals"]
_WRITE = os.environ.get("TERP_WRITE_GOLDENS") == "1"


def _tables(raw: dict | None) -> Tables:
    published = published_tables()
    if not raw:
        return published
    return Tables(
        datastores=read_table(raw["datastores"]),
        base_images=published.base_images,
        system_packages=published.system_packages,
        recipes=published.recipes + tuple(
            KindRecipe(
                kind=entry["kind"],
                title=entry["title"],
                data_path=entry["dataPath"],
                healthcheck=tuple(entry["healthcheck"]),
                environment=tuple(tuple(pair) for pair in entry["environment"]),
                variable=entry["variable"],
                url=entry["url"],
            )
            for entry in raw["recipes"]
        ),
    )


def _declare(raw: dict, tables: Tables) -> reader.Declaration:
    """A sample's declaration, as the reader reads it."""
    declared, findings = reader.read(raw, tables.datastores, tables.system_packages)
    assert findings == [], findings
    assert isinstance(declared, reader.Declaration)
    return declared


def _sample(name: str) -> tuple[dict, reader.Declaration, Tables]:
    folder = _GOLDENS / name
    meta = json.loads((folder / "sample.json").read_text(encoding="utf-8"))
    tables = _tables(meta.get("tables"))
    raw = json.loads((folder / "deployment.json").read_text(encoding="utf-8"))
    return meta, _declare(raw, tables), tables


def _render(name: str) -> dict[str, bytes]:
    meta, declaration, tables = _sample(name)
    files, found = generate(
        declaration, meta["project"], tables=tables, frontend_lock=meta["frontendLock"]
    )
    assert found == [], found
    return files


def _seed(*, use_files: bool = False) -> reader.Declaration:
    return _declare(template_seed("generated", use_files=use_files), published_tables())


def _profile(files: dict[str, bytes]) -> dict:
    return yaml.safe_load(files[PROFILE].decode("ascii"))


# --------------------------------------------------------------------------- #
# the seed is the template                                                      #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("use_files", [False, True], ids=["default", "use_files"])
def test_the_seed_renders_the_template_s_own_files_byte_for_byte(use_files: bool) -> None:
    """Decision 1: the template's three files are the render of the seed, held byte for
    byte, with the slug left as the template's placeholder. So a hardening change is made
    once, in the generator, and adopting generated in a template-shaped app at the same
    template version changes no build file.

    For every answer the seed renders on: with ``use_files`` the seed declares the files
    volume, and the profile carries it exactly as the generator renders it, so an
    app with files adopts ``generated`` without a build-file change either."""
    files, found = generate(
        _seed(use_files=use_files), _SLUG, tables=published_tables(), frontend_lock=True
    )
    assert found == []
    assert set(files) == set(OWNED_PATHS)
    for path, template in _TEMPLATE_FILES.items():
        rendered = files[path].replace(_SLUG.encode(), _PLACEHOLDER.encode())
        text = answer_files(template.read_bytes().decode("ascii"), use_files)
        assert text.encode("ascii") == rendered, (
            f"template/project/{template.name} is not the seed's render: change the generator "
            "(terp.arch.deployment.generator), never the template's copy, and write the "
            "template's file from the render"
        )
    assert _SLUG.encode() not in b"".join(_TEMPLATE_FILES[path].read_bytes() for path in files)


def test_the_files_volume_is_rendered_only_where_the_answer_is_on() -> None:
    """The use_files answer is the only difference: the volume, its mount on the api and
    nothing else. Without the answer the profile mounts nothing at the storage
    root, as the seed declares no volume."""
    without, _ = generate(_seed(), _SLUG, tables=published_tables(), frontend_lock=True)
    with_files, _ = generate(
        _seed(use_files=True), _SLUG, tables=published_tables(), frontend_lock=True
    )
    assert without[BACKEND_DOCKERFILE] == with_files[BACKEND_DOCKERFILE]
    assert without[FRONTEND_DOCKERFILE] == with_files[FRONTEND_DOCKERFILE]
    plain, files = _profile(without), _profile(with_files)
    assert files["volumes"] == {"db-data": None, "files-data": None}
    assert files["services"]["api"]["volumes"] == [f"files-data:{APP_ROOT}/{MOUNT_PATH}"]
    for name, service in files["services"].items():
        if name != "api":
            assert service == plain["services"][name], f"{name} changed with use_files"
    assert "volumes" not in plain["services"]["api"]
    assert plain["volumes"] == {"db-data": None}


def test_the_template_s_placeholder_is_the_project_name_a_render_uses() -> None:
    """The profile's placeholder stands where the generator writes [project].name, and the
    template's pyproject.toml writes the same placeholder there."""
    pyproject = (_TEMPLATE / "pyproject.toml.jinja").read_text(encoding="utf-8")
    assert f'name = "{_PLACEHOLDER}"' in pyproject
    profile = _TEMPLATE_FILES[PROFILE].read_text(encoding="utf-8")
    assert profile.count(_PLACEHOLDER) == 3
    for use_files in (False, True):
        text = answer_files(profile, use_files)
        assert "{%" not in text and "{#" not in text, "the render holds no other Jinja"
    assert profile.count("{%- if use_files %}") == 2, "the volume and its mount, nothing else"


# --------------------------------------------------------------------------- #
# the goldens                                                                   #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("name", _SAMPLES)
def test_a_golden_sample_renders_exactly_its_expected_files(name: str) -> None:
    files = _render(name)
    folder = _GOLDENS / name
    meta = json.loads((folder / "sample.json").read_text(encoding="utf-8"))
    if _WRITE:  # pragma: no cover - the writer is run by hand, and its diff reviewed
        (folder / "expected").mkdir(exist_ok=True)
        (folder / "expected" / PROFILE).write_bytes(files[PROFILE])
        meta["renders"] = list(files)
        (folder / "sample.json").write_bytes((json.dumps(meta, indent=2) + "\n").encode("ascii"))
    assert list(files) == meta["renders"], "a path the declaration renders nothing for is absent"
    assert files[PROFILE] == (folder / "expected" / PROFILE).read_bytes(), (
        f"{name}: the profile moved; if on purpose, write the goldens (TERP_WRITE_GOLDENS=1) "
        "and review the diff"
    )
    for path in (BACKEND_DOCKERFILE, FRONTEND_DOCKERFILE):
        if path in files:
            assert files[path] == _TEMPLATE_FILES[path].read_bytes(), (
                f"{name}: {path} takes no declaration input in this version: it is the template's"
            )


def test_the_reference_app_s_profile_is_the_grown_sample_s_render() -> None:
    """The grown sample is the reference shape, and the reference app's own production
    profile is its render: the shape every lane runs is one the generator renders, so the
    generated lane ADR 0187 adds next starts from a profile that already holds."""
    overlay = _REPO / "apps" / "reference" / "overlay" / PROFILE
    assert overlay.read_bytes() == _render("grown")[PROFILE]
    meta, _declaration, _tables_ = _sample("grown")
    answers = (_REPO / "apps" / "reference" / "answers.yml").read_text(encoding="utf-8")
    assert f"project_slug: {meta['project']}" in answers.splitlines()


def test_the_samples_are_the_ones_the_adr_names() -> None:
    assert set(_SAMPLES) >= {
        "grown", "no-frontend", "no-api", "no-api-no-migration", "external-database",
        "hostile-values", "store", "renamed",
    }
    for name in _SAMPLES:
        assert json.loads((_GOLDENS / name / "sample.json").read_text(encoding="utf-8"))["about"]


@pytest.mark.parametrize("name", sorted(_REFUSALS))
def test_a_refusal_sample_is_refused_with_its_own_message(name: str) -> None:
    sample = _REFUSALS[name]
    files, found = generate(
        reader._declaration(sample["declaration"]),
        sample["project"],
        tables=_tables(sample.get("tables")),
        frontend_lock=sample["frontendLock"],
    )
    assert files == {}, "all files or none"
    messages = [finding.message for finding in found]
    for expected in sample["refused"]:
        assert any(expected in message for message in messages), (expected, messages)
    assert all('"build": "own"' in finding.remedy for finding in found), (
        "every refusal names own as the way out (ADR 0111's degradation test)"
    )
    assert all("(allowed: " in message for message in messages), "and what is allowed"


def test_two_volumes_render_where_each_unit_mounts_one() -> None:
    """The refusal of a second volume at one mount point is per unit: two volumes on two
    units are two mount points, and render."""
    raw = template_seed("generated", use_files=True)
    raw["volumes"].append(
        {"id": "more-files", "mount": {"path": "var/files", "units": ["migrate"]}}
    )
    files, found = generate(
        _declare(raw, published_tables()), _SLUG, tables=published_tables(), frontend_lock=True
    )
    assert found == []
    services = _profile(files)["services"]
    assert services["api"]["volumes"] == [f"files-data:{APP_ROOT}/{MOUNT_PATH}"]
    assert services["migrate"]["volumes"] == [f"more-files:{APP_ROOT}/{MOUNT_PATH}"]


def test_a_refusal_names_the_file_it_is_about() -> None:
    sample = _REFUSALS["a-project-name-docker-refuses"]
    _files, found = generate(
        reader._declaration(sample["declaration"]), "Demo_App",
        tables=published_tables(), frontend_lock=True,
    )
    assert [finding.file for finding in found] == ["pyproject.toml"]
    _files, found = generate(
        reader._declaration(_REFUSALS["a-start-order-cycle"]["declaration"]), "demo",
        tables=published_tables(), frontend_lock=True,
    )
    assert {finding.file for finding in found} == {"deployment.json"}


@pytest.mark.parametrize(
    ("project", "accepted"),
    [
        ("demo", True), ("my-terp-app", True), ("my_app", True), ("my__app", True),
        ("a1-b2", True), ("1app", True), ("my-", True),
        ("My-App", False), ("my.app", False), ("my___app", False), ("my_", False),
        ("_app", False), ("-app", False), ("my app", False), ("", False), ("a" * 300, False),
    ],
)
def test_the_project_name_is_refused_only_where_compose_or_docker_refuses_it(
    project: str, accepted: bool
) -> None:
    # Used verbatim, never normalised: <name>-prod is compose's project name and
    # <name>-backend-prod / <name>-frontend-prod are Docker repository path components.
    _files, found = generate(_seed(), project, tables=published_tables(), frontend_lock=True)
    assert (found == []) is accepted, found


# --------------------------------------------------------------------------- #
# properties over every render                                                  #
# --------------------------------------------------------------------------- #
_HASH_SCRIPT = """
import hashlib, json, sys
sys.path.insert(0, sys.argv[1])
import test_deployment_generator as suite
print(json.dumps({
    name: {path: hashlib.sha256(data).hexdigest() for path, data in suite._render(name).items()}
    for name in suite._SAMPLES
}, sort_keys=True))
"""


def _hashes() -> dict[str, dict[str, str]]:
    return {
        name: {path: hashlib.sha256(data).hexdigest() for path, data in _render(name).items()}
        for name in _SAMPLES
    }


@pytest.mark.parametrize("seed", ["0", "1", "4242", "random"])
def test_renders_are_byte_identical_across_processes_and_hash_seeds(seed: str) -> None:
    environment = dict(os.environ, PYTHONHASHSEED=seed)
    run = subprocess.run(
        [sys.executable, "-c", _HASH_SCRIPT, str(pathlib.Path(__file__).parent)],
        capture_output=True, text=True, env=environment, cwd=_REPO, check=False,
    )
    assert run.returncode == 0, run.stderr
    assert json.loads(run.stdout) == _hashes()


#: The YAML 1.2 core schema's resolvers (yaml.org/spec/1.2.2, 10.3.2), applied to a plain
#: scalar: a match is a scalar compose's own reader would not read as a string. PyYAML,
#: which is YAML 1.1, is the other reader.
_YAML_12 = re.compile(
    r"null|Null|NULL|~|true|True|TRUE|false|False|FALSE"
    r"|[-+]?[0-9]+|0o[0-7]+|0x[0-9a-fA-F]+"
    r"|[-+]?(\.[0-9]+|[0-9]+(\.[0-9]*)?)([eE][-+]?[0-9]+)?"
    r"|[-+]?\.(inf|Inf|INF)|\.nan|\.NaN|\.NAN"
)


#: The keys whose plain value is meant as a boolean or an integer: fixed structure, never
#: built from a declaration value or an id.
_TYPED_KEYS = {"required": ("true", "false"), "disable": ("true",), "init": ("true",),
               "retries": ("3",)}


def _plain_scalars(node: yaml.Node, key: str | None = None):
    """Every plain scalar of a composed document, with the key it is the value of."""
    if isinstance(node, yaml.MappingNode):
        for name, item in node.value:
            yield from _plain_scalars(name)
            yield from _plain_scalars(item, name.value)
    elif isinstance(node, yaml.SequenceNode):
        for item in node.value:
            yield from _plain_scalars(item, key)
    elif isinstance(node, yaml.ScalarNode) and node.style is None:
        yield key, node.value, node.tag


def _named_volumes(name: str) -> list[tuple[str, None]]:
    """The top-level named volumes: written with no options, so their value is empty."""
    return [(volume, None) for volume in _profile(_render(name)).get("volumes", {})]


@pytest.mark.parametrize("name", _SAMPLES)
def test_every_plain_scalar_reads_back_as_a_string_under_yaml_1_1_and_1_2(name: str) -> None:
    """PyYAML is YAML 1.1 (``no`` is false, ``0o17`` a string); the 1.2 core schema is the
    other reading (``0o17`` is 15, ``1e3`` a thousand). A plain scalar built from an id or
    the project name must be the same string under both."""
    document = yaml.compose(_render(name)[PROFILE].decode("ascii"))
    seen = 0
    for key, value, tag in _plain_scalars(document):
        if key in _TYPED_KEYS:
            assert value in _TYPED_KEYS[key], (name, key, value)
        elif value == "<<":
            assert tag == "tag:yaml.org,2002:merge"
        elif value == "":
            assert key in {name for name, _ in _named_volumes(name)}, (name, key)
        else:
            seen += 1
            assert tag == "tag:yaml.org,2002:str", (name, key, value, tag)
            assert _YAML_12.fullmatch(value) is None, (name, key, value, "YAML 1.2")
    assert seen > 10


def _services(files: dict[str, bytes]) -> dict[str, dict]:
    return _profile(files)["services"]


def _commands(declaration: reader.Declaration) -> dict[str, tuple[str, ...]]:
    """The command each unit runs: declared, or the generator's own for its role."""
    run: dict[str, tuple[str, ...]] = {}
    step_taken = False
    for unit in declaration.units:
        if unit.command is not None:
            run[unit.id] = unit.command
        elif unit.kind is None and unit.role == "one-shot" and not step_taken:
            run[unit.id], step_taken = generator.MIGRATION_STEP, True
        elif unit.kind is None and unit.role in generator.DEFAULT_COMMANDS:
            run[unit.id] = generator.DEFAULT_COMMANDS[unit.role]
    return run


@pytest.mark.parametrize("name", _SAMPLES)
def test_every_value_reaches_compose_as_a_literal(name: str) -> None:
    _meta, declaration, _tables_ = _sample(name)
    services = _services(_render(name))
    for ident, command in _commands(declaration).items():
        written = services[ident]["command"]
        assert tuple(compose_literal(part) for part in written) == command, (ident, written)
    for unit in declaration.units:
        if unit.kind is None and unit.role == "api":
            probe = services[unit.id]["healthcheck"]["test"]
            assert probe[:3] == ["CMD", "python", "-c"] and compose_literal(probe[4]) == unit.liveness_path
            assert len(probe) == 5, "the path is the probe's one argument, never its code"
    for volume in declaration.volumes:
        for ident in volume.mount.units:
            assert f"{volume.id}:/srv/var/files" in [
                compose_literal(entry) for entry in services[ident]["volumes"]
            ]


@pytest.mark.parametrize("name", _SAMPLES)
def test_the_truth_rule_deploy_safety_and_the_escape_audit_pass(
    name: str, tmp_path: pathlib.Path
) -> None:
    meta, declaration, tables = _sample(name)
    files = _render(name)
    for path, data in files.items():
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_bytes(data)
    manifest = _GOLDENS / name / "environment.schema.json"
    if manifest.is_file():
        shutil.copy(manifest, tmp_path / "environment.schema.json")
    (tmp_path / ".git").mkdir()
    assert truth_findings(tmp_path, declaration, tables.datastores) == []
    profile = _profile(files)
    assert audit(profile) == [], "deploy-safety"
    assert escape_findings(profile, tables) == [], "the executor's escape audit"
    tags = [
        token for token in yaml.scan(files[PROFILE].decode("ascii"))
        if isinstance(token, yaml.TagToken)
    ]
    assert tags == [], "the audit refuses any YAML tag, and the generator writes none"


@pytest.mark.parametrize("name", _SAMPLES)
def test_the_production_profile_s_invariants_hold(name: str) -> None:
    """ADR 0062's invariants, held over every render rather than over the seed's alone:
    ENVIRONMENT=production and required secrets on every backend unit, the DATABASE_URL
    seam, restart policies, healthchecks, no seed, no --reload, the env files, the logs."""
    _meta, declaration, _tables_ = _sample(name)
    services = _services(_render(name))
    assert set(services) == {unit.id for unit in declaration.units}, "the declared units, only"
    databases = [unit.id for unit in declaration.units if unit.role == "database"]
    for unit in declaration.units:
        service = services[unit.id]
        assert service["logging"] == {"driver": "json-file",
                                      "options": {"max-size": "10m", "max-file": "3"}}
        assert "terp seed" not in " ".join(service.get("command") or [])
        assert "--reload" not in (service.get("command") or []) and "develop" not in service
        if unit.kind is not None:
            assert service["restart"] == "unless-stopped" and service["healthcheck"]["test"]
            if unit.kind == "postgres":
                assert ":?" in service["environment"]["POSTGRES_PASSWORD"]
            continue
        if unit.role == "web":
            assert "env_file" not in service and service["restart"] == "unless-stopped"
            assert service["healthcheck"]["test"][0] == "CMD-SHELL"
            continue
        env = service["environment"]
        assert env["ENVIRONMENT"] == "production"
        assert env["SECRET_KEY"].startswith("${SECRET_KEY:?")
        if databases:
            assert env["DATABASE_URL"].startswith("${DATABASE_URL:-")
            assert f"@{databases[0]}:5432/" in env["DATABASE_URL"]
        else:
            assert env["DATABASE_URL"].startswith("${DATABASE_URL:?")
            assert "POSTGRES_PASSWORD" not in json.dumps(services)
        assert service["env_file"] == [
            {"path": ".app.env", "required": False},
            {"path": f".app.{unit.id}.env", "required": False},
        ]
        if unit.role == "one-shot":
            assert service["restart"] == "no" and "healthcheck" not in service
        elif unit.role == "api":
            assert service["restart"] == "unless-stopped" and "init" not in service
        else:
            assert service["restart"] == "unless-stopped" and service["init"] is True
            assert "healthcheck" not in service, "ready once it runs; see the next test"


@pytest.mark.parametrize("name", _SAMPLES)
def test_a_render_can_pass_docker_compose_up_wait(name: str) -> None:
    """A deploy runs `docker compose up -d --wait`, which (Compose 2.40, measured) refuses a
    container that turns unhealthy and a service whose check is disabled ("has no healthcheck
    configured"), and waits for a service with no check until it runs. So the backend image
    carries no HEALTHCHECK for a unit that serves no HTTP to inherit, no rendered service
    disables one, and every service that has one probes something it serves."""
    files = _render(name)
    if BACKEND_DOCKERFILE in files:
        lines = files[BACKEND_DOCKERFILE].decode("ascii").splitlines()
        assert not any(line.startswith("HEALTHCHECK") for line in lines)
    _meta, declaration, _tables_ = _sample(name)
    services = _services(files)
    for unit in declaration.units:
        check = services[unit.id].get("healthcheck")
        if check is None:
            assert unit.kind is None and unit.role not in ("api", "web"), unit.id
            continue
        assert "disable" not in check and check["test"], unit.id
        assert unit.kind is not None or unit.role in ("api", "web"), unit.id


def test_every_from_is_a_base_image_table_digest() -> None:
    images = {base.image for base in published_tables().base_images.images}
    for path in (BACKEND_DOCKERFILE, FRONTEND_DOCKERFILE):
        lines = _TEMPLATE_FILES[path].read_text(encoding="utf-8").splitlines()
        froms = [line.split()[1] for line in lines if line.startswith("FROM ")]
        external = [image for image in froms if "@sha256:" in image or ":" in image]
        assert external and set(external) <= images, (path, external)
        assert all(image in images or image in ("deps",) for image in froms), froms
        for index, line in enumerate(lines):
            if line.startswith("FROM ") and "@sha256:" in line:
                image = line.split()[1]
                base = next(b for b in published_tables().base_images.images if b.image == image)
                assert lines[index - 1] == f"# {base.tag}", "the tag it was read from stands above"


@pytest.mark.parametrize("name", [*_SAMPLES, "seed"])
def test_the_output_is_ascii_lf_with_one_final_newline_and_no_trailing_space(name: str) -> None:
    files = (
        generate(_seed(), _SLUG, tables=published_tables(), frontend_lock=True)[0]
        if name == "seed"
        else _render(name)
    )
    for path, data in files.items():
        data.decode("ascii")
        assert b"\r" not in data and data.endswith(b"\n") and not data.endswith(b"\n\n"), path
        assert not any(line != line.rstrip() for line in data.decode().split("\n")), path
        assert b"\t" not in data, path


# --------------------------------------------------------------------------- #
# the encoders                                                                  #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("text", "plain"),
    [
        ("db", True), ("db-data", True), (".app.no.env", True), ("api:8000", True),
        ("db-data:/var/lib/postgresql/data", True), ("my-app-prod", True),
        ("no", False), ("No", False), ("y", False), ("off", False), ("true", False),
        ("null", False), ("~", False), ("1e3", False), ("0o17", False), ("0x1F", False),
        ("017", False), ("1:30", False), ("1.5", False), (".5", False), (".inf", False),
        (".NaN", False), ("2026-10-21", False), ("<<", False), ("=", False),
        ("a b", False), ("a#b", False), ("-a", False), ("", False), ("a: b", False),
    ],
)
def test_a_scalar_stands_plain_only_where_both_yamls_read_it_as_this_string(
    text: str, plain: bool
) -> None:
    assert plain_safe(text) is plain, text


def test_an_id_that_starts_with_a_digit_is_quoted_even_where_yaml_reads_a_string() -> None:
    assert scalar("1app-data:/var/lib/postgresql/data") == '"1app-data:/var/lib/postgresql/data"'
    assert scalar("1app-prod", leading_id=False) == "1app-prod", "a project name is not an id"
    assert scalar("no") == '"no"' and scalar("db") == "db"


def test_a_value_is_always_double_quoted_ascii_with_every_dollar_doubled() -> None:
    assert generator.value("a$b") == '"a$$b"'
    assert generator.value('say "hi" \\ now') == '"say \\"hi\\" \\\\ now"'
    assert generator.value("café \U0001f600") == '"caf\\u00E9 \\U0001F600"'
    assert generator.value(" \x07") == '"\\u2028\\u0007"', "never a raw control or separator"
    assert yaml.safe_load(generator.value("café \U0001f600 \"q\" \\")) == (
        "café \U0001f600 \"q\" \\"
    )


# --------------------------------------------------------------------------- #
# the escape audit                                                              #
# --------------------------------------------------------------------------- #
def test_the_escape_audit_finds_every_interpolation_outside_its_place() -> None:
    tables = published_tables()
    seed = _profile(generate(_seed(), "demo", tables=tables, frontend_lock=True)[0])
    assert escape_findings(seed, tables) == []
    for change, expected in (
        (lambda p: p["services"]["migrate"].update(command=["echo", "${SECRET_KEY}"]),
         "services.migrate.command[]"),
        (lambda p: p["services"]["api"]["environment"].update(EXTRA="$HOME"),
         "services.api.environment.EXTRA"),
        (lambda p: p["services"]["api"]["environment"].update(
            SECRET_KEY="${SECRET_KEY:-weak}"), "services.api.environment.SECRET_KEY"),
        (lambda p: p["services"]["web"]["ports"].append("${OTHER_PORT}:8080"),
         "services.web.ports[]"),
        (lambda p: p["services"].update({"$name": {}}), "the key '$name'"),
        (lambda p: p["x-backend"]["environment"].update(
            DATABASE_URL="${DATABASE_URL:-postgresql+psycopg://app:${HOME}@db:5432/app}"),
         "x-backend.environment.DATABASE_URL"),
    ):
        profile = copy.deepcopy(seed)
        change(profile)
        found = escape_findings(profile, tables)
        assert any(expected in item for item in found), (expected, found)
    listed = [place for place, _pattern in fixed_interpolations(tables)]
    assert "environment.POSTGRES_PASSWORD" in listed and "environment.DATABASE_URL" in listed
    assert escape_findings(["$$x", "plain"], tables) == []
    assert escape_findings(["$x"], tables) == ["[]: '$x' interpolates outside the fixed list"]


# --------------------------------------------------------------------------- #
# the generator's own discipline                                                #
# --------------------------------------------------------------------------- #
#: The generator's modules: the function, its refusals, its profile, its one YAML encoder and
#: its fixed text.
_GENERATOR_MODULES = ("generator", "_refusals", "_compose", "_yaml", "_generator_text")
_ALLOWED_IMPORTS = {
    "__future__",
    "dataclasses",
    "re",
    "terp.arch.deployment.reader",
    "terp.arch.deployment.tables",
    *(f"terp.arch.deployment.{module}" for module in _GENERATOR_MODULES),
}


@pytest.mark.parametrize("module", _GENERATOR_MODULES)
def test_the_generator_imports_the_standard_library_and_the_reader_only(module: str) -> None:
    """Decision 2: a pure function, no I/O, no template engine, no YAML library: each of its
    modules imports the standard library's text tools and the reader's own modules, and
    nothing else, and calls nothing that reads, writes or runs code."""
    source = pathlib.Path(generator.__file__).with_name(f"{module}.py")
    tree = ast.parse(source.read_text(encoding="utf-8"))
    imported = {
        alias.name for node in ast.walk(tree) if isinstance(node, ast.Import)
        for alias in node.names
    } | {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    assert imported <= _ALLOWED_IMPORTS, sorted(imported - _ALLOWED_IMPORTS)
    called = {
        node.func.id for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert not called & {"open", "exec", "eval", "compile", "__import__", "input"}, called


# --------------------------------------------------------------------------- #
# the tables                                                                    #
# --------------------------------------------------------------------------- #
def test_the_published_tables_carry_every_base_by_digest_and_say_where_it_came_from() -> None:
    tables = published_tables()
    assert [base.name for base in tables.base_images.images] == list(BASE_IMAGE_NAMES)
    assert set(BASE_IMAGE_SOURCES) == set(BASE_IMAGE_NAMES)
    for base in tables.base_images.images:
        assert re.fullmatch(r"[a-z0-9./-]+@sha256:[0-9a-f]{64}", base.image), base
    assert tables.system_packages.packages == (), "empty until a measured need"
    assert [recipe.kind for recipe in tables.recipes] == ["postgres"]
    assert {entry.kind for entry in tables.datastores.entries} <= {
        recipe.kind for recipe in tables.recipes
    }, "every published kind has a recipe"
    assert tables.recipe("redis") is None


_BASES = json.loads(
    (pathlib.Path(generator.__file__).with_name("base-images.json")).read_text(encoding="utf-8")
)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda raw: raw.update(extra=1), "nothing else"),
        (lambda raw: raw["images"].pop("uv"), "names exactly"),
        (lambda raw: raw["images"].update(uv={"image": "x"}), "exactly an image"),
        (lambda raw: raw["images"]["uv"].update(image="ghcr.io/astral-sh/uv:latest"),
         "by digest alone"),
        (lambda raw: raw["images"]["uv"].update(image=7), "by digest alone"),
        (lambda raw: raw["images"]["uv"].update(tag="latest"), "names no tag"),
    ],
)
def test_a_base_image_table_in_another_shape_is_refused(change, message) -> None:
    raw = copy.deepcopy(_BASES)
    change(raw)
    with pytest.raises(TableError, match=message):
        read_base_images(raw)
    with pytest.raises(TableError, match="nothing else"):
        read_base_images([])


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ({"packages": {}, "extra": 1}, "nothing else"),
        ([], "nothing else"),
        ({"packages": {"curl": "8.0"}}, "its pinned source"),
    ],
)
def test_a_system_package_table_in_another_shape_is_refused(raw, message) -> None:
    with pytest.raises(TableError, match=message):
        read_system_packages(raw)


def test_a_system_package_table_lists_its_names() -> None:
    table = read_system_packages({"packages": {"zlib1g": {}, "curl": {}}})
    assert table.packages == ("curl", "zlib1g")
    declaration = dataclasses.replace(_seed(), system_packages=("curl", "jq"))
    tables = Tables(published_tables().datastores, published_tables().base_images, table,
                    published_tables().recipes)
    _files, found = generate(declaration, "demo", tables=tables, frontend_lock=True)
    assert [finding.message for finding in found] == [
        'generator.systemPackages[1] "jq" is not in the system-package table (allowed: a '
        "package of the table: curl, zlib1g)"
    ]


# --------------------------------------------------------------------------- #
# the Docker lane                                                               #
# --------------------------------------------------------------------------- #
def _docker_compose() -> list[str] | None:
    docker = shutil.which("docker")
    if docker is None:
        return None
    probe = subprocess.run([docker, "compose", "version"], capture_output=True, check=False)
    return [docker, "compose"] if probe.returncode == 0 else None


def test_docker_compose_reads_every_hostile_value_back_literally(tmp_path: pathlib.Path) -> None:
    """Decision 8's Docker lane: compose itself, not a reading of it, gets every declared
    value back as written - no interpolation, no YAML retyping, no lost character.

    ``config`` prints the resolved model in compose's own syntax, so a literal ``$`` comes
    back doubled again; it is read the way compose reads a file. A ``$HOME`` compose had
    interpolated would come back as the HOME this run sets instead."""
    compose = _docker_compose()
    if compose is None:
        pytest.skip("no docker compose here; CI's runners carry it")
    _meta, declaration, _tables_ = _sample("hostile-values")
    files = _render("hostile-values")
    (tmp_path / PROFILE).write_bytes(files[PROFILE])
    # The CLI's own environment (it finds its plugins through it), with the profile's own
    # variables unset but the two it requires. HOME stays set: a `$HOME` compose
    # interpolated would come back as that path rather than as written.
    environment = {
        key: value for key, value in os.environ.items()
        if key.upper() not in ("DATABASE_URL", "WEB_PORT", "BACKEND_CORS_ORIGINS",
                               "COMPOSE_FILE", "COMPOSE_PROJECT_NAME", "COMPOSE_PROFILES")
    }
    environment |= {"SECRET_KEY": "s" * 40, "POSTGRES_PASSWORD": "p", "HOME": "/home/someone"}
    run = subprocess.run(
        [*compose, "-p", "gen-hostile", "-f", str(tmp_path / PROFILE), "config", "--format",
         "json"],
        capture_output=True, text=True, encoding="utf-8", env=environment, cwd=tmp_path,
        check=False,
    )
    assert run.returncode == 0, run.stderr
    resolved = json.loads(run.stdout)
    services = resolved["services"]
    assert set(services) == {unit.id for unit in declaration.units}
    for ident, command in _commands(declaration).items():
        assert tuple(compose_literal(part) for part in services[ident]["command"]) == command, ident
    assert "/home/someone" not in run.stdout, "nothing was interpolated from the environment"
    api = next(unit for unit in declaration.units if unit.role == "api")
    assert compose_literal(services[api.id]["healthcheck"]["test"][-1]) == api.liveness_path
    assert services["web"]["environment"]["API_UPSTREAM"] == "1e3:8000"
    assert {v["source"] for v in services["0o17"]["volumes"]} == {"files"}
