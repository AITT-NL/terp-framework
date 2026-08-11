"""The adoptable-capability registry behind ``terp inspect capabilities``.

The gate tells an author what they may **not** do; nothing told them what the platform
already **offers**. An app that needs run progress hand-rolls polling, an app that needs
durable delivery fires a post-commit callback and hopes — not because the author was
careless, but because ``terp-cap-realtime`` and ``terp-cap-outbox`` were invisible from
inside the project. Discoverability is a platform responsibility, so it ships as a
command: one screen listing every capability, whether this app has it, the exact
``uv add`` line, and the composition-root shape it expects.

The registry is static (it must describe capabilities that are *not* installed), so it
is pinned against the real packages by ``tests/architecture/test_cli_capabilities.py``:
every capability directory appears here exactly once, and ``kind`` agrees with whether
the package declares a ``terp.capabilities`` router entry point.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from importlib import metadata


@dataclass(frozen=True)
class Capability:
    """One adoptable ``terp-cap-*`` package, as an author needs to see it."""

    name: str
    """Package suffix, e.g. ``realtime`` (dist ``terp-cap-realtime``)."""

    summary: str
    """One line: what it gives you, in problem terms."""

    kind: str
    """``routed`` (discovery mounts a router) or ``library`` (you wire it yourself)."""

    wiring: str
    """The composition-root shape, copy-pasteable."""

    guide: str | None = None
    """``terp guide`` topic covering it, when one exists."""

    @property
    def distribution(self) -> str:
        """The PyPI distribution name."""
        return "terp-cap-" + self.name.replace("_", "-")

    @property
    def module(self) -> str:
        """The import path."""
        return "terp.capabilities." + self.name


CAPABILITIES: tuple[Capability, ...] = (
    Capability(
        name="access",
        summary="RBAC permission grants + a fail-closed require_permission dependency.",
        kind="routed",
        wiring="create_app(..., discover_capabilities=True)",
        guide="access",
    ),
    Capability(
        name="audit",
        summary="Durable append-only sink for the core audit seam (who changed what).",
        kind="routed",
        wiring="create_app(..., audit_sink=persist_audit)",
    ),
    Capability(
        name="auth",
        summary="Argon2 password hashing, JWT access tokens, the get_principal seam.",
        kind="library",
        wiring="mount the login router in app/auth.py",
        guide="passwords",
    ),
    Capability(
        name="eventbus",
        summary="In-process dispatcher for the core event seam — react without coupling.",
        kind="library",
        wiring="create_app(..., event_dispatcher=dispatch_in_process)",
        guide="events",
    ),
    Capability(
        name="files",
        summary="Owner-scoped file objects: metadata in the DB, bytes behind a storage port.",
        kind="routed",
        wiring="create_app(..., discover_capabilities=True)",
        guide="files",
    ),
    Capability(
        name="groups",
        summary="Admin-managed user groups that bundle access-grant permissions.",
        kind="routed",
        wiring="create_app(..., discover_capabilities=True)",
        guide="access",
    ),
    Capability(
        name="identity",
        summary="Persisted user store backing authentication.",
        kind="library",
        wiring="create_app(..., discover_capabilities=True)",
    ),
    Capability(
        name="jobs_celery",
        summary="Run catalog jobs on a Celery broker, with zero domain change.",
        kind="library",
        wiring="create_app(..., job_queue=CeleryJobQueue(...))",
        guide="jobs",
    ),
    Capability(
        name="oidc",
        summary="Single sign-on via the OpenID Connect code flow with PKCE.",
        kind="library",
        wiring="build_oidc_module(...) in app/auth.py, mounted when OIDC_* is set",
    ),
    Capability(
        name="outbox",
        summary="Transactional, leased, retrying post-commit delivery for jobs and events.",
        kind="library",
        wiring=(
            "create_app(..., job_queue=OutboxJobQueue(), "
            "event_dispatcher=outbox_event_dispatcher)"
        ),
        guide="outbox",
    ),
    Capability(
        name="realtime",
        summary="Typed, policy-gated SSE/WebSocket channels with one-use connection tickets.",
        kind="routed",
        wiring="create_app(..., discover_capabilities=True) + configure_realtime(...)",
        guide="realtime",
    ),
    Capability(
        name="redis",
        summary="Shared idempotency / throttling / cache state for multi-replica deploys.",
        kind="library",
        wiring="create_app(..., idempotency_store=RedisIdempotencyStore(...))",
        guide="idempotency",
    ),
    Capability(
        name="scheduler_apscheduler",
        summary="Fire catalog schedules on their cron in-process, through the jobs seam.",
        kind="library",
        wiring="terp jobs scheduler",
        guide="jobs",
    ),
    Capability(
        name="scheduler_celery_beat",
        summary="Drive catalog schedules from Celery beat, through the jobs seam.",
        kind="library",
        wiring="celery beat against the generated schedule",
        guide="jobs",
    ),
    Capability(
        name="sync",
        summary="Reconcile a local entity against an external system on the jobs seam.",
        kind="library",
        wiring="declare a SyncSpec; run it through the jobs/scheduler seam",
        guide="jobs",
    ),
    Capability(
        name="tenancy",
        summary="Tenant isolation by construction (session-level filter + insert stamp).",
        kind="library",
        wiring="install_tenancy(...) at the composition root",
        guide="tenancy",
    ),
    Capability(
        name="users",
        summary="Admin user management over the identity store.",
        kind="routed",
        wiring="create_app(..., discover_capabilities=True)",
    ),
    Capability(
        name="webhooks",
        summary="Reliable, signed, SSRF-guarded outbound webhooks on the jobs/outbox seam.",
        kind="routed",
        wiring="create_app(..., discover_capabilities=True)",
    ),
)


def _installed_version(capability: Capability) -> str | None:
    """*capability*'s installed version, or ``None`` when it is not installed.

    One lookup answers both questions the report asks — whether the app has it,
    and which release — so the two can never disagree.
    """
    try:
        return metadata.distribution(capability.distribution).version
    except metadata.PackageNotFoundError:
        return None


def render_capabilities(*, fmt: str = "text") -> str:
    """Render every adoptable capability, marking the ones this app already has.

    Answers the question the gate never could: *what else is on the shelf?* Installed
    capabilities are listed first so the reader sees the current profile, then the
    adoptable ones with the exact ``uv add`` line and wiring shape — no package index
    search, no guessing at a name.

    Versions are shown, and the ``uv add`` line is **pinned**, because Terp releases in
    lockstep: an unpinned adopt resolves to whatever is newest, which is precisely how
    an app ends up with one package a release ahead of the rest. This surface was the
    natural place to notice that and said nothing.
    """
    from terp.cli.version import platform_version

    rows = [(cap, _installed_version(cap)) for cap in CAPABILITIES]
    pin = platform_version()
    if fmt == "json":
        return json.dumps(
            {
                "platform_version": pin,
                "capabilities": [
                    {
                        "name": cap.name,
                        "distribution": cap.distribution,
                        "module": cap.module,
                        "summary": cap.summary,
                        "kind": cap.kind,
                        "wiring": cap.wiring,
                        "guide": cap.guide,
                        "installed": version is not None,
                        "version": version,
                    }
                    for cap, version in rows
                ],
            },
            indent=2,
        )

    installed = [(cap, version) for cap, version in rows if version is not None]
    available = [cap for cap, version in rows if version is None]
    requirement = f"=={pin}" if pin else ""
    lines = [
        "Capabilities",
        "",
        "Opt-in packages the platform maintains. A `routed` capability mounts its own",
        "router when discovery is on; a `library` capability is imported and wired at",
        "the composition root. Adopting one is always: add the dependency, wire it, run",
        "`uv run terp migrate` if it ships tables.",
        "",
        "Terp releases in lockstep, so every terp-* package carries the same version",
        "and the `uv add` lines below are pinned to it. `terp --version` reports the",
        "whole set and names any package that has drifted out of step.",
        "",
        f"Installed in this app ({len(installed)})",
        "",
    ]
    for cap, version in installed:
        lines.append(f"  {cap.distribution:<32} {version:<10} {cap.kind}")
        lines.append(f"      {cap.summary}")
    if not installed:
        lines.append("  (none)")
    lines += ["", f"Available to adopt ({len(available)})", ""]
    for cap in available:
        lines.append(f"  {cap.distribution:<32} {'—':<10} {cap.kind}")
        lines.append(f"      {cap.summary}")
        lines.append(f"      uv add {cap.distribution}{requirement}")
        lines.append(f"      {cap.wiring}")
        if cap.guide is not None:
            lines.append(f"      uv run terp guide {cap.guide}")
    if not available:
        lines.append("  (none — every maintained capability is installed)")
    lines += [
        "",
        "Do not hand-roll what a capability owns. If you need something none of these",
        "covers, stop and report the missing capability rather than building a local",
        "substitute (`uv run terp guide capability`).",
    ]
    return "\n".join(lines)
