"""``terp env`` — the inner loop's own command over ``.app.env``.

Both halves of the platform had a values story for a *deployed* environment and
neither had one for the machine the code is written on: the documented route was
``cp .app.env.example .app.env`` plus a text editor, and the only seam was a
hand-maintained file. These assertions hold the two rules that make the command a
seam rather than a shortcut — the manifest is the allow-list, and a secret's value
is never printed — plus the parity with ``env-seams`` that makes the example file
generated rather than maintained.
"""

from __future__ import annotations

import json
import pathlib
import sys

import pytest

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "packages" / "backend" / "cli" / "src"))

from terp.cli import main  # noqa: E402
from terp.cli.envfile import MASKED, run_env_command  # noqa: E402
from terp.cli.envseams import run_env_seams_check  # noqa: E402

_MANIFEST = {
    "type": "object",
    "properties": {
        "VENDOR_API_URL": {
            "type": "string",
            "title": "Where the vendor API lives",
            "default": "http://api:8000",
            "resolvedBy": "container",
        },
        "VENDOR_TOKEN": {"type": "string", "format": "secret"},
    },
    "required": [],
}


def _project(tmp_path: pathlib.Path, manifest: dict | str | None = None) -> pathlib.Path:
    if manifest is not None:
        body = manifest if isinstance(manifest, str) else json.dumps(manifest)
        (tmp_path / "environment.schema.json").write_text(body, encoding="utf-8")
    return tmp_path


def _env(root: pathlib.Path) -> str:
    return (root / ".app.env").read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# the manifest is the allow-list
# --------------------------------------------------------------------------- #
def test_an_undeclared_name_is_refused(tmp_path: pathlib.Path) -> None:
    """A value under a name the manifest does not declare reaches no deployed
    environment: a deploy tool renders declarations and nothing else. Writing it
    silently would be the local file quietly disagreeing with every other one."""
    root = _project(tmp_path, _MANIFEST)
    with pytest.raises(SystemExit, match="not declared"):
        run_env_command(action="set", root=str(root), names=["SNEAKY=1"])
    assert not (root / ".app.env").exists(), "a refusal writes nothing at all"


def test_declare_makes_the_name_real_in_the_same_breath(
    tmp_path: pathlib.Path,
) -> None:
    """The difference between a guard and an obstacle: the one flag that turns a
    refusal into a declaration, so the manifest and the file stay in step."""
    root = _project(tmp_path, _MANIFEST)
    run_env_command(action="set", root=str(root), names=["SNEAKY=1"], declare=True)

    manifest = json.loads((root / "environment.schema.json").read_text(encoding="utf-8"))
    assert manifest["properties"]["SNEAKY"] == {"type": "string"}
    assert "SNEAKY=1" in _env(root)
    # ...and it leaves the declarations that were already there alone.
    assert "VENDOR_API_URL" in manifest["properties"]


def test_a_manifest_the_reader_refuses_stops_everything(
    tmp_path: pathlib.Path,
) -> None:
    """A deploy tool's reader fails closed on the WHOLE file, so a manifest with
    one defect declares nothing at all. Editing values against it would be
    arranging furniture in a house with no walls."""
    root = _project(tmp_path, '{"properties": {"lower_case": {"type": "string"}}}')
    with pytest.raises(SystemExit, match="not usable as written"):
        run_env_command(action="list", root=str(root))


# --------------------------------------------------------------------------- #
# a secret's value is never printed
# --------------------------------------------------------------------------- #
def test_a_secret_is_masked_on_the_way_in_and_on_the_way_out(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`"format": "secret"` means the value belongs in a sealed store or the
    developer's own file — not in terminal scrollback, a screen share or a CI log.
    It still has to REACH the file, which is the distinction being tested."""
    root = _project(tmp_path, _MANIFEST)
    run_env_command(action="set", root=str(root), names=["VENDOR_TOKEN=sk-live-abc"])
    written = capsys.readouterr().out
    assert MASKED in written and "sk-live-abc" not in written

    run_env_command(action="list", root=str(root))
    listed = capsys.readouterr().out
    assert MASKED in listed and "sk-live-abc" not in listed

    assert "sk-live-abc" in _env(root), (
        "the value must still be delivered — .app.env is gitignored, the terminal is not"
    )


def test_a_plain_value_is_shown(tmp_path: pathlib.Path, capsys) -> None:
    root = _project(tmp_path, _MANIFEST)
    run_env_command(action="set", root=str(root), names=["VENDOR_API_URL=http://api:9000"])
    run_env_command(action="list", root=str(root))
    assert "http://api:9000" in capsys.readouterr().out


# --------------------------------------------------------------------------- #
# init / unset / check
# --------------------------------------------------------------------------- #
def test_init_writes_the_declarations_with_their_defaults(
    tmp_path: pathlib.Path, capsys
) -> None:
    root = _project(tmp_path, _MANIFEST)
    run_env_command(action="init", root=str(root))
    body = _env(root)
    assert "VENDOR_API_URL=http://api:8000" in body
    assert "VENDOR_TOKEN=" in body, "a secret gets its name, never a default"
    assert "VENDOR_TOKEN" in capsys.readouterr().out, "and is named as still to fill in"


def test_init_refuses_to_clobber_an_existing_file(tmp_path: pathlib.Path) -> None:
    root = _project(tmp_path, _MANIFEST)
    (root / ".app.env").write_text("VENDOR_API_URL=mine\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="already exists"):
        run_env_command(action="init", root=str(root))
    assert _env(root) == "VENDOR_API_URL=mine\n"


def test_unset_reports_what_was_not_there(tmp_path: pathlib.Path, capsys) -> None:
    root = _project(tmp_path, _MANIFEST)
    run_env_command(action="set", root=str(root), names=["VENDOR_API_URL=x"])
    capsys.readouterr()
    run_env_command(action="unset", root=str(root), names=["VENDOR_API_URL", "ABSENT"])
    assert "not set anyway: ABSENT" in capsys.readouterr().out
    assert "VENDOR_API_URL" not in _env(root)


def test_check_names_both_directions_of_disagreement(
    tmp_path: pathlib.Path, capsys
) -> None:
    root = _project(tmp_path, _MANIFEST)
    (root / ".app.env").write_text("VENDOR_API_URL=x\nSTRAY=1\n", encoding="utf-8")
    assert run_env_command(action="check", root=str(root)) == 1
    out = capsys.readouterr().out
    assert "VENDOR_TOKEN: declared but not set" in out
    assert "STRAY" in out and "reaches no deployed environment" in out


def test_a_file_the_parser_cannot_read_is_never_rewritten(
    tmp_path: pathlib.Path,
) -> None:
    """Rewriting from a partial parse would silently drop whatever failed, which
    is the class of bug this whole seam exists to remove."""
    root = _project(tmp_path, _MANIFEST)
    broken = 'VENDOR_API_URL="unterminated\n'
    (root / ".app.env").write_text(broken, encoding="utf-8")
    with pytest.raises(SystemExit, match="cannot be read"):
        run_env_command(action="set", root=str(root), names=["VENDOR_API_URL=x"])
    assert _env(root) == broken


# --------------------------------------------------------------------------- #
# the generator half of the env-seams parity check
# --------------------------------------------------------------------------- #
def test_example_satisfies_the_check_that_demands_it(tmp_path: pathlib.Path) -> None:
    """The point of `example`: an app satisfies the parity check by running a
    command instead of hand-maintaining a third file."""
    root = _project(tmp_path, _MANIFEST)
    assert run_env_seams_check(root)[0] == 1, "no example file yet, so env-seams is red"

    run_env_command(action="example", root=str(root))

    exit_code, output = run_env_seams_check(root)
    assert exit_code == 0, output


def test_a_generated_example_never_carries_a_secret_value(
    tmp_path: pathlib.Path,
) -> None:
    """This file is committed. The name tells a reader what to supply; supplying
    it here would put the credential in git."""
    root = _project(tmp_path, _MANIFEST)
    run_env_command(action="set", root=str(root), names=["VENDOR_TOKEN=sk-live-abc"])
    run_env_command(action="example", root=str(root))

    example = (root / ".app.env.example").read_text(encoding="utf-8")
    assert "sk-live-abc" not in example
    assert "VENDOR_TOKEN=" in example
    assert "VENDOR_API_URL=http://api:8000" in example, "a default is a helpful example"


def test_env_is_not_in_any_verify_profile() -> None:
    """`env-seams` already gates the seam; this is a developer's command, and a
    gate that edits your files is not a gate."""
    from terp.cli.verify import PROFILES

    for profile, checks in PROFILES.items():
        for check in checks:
            assert not check.command.startswith("terp env "), f"{profile}/{check.id}"


def test_the_cli_exposes_every_subcommand(tmp_path: pathlib.Path) -> None:
    root = _project(tmp_path, _MANIFEST)
    with pytest.raises(SystemExit) as excinfo:
        main(["env", "init", "--root", str(root)])
    assert excinfo.value.code == 0
    assert (root / ".app.env").is_file()


# --------------------------------------------------------------------------- #
# what the first review of this command found
# --------------------------------------------------------------------------- #
def test_required_is_read_from_the_document_not_the_property(
    tmp_path: pathlib.Path, capsys
) -> None:
    """The dialect puts required names in a DOCUMENT-level array. Reading them off
    each property meant `check` never reported a required-and-empty variable and
    exited 0 — a green for the one thing it exists to catch."""
    root = _project(
        tmp_path,
        {
            "type": "object",
            "properties": {"VENDOR_API_URL": {"type": "string"}},
            "required": ["VENDOR_API_URL"],
        },
    )
    (root / ".app.env").write_text("VENDOR_API_URL=\n", encoding="utf-8")

    assert run_env_command(action="check", root=str(root)) == 1
    assert "required by the manifest and empty" in capsys.readouterr().out


def test_example_refuses_an_unusable_manifest(tmp_path: pathlib.Path) -> None:
    """An unusable manifest declares NOTHING, so rendering from it would replace
    the committed example with a header and report success — the loudest possible
    way to lose a file."""
    root = _project(tmp_path, '{"properties": {"lower_case": {"type": "string"}}}')
    (root / ".app.env.example").write_text("KEEP=me\n", encoding="utf-8")

    with pytest.raises(SystemExit, match="not usable as written"):
        run_env_command(action="example", root=str(root))

    assert (root / ".app.env.example").read_text(encoding="utf-8") == "KEEP=me\n"


@pytest.mark.parametrize(
    ("name", "reason"),
    [
        ("SECRET_KEY", "platform-owned"),
        ("lower_case", "UPPER_SNAKE"),
        ("VITE_THING", "build-time"),
    ],
)
def test_declare_will_not_brick_the_manifest(
    tmp_path: pathlib.Path, name: str, reason: str
) -> None:
    """`--declare` writes to the file whose reader fails closed on the WHOLE file.
    One name it refuses and every declaration is dropped, the app's secrets
    included. A convenience flag that can do that is not a convenience."""
    root = _project(tmp_path, _MANIFEST)
    before = (root / "environment.schema.json").read_text(encoding="utf-8")

    with pytest.raises(SystemExit, match=reason):
        run_env_command(
            action="set", root=str(root), names=[f"{name}=x"], declare=True
        )

    assert (root / "environment.schema.json").read_text(encoding="utf-8") == before


def test_a_generated_example_quotes_the_way_the_live_file_does(
    tmp_path: pathlib.Path,
) -> None:
    """A default containing ` #` would otherwise be truncated the moment the
    example is copied to .app.env, and a non-string default would render as
    Python's `True`."""
    root = _project(
        tmp_path,
        {
            "type": "object",
            "properties": {
                "TRICKY": {"type": "string", "default": "keep # this"},
                "FLAGGED": {"type": "boolean", "default": True},
            },
            "required": [],
        },
    )
    run_env_command(action="example", root=str(root))

    example = (root / ".app.env.example").read_text(encoding="utf-8")
    assert 'TRICKY="keep # this"' in example
    assert "FLAGGED=True" in example

    # ...and copying it through is lossless.
    from terp.cli.envseams import parse_dotenv

    values, problems = parse_dotenv(example)
    assert problems == []
    assert values["TRICKY"] == "keep # this"


def test_a_multi_line_value_round_trips_instead_of_blocking(
    tmp_path: pathlib.Path,
) -> None:
    """A certificate or a private key is the ordinary case here, and `parse_dotenv`
    legitimately produces such a value from a quoted escape. Refusing it on write
    would make a file this tool can READ one it will not touch, permanently."""
    from terp.cli.envseams import parse_dotenv

    root = _project(
        tmp_path,
        {"type": "object", "properties": {"PEM_KEY": {"type": "string"}}, "required": []},
    )
    secret_key = "-----BEGIN\nMIIB-----"
    run_env_command(action="set", root=str(root), names=[f"PEM_KEY={secret_key}"])

    values, problems = parse_dotenv(_env(root))
    assert problems == [] and values["PEM_KEY"] == secret_key

    # ...and the file stays workable afterwards, which is the half that bit.
    run_env_command(action="set", root=str(root), names=["PEM_KEY=plain"])
    assert parse_dotenv(_env(root))[0]["PEM_KEY"] == "plain"


def test_a_null_default_is_empty_not_the_string_none(
    tmp_path: pathlib.Path, capsys
) -> None:
    """`str(None)` is "None", which is truthy — so it would read as "already filled
    in" in the still-to-fill list and keep `check` green on a variable nobody set."""
    root = _project(
        tmp_path,
        {
            "type": "object",
            "properties": {"OPT": {"type": "string", "default": None}},
            "required": [],
        },
    )
    run_env_command(action="init", root=str(root))
    assert "OPT=None" not in _env(root)
    assert "OPT" in capsys.readouterr().out, "and it is named as still to fill in"

    run_env_command(action="example", root=str(root))
    assert "OPT=None" not in (root / ".app.env.example").read_text(encoding="utf-8")


def test_example_refuses_to_wipe_a_committed_file_with_nothing(
    tmp_path: pathlib.Path,
) -> None:
    """`manifest_findings` is empty for a manifest that is merely ABSENT, so the
    usability guard does not cover this — and this command overwrites a COMMITTED
    file. Replacing it with a header and reporting success is the loudest possible
    way to lose it."""
    root = _project(tmp_path, {"type": "object", "properties": {}, "required": []})
    (root / ".app.env.example").write_text("KEEP=me\n", encoding="utf-8")

    with pytest.raises(SystemExit, match="declares no variables"):
        run_env_command(action="example", root=str(root))
    assert (root / ".app.env.example").read_text(encoding="utf-8") == "KEEP=me\n"

    # ...and the same when there is no manifest at all.
    (root / "environment.schema.json").unlink()
    with pytest.raises(SystemExit, match="declares no variables"):
        run_env_command(action="example", root=str(root))
    assert (root / ".app.env.example").read_text(encoding="utf-8") == "KEEP=me\n"


# --------------------------------------------------------------------------- #
# the paths a person actually hits by mistake
# --------------------------------------------------------------------------- #
def test_a_manifest_with_no_required_array_asks_for_nothing(
    tmp_path: pathlib.Path,
) -> None:
    """`required` is optional, and an unreadable or absent manifest asks for
    nothing rather than raising — `check` still has the file to report on."""
    from terp.cli.envfile import _required_names

    assert _required_names(tmp_path) == set(), "no manifest at all"
    (tmp_path / "environment.schema.json").write_text("{ not json", encoding="utf-8")
    assert _required_names(tmp_path) == set(), "unreadable"
    (tmp_path / "environment.schema.json").write_text(
        '{"properties": {}, "required": "NOPE"}', encoding="utf-8"
    )
    assert _required_names(tmp_path) == set(), "not a list"


def test_declare_creates_the_manifest_when_there_is_none(
    tmp_path: pathlib.Path,
) -> None:
    """An app that has not declared anything yet still gets a first variable."""
    run_env_command(
        action="set", root=str(tmp_path), names=["FIRST=1"], declare=True
    )
    manifest = json.loads(
        (tmp_path / "environment.schema.json").read_text(encoding="utf-8")
    )
    assert manifest["properties"]["FIRST"] == {"type": "string"}
    assert "FIRST=1" in _env(tmp_path)


def test_declare_refuses_to_exceed_the_dialect_limit(tmp_path: pathlib.Path) -> None:
    """The reader drops the WHOLE file past the property cap, so adding the one
    that crosses it would cost every declaration already there."""
    from terp.cli.envschema import MAX_PROPERTIES

    properties = {f"VAR_{index}": {"type": "string"} for index in range(MAX_PROPERTIES)}
    root = _project(
        tmp_path, {"type": "object", "properties": properties, "required": []}
    )
    with pytest.raises(SystemExit, match="over the dialect's limit"):
        run_env_command(
            action="set", root=str(root), names=["ONE_TOO_MANY=1"], declare=True
        )


def test_an_unknown_action_is_refused(tmp_path: pathlib.Path) -> None:
    root = _project(tmp_path, _MANIFEST)
    with pytest.raises(SystemExit, match="unknown action"):
        run_env_command(action="frobnicate", root=str(root))


def test_set_and_unset_need_something_to_do(tmp_path: pathlib.Path) -> None:
    root = _project(tmp_path, _MANIFEST)
    with pytest.raises(SystemExit, match="expected NAME=value"):
        run_env_command(action="set", root=str(root), names=["JUST_A_NAME"])
    with pytest.raises(SystemExit, match="nothing to set"):
        run_env_command(action="set", root=str(root), names=[])
    with pytest.raises(SystemExit, match="nothing to unset"):
        run_env_command(action="unset", root=str(root), names=[])


def test_init_needs_something_to_write(tmp_path: pathlib.Path) -> None:
    root = _project(tmp_path, {"type": "object", "properties": {}, "required": []})
    with pytest.raises(SystemExit, match="nothing to"):
        run_env_command(action="init", root=str(root))


def test_list_says_so_when_there_is_nothing_at_all(
    tmp_path: pathlib.Path, capsys
) -> None:
    root = _project(tmp_path, {"type": "object", "properties": {}, "required": []})
    assert run_env_command(action="list", root=str(root)) == 0
    assert "declares nothing" in capsys.readouterr().out


def test_list_names_a_value_that_reaches_no_environment(
    tmp_path: pathlib.Path, capsys
) -> None:
    root = _project(tmp_path, _MANIFEST)
    (root / ".app.env").write_text("STRAY=1\n", encoding="utf-8")
    run_env_command(action="list", root=str(root))
    assert "not declared" in capsys.readouterr().out


def test_check_is_green_on_an_app_that_agrees_with_its_manifest(
    tmp_path: pathlib.Path, capsys
) -> None:
    root = _project(tmp_path, _MANIFEST)
    run_env_command(
        action="set",
        root=str(root),
        names=["VENDOR_API_URL=http://api:8000", "VENDOR_TOKEN=x"],
    )
    capsys.readouterr()
    assert run_env_command(action="check", root=str(root)) == 0
    assert "supplies every declared variable" in capsys.readouterr().out
