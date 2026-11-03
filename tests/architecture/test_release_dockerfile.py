"""The configuration a Dockerfile gives its image, as ``sign`` replays it (ADR 0187 decision 6).

``sign`` holds the backend image's entrypoint, command, environment, user, working directory,
healthcheck, volumes, stop signal and shell to what the commit's Dockerfile makes of its base's
configuration. Each case is a Dockerfile and the configuration BuildKit gives its last stage,
written out by hand; a shape the replay does not follow is refused as one ``sign`` cannot
compare, never guessed at.
"""

from __future__ import annotations

import pytest

from terp.cli.release import _dockerfile
from terp.cli.release._common import ReleaseError

BASE = {"Env": ["PATH=/usr/local/bin:/usr/bin", "LANG=C.UTF-8"], "Cmd": ["python3"], "OnBuild": None}
PLATFORM = "linux/arm64/v8"


def _replay(text: str, base: dict | None = None, **build_args: str) -> dict:
    return _dockerfile.runtime_config(text, "Dockerfile", base or BASE, build_args or {"SOURCE_DATE_EPOCH": "7"}, PLATFORM)


def _env(text: str, base: dict | None = None) -> dict[str, str]:
    return dict(item.partition("=")[::2] for item in _replay(text, base)["Env"])


def test_env_replaces_a_base_variable_in_place_and_appends_a_new_one() -> None:
    config = _replay('FROM b\nENV A=1 \\\n    PATH="/srv/bin:$PATH"\n')
    assert config["Env"] == ["PATH=/srv/bin:/usr/local/bin:/usr/bin", "LANG=C.UTF-8", "A=1"]
    assert config["Cmd"] == ["python3"] and config["Entrypoint"] is None


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("ENV A=1 B=$A", {"A": "1", "B": ""}),  # one instruction expands against the env before it
        ("ENV A old form value", {"A": "old form value"}),
        ("ENV A", {"A": ""}),
        ("ENV A='$LANG x' B=\"$LANG \\\"q\\\" \\$x \\y\"", {"A": "$LANG x", "B": 'C.UTF-8 "q" $x \\y'}),
        ("ENV A=a\\ b C=\"\"", {"A": "a b", "C": ""}),
        ("ENV A=${LANG} B=${NOPE:-d} C=${LANG:-d} D=${NOPE-d} E=${EMPTY-d} F=${EMPTY:-d}", {
            "A": "C.UTF-8", "B": "d", "C": "C.UTF-8", "D": "d", "E": "", "F": "d"}),
        ("ENV A=${LANG:+set} B=${NOPE:+set} C=${EMPTY+set} D=${NOPE+set} E=${EMPTY:+set}", {
            "A": "set", "B": "", "C": "set", "D": "", "E": ""}),
        ("ENV A=${NOPE:-${LANG}} B=${NOPE:-\"a}b\"}", {"A": "C.UTF-8", "B": "a}b"}),
        ("ENV A=$1 B=$$ C=$ D=x$", {"A": "", "B": "", "C": "$", "D": "x$"}),
        ("ENV A=x\\", {"A": "x"}),
    ],
)
def test_env_words_are_read_as_buildkit_s_lexer_reads_them(line: str, expected: dict[str, str]) -> None:
    base = {**BASE, "Env": [*BASE["Env"], "EMPTY="]}
    found = _env(f"FROM b\n{line}\n", base)
    assert {key: found[key] for key in expected} == expected


def test_args_take_the_build_s_value_a_default_a_global_or_the_target_platform() -> None:
    text = (
        "ARG GLOBAL=g OTHER\nARG SOURCE_DATE_EPOCH\nFROM b\n"
        "ARG SOURCE_DATE_EPOCH GLOBAL OTHER LOCAL=l TARGETARCH TARGETVARIANT NONE\n"
        "ENV E=$SOURCE_DATE_EPOCH G=$GLOBAL O=${OTHER-unset} L=$LOCAL T=$TARGETARCH/$TARGETVARIANT N=${NONE-unset}\n"
        "ENV LANG=env\nARG LANG=arg\nENV FROM_ENV=$LANG\n"
    )
    found = _env(text)
    assert found["E"] == "7" and found["G"] == "g" and found["O"] == "unset" and found["L"] == "l"
    assert found["T"] == "arm64/v8" and found["N"] == "unset"
    assert found["FROM_ENV"] == "env", "ENV wins over an ARG of the same name"
    assert "SOURCE_DATE_EPOCH" not in found and "LOCAL" not in found, "an ARG never reaches the image"


def test_workdir_user_stopsignal_and_volumes_are_expanded() -> None:
    config = _replay(
        "FROM b\nARG HOME=/srv\nWORKDIR $HOME\nWORKDIR sub/../app\nUSER ${NOPE:-appuser}\nSTOPSIGNAL SIGTERM\n"
        'VOLUME ["/data"]\nVOLUME $HOME/a /b\n'
    )
    assert config["WorkingDir"] == "/srv/app" and config["User"] == "appuser" and config["StopSignal"] == "SIGTERM"
    assert config["Volumes"] == {"/data": {}, "/srv/a": {}, "/b": {}}
    assert _replay("FROM b\nWORKDIR app\n")["WorkingDir"] == "/app"


def test_cmd_and_entrypoint_take_the_exec_form_or_the_shell_s() -> None:
    assert _replay('FROM b\nCMD ["a", "b"]\n')["Cmd"] == ["a", "b"]
    assert _replay("FROM b\nCMD run $X   now\n")["Cmd"] == ["/bin/sh", "-c", "run $X   now"]
    assert _replay("FROM b\nCMD [not json\n")["Cmd"] == ["/bin/sh", "-c", "[not json"]
    assert _replay('FROM b\nCMD [1, 2]\n')["Cmd"] == ["/bin/sh", "-c", "[1, 2]"]
    shell = _replay('FROM b\nSHELL ["/bin/bash", "-eu", "-c"]\nENTRYPOINT exec app\n')
    assert shell["Entrypoint"] == ["/bin/bash", "-eu", "-c", "exec app"] and shell["Shell"] == ["/bin/bash", "-eu", "-c"]
    assert shell["Cmd"] is None, "a new ENTRYPOINT drops the CMD the base gave"
    kept = _replay('FROM b\nCMD ["x"]\nENTRYPOINT ["e"]\n')
    assert kept["Cmd"] == ["x"] and kept["Entrypoint"] == ["e"], "a CMD the stage set itself stays"


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("HEALTHCHECK NONE", {"Test": ["NONE"]}),
        ('HEALTHCHECK CMD ["probe", "-q"]', {"Test": ["CMD", "probe", "-q"]}),
        ("HEALTHCHECK --interval=1m30s --timeout=500ms --start-period=0 --start-interval=1.5s --retries=3 CMD probe -q",
         {"Test": ["CMD-SHELL", "probe -q"], "Interval": 90 * 10**9, "Timeout": 500 * 10**6, "StartPeriod": 0,
          "StartInterval": 1500 * 10**6, "Retries": 3}),
    ],
)
def test_a_healthcheck_is_read_with_its_flags(line: str, expected: dict) -> None:
    assert _replay(f"FROM b\n{line}\n")["Healthcheck"] == expected


def test_the_last_stage_inherits_the_stages_it_is_built_from() -> None:
    text = (
        "# syntax=docker/dockerfile:1\n# a comment, not a directive\n\n"
        "FROM --platform=$TARGETPLATFORM b AS Deps\nARG A=from-deps\nENV DEPS=1\nCMD [\"deps\"]\n"
        "FROM other AS unrelated\nENV NOT=1\n"
        "FROM deps\nENV FROM_ARG=$A\nENTRYPOINT [\"e\"]\n"
    )
    config = _replay(text)
    env = dict(item.partition("=")[::2] for item in config["Env"])
    assert env["DEPS"] == "1" and env["FROM_ARG"] == "from-deps" and "NOT" not in env
    assert config["Cmd"] is None, "a CMD another stage set is the base's, as far as this stage goes"
    assert _dockerfile.chain(_dockerfile._stages(text, "Dockerfile")[1])[0].name == "deps"


def test_continuations_skip_comments_and_blank_lines_and_heredoc_bodies_are_no_instructions() -> None:
    text = (
        "FROM b\nENV A=1 \\\n# inside\n\n    B=2\n"
        "RUN <<EOF\nENV PLANTED=1\nEOF\n"
        "COPY <<-'END' /x\n\tENV PLANTED=2\n\tEND\n"
        'RUN ["sh", "-c", "a <<EOF"]\nENV C=3\n'
        "run\techo tabbed\n"
    )
    assert _env(text) == {"PATH": "/usr/local/bin:/usr/bin", "LANG": "C.UTF-8", "A": "1", "B": "2", "C": "3"}


def test_an_onbuild_trigger_of_the_last_stage_runs_nothing_here() -> None:
    assert _replay("FROM b\nONBUILD ENV X=1\nLABEL a=b\nEXPOSE 80\nMAINTAINER x\n")["Env"] == BASE["Env"]


@pytest.mark.parametrize(
    ("text", "base", "expected"),
    [
        ("# escape=`\nFROM b\n", None, "sets the escape character to '`'"),
        ("ENV A=1\n", None, "has no FROM"),
        ("FROM b\n", {**BASE, "OnBuild": ["RUN x"]}, "is built on a base with ONBUILD triggers"),
        ("FROM b AS s\nONBUILD RUN x\nFROM s\n", None, "has an ONBUILD trigger in a stage another is built from"),
        ("FROM b\nFROBNICATE x\n", None, "has an instruction FROBNICATE this reader does not know"),
        ("FROM b\nENV A=1 B\n", None, "that is no list of name=value"),
        ("FROM b\nENV A='open\n", None, "leaves a quote open"),
        ('FROM b\nENV A="open\n', None, "leaves a quote open"),
        ("FROM b\nENV A=${\n", None, "uses a ${...} form without a variable name"),
        ("FROM b\nENV A=${B:?no}\n", None, "expands ${B} in a form this reader does not"),
        ("FROM b\nENV A=${B:-x\n", None, "leaves a ${ open"),
        ("FROM b\nARG BUILDPLATFORM\n", None, "reads the builder's own platform (BUILDPLATFORM)"),
        ("FROM b\nSHELL /bin/bash\n", None, "has a SHELL that is no JSON list"),
        ("FROM b\nHEALTHCHECK --interval=soon CMD x\n", None, "a duration 'soon'"),
        ("FROM b\nHEALTHCHECK --retries=many CMD x\n", None, "--retries=many"),
        ("FROM b\nHEALTHCHECK --bogus=1 CMD x\n", None, "the flag --bogus"),
        ("FROM b\nHEALTHCHECK RUN x\n", None, "has a HEALTHCHECK 'RUN x'"),
        ("FROM b\nHEALTHCHECK CMD\n", None, "has a HEALTHCHECK 'CMD'"),
    ],
)
def test_a_shape_the_replay_does_not_follow_is_refused_by_name(text: str, base: dict | None, expected: str) -> None:
    with pytest.raises(ReleaseError, match="a shape sign cannot compare") as refused:
        _replay(text, base)
    assert expected in refused.value.message


def test_the_differences_name_each_field_and_each_variable_but_never_a_value() -> None:
    expected = {"Env": ["A=1", "B=secret"], "Cmd": ["x"], "WorkingDir": "/", "Healthcheck": {"Test": ["NONE"], "Retries": 0},
                "Volumes": {"/a": {}}}
    same = {"Env": ["B=secret", "A=1"], "Cmd": ["x"], "WorkingDir": "", "Healthcheck": {"Test": ["NONE"]},
            "Volumes": {"/a": {}}, "Labels": {"x": "y"}}
    assert _dockerfile.differences(expected, same) == []
    found = _dockerfile.differences(expected, {"Env": ["A=1", "B=s3cr3t-2", "C=1", "C=2"], "Cmd": [], "User": "root"})
    assert found == [
        'the image\'s Cmd is null, and its Dockerfile makes it ["x"]',
        'the image\'s User is "root", and its Dockerfile makes it null',
        'the image\'s Healthcheck is null, and its Dockerfile makes it {"Test": ["NONE"]}',
        'the image\'s Volumes is null, and its Dockerfile makes it ["/a"]',
        "the image's environment sets a variable more than once",
        "the image's environment gives B another value than its Dockerfile does",
        "the image's environment sets C, which its Dockerfile does not",
    ]
    assert not any("secret" in finding or "s3cr3t" in finding for finding in found)
