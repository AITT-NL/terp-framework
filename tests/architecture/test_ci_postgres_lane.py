"""Every test module that takes ``terp_db_url`` or ``terp_pg_url`` runs in CI's PostgreSQL lane.

The first runs a test on SQLite and again on PostgreSQL wherever ``TERP_TEST_POSTGRES_URL``
names a server, and the second on PostgreSQL alone. The dedicated lane requires every
case to run, including restore drills with a matching client. A skip is green, and the
module's claim to cover both dialects reads as true. That happened to the audit activity's
per-day counts in 0.32.0's development: claimed for both, run on one.

The lane installs PostgreSQL's matching client from PGDG's archive, whose signing key is
committed beside the workflow: fetched on every run, one unretried curl failed the lane twice,
and the run trusted whatever key came back. So the key is held here to the one PGDG publishes,
and the step to installing it from the repository with apt retrying.
"""

from __future__ import annotations

import base64
import hashlib
import pathlib
import re

import yaml

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_LANE_STEP = "Run every test that takes terp_db_url against PostgreSQL"
_CLIENT_STEP = "Install the matching PostgreSQL client (for the restore drill)"

#: PGDG's archive signing key, committed so no run fetches it.
_PGDG_KEY = _REPO_ROOT / ".github" / "keys" / "apt.postgresql.org.asc"

#: The key's fingerprint, as https://www.postgresql.org/download/linux/debian/ gives it (ACCC4CF8).
_PGDG_FINGERPRINT = "B97B0AFCAA1A47F044F244A07FCC7D46ACCC4CF8"

_PUBLIC_KEY, _SIGNATURE, _USER_ID, _SUBKEY = 6, 2, 13, 14


def _step(name: str) -> dict:
    workflow = yaml.safe_load((_REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))
    for job in workflow["jobs"].values():
        for step in job.get("steps", ()):
            if step.get("name") == name:
                return step
    raise AssertionError(f"no CI step named {name!r}")


def _lane_command() -> str:
    step = _step(_LANE_STEP)
    assert step["env"]["TERP_REQUIRE_POSTGRES_LANE"] == "1", "a skip in the lane must fail"
    return step["run"]


def _packets(armored: str) -> list[tuple[int, bytes]]:
    """``(tag, body)`` of every OpenPGP packet in an ASCII-armored public key block (RFC 4880).

    Read here rather than by gpg, so the gate needs no keyring tool on any host it runs on.
    """
    lines = armored.strip().splitlines()
    assert (lines[0], lines[-1]) == ("-----BEGIN PGP PUBLIC KEY BLOCK-----", "-----END PGP PUBLIC KEY BLOCK-----")
    body = lines[lines.index("") + 1 : -1]  # the armor's headers end at its first blank line
    data = base64.b64decode("".join(line for line in body if not line.startswith("=")))
    found: list[tuple[int, bytes]] = []
    at = 0
    while at < len(data):
        header = data[at]
        assert header & 0x80, f"byte {at} starts no packet"
        if header & 0x40:  # the new format: a one, two or five octet length
            tag, first = header & 0x3F, data[at + 1]
            assert first < 224 or first == 255, "a partial length is never a key's"
            if first < 192:
                length, at = first, at + 2
            elif first < 224:
                length, at = ((first - 192) << 8) + data[at + 2] + 192, at + 3
            else:
                length, at = int.from_bytes(data[at + 2 : at + 6], "big"), at + 6
        else:  # the old format: the length's size is in the header's low bits
            tag, size = (header >> 2) & 0x0F, {0: 1, 1: 2, 2: 4}[header & 0x03]
            length, at = int.from_bytes(data[at + 1 : at + 1 + size], "big"), at + 1 + size
        found.append((tag, data[at : at + length]))
        at += length
    return found


def _fingerprint(key: bytes) -> str:
    """A version 4 key's fingerprint: SHA-1 over 0x99, its body's two-octet length, and its body."""
    assert key[0] == 4, "a version 4 key"
    return hashlib.sha1(b"\x99" + len(key).to_bytes(2, "big") + key, usedforsecurity=False).hexdigest().upper()


def test_the_committed_pgdg_key_is_the_one_pgdg_publishes() -> None:
    """One primary key, PGDG's, and no subkey: apt then accepts the archive only as signed by it."""
    packets = _packets(_PGDG_KEY.read_text(encoding="ascii"))
    keys = [body for tag, body in packets if tag == _PUBLIC_KEY]
    assert [_fingerprint(key) for key in keys] == [_PGDG_FINGERPRINT]
    assert packets[0][0] == _PUBLIC_KEY and _SUBKEY not in {tag for tag, _ in packets}
    assert {tag for tag, _ in packets} <= {_PUBLIC_KEY, _USER_ID, _SIGNATURE}


def test_the_lane_installs_the_committed_key_and_apt_retries() -> None:
    """The lane cannot go back to a key fetched once, unretried and unchecked, on every run."""
    run = _step(_CLIENT_STEP)["run"]
    assert f"install -m 0644 {_PGDG_KEY.relative_to(_REPO_ROOT).as_posix()} " in run
    assert re.search(r"\b(?:curl|wget)\b|postgresql\.org/media/keys|--recv-keys?\b", run) is None, (
        "the step fetches a key: install the committed one instead"
    )
    apt = [line for line in run.splitlines() if re.search(r"(?:^|\s)apt(?:-get)?\s", line)]
    assert len(apt) == 2 and all("-o Acquire::Retries=5" in line for line in apt), apt


def _modules_taking_the_fixture() -> set[str]:
    taking = re.compile(r"\bterp_(?:db|pg)_url\b")
    return {
        path.relative_to(_REPO_ROOT).as_posix()
        for path in (_REPO_ROOT / "tests").rglob("test_*.py")
        if path.name != pathlib.Path(__file__).name
        and taking.search(path.read_text(encoding="utf-8"))
        # The fixture's own tests monkeypatch the environment and name the fixture
        # without taking it; they run in the gate like any other module.
        and path.name != "test_testing_db_fixtures.py"
    }


def test_the_lane_runs_every_module_that_takes_the_fixture() -> None:
    command = _lane_command()
    missing = sorted(module for module in _modules_taking_the_fixture() if module not in command)
    assert not missing, f"never run on PostgreSQL in CI: {missing}"


def test_the_fixture_is_found_where_it_is_taken() -> None:
    """Held against the modules known to take one, so an empty scan cannot pass."""
    assert {
        "tests/architecture/test_migrations_conformance.py",
        "tests/architecture/test_audit_activity.py",
        # terp_pg_url, the PostgreSQL-only half: it skips anywhere but the lane just the same.
        "tests/architecture/test_readiness_postgres.py",
    } <= _modules_taking_the_fixture()
