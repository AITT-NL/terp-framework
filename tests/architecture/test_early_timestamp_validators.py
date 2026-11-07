"""ADR 0207: an app's own early validator on a timestamp field is the escape, named and counted.

A ``before``, ``wrap`` or ``plain`` validator sees a timestamp's text before its type does, and
before the refusal ``BaseSchema`` puts in front of that type, so it can read a time with no UTC
offset in a zone of its own choosing. ``request_timestamps_carry_their_offset`` counts each one
where it is declared, so taking it is the rule's marker, which the app's budget counts; a wall
time in a named zone is ``LocalTimeIn``'s, which names the instant.
"""

from __future__ import annotations

import pathlib

import pytest

from terp.arch.rules.request_timestamps import check_request_timestamps_carry_their_offset

_HEADER = (
    "import datetime as dt\n"  # 1
    "from datetime import date, datetime\n"  # 2
    "from typing import Annotated, Literal, Optional\n"  # 3
    "\n"  # 4
    "import pydantic\n"  # 5
    "from pydantic import AfterValidator, BeforeValidator, Field, PlainValidator, WrapValidator\n"  # 6
    "from pydantic import field_validator, model_validator, validator\n"  # 7
    "from terp.core import BaseSchema, LocalTimeIn\n"  # 8
    "\n"  # 9
    "\n"  # 10
    "def read(value):\n"  # 11
    "    return value\n"  # 12
    "\n"  # 13
    "\n"  # 14
)
_FIRST = _HEADER.count("\n") + 1


def _lines(tmp_path: pathlib.Path, body: str, *, header: str = _HEADER) -> list[int]:
    app = tmp_path / "app"
    path = app / "modules" / "meetings" / "schemas.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(header + body, encoding="utf-8")
    violations = check_request_timestamps_carry_their_offset(app)
    assert {violation.rule for violation in violations} <= {"request_timestamps_carry_their_offset"}
    return [violation.line - header.count("\n") for violation in violations]


@pytest.mark.parametrize(
    "annotation",
    [
        "Annotated[datetime, BeforeValidator(read)]",
        "Annotated[datetime, WrapValidator(lambda v, h: h(v))]",
        "Annotated[datetime, PlainValidator(read)]",
        "Annotated[dt.datetime, pydantic.BeforeValidator(read)]",
        "Annotated[pydantic.AwareDatetime, BeforeValidator(read)]",
        "Annotated[datetime | None, BeforeValidator(read)]",
        "Annotated[Optional[datetime], Field(description='when'), BeforeValidator(read)]",
        "Annotated[list[datetime], BeforeValidator(read)]",
        '"Annotated[datetime, BeforeValidator(read)]"',
    ],
)
def test_an_early_validator_in_a_timestamps_annotation_is_counted_at_its_line(
    tmp_path: pathlib.Path, annotation: str
) -> None:
    assert _lines(tmp_path, f"class Meeting(BaseSchema):\n    starts_at: {annotation}\n") == [2]


def test_it_is_counted_through_an_import_alias_a_bound_validator_and_a_type_alias(tmp_path: pathlib.Path) -> None:
    header = _HEADER + (
        "from datetime import datetime as Moment\n"  # +1
        "from pydantic import BeforeValidator as Early\n"  # +2
        "\n"  # +3
        "AMSTERDAM = BeforeValidator(read)\n"  # +4
        "Stamp = Optional[Moment]\n"  # +5
    )
    body = (
        "Lenient = Annotated[Stamp, Early(read)]\n"  # 1: counted where the alias is bound
        "\n"
        "\n"
        "class Meeting(BaseSchema):\n"  # 4
        "    starts_at: Annotated[Moment, AMSTERDAM]\n"  # 5
        "    ends_at: Lenient\n"  # 6: and at each use, as NaiveMeansUtc's aliases are
    )
    assert _lines(tmp_path, body, header=header) == [1, 5, 6]


def test_a_type_that_carries_one_counts_at_each_use_however_it_is_reached(tmp_path: pathlib.Path) -> None:
    body = (
        "Lenient = Annotated[datetime, BeforeValidator(read)]\n"  # 1
        "Optionally = Lenient | None\n"  # 2: bound to a type that carries it
        "\n"
        "\n"
        "class Meeting(BaseSchema):\n"  # 5
        "    starts_at: Lenient\n"  # 6
        "    ends_at: Optionally\n"  # 7
        "    noted_at: 'Lenient | None' = None\n"  # 8
    )
    assert _lines(tmp_path, body) == [1, 2, 6, 7, 8]


def test_annotated_and_the_validators_are_followed_through_every_alias(tmp_path: pathlib.Path) -> None:
    header = _HEADER + (
        "import typing\n"  # +1
        "from typing import Annotated as Typed\n"  # +2
        "\n"  # +3
        "Meta = typing.Annotated\n"  # +4
        "Early = BeforeValidator\n"  # +5
        "Choose = pydantic.field_validator\n"  # +6
    )
    body = (
        "class Meeting(BaseSchema):\n"  # 1
        "    starts_at: Typed[datetime, BeforeValidator(read)]\n"  # 2
        "    ends_at: Meta[datetime, Early(read)]\n"  # 3
        "    noted_at: datetime\n"  # 4
        "\n"  # 5
        '    @Choose("noted_at", mode="before")\n'  # 6
        "    @classmethod\n"
        "    def read_it(cls, value):\n"
        "        return value\n"
    )
    assert _lines(tmp_path, body, header=header) == [2, 3, 6]


def test_a_field_validator_written_as_a_call_in_the_class_body_counts(tmp_path: pathlib.Path) -> None:
    body = (
        "class Meeting(BaseSchema):\n"  # 1
        "    starts_at: datetime\n"  # 2
        '    read_it = field_validator("starts_at", mode="before")(classmethod(read))\n'  # 3
    )
    assert _lines(tmp_path, body) == [3]


def test_a_validator_a_base_declares_counts_for_a_subclass_s_timestamp_field(tmp_path: pathlib.Path) -> None:
    body = (
        "class AppSchema(BaseSchema):\n"  # 1
        '    @field_validator("*", mode="before")\n'  # 2: applies to every subclass's fields
        "    @classmethod\n"
        "    def read_local(cls, value):\n"
        "        return value\n"
        "\n"  # 6
        '    @field_validator("starts_at", mode="before", check_fields=False)\n'  # 7
        "    @classmethod\n"
        "    def read_start(cls, value):\n"
        "        return value\n"
        "\n"
        "\n"
        "class Meeting(AppSchema):\n"  # 13
        "    starts_at: datetime\n"  # 14
        "\n"
        "\n"
        "class Note(AppSchema):\n"  # 17: no timestamp, and the base alone has none either
        "    title: str\n"
    )
    assert _lines(tmp_path, body) == [2, 7]


def test_a_file_the_parser_takes_never_crashes_the_rule(tmp_path: pathlib.Path) -> None:
    chain = " + ".join(['"s"'] * 1500)
    deeper = " + ".join(['"s"'] * 100_000)
    body = (
        f"MESSAGE = {chain}\n"  # 1: a long chain of concatenations, walked without recursing
        f"QUOTED = {deeper!r}\n"  # 2: a string the parser cannot build, too deep
        'NULL = "\\x00"\n'  # 3: a string the parser refuses
        "Lenient = Annotated[datetime, BeforeValidator(read)]\n"  # 4: still seen
    )
    assert _lines(tmp_path, body) == [4]


@pytest.mark.parametrize(
    "decorator",
    [
        '@field_validator("starts_at", mode="before")',
        '@field_validator("starts_at", mode="wrap")',
        '@field_validator("starts_at", mode="plain")',
        '@field_validator("title", "starts_at", mode="before")',
        '@field_validator("*", mode="before")',
        '@field_validator(*FIELDS, mode="before")',  # a name it cannot read counts
        '@field_validator("starts_at", mode=MODE)',  # so does a mode it cannot read
        '@field_validator("starts_at", **OPTIONS)',  # and one passed in a mapping
        '@pydantic.field_validator("starts_at", mode="before")',
        '@validator("starts_at", pre=True)',  # Pydantic 1's, which runs before the type
        '@validator("starts_at", pre=PRE)',
    ],
)
def test_an_early_field_validator_on_a_timestamp_field_is_counted_at_its_decorator(
    tmp_path: pathlib.Path, decorator: str
) -> None:
    body = (
        "class Meeting(BaseSchema):\n"  # 1
        "    title: str\n"  # 2
        "    starts_at: datetime\n"  # 3
        "\n"  # 4
        f"    {decorator}\n"  # 5
        "    @classmethod\n"
        "    def read_it(cls, value):\n"
        "        return value\n"
    )
    assert _lines(tmp_path, body) == [5]


def test_a_new_type_and_a_type_alias_type_over_a_timestamp_are_timestamps(tmp_path: pathlib.Path) -> None:
    header = _HEADER + (
        "from typing import NewType, TypeAliasType\n"  # +1
        "\n"  # +2
        'Stamp = NewType("Stamp", datetime)\n'  # +3
        'Window = TypeAliasType("Window", list[Stamp])\n'  # +4
        "EPOCH = datetime(1970, 1, 1)\n"  # +5: a value, which binds no type
    )
    body = (
        "class Meeting(BaseSchema):\n"  # 1
        "    starts_at: Stamp\n"  # 2
        "    slots: Window\n"  # 3
        "\n"  # 4
        '    @field_validator("starts_at", mode="before")\n'  # 5
        "    @classmethod\n"
        "    def read_it(cls, value):\n"
        "        return value\n"
        "\n"  # 9
        '    @field_validator("slots", mode="before")\n'  # 10
        "    @classmethod\n"
        "    def read_them(cls, value):\n"
        "        return value\n"
    )
    assert _lines(tmp_path, body, header=header) == [5, 10]


def test_an_attribute_of_the_datetime_module_is_a_timestamp_only_when_it_is_one(tmp_path: pathlib.Path) -> None:
    header = "import datetime\nfrom typing import Annotated\n\nfrom pydantic import BeforeValidator, Field\n\n\n"
    body = (
        "def read(value):\n"  # 1
        "    return value\n"  # 2
        "\n"  # 3
        "\n"  # 4
        "Day = Annotated[datetime.date, BeforeValidator(read)]\n"  # 5: a day
        "Moment = Annotated[datetime.datetime, BeforeValidator(read)]\n"  # 6
        'Text = Annotated[str, Field(description="datetime"), BeforeValidator(read)]\n'  # 7: str
    )
    assert _lines(tmp_path, body, header=header) == [6]


def test_a_field_its_base_declares_in_the_same_file_is_a_timestamp_too(tmp_path: pathlib.Path) -> None:
    body = (
        "class Timed(BaseSchema):\n"  # 1
        "    starts_at: 'datetime | None' = None\n"  # 2
        "\n"
        "\n"
        "class Meeting(Timed):\n"  # 5
        '    @field_validator("starts_at", mode="before")\n'  # 6
        "    @classmethod\n"
        "    def read_it(cls, value):\n"
        "        return value\n"
    )
    assert _lines(tmp_path, body) == [6]


def test_what_is_not_an_early_validator_on_a_timestamp_is_not_counted(tmp_path: pathlib.Path) -> None:
    body = (
        "class Meeting(BaseSchema):\n"
        '    starts_at: Annotated[datetime, LocalTimeIn("Europe/Amsterdam")]\n'
        "    checked_at: Annotated[datetime, AfterValidator(read)]\n"
        "    day: Annotated[date, BeforeValidator(read)]\n"
        "    other_day: Annotated[dt.date, BeforeValidator(read)]\n"
        "    title: Annotated[str, BeforeValidator(read), Field(description='datetime')]\n"
        '    kind: Literal["datetime"] = "datetime"\n'
        "    noted: 'not a type at all' = None\n"
        "    ends_at: datetime\n"
        "\n"
        '    @field_validator("ends_at")\n'  # after, Pydantic's default
        "    @classmethod\n"
        "    def check_end(cls, value):\n"
        "        return value\n"
        "\n"
        '    @field_validator("ends_at", mode="after")\n'
        "    @classmethod\n"
        "    def check_end_again(cls, value):\n"
        "        return value\n"
        "\n"
        '    @field_validator("title", mode="before")\n'  # not a timestamp field
        "    @classmethod\n"
        "    def strip(cls, value):\n"
        "        return value\n"
        "\n"
        '    @field_validator("kind", mode="before")\n'  # a Literal value is text, not a type
        "    @classmethod\n"
        "    def lower(cls, value):\n"
        "        return value\n"
        "\n"
        '    @validator("ends_at", pre=False)\n'
        "    def old_after(cls, value):\n"
        "        return value\n"
        "\n"
        '    @model_validator(mode="before")\n'  # sees the body, not a field (ADR 0206, Open)
        "    @classmethod\n"
        "    def whole(cls, data):\n"
        "        return data\n"
        "\n"
        "    @staticmethod\n"
        "    def helper():\n"
        "        return None\n"
        "\n"
        "\n"
        "class Untimed(BaseSchema):\n"
        "    title: str\n"
        "\n"
        '    @field_validator("title", mode="before")\n'
        "    @classmethod\n"
        "    def strip(cls, value):\n"
        "        return value\n"
        "\n"
        "\n"
        "EPOCH = datetime(1970, 1, 1)\n"
        "NOTHING = Annotated[()]\n"
    )
    assert _lines(tmp_path, body) == []


def test_a_field_a_base_from_another_module_declares_is_not_resolved(tmp_path: pathlib.Path) -> None:
    # A recorded residual: the check resolves a base by its name within the file.
    body = (
        "from app.common import Timed\n"
        "\n"
        "\n"
        "class Meeting(Timed):\n"
        '    @field_validator("starts_at", mode="before")\n'
        "    @classmethod\n"
        "    def read_it(cls, value):\n"
        "        return value\n"
    )
    assert _lines(tmp_path, body) == []


def test_the_message_names_local_time_in_the_marker_and_the_budget(tmp_path: pathlib.Path) -> None:
    app = tmp_path / "app"
    path = app / "schemas.py"
    path.parent.mkdir(parents=True)
    path.write_text(
        _HEADER + "class Meeting(BaseSchema):\n    starts_at: Annotated[datetime, BeforeValidator(read)]\n",
        encoding="utf-8",
    )
    ((violation),) = check_request_timestamps_carry_their_offset(app)
    assert violation.line == _FIRST + 1
    assert "LocalTimeIn('Europe/Amsterdam')" in violation.message
    assert "arch-allow-request-timestamps-carry-their-offset" in violation.message
    assert "escape-hatch-budget.json" in violation.message


def test_one_line_that_takes_both_escapes_is_one_finding(tmp_path: pathlib.Path) -> None:
    header = _HEADER + "from terp.core import NaiveMeansUtc\n"
    body = "class Meeting(BaseSchema):\n    starts_at: Annotated[NaiveMeansUtc, BeforeValidator(read)]\n"
    assert _lines(tmp_path, body, header=header) == [2]


def test_the_boundarys_own_packages_are_not_its_users(tmp_path: pathlib.Path) -> None:
    app = tmp_path / "app"
    path = app / "schemas.py"
    path.parent.mkdir(parents=True)
    path.write_text(_HEADER + "Lenient = Annotated[datetime, BeforeValidator(read)]\n", encoding="utf-8")
    assert len(check_request_timestamps_carry_their_offset(app)) == 1
    assert check_request_timestamps_carry_their_offset(app, package="terp.core") == []
    assert check_request_timestamps_carry_their_offset(app, package="terp.arch") == []
