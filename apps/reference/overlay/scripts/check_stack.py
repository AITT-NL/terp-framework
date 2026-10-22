"""Drive the reference app's stack end to end, through every capability it exists to carry.

    uv run python scripts/check_stack.py --workbench              # this checkout's dev stack
    uv run python scripts/check_stack.py --rebuilds               # ...and its dependency changes
    uv run python scripts/check_stack.py --api URL --mailpit URL   # any running deployment

The unit suite proves each path with its outbound edge faked; this proves them against the
real services of a running stack, which is what a lane that deploys the app has to know:

1. sign in as the seeded administrator (``terp seed``);
2. post a notice, and wait for its mail to reach the catcher -- the API enqueued it in the
   notice's own transaction, the worker drained the outbox, the relay delivered it;
3. ask for a snapshot, and wait for the worker to store it -- one egress call to the
   declared host, its bytes in the files volume, a row that points at them;
4. read those bytes back through the files capability and compare them with the row.

``--workbench`` is the whole procedure for this checkout, so no lane has to restate it: it
starts the development stack (``docker compose up`` of :data:`WORKBENCH_SERVICES`, then
``terp seed``), finds the API and the catcher's inbox on their published ports, runs the
steps above, and then holds the processes no request reaches: the scheduler registered its
cron, the companion read the backlog, and every long-running service is still running. Run
``terp ports assign`` and ``terp env init`` first, as the README says.

``--rebuilds`` holds the development loop's dependency change against a running stack
(run it after ``--workbench``): under ``docker compose watch --no-up``, given the services
on the backend image, it changes the backend's lock and waits for every long-running
backend service to come back on the rebuilt image, ``migrate`` run first, in one rebuild.
The lock is put back afterwards.

The HTTP half needs only the standard library. It exits non-zero naming the first step that
did not happen within ``--timeout`` seconds; nothing is skipped, because a skipped check is
a green one.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import signal
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections.abc import Callable
from typing import Any

#: The seeded development login (app/seed.py): known, printed and shared by design, and
#: refused by `terp seed` in production.
SEED_EMAIL = "admin@example.test"
SEED_PASSWORD = "correct horse battery staple"  # noqa: S105 - the published dev seed login

#: The long-running services of the development stack: the template's API, and the four the
#: reference app adds. `web` is not needed to drive the backend and is left out.
WORKBENCH_SERVICES = ("api", "worker", "scheduler", "monitor", "mailcatcher")

#: What the scheduler's log names once its cron is registered, and what the companion's
#: says once it has read the backlog.
SCHEDULE_NAME = "notices.snapshot.hourly"
MONITOR_LINE = "outbox:"

#: The long-running services on the backend image: what a backend rebuild must bring back.
BACKEND_SERVICES = ("api", "worker", "scheduler", "monitor")

#: Every service on the backend image, the two one-shots included: what `--rebuilds` hands
#: `watch`. Not the whole project, because a rebuild converges every service `watch` was
#: given, and `web` has neither a container nor an image in a lane that cannot build the
#: frontend: creating it fails the convergence ("Failed to recreate services after
#: update"), and `watch` then starts nothing, so every service it had already recreated
#: stays stopped. A developer's `terp docker dev` brings every service up first, so its
#: rebuilds never meet a service without an image; this check would, and it holds the
#: backend's rebuild, not the frontend's buildability.
ON_BACKEND_IMAGE = ("migrate", "seed", *BACKEND_SERVICES)

#: Seconds `watch` is left alone after a rebuild has settled, so a second rebuild it was
#: going to fire for the same change has time to show in its output.
REBUILD_QUIET_SECONDS = 15


class StackCheckFailed(RuntimeError):
    """One step of the check did not happen."""


def _request(
    method: str,
    url: str,
    *,
    body: object | None = None,
    token: str | None = None,
) -> tuple[int, bytes]:
    headers = {"Accept": "application/json"}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    # S310 asks that a URL never reach a `file:` or custom scheme; the check is made here,
    # explicitly, so the two opt-outs below are about a URL already known to be http(s).
    if urllib.parse.urlsplit(url).scheme not in ("http", "https"):
        raise StackCheckFailed(f"not an http(s) address: {url}")
    request = urllib.request.Request(url, data=data, headers=headers, method=method)  # noqa: S310 - scheme checked above
    try:
        with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310 - scheme checked above
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


def _json(method: str, url: str, *, expect: int, **kwargs: Any) -> Any:
    status, payload = _request(method, url, **kwargs)
    if status != expect:
        raise StackCheckFailed(f"{method} {url} answered {status}, not {expect}: {payload[:300]!r}")
    return json.loads(payload)


def _wait_for(what: str, probe: Callable[[], Any], *, timeout: float, every: float = 2.0) -> Any:
    deadline = time.monotonic() + timeout
    while True:
        found = probe()
        if found:
            return found
        if time.monotonic() > deadline:
            raise StackCheckFailed(f"{what} did not happen within {timeout:.0f}s")
        time.sleep(every)


def check(api: str, mailpit: str, *, timeout: float = 90.0) -> list[str]:
    """Run every HTTP step against *api* and *mailpit*; return what was proven."""
    api, mailpit = api.rstrip("/"), mailpit.rstrip("/")
    proven: list[str] = []

    login = _json(
        "POST",
        f"{api}/api/v1/auth/login",
        body={"email": SEED_EMAIL, "password": SEED_PASSWORD},
        expect=200,
    )
    token = login["access_token"]
    proven.append("signed in as the seeded administrator")

    subject = f"Reference stack check {uuid.uuid4().hex[:12]}"
    _json(
        "POST",
        f"{api}/api/v1/notices/",
        body={
            "title": subject,
            "body": "Sent by scripts/check_stack.py.",
            "recipient": "stack-check@reference.example",
        },
        token=token,
        expect=201,
    )

    def _caught() -> bool:
        listing = _json("GET", f"{mailpit}/api/v1/messages?limit=200", expect=200)
        return any(message.get("Subject") == subject for message in listing.get("messages", []))

    _wait_for("the notice's mail reaching the catcher", _caught, timeout=timeout)
    proven.append("a posted notice was mailed by the worker through the relay")

    before = _json("GET", f"{api}/api/v1/notices/snapshots/", token=token, expect=200)["total"]
    _json("POST", f"{api}/api/v1/notices/snapshots/", token=token, expect=202)

    def _stored() -> dict[str, Any] | None:
        page = _json("GET", f"{api}/api/v1/notices/snapshots/?limit=100", token=token, expect=200)
        if page["total"] <= before:
            return None
        return max(page["items"], key=lambda item: item["created_at"])

    snapshot = _wait_for("the requested snapshot being stored", _stored, timeout=timeout)
    if snapshot["status_code"] != 200 or not snapshot["file_id"]:
        raise StackCheckFailed(f"the snapshot came back without a stored 200: {snapshot}")
    proven.append(f"the worker fetched {snapshot['url']} through the egress policy")

    status, content = _request("GET", f"{api}/api/v1/files/{snapshot['file_id']}/content", token=token)
    if status != 200 or len(content) != snapshot["size"]:
        raise StackCheckFailed(
            f"the stored snapshot read back {status} with {len(content)} bytes, "
            f"not 200 with {snapshot['size']}"
        )
    proven.append(f"its {snapshot['size']} bytes read back from file storage")
    return proven


def _compose(*args: str, capture: bool = False) -> str:
    """Run one `docker compose` command for this checkout; fail the check if it fails."""
    # A fixed argv and no shell: every argument is one of this script's own constants.
    completed = subprocess.run(  # noqa: S603 - see above
        ["docker", "compose", *args],  # noqa: S607 - docker is found on PATH, as a person runs it
        check=False,
        capture_output=capture,
        text=True,
    )
    if completed.returncode != 0:
        raise StackCheckFailed(f"`docker compose {' '.join(args)}` exited {completed.returncode}")
    return completed.stdout or ""


def _api_port(root: pathlib.Path) -> str:
    """The host port `terp ports assign` claimed for this checkout's API, read from ``.env``."""
    env = root / ".env"
    lines = env.read_text(encoding="utf-8").splitlines() if env.is_file() else []
    for line in lines:
        name, _, value = line.partition("=")
        if name.strip() == "API_PORT" and value.strip():
            return value.strip().strip('"')
    raise StackCheckFailed("no API_PORT in .env: run `uv run terp ports assign` first")


def check_workbench(root: pathlib.Path, *, timeout: float) -> list[str]:
    """Start this checkout's development stack, drive it, and hold its background processes."""
    # Bounded: a service that never turns healthy fails the check rather than holding it.
    _compose("up", "-d", "--wait", "--wait-timeout", "600", "--build", *WORKBENCH_SERVICES)
    _compose("run", "--rm", "seed")
    api = f"http://127.0.0.1:{_api_port(root)}"
    mailpit = f"http://{_compose('port', 'mailcatcher', '8025', capture=True).strip()}"
    proven = check(api, mailpit, timeout=timeout)

    def _logged(service: str, needle: str) -> Callable[[], bool]:
        return lambda: needle in _compose("logs", service, capture=True)

    _wait_for("the scheduler registering its cron", _logged("scheduler", SCHEDULE_NAME), timeout=timeout)
    proven.append(f"the scheduler registered {SCHEDULE_NAME}")
    _wait_for("the companion reading the backlog", _logged("monitor", MONITOR_LINE), timeout=timeout)
    proven.append("the monitor companion read the outbox backlog")
    running = set(_compose("ps", "--status", "running", "--services", capture=True).split())
    stopped = sorted(set(WORKBENCH_SERVICES) - running)
    if stopped:
        raise StackCheckFailed(f"no longer running: {', '.join(stopped)}")
    proven.append(f"still running: {', '.join(WORKBENCH_SERVICES)}")
    return proven


def _containers() -> dict[str, dict[str, Any]]:
    """Service -> what its container runs: id, image, state and exit code.

    Read while a rebuild may be recreating the stack, so neither half may fail the check:
    `ps` can refuse in the middle of a rename, and a container listed a moment ago can be
    gone, in which case `inspect` fails on it and still prints the others. What could not
    be read is simply not there yet; the caller waits for what it needs.
    """
    listing = subprocess.run(  # noqa: S603 - a fixed argv
        ["docker", "compose", "ps", "--all", "--quiet"],  # noqa: S607 - docker is found on PATH
        check=False,
        capture_output=True,
        text=True,
    )
    listed = listing.stdout.split() if listing.returncode == 0 else []
    if not listed:
        return {}
    completed = subprocess.run(  # noqa: S603 - fixed argv; the ids come from compose itself
        ["docker", "inspect", *listed],  # noqa: S607 - docker is found on PATH, as a person runs it
        check=False,
        capture_output=True,
        text=True,
    )
    try:
        entries = json.loads(completed.stdout or "[]")
    except json.JSONDecodeError:
        return {}
    found: dict[str, dict[str, Any]] = {}
    for entry in entries:
        service = entry["Config"]["Labels"].get("com.docker.compose.service")
        found[service] = {
            "id": entry["Id"],
            "image": entry["Image"],
            "status": entry["State"]["Status"],
            "exit": entry["State"]["ExitCode"],
        }
    return found


def _start_watch(log: pathlib.Path) -> subprocess.Popen[bytes]:
    """`docker compose watch --no-up` over :data:`ON_BACKEND_IMAGE`, in a process group of its
    own, its output into *log*."""
    if os.name == "nt":
        group: dict[str, Any] = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    else:
        group = {"start_new_session": True}
    with log.open("wb") as sink:
        return subprocess.Popen(  # noqa: S603 - a fixed argv
            ["docker", "compose", "watch", "--no-up", *ON_BACKEND_IMAGE],  # noqa: S607 - docker on PATH
            stdout=sink,
            stderr=subprocess.STDOUT,
            **group,
        )


def _what_happened(log: pathlib.Path) -> str:
    """What a failed rebuild left behind: each service's container, and what `watch` said.

    A lane's log keeps nothing else: `watch` writes into a temporary file, and a container
    that was recreated and never started has no log of its own to show.
    """
    states = ", ".join(
        f"{name}={found['status']}({found['image'].removeprefix('sha256:')[:12]})"
        for name, found in sorted(_containers().items())
    )
    said = [
        line
        for line in log.read_text(encoding="utf-8", errors="replace").splitlines()
        if line.strip() and not line.startswith("#")
    ]
    return f"\n  containers: {states}\n  watch said, last lines:\n    " + "\n    ".join(said[-15:])


def _stop_watch(process: subprocess.Popen[bytes]) -> None:
    """End `watch` and the compose plugin beneath it: the docker CLI runs it as a second process."""
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(  # noqa: S603 - a fixed argv
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],  # noqa: S607 - a system tool
            check=False,
            capture_output=True,
        )
    else:
        os.killpg(process.pid, signal.SIGINT)
    try:
        process.wait(timeout=30)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def _rebuilds(log: pathlib.Path) -> int:
    """How many rebuilds `watch` has begun, by its own log line."""
    return log.read_text(encoding="utf-8", errors="replace").count("Rebuilding service(s)")


def check_rebuilds(root: pathlib.Path, *, timeout: float) -> list[str]:
    """A dependency change under `watch`: every service on the rebuilt image comes back, once.

    Built from `api`, a backend rebuild recreated the worker, the scheduler, the companion
    and both one-shots on the new image and started none of them, and one `uv add` fired
    two rebuilds. This holds the fix against the compose that runs here. The frontend's
    rebuild is not driven, and `watch` is given only the services on the backend image
    (:data:`ON_BACKEND_IMAGE`): a lane that installs unreleased `@terpjs` packages from
    outside the build context cannot build the frontend image at all. On a failure the
    message carries each container's state and what `watch` said.
    """
    proven: list[str] = []
    before = _containers()
    missing = [name for name in BACKEND_SERVICES if before.get(name, {}).get("status") != "running"]
    if missing:
        raise StackCheckFailed(f"start the stack first (--workbench); not running: {missing}")
    lock = root / "uv.lock"
    original = lock.read_bytes()
    log = pathlib.Path(tempfile.mkdtemp(prefix="check-stack-")) / "watch.log"
    process = _start_watch(log)
    try:
        _wait_for(
            "watch starting",
            lambda: "Watch enabled" in log.read_text(encoding="utf-8", errors="replace"),
            timeout=timeout,
        )
        # A trailing newline: the same lock to every reader, and a changed file to watch.
        lock.write_bytes(original + b"\n")

        def backend_back() -> dict[str, dict[str, Any]] | None:
            now = _containers()
            image = now.get("api", {}).get("image")
            on_new = all(
                now.get(name, {}).get("image") == image and now[name]["status"] == "running"
                for name in BACKEND_SERVICES
            )
            migrated = now.get("migrate", {})
            ran = (
                migrated.get("id") != before.get("migrate", {}).get("id")
                and migrated.get("status") == "exited"
            )
            return now if image != before["api"]["image"] and on_new and ran else None

        try:
            rebuilt = _wait_for(
                "every backend service back on the rebuilt image", backend_back, timeout=timeout
            )
            if rebuilt["migrate"]["exit"] != 0:
                raise StackCheckFailed(f"migrate exited {rebuilt['migrate']['exit']} after the rebuild")
            time.sleep(REBUILD_QUIET_SECONDS)
            if (count := _rebuilds(log)) != 1:
                raise StackCheckFailed(f"one change to uv.lock fired {count} rebuilds")
        except StackCheckFailed as failure:
            raise StackCheckFailed(f"{failure}{_what_happened(log)}") from failure
        proven.append(
            f"a backend rebuild brought {', '.join(BACKEND_SERVICES)} back on the new image, "
            "migrate first, in one rebuild"
        )
    finally:
        _stop_watch(process)
        lock.write_bytes(original)
    return proven


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument(
        "--workbench",
        action="store_true",
        help="Start this checkout's development stack and check all of it",
    )
    target.add_argument(
        "--rebuilds",
        action="store_true",
        help="Against the running development stack, hold what a dependency change rebuilds",
    )
    target.add_argument("--api", help="Where a running deployment's API answers")
    parser.add_argument("--mailpit", help="Where the relay's inbox answers (with --api)")
    parser.add_argument("--timeout", type=float, default=90.0, help="Seconds per step (default: 90)")
    args = parser.parse_args(argv)
    if args.api and not args.mailpit:
        parser.error("--api needs --mailpit: the mail step is never skipped")
    try:
        if args.workbench:
            proven = check_workbench(pathlib.Path.cwd(), timeout=args.timeout)
        elif args.rebuilds:
            proven = check_rebuilds(pathlib.Path.cwd(), timeout=args.timeout)
        else:
            proven = check(args.api, args.mailpit, timeout=args.timeout)
    except StackCheckFailed as failure:
        print(f"stack check FAILED: {failure}", file=sys.stderr)
        return 1
    for line in proven:
        print(f"ok  {line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
