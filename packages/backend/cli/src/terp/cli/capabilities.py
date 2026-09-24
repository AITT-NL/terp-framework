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

import importlib
import inspect
import json
import pathlib
import re
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
        name="mfa",
        summary="A TOTP second factor with recovery codes, wired into login through the second_factor seam.",
        kind="library",
        wiring="build_login_module(..., second_factor=MfaService()) + specs=[mfa.module]",
        guide="passwords",
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
        name="egress",
        summary="The declared way out of the process — an allowlisted, SSRF-guarded, time-bounded HTTP client whose every attempt is observable.",
        kind="library",
        wiring="EgressClient(EgressPolicy(allowed_hosts=(...), timeout_seconds=...))",
        guide="capability",
    ),
    Capability(
        name="leases",
        summary="Fenced, expiring custody of work — and a reaper that recovers a dead worker's claim.",
        kind="library",
        wiring="create_app(..., lease_store=DatabaseLeaseStore()) + specs=[leases.module]",
        guide="leases",
    ),
    Capability(
        name="mail",
        summary="Send e-mail through one declared relay — encrypted, a fixed sender, delivered by the jobs seam so a send commits with its write.",
        kind="library",
        wiring="configure_mail(mail_settings_from_environment(os.environ)) + JobCatalog([MAIL_SEND])",
        guide="mail",
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


#: Names that are a WIRING POINT rather than a value: something a composition root
#: calls or constructs and hands to ``create_app``. The vocabulary is the platform's
#: own -- ``build_*`` makes a router or a module, ``register_*`` adds to a registry, and
#: the ``*Store`` / ``*Queue`` / ``*Scheduler`` / ``*Middleware`` / ``*Resolver`` suffixes
#: name the implementations a seam takes.
#:
#: Deliberately not "everything the package exports": that is 391 names across twenty
#: capabilities, most of them operation ids, error types and status literals, and a
#: report of 391 things is a report of nothing.
_WIRING_SEAM = re.compile(
    r"^(?:build_|register_|make_)"
    r"|(?:Store|Queue|Scheduler|Middleware|Resolver|Reaper|Sink)$"
)


def wiring_seams(capability: Capability) -> tuple[str, ...]:
    """Every wiring point an INSTALLED capability exports, from its own ``__all__``.

    Computed rather than curated, and that is the point: a hand-written seam list is a
    second place to forget, and forgetting is the whole failure here. A capability that
    grows a seam after an app adopted it gets it listed on the next run, with no edit
    anywhere.

    Empty for a capability that is not installed -- reading its surface needs the import.
    """
    try:
        module = importlib.import_module(capability.module)
    except Exception:  # noqa: BLE001 - a broken optional import is "no seams to report"
        return ()
    found = []
    for name in getattr(module, "__all__", ()):
        if not _WIRING_SEAM.search(name):
            continue
        member = getattr(module, name, None)
        if inspect.isfunction(member) or inspect.isclass(member):
            found.append(name)
    return tuple(sorted(found))


#: Directories whose contents are not this app's source. Deliberately the harness's own
#: list rather than a shorter one written here: an app whose virtualenv is called `venv`
#: instead of `.venv` would otherwise have all of site-packages read into the blob, where
#: every seam name appears and the report goes silently empty.
_SKIP_DIRS = frozenset(
    {
        "__pycache__",
        ".venv",
        "venv",
        "env",
        ".tox",
        "site-packages",
        "node_modules",
        "build",
        "dist",
        ".git",
    }
)


def app_sources(root: pathlib.Path | str) -> str:
    """Every Python source under *root*, concatenated once.

    Built once per run and passed down rather than rebuilt per capability. The per-
    capability version walked the tree and re-read every file for each of ~19 installed
    capabilities -- 2.75s and 505 files read nineteen times on this repository -- for a
    blob that cannot change between them.

    `rglob` yields directories and dangling symlinks that match the glob too, so the
    `is_file()` guard is not defensive noise: a directory named `generated.py/` would
    otherwise take the whole command down with `IsADirectoryError`, and this command is
    explicitly information rather than a finding.
    """
    parts = []
    for path in sorted(pathlib.Path(root).rglob("*.py")):
        if any(part in _SKIP_DIRS for part in path.parts) or not path.is_file():
            continue
        try:
            parts.append(path.read_text(encoding="utf-8", errors="ignore"))
        except OSError:
            continue
    return "\n".join(parts)


def unwired_seams(
    capability: Capability,
    root: pathlib.Path | str,
    *,
    seams: tuple[str, ...] | None = None,
    sources: str | None = None,
) -> tuple[str, ...]:
    """The installed capability's wiring points this app's source never mentions.

    The question a consumer cannot currently ask. The registry answers "do I have this
    capability", and an installed-and-mounted capability looks finished at that
    granularity -- so a seam the package grows later is invisible from inside the
    project forever. `POST /custody/{kind}/{key}/heartbeat` shipped in 0.11.0 and an app
    on 0.24.0 still stated in four places that it did not exist. Thirteen releases, a
    6,842-line changelog, and no consumer reads the delta.

    A name match over the app's own sources, deliberately: it is cheap, it has no false
    negatives that matter (referencing a seam without writing its name is not a thing),
    and a false positive costs a reader one glance. Reporting nothing is the failure
    mode worth avoiding here, not reporting one thing twice.

    *seams* and *sources* let a caller reporting on many capabilities compute each once;
    both default to doing it here, so a single call still works on its own.
    """
    seams = wiring_seams(capability) if seams is None else seams
    if not seams:
        return ()
    blob = app_sources(root) if sources is None else sources
    return tuple(
        seam for seam in seams if not re.search(rf"\b{re.escape(seam)}\b", blob)
    )


def render_capabilities(*, fmt: str = "text", root: str | pathlib.Path = ".") -> str:
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
    # Only for what is installed: an unadopted capability's unused seams are the whole
    # package, which is what the "available to adopt" section already says.
    #
    # The source blob and each capability's seam tuple are computed ONCE and shared: the
    # text cannot change between capabilities, and both halves of the JSON manifest below
    # are then the same traversal rather than two that could drift.
    installed_names = [cap.name for cap, version in rows if version is not None]
    sources = app_sources(root) if installed_names else ""
    seams = {
        cap.name: wiring_seams(cap) for cap, version in rows if version is not None
    }
    unwired = {
        cap.name: unwired_seams(cap, root, seams=seams[cap.name], sources=sources)
        for cap, version in rows
        if version is not None
    }
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
                        "seams": list(seams.get(cap.name, ())),
                        "unwired_seams": list(unwired.get(cap.name, ())),
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
        "  `not used here` names wiring points the package exports and this app's",
        "  source never mentions. It is information, not a finding: most of them are",
        "  alternatives you correctly did not take. It exists because an installed",
        "  capability looks finished, so a seam it grows afterwards is invisible from",
        "  inside the project -- which is how a liveness endpoint shipped, and an app",
        "  went on stating in its own source that there was none.",
        "",
    ]
    for cap, version in installed:
        lines.append(f"  {cap.distribution:<32} {version:<10} {cap.kind}")
        lines.append(f"      {cap.summary}")
        missing = unwired.get(cap.name, ())
        if missing:
            lines.append(f"      not used here: {', '.join(missing)}")
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
