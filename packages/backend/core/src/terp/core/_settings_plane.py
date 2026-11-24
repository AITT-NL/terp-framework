"""What the settings object contributes to a control plane, resolved before any boot check.

A control plane is source, built once and run in several environments. Three of its values
are facts of an environment and not of the source: the service principal a declared job's
writes are stamped with (ADR 0129), the browser origins that may call the API (ADR 0210),
and the proxy hop a deploy tool's edge puts in front of it (ADR 0220). The app declares
that it takes the first two from its environment; the third is the deploy tool's alone.
``create_app`` resolves them here, before it reads a single production refusal: resolving
afterwards would refuse a boot over a value the process already had.
"""

from __future__ import annotations

import dataclasses
import logging

from terp.core.config import get_settings
from terp.core.control_plane import ControlPlane

_logger = logging.getLogger("terp.core")


def _with_job_actor(plane: ControlPlane) -> ControlPlane:
    """Fill an unset ``job_system_actor_id`` from ``JOB_SYSTEM_ACTOR_ID`` (ADR 0129).

    ADR 0125 established that a declared job must name the actor its writes are
    stamped with, and refused a platform-wide sentinel: an FK-less constant would
    store fine and resolve to no principal anywhere, which is the same defect wearing
    a value. That reasoning is about the *default*, and it left the *delivery* to every
    app — so each one that declared a job hand-rolled the same env read, UUID parse and
    error path for a fact that is not a source constant at all. The id belongs to a
    service principal in a particular database, and one image runs against several.

    So the settings object carries the conventional address and this is where it lands.
    An explicit ``ControlPlane(job_system_actor_id=...)`` still wins, because an app
    that resolves the principal some other way must keep saying so. Unset in both
    places is unchanged from before: ``production_problems`` reports it and production
    refuses the boot.

    Runs before that refusal is read, which is the whole point — resolving afterwards
    would refuse a boot over a value the process already had.
    """
    if plane.job_system_actor_id is not None:
        return plane
    from_settings = get_settings().JOB_SYSTEM_ACTOR_ID
    if from_settings is None:
        return plane
    return dataclasses.replace(plane, job_system_actor_id=from_settings)


def _with_environment_cors(plane: ControlPlane) -> tuple[ControlPlane, str | None]:
    """Fill a ``CorsPolicy.from_environment()`` allowlist from ``BACKEND_CORS_ORIGINS``.

    The variable used to open nothing: it was read only to refuse ``*``, while the
    allowlist came from ``CorsPolicy.allow([...])`` in source, so an origin an operator or
    a deploy tool wrote there was refused by the browser with nothing in any log. A plane
    that declares it reads its origins from the environment now does. One that declares
    them another way still ignores the variable, and says so once at boot when it is set,
    because a setting that silently does nothing is how that went unnoticed.
    """
    cors = plane.security.cors
    named = get_settings().BACKEND_CORS_ORIGINS
    if not cors.origins_from_environment:
        if named:
            _logger.warning(
                "BACKEND_CORS_ORIGINS names %d origin(s) and the control plane does not read "
                "them: its CORS is declared in source. Declare CorsPolicy.from_environment() "
                "to allow the origins the environment names, or clear the variable.",
                len(named),
            )
        return plane, None
    resolved = cors.with_environment_origins(named)
    if isinstance(resolved, str):
        return plane, resolved
    return dataclasses.replace(
        plane, security=dataclasses.replace(plane.security, cors=resolved)
    ), None


def _with_edge_hops(plane: ControlPlane) -> ControlPlane:
    """Add ``TERP_EDGE_HOPS``, the hop a deploy tool's edge puts in front, to the app's count.

    ``SecurityConfig.trusted_proxy_hops`` counts the proxies the app puts in front of its
    api itself, in its own code: one where a web unit's nginx appends the caller to
    ``X-Forwarded-For``, none for an api-only app (ADR 0202). A deploy tool that serves the
    app through an edge of its own adds a hop the source cannot know of, because one image
    runs behind that edge in one environment and without it in another. Counted by neither,
    every caller resolves to the address the last hop sees, and the rate limit, the login
    lockout and the OIDC callback throttle become one shared bucket.

    So the tool that runs the edge says so, and the count is the sum, whatever the source
    declares (ADR 0220): the app never counts the edge's hop, and cannot refuse it. Said
    once at boot, because a count that is not the one in the source is otherwise invisible.
    """
    edge = get_settings().TERP_EDGE_HOPS
    if edge == 0:
        return plane
    declared = plane.security.trusted_proxy_hops
    _logger.info(
        "TERP_EDGE_HOPS adds the edge's %d proxy hop to the %d the control plane declares: "
        "the caller is entry %d from the right of X-Forwarded-For",
        edge,
        declared,
        declared + edge,
    )
    security = dataclasses.replace(plane.security, trusted_proxy_hops=declared + edge)
    return dataclasses.replace(plane, security=security)


def plane_from_settings(plane: ControlPlane) -> tuple[ControlPlane, str | None]:
    """*plane* with every value it takes from the environment filled in, and the reason a
    setting cannot be taken, when one cannot: the composition root refuses the boot with it."""
    return _with_environment_cors(_with_edge_hops(_with_job_actor(plane)))
