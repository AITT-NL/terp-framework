"""A production process writes nothing but ``terp-log/1`` records (ADR 0188).

``test_structured_logs.py`` holds each kind of line to the schema in-process. This file
holds the claim that matters to a reader of a container's output: **every** line a served
app writes, from the moment uvicorn starts it to the moment it stops, is one JSON object
that validates against the schema shipped with terp-core -- uvicorn's own startup and
shutdown lines, the access lines, the guard's decisions, errors, a library's traceback, a
warning, a thread that died, a log call with broken arguments -- and no secret the
requests carried reaches any of them. A second served app holds the personal-data marker
to the same bar: no value of a field declared ``Personal`` reaches its output (ADR 0190).

It runs the app the way the template's production image does (``uvicorn app:app
--timeout-graceful-shutdown 8``, ``ENVIRONMENT=production``, no log configuration on the
command line), because that is where the plain-text lines came from: uvicorn configures
its own loggers before it imports the app, and those loggers did not propagate.

Two boots that end in a refusal are held to the same bar: a composition the production
guardrails refuse, and a configuration the settings refuse before ``terp.core`` has even
finished importing. A refusal is the line an operator reads first.
"""

from __future__ import annotations

import json
import os
import signal
import secrets
import socket
import subprocess
import sys
import textwrap
import time
import uuid
from pathlib import Path
from typing import Any

import httpx
import pytest
from jsonschema import Draft202012Validator

from terp.core import log_record_schema

_SCHEMA = log_record_schema()
_VALIDATOR = Draft202012Validator(_SCHEMA)

# Fixture credentials the output must not hold, generated per run (ADR 0163): a literal here
# would be a credential-shaped string in the history every secret scan reads.
_TOKEN = "served-tok-" + secrets.token_hex(5)
_PASSWORD = "served-pw-" + secrets.token_hex(4)
_DB_PASSWORD = "served-db-" + secrets.token_hex(4)
_SECRET_KEY = "served-secret-key-" + secrets.token_hex(16)
_ACTOR = uuid.UUID("5b1f2e3d-4c5a-4b6c-8d7e-9f0a1b2c3d4e")
_SECRETS = (_TOKEN, _PASSWORD, _DB_PASSWORD, _SECRET_KEY)

_SERVED_APP = textwrap.dedent(
    """
    import logging
    import threading
    import uuid
    import warnings

    from fastapi import APIRouter, Request
    from starlette.requests import HTTPConnection

    from terp.core import (
        VIEWER, AuditPolicy, ControlPlane, CorsPolicy, ModuleSpec, NotFoundError, Policy,
        Principal, SecurityConfig, create_app,
    )

    TOKEN = {token!r}
    PASSWORD = {password!r}
    ACTOR = uuid.UUID({actor!r})
    _log = logging.getLogger("served.probe")
    router = APIRouter()


    @router.get("/items/{{item_id}}")
    def read_item(item_id: uuid.UUID) -> dict[str, str]:
        return {{"id": str(item_id)}}


    @router.post("/items")
    def write_item() -> dict[str, str]:
        return {{}}


    @router.get("/missing")
    def missing() -> dict[str, str]:
        raise NotFoundError(log_context={{"token": TOKEN, "cause": "Authorization: Bearer " + TOKEN}})


    @router.get("/boom")
    def boom() -> dict[str, str]:
        raise RuntimeError("password=" + PASSWORD)


    def _die() -> None:
        raise ValueError("token=" + TOKEN)


    @router.get("/noise")
    def noise(request: Request) -> dict[str, str]:
        _log.info("caller sent %s", request.headers.get("authorization"))
        _log.info("%d items", "many")  # a broken log call
        warnings.warn("a deprecated knob", UserWarning, stacklevel=1)
        worker = threading.Thread(target=_die, name="worker")
        worker.start()
        worker.join()
        return {{}}


    def principal(connection: HTTPConnection) -> Principal | None:
        if connection.headers.get("authorization") == "Bearer " + TOKEN:
            return Principal(id=ACTOR, role=VIEWER)
        return None


    app = create_app(
        [ModuleSpec(name="probe", router=router, policy=Policy.default())],
        principal_provider=principal,
        control_plane=ControlPlane(
            security=SecurityConfig(cors=CorsPolicy.disabled(reason="a same-origin probe")),
            audit=AuditPolicy.disabled(reason="a probe that writes nothing"),
        ),
    )
    """
).format(token=_TOKEN, password=_PASSWORD, actor=str(_ACTOR))

# Production refuses a composition whose CORS posture was never declared.
_REFUSED_APP = "from terp.core import create_app\n\napp = create_app([])\n"


def _closed_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _environment(**overrides: str) -> dict[str, str]:
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("TERP_", "DB_")) and key not in {"ENVIRONMENT", "SECRET_KEY",
                                                                  "DATABASE_URL", "DEBUG"}
    }
    env.update(
        ENVIRONMENT="production",
        SECRET_KEY=_SECRET_KEY,
        # Nothing listens there; the bound makes the readiness probe fail fast everywhere
        # (a connect to a closed local port can hang rather than be refused).
        DATABASE_URL=(
            f"postgresql+psycopg://probe:{_DB_PASSWORD}@127.0.0.1:{_closed_port()}/probe"
            "?connect_timeout=1"
        ),
        PYTHONUNBUFFERED="1",
        PYTHONPATH=os.pathsep.join(filter(None, [overrides.pop("PYTHONPATH", ""),
                                                env.get("PYTHONPATH", "")])),
    )
    env.update(overrides)
    return env


def _records(*outputs: Path) -> list[dict[str, Any]]:
    """Every line of *outputs*, each of which must be one valid ``terp-log/1`` record."""
    records: list[dict[str, Any]] = []
    for output in outputs:
        for number, text in enumerate(output.read_text(encoding="utf-8").splitlines(), 1):
            if not text.strip():
                continue
            try:
                record = json.loads(text)
            except ValueError:
                pytest.fail(f"{output.name}:{number} is not a JSON record: {text[:200]!r}")
            errors = sorted(error.message for error in _VALIDATOR.iter_errors(record))
            assert errors == [], f"{output.name}:{number} breaks terp-log/1: {errors}"
            assert set(record) <= set(_SCHEMA["properties"]), sorted(record)
            records.append(record)
    for secret in _SECRETS:
        for output in outputs:
            assert secret not in output.read_text(encoding="utf-8"), f"{secret!r} in {output.name}"
    return records


def _serve(
    tmp_path: Path, module: str, source: str
) -> tuple[subprocess.Popen[bytes], int, Path, Path]:
    (tmp_path / f"{module}.py").write_text(source, encoding="utf-8")
    port = _closed_port()
    stdout, stderr = tmp_path / "stdout.log", tmp_path / "stderr.log"
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
    # The child keeps its own copies of the two handles; this process closes its own.
    with stdout.open("wb") as out, stderr.open("wb") as err:
        process = subprocess.Popen(  # noqa: S603 - the template's own production command
            [sys.executable, "-m", "uvicorn", f"{module}:app", "--host", "127.0.0.1",
             "--port", str(port), "--timeout-graceful-shutdown", "8"],
            cwd=tmp_path,
            env=_environment(PYTHONPATH=str(tmp_path)),
            stdout=out,
            stderr=err,
            creationflags=flags,
        )
    return process, port, stdout, stderr


def _stop(process: subprocess.Popen[bytes]) -> None:
    """Ask uvicorn to shut down gracefully, the way an orchestrator's stop does."""
    if sys.platform == "win32":
        os.kill(process.pid, signal.CTRL_BREAK_EVENT)
    else:
        process.send_signal(signal.SIGTERM)
    try:
        process.wait(timeout=30)
    except subprocess.TimeoutExpired:  # pragma: no cover - only a hung server lands here
        process.kill()
        raise


def test_every_line_a_served_production_app_writes_is_a_terp_log_record(tmp_path: Path) -> None:
    process, port, stdout, stderr = _serve(tmp_path, "served_app", _SERVED_APP)
    base = f"http://127.0.0.1:{port}"
    auth = {"Authorization": f"Bearer {_TOKEN}"}
    requests = 0
    try:
        with httpx.Client(base_url=base, timeout=30) as client:
            deadline = time.monotonic() + 60
            while True:
                assert process.poll() is None, stderr.read_text(encoding="utf-8")
                try:
                    requests += 1
                    if client.get("/health/live").status_code == 200:
                        break
                except httpx.TransportError:
                    requests -= 1  # refused before it reached the app: no request was made
                assert time.monotonic() < deadline, "the served app never became live"
                time.sleep(0.2)
            item = uuid.uuid4()
            calls = [
                ("GET", "/health/ready", {}, 503),  # the database is unreachable
                ("GET", f"/api/v1/probe/items/{item}", auth, 200),
                ("POST", "/api/v1/probe/items", auth, 403),
                ("GET", f"/api/v1/probe/items/{item}", {}, 401),
                ("GET", "/api/v1/probe/missing", auth, 404),
                ("GET", "/api/v1/probe/boom", auth, 500),
                ("GET", "/api/v1/probe/noise", auth, 200),
                ("GET", f"/elsewhere/{item}?token={_TOKEN}", {}, 404),
            ]
            for method, path, headers, status in calls:
                assert client.request(method, path, headers=headers).status_code == status, path
                requests += 1
    finally:
        _stop(process)

    records = _records(stdout, stderr)
    by_event: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        by_event.setdefault(record.get("event", "-"), []).append(record)
    messages = [record["message"] for record in records if record["logger"] == "uvicorn.error"]

    # uvicorn's own lines, from start to stop, are records too.
    for expected in ("Started server process", "Application startup complete",
                     "Uvicorn running on", "Shutting down", "Finished server process"):
        assert any(message.startswith(expected) for message in messages), (expected, messages)
    # One access line per request, and uvicorn's raw-path copy of it is gone.
    assert len(by_event["http.access"]) == requests
    assert not [record for record in records if record["logger"] == "uvicorn.access"]
    assert str(item) not in stdout.read_text(encoding="utf-8") + stderr.read_text(encoding="utf-8")
    routes = {record["http"].get("route") for record in by_event["http.access"]}
    assert "/api/v1/probe/items/{item_id}" in routes and None in routes
    # The guard's decisions ride their access lines; each AppError is written once.
    assert {record["guard"]["outcome"] for record in by_event["http.access"]
            if "guard" in record} == {"allow", "deny"}
    assert sorted(record["error"]["code"] for record in by_event["error.app"]) == [
        "authentication_required", "not_found", "permission_denied"]
    assert len(by_event["error.unhandled"]) == 1
    # Starlette re-raises that exception to the server once it has been answered; the
    # server's own copy ("Exception in ASGI application") is the duplicate, and is gone.
    assert not [message for message in messages if message.startswith("Exception in ASGI")]
    assert sum("RuntimeError" in record.get("exc_info", "") for record in records) == 1
    # The library traceback, the warning, the dead thread and the broken log call.
    assert any(record["message"] == "database readiness check failed" and "exc_info" in record
               for record in records)
    assert any("a deprecated knob" in record["message"]
               for record in records if record["logger"] == "py.warnings")
    assert [record["message"].split(":")[0] for record in by_event["error.uncaught"]] == [
        "uncaught ValueError in thread worker"]
    assert len(by_event["log.failure"]) == 1
    # Startup said what the production boot warns about, as records.
    assert any(record["level"] == "WARNING" and record["logger"] == "terp.core"
               for record in records)


# The personal values a served app is handed and must never write (ADR 0190), generated per
# run for the same reason the credentials are.
_EMAIL = f"served-{secrets.token_hex(5)}@example.test"
_PHONE = "+31 6 " + "".join(str(secrets.randbelow(10)) for _ in range(8))

_SERVED_PERSONAL_APP = textwrap.dedent(
    """
    import logging
    import uuid

    from fastapi import APIRouter
    from starlette.requests import HTTPConnection

    from terp.core import (
        VIEWER, AuditPolicy, BaseSchema, ControlPlane, CorsPolicy, ModuleSpec, NotFoundError,
        Personal, Policy, Principal, SecurityConfig, create_app,
    )

    TOKEN = {token!r}
    EMAIL = {email!r}
    PHONE = {phone!r}
    ACTOR = uuid.UUID({actor!r})
    _log = logging.getLogger("served.personal")
    router = APIRouter()


    class Customer(BaseSchema):
        id: uuid.UUID
        email: str = Personal(max_length=320)
        phone: str | None = Personal(default=None, max_length=32)
        note: str = ""


    class Strict(BaseSchema):
        email: str = Personal(max_length=8)


    def customer() -> Customer:
        return Customer(id=uuid.uuid4(), email=EMAIL, phone=PHONE, note="vip")


    @router.get("/customers/{{customer_id}}")
    def read_customer(customer_id: uuid.UUID, email: str = "") -> dict[str, str]:
        return {{"id": str(customer_id)}}


    @router.get("/by-name")
    def by_name() -> dict[str, str]:
        raise NotFoundError(log_context={{"email": EMAIL, "phone": PHONE}})


    @router.get("/by-model")
    def by_model() -> dict[str, str]:
        raise NotFoundError(log_context={{"customer": customer()}})


    @router.get("/logged")
    def logged() -> dict[str, str]:
        _log.info("customer %s", customer(), extra={{"customer": customer(), "email": EMAIL}})
        _log.warning(f"customer {{customer()}}")
        return {{}}


    @router.get("/boom")
    def boom() -> dict[str, str]:
        raise RuntimeError(f"cannot bill {{customer()}}")


    @router.get("/invalid")
    def invalid() -> dict[str, str]:
        Strict(email=EMAIL)
        return {{}}


    def principal(connection: HTTPConnection) -> Principal | None:
        if connection.headers.get("authorization") == "Bearer " + TOKEN:
            return Principal(id=ACTOR, role=VIEWER)
        return None


    app = create_app(
        [ModuleSpec(name="people", router=router, policy=Policy.default())],
        principal_provider=principal,
        control_plane=ControlPlane(
            security=SecurityConfig(cors=CorsPolicy.disabled(reason="a same-origin probe")),
            audit=AuditPolicy.disabled(reason="a probe that writes nothing"),
        ),
    )
    """
).format(token=_TOKEN, email=_EMAIL, phone=_PHONE, actor=str(_ACTOR))


def test_no_declared_personal_value_reaches_a_served_production_log(tmp_path: Path) -> None:
    """The exit test of the personal-data marker, against a production uvicorn process.

    Every path a value can take into a line -- a query string beside the access line,
    ``log_context`` by name and by model, a model as an argument, in ``extra=`` and in an
    f-string, an unexpected exception built from a model, a validation error of a personal
    field -- and the process's whole output holds none of the declared values.
    """
    process, port, stdout, stderr = _serve(tmp_path, "served_people", _SERVED_PERSONAL_APP)
    auth = {"Authorization": f"Bearer {_TOKEN}"}
    try:
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=30) as client:
            deadline = time.monotonic() + 60
            while True:
                assert process.poll() is None, stderr.read_text(encoding="utf-8")
                try:
                    if client.get("/health/live").status_code == 200:
                        break
                except httpx.TransportError:
                    pass
                assert time.monotonic() < deadline, "the served app never became live"
                time.sleep(0.2)
            calls = [
                (f"/api/v1/people/customers/{uuid.uuid4()}?email={_EMAIL}", 200),
                ("/api/v1/people/by-name", 404),
                ("/api/v1/people/by-model", 404),
                ("/api/v1/people/logged", 200),
                ("/api/v1/people/boom", 500),
                ("/api/v1/people/invalid", 500),
            ]
            for path, status in calls:
                assert client.get(path, headers=auth).status_code == status, path
    finally:
        _stop(process)

    records = _records(stdout, stderr)
    output = stdout.read_text(encoding="utf-8") + stderr.read_text(encoding="utf-8")
    for value in (_EMAIL, _PHONE):
        assert value not in output, f"{value!r} reached the served output"
    by_event: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        by_event.setdefault(record.get("event", "-"), []).append(record)
    # Each path was taken, and withheld rather than skipped.
    contexts = [record.get("context") for record in by_event["error.app"]]
    assert {"email": "[PERSONAL]", "phone": "[PERSONAL]"} in contexts
    assert any("email=[PERSONAL]" in str(context) for context in contexts)
    logged = [record for record in records if record["logger"] == "served.personal"]
    assert len(logged) == 2 and all("[PERSONAL]" in record["message"] for record in logged)
    assert logged[0]["extra"]["email"] == "[PERSONAL]"
    unhandled = by_event["error.unhandled"]
    assert len(unhandled) == 2
    assert "[PERSONAL]" in unhandled[0]["exc_info"] and "ValidationError" in unhandled[1]["exc_info"]


def test_a_refused_production_boot_is_a_terp_log_record(tmp_path: Path) -> None:
    process, _port, stdout, stderr = _serve(tmp_path, "refused_app", _REFUSED_APP)
    assert process.wait(timeout=60) != 0
    records = _records(stdout, stderr)
    (refusal,) = [record for record in records if record.get("event") == "error.uncaught"]
    assert refusal["level"] == "CRITICAL"
    assert refusal["error"] == {"type": "BootError"}
    assert "insecure production security config" in refusal["message"]
    assert "BootError" in refusal["exc_info"]


def test_a_refused_configuration_is_a_record_that_does_not_print_it(tmp_path: Path) -> None:
    stdout, stderr = tmp_path / "stdout.log", tmp_path / "stderr.log"
    with stdout.open("wb") as out, stderr.open("wb") as err:
        result = subprocess.run(  # noqa: S603 - the interpreter running this suite
            [sys.executable, "-c", "import terp.core"],
            cwd=tmp_path,
            env=_environment(SECRET_KEY="short-and-weak"),
            stdout=out,
            stderr=err,
            timeout=120,
            check=False,
        )
    assert result.returncode != 0
    (refusal,) = _records(stdout, stderr)
    assert refusal["event"] == "error.uncaught"
    assert "Insecure production configuration" in refusal["message"]
    output = stdout.read_text(encoding="utf-8") + stderr.read_text(encoding="utf-8")
    assert "short-and-weak" not in output
