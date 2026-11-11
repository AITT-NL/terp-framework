"""Template acceptance's production boot: the rendered app, built and asked, in production mode.

Every deploy of a Terp app runs it with ``ENVIRONMENT=production``, and production refuses
things the development loop only warns about. Nothing in template acceptance ran a rendered
app that way, so a template whose composition root a production boot refuses went out green:
the single sign-on wiring built ``FederatedIdentityService(allow_provisioning=True)`` with
no allowlist, which raises under production at import, whether or not SSO was configured.

This runs, from the rendered app's own environment (so exactly the capabilities it
installs are discovered):

1. ``terp migrate upgrade`` against a scratch PostgreSQL database, because the template's
   production migration guard refuses a database that is behind the code, and production
   refuses SQLite;
2. each boot case in a fresh interpreter, with ``ENVIRONMENT=production`` and a generated
   ``SECRET_KEY``: ``app.main`` is imported, which builds the app, the ASGI lifespan is
   started, and ``/health/ready`` must answer 200.

The cases: SSO not configured, which every render must boot. An app whose recorded answers
say ``use_sso: true`` mounts its SSO routes in that boot too, because the modules an app
mounts do not depend on a setting (ADR 0211), and the route must then refuse by name as not
configured. It boots twice more: SSO configured with ``OIDC_ALLOWED_EMAIL_DOMAINS``, which
boots with the same routes mounted; and SSO configured without it, which must be refused,
in the federated-identity service's own words.

A render that holds its ``authz-surface.json`` must also say, in each boot that succeeds,
that it compared the routes it serves with that record (ADR 0212). A boot that passed
without the comparison would otherwise read here exactly like one that passed it.

Usage, from the rendered app::

    uv run python <framework>/tools/production_boot.py --database-url postgresql+psycopg://...

The database must be empty: the boot is a first deploy. Credential-shaped values (the
SECRET_KEY, the OIDC client secret) are generated per run and never printed.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import secrets
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

#: What the child interpreter runs: build the app by importing it, start its lifespan, ask
#: for readiness, say which of the routes this tool asks about are mounted, and ask each path
#: given as an argument, reporting its status and the code of its error envelope. Stdlib
#: only, so it needs nothing the rendered app does not install.
PROBE = r"""
import asyncio
import json
import sys

from app.main import app


async def _lifespan(app, inbox, outbox):
    await app({"type": "lifespan", "asgi": {"version": "3.0"}}, inbox.get, outbox.put)


async def _get(path):
    sent = []
    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
        "method": "GET", "scheme": "http", "path": path, "raw_path": path.encode(),
        "root_path": "", "query_string": b"", "headers": [(b"host", b"localhost")],
        "client": ("127.0.0.1", 50000), "server": ("localhost", 80),
    }

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    await app(scope, receive, send)
    status = next(m["status"] for m in sent if m["type"] == "http.response.start")
    body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    return status, body


def _code(body):
    try:
        answer = json.loads(body)
    except ValueError:
        return None
    return answer.get("code") if isinstance(answer, dict) else None


async def main():
    inbox, outbox = asyncio.Queue(), asyncio.Queue()
    await inbox.put({"type": "lifespan.startup"})
    task = asyncio.create_task(_lifespan(app, inbox, outbox))
    started = await outbox.get()
    if started["type"] != "lifespan.startup.complete":
        raise SystemExit(f"lifespan startup failed: {started}")
    ready, _ = await _get("/health/ready")
    asked = {}
    for path in sys.argv[1:]:
        status, body = await _get(path)
        asked[path] = [status, _code(body)]
    await inbox.put({"type": "lifespan.shutdown"})
    await outbox.get()
    await task
    paths = sorted(app.openapi()["paths"])
    print(json.dumps({"ready": ready, "paths": paths, "asked": asked}))


asyncio.run(main())
"""

#: The route the SSO module mounts for the provider the template names ``sso``.
SSO_ROUTE = "/api/v1/oidc/{provider}/authorize"

#: That route as a client asks it, and what it must answer while no provider is configured:
#: the status and the code of ``SsoNotConfiguredError`` (terp.capabilities.oidc, ADR 0211).
SSO_ASKED = "/api/v1/oidc/sso/authorize"
SSO_NOT_CONFIGURED = [503, "sso_not_configured"]

#: The refusal FederatedIdentityService raises in production for provisioning with no
#: allowlist (terp.capabilities.identity.federated).
ALLOWLIST_REFUSAL = "requires an identity allowlist in production"

#: The record of who can reach what, and what a production boot logs once it has compared
#: the routes it serves with it and found no difference (terp.core.authz_surface, ADR 0212).
RECORD = "authz-surface.json"
COMPARED = "authz-surface.json matches the routes this app serves"

#: The answers file copier records a render's answers in; ``use_sso`` is one of them.
ANSWERS = ".copier-answers.yml"

Runner = Callable[..., subprocess.CompletedProcess[str]]


class BootError(RuntimeError):
    """A case did not boot, or did not refuse, the way it must; the message says which."""


@dataclass(frozen=True)
class Case:
    """One production boot: its name, the environment it adds, and what must happen."""

    name: str
    env: dict[str, str] = field(default_factory=dict)
    sso_mounted: bool = False
    #: The mounted routes must refuse as not configured: no provider is set in this boot.
    sso_refuses: bool = False
    refused_with: str | None = None


def cases(*, sso: bool, secret: Callable[[], str] = secrets.token_urlsafe) -> list[Case]:
    """The boot cases for an app rendered with or without single sign-on."""
    if not sso:
        return [Case("SSO not configured")]
    # The same routes in every boot of a render with SSO (ADR 0211): with no provider set
    # they are mounted and refuse, so the access check sees one app wherever it runs.
    off = Case("SSO not configured", sso_mounted=True, sso_refuses=True)
    oidc = {
        # Never contacted: discovery is fetched on the first sign-in, not at boot.
        "OIDC_ISSUER": "https://idp.example.test",
        "OIDC_CLIENT_ID": "terp-production-boot",
        "OIDC_CLIENT_SECRET": secret(),
        "OIDC_REDIRECT_URI": "https://app.example.test/auth/sso/callback",
    }
    return [
        off,
        Case(
            "SSO configured with OIDC_ALLOWED_EMAIL_DOMAINS",
            {**oidc, "OIDC_ALLOWED_EMAIL_DOMAINS": "example.test,example.org"},
            sso_mounted=True,
        ),
        Case("SSO configured without an allowlist", oidc, refused_with=ALLOWLIST_REFUSAL),
    ]


def rendered_with_sso(root: pathlib.Path) -> bool:
    """Whether the app's recorded answers say it was rendered with single sign-on."""
    answers = root / ANSWERS
    if not answers.is_file():
        raise BootError(f"no {ANSWERS} in {root}: this boots a render of the template")
    return any(
        line.strip() == "use_sso: true"
        for line in answers.read_text(encoding="utf-8").splitlines()
    )


def production_env(database_url: str, case: Case, base: dict[str, str]) -> dict[str, str]:
    """The environment a case boots in: production, a generated key, the scratch database."""
    inherited = {
        key: value
        for key, value in base.items()
        if not key.startswith("OIDC_") and key not in ("ENVIRONMENT", "SECRET_KEY")
    }
    return {
        **inherited,
        "ENVIRONMENT": "production",
        "SECRET_KEY": secrets.token_hex(32),
        "DATABASE_URL": database_url,
        **case.env,
    }


def migrate(root: pathlib.Path, database_url: str, run: Runner, python: str) -> None:
    """Bring the scratch database to every head, as the profile's one-shot does."""
    env = production_env(database_url, Case("migrate"), dict(os.environ))
    argv = [
        python, "-c", "import sys; from terp.cli import main; main(sys.argv[1:])",
        "migrate", "upgrade", "--app-root", str(root / "app"),
    ]
    done = run(argv, cwd=root, env=env, capture_output=True, text=True, check=False)
    if done.returncode != 0:
        raise BootError(
            f"terp migrate upgrade exited {done.returncode}:\n{done.stdout}{done.stderr}"
        )


def boot(
    root: pathlib.Path, database_url: str, case: Case, run: Runner, python: str
) -> str:
    """Boot *case* in a fresh interpreter and hold it to what it must do."""
    env = production_env(database_url, case, dict(os.environ))
    asked = [SSO_ASKED] if case.sso_refuses else []
    done = run(
        [python, "-c", PROBE, *asked],
        cwd=root, env=env, capture_output=True, text=True, check=False,
    )
    output = f"{done.stdout}{done.stderr}"
    if case.refused_with is not None:
        if done.returncode == 0:
            raise BootError(f"{case.name}: booted in production, where it must be refused")
        if case.refused_with not in output:
            raise BootError(
                f"{case.name}: refused, but not with {case.refused_with!r}:\n{output}"
            )
        return f"{case.name}: refused in production, by name"
    if done.returncode != 0:
        raise BootError(f"{case.name}: the production boot failed:\n{output}")
    report = json.loads(done.stdout.strip().splitlines()[-1])
    if report["ready"] != 200:
        raise BootError(f"{case.name}: /health/ready answered {report['ready']}, not 200")
    if (root / RECORD).is_file() and COMPARED not in output:
        raise BootError(
            f"{case.name}: booted with {RECORD} beside it and did not say it compared the "
            "routes it serves with that record. The app holds itself to the record when it "
            f"starts (ADR 0212), and says so: {COMPARED!r}"
        )
    mounted = SSO_ROUTE in report["paths"]
    if mounted != case.sso_mounted:
        state = "mounted" if mounted else "not mounted"
        raise BootError(f"{case.name}: the SSO routes are {state}")
    if not case.sso_refuses:
        return f"{case.name}: boots in production, ready" + (", SSO mounted" if mounted else "")
    answered = report.get("asked", {}).get(SSO_ASKED)
    if answered != SSO_NOT_CONFIGURED:
        status, code = SSO_NOT_CONFIGURED
        raise BootError(
            f"{case.name}: {SSO_ASKED} answered {answered}, not {status} {code}. A route "
            "mounted while single sign-on is not configured must refuse by that name: build "
            "the module with allow_no_provider=True"
        )
    return f"{case.name}: boots in production, ready, SSO mounted and refusing by name"


def main(argv: Sequence[str] | None = None, *, run: Runner = subprocess.run) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--database-url", required=True, help="An empty PostgreSQL database")
    parser.add_argument("--root", type=pathlib.Path, default=pathlib.Path.cwd())
    args = parser.parse_args(argv)
    root = args.root.resolve()
    try:
        sso = rendered_with_sso(root)
        migrate(root, args.database_url, run, sys.executable)
        done = [
            boot(root, args.database_url, case, run, sys.executable)
            for case in cases(sso=sso)
        ]
    except BootError as exc:
        print(f"production_boot: {exc}", file=sys.stderr)
        return 1
    for line in done:
        print(f"ok  {line}")
    return 0


if __name__ == "__main__":  # pragma: no cover - entry point
    raise SystemExit(main())
