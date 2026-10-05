"""``terp docker dev`` undoes a pre-0.30.0 ``node_modules`` volume before ``watch`` (issue #136).

0.30.0 made the frontend's mask a ``tmpfs``. A workbench that was up before the upgrade
kept the old anonymous volume, because Compose reattaches it on a recreate, and the dev
server served the first boot's packages with every container healthy. Docker is never
started here: every call is answered by an injected capture, as in ``test_cli_docker``.
"""

from __future__ import annotations

import json
import pathlib
import sys

import pytest

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "packages" / "backend" / "cli" / "src"))

from terp.cli import run_docker_dev_command  # noqa: E402
from terp.cli.docker_masks import (  # noqa: E402
    clear_stale_masks,
    containers,
    stale_volumes,
    tmpfs_targets,
)

MASK = "/app/frontend/node_modules"

CONFIG = json.dumps(
    {
        "services": {
            "web": {
                "volumes": [
                    {"type": "bind", "source": "/src/frontend", "target": "/app/frontend"},
                    {"type": "tmpfs", "target": MASK},
                ]
            },
            "api": {"volumes": [{"type": "volume", "source": "data", "target": "/data"}]},
        }
    }
)
PS = '[{"Service": "web", "ID": "c-web"}, {"Service": "api", "ID": "c-api"}]'


def _inspect(*mounts: dict) -> str:
    return json.dumps([{"Mounts": list(mounts)}])


STALE = _inspect(
    {"Type": "bind", "Source": "/src/frontend", "Destination": "/app/frontend"},
    {"Type": "volume", "Name": "0f3a9c", "Destination": MASK},
)
FRESH = _inspect({"Type": "tmpfs", "Destination": MASK})


class _Docker:
    """Answers each docker call by its verb; records every call in order."""

    def __init__(
        self,
        *,
        config: tuple[int, str] = (0, CONFIG),
        ps: tuple[int, str] = (0, PS),
        inspect: tuple[int, str] = (0, STALE),
        rm: int = 0,
        volume_rm: int = 0,
    ) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.answers = {"config": config, "ps": ps, "inspect": inspect}
        self.rm, self.volume_rm = rm, volume_rm

    def __call__(self, argv) -> tuple[int, str]:
        argv = tuple(argv)
        self.calls.append(argv)
        if argv[:2] == ("docker", "volume"):
            return self.volume_rm, ""
        if argv[:2] == ("docker", "inspect"):
            return self.answers["inspect"]
        verb = next(word for word in ("config", "ps", "rm") if word in argv)
        return (self.rm, "") if verb == "rm" else self.answers[verb]


def _compose(tmp_path: pathlib.Path) -> pathlib.Path:
    path = tmp_path / "docker-compose.yml"
    path.write_text("services: {}\n", encoding="utf-8")
    return path


def test_a_stale_mask_is_removed_with_its_container_and_nothing_else(tmp_path) -> None:
    docker = _Docker()
    note = clear_stale_masks(_compose(tmp_path), project_name="app", capture=docker)

    compose = ("docker", "compose", "-f", str(tmp_path / "docker-compose.yml"), "-p", "app")
    assert docker.calls == [
        (*compose, "config", "--format", "json"),
        (*compose, "ps", "--all", "--format", "json"),
        ("docker", "inspect", "c-web"),
        (*compose, "rm", "--stop", "--force", "web"),
        ("docker", "volume", "rm", "0f3a9c"),
    ]
    assert "'web' still mounted a volume where the compose file declares a tmpfs" in note
    assert "this start creates both fresh" in note


def test_a_workbench_already_on_the_tmpfs_is_left_alone(tmp_path) -> None:
    docker = _Docker(inspect=(0, FRESH))
    assert clear_stale_masks(_compose(tmp_path), capture=docker) == ""
    assert not [call for call in docker.calls if "rm" in call]


def test_a_failed_removal_says_what_to_run_by_hand(tmp_path) -> None:
    container_kept = _Docker(rm=1)
    for docker in (container_kept, _Docker(volume_rm=1)):
        note = clear_stale_masks(_compose(tmp_path), capture=docker)
        assert "Removing it failed; once, by hand:" in note
        assert "up -d --no-deps --force-recreate --renew-anon-volumes web" in note
        assert "docker volume rm 0f3a9c" in note
    # A volume is never removed from under a container that is still there.
    assert ("docker", "volume", "rm", "0f3a9c") not in container_kept.calls


def test_nothing_is_asked_past_what_is_there(tmp_path) -> None:
    """No tmpfs declared, or no container yet: nothing is removed. And a docker call
    that failed is never acted on, whatever it printed: each failing case below answers
    with exactly the output that would otherwise lead to a removal."""
    cases = (
        _Docker(config=(0, json.dumps({"services": {"api": {}}}))),
        _Docker(config=(1, CONFIG)),
        _Docker(ps=(0, '[{"Service": "api", "ID": "c-api"}]')),
        _Docker(ps=(1, PS)),
        _Docker(inspect=(1, STALE)),
    )
    for docker in cases:
        assert clear_stale_masks(_compose(tmp_path), capture=docker) == ""
        assert not [call for call in docker.calls if "rm" in call]


def test_no_docker_on_path_leaves_the_start_to_watch(tmp_path) -> None:
    """The check runs before `watch`; a missing docker is `watch`'s error to report."""

    def missing(argv):
        raise FileNotFoundError("docker")

    _compose(tmp_path)
    runs: list = []
    message = run_docker_dev_command(
        root=tmp_path, runner=lambda argv: runs.append(argv) or 0, capture=missing
    )
    assert runs and message == "docker compose watch exited with status 0"


def test_the_start_prints_what_it_undid_before_watch(tmp_path, capsys) -> None:
    _compose(tmp_path)
    order: list[str] = []
    docker = _Docker()

    def capture(argv):
        order.append("rm" if "rm" in argv else "ask")
        return docker(argv)

    run_docker_dev_command(root=tmp_path, runner=lambda argv: order.append("watch") or 0, capture=capture)
    assert order.index("watch") > max(i for i, step in enumerate(order) if step == "rm")
    assert "still mounted a volume" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("config", "expected"),
    [
        ("not json", {}),
        ("[]", {}),
        ('{"services": []}', {}),
        ('{"services": {"web": "nope"}}', {}),
        (
            json.dumps({"services": {"web": {"tmpfs": "/run:size=1m"}}}),
            {"web": frozenset({"/run"})},
        ),
        (
            json.dumps({"services": {"web": {"tmpfs": ["/scratch", "", 3], "volumes": ["x", {"type": "tmpfs"}]}}}),
            {"web": frozenset({"/scratch"})},
        ),
    ],
)
def test_tmpfs_targets_reads_both_spellings_and_nothing_else(config, expected) -> None:
    assert tmpfs_targets(config) == expected


def test_containers_reads_an_array_one_object_or_lines() -> None:
    assert containers("") == {}
    assert containers('{"Service": "web", "ID": "a"}') == {"web": "a"}
    lines = '{"Service": "web", "ID": "a"}\n\nnot json\n{"Service": "web", "ID": "b"}\n{"ID": "c"}'
    assert containers(lines) == {"web": "a"}
    assert containers('[1, {"Service": "api", "ID": ""}, {"Service": "api", "ID": "d"}]') == {"api": "d"}


def test_only_a_volume_at_a_tmpfs_path_is_stale() -> None:
    inspected = _inspect(
        # Named, so it is the type alone that keeps a bind out.
        {"Type": "bind", "Name": "a-bind", "Source": "/x", "Destination": MASK},
        {"Type": "volume", "Name": "named-data", "Destination": "/data"},
        {"Type": "volume", "Destination": MASK},
        "not a mount",
        {"Type": "volume", "Name": "0f3a9c", "Destination": MASK},
        {"Type": "volume", "Name": "0f3a9c", "Destination": MASK},
    )
    assert stale_volumes(inspected, frozenset({MASK})) == ("0f3a9c",)
    assert stale_volumes("", frozenset({MASK})) == ()
