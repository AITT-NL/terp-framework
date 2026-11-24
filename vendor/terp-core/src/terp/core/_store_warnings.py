"""The two production notices that a shared-store promise is kept per worker here.

Split out of ``terp.core.app`` unchanged: ``create_app`` says each once at a production boot,
and they are the same bargain told about two stores. Logged under ``terp.core``, as before.
"""

from __future__ import annotations

import logging

from terp.core.idempotency import IdempotencyStore, is_shared_idempotency_store
from terp.core.throttling import ThrottleStore, is_shared_throttle_store

_logger = logging.getLogger("terp.core")


def _warn_unshared_idempotency_in_production(
    idempotency_store: IdempotencyStore | None, require_shared_idempotency_store: bool
) -> None:
    """Say out loud, once, that idempotency is per-worker in this production deployment.

    The boot guard (``require_shared_idempotency_store``) is opt-in for a good reason: a
    per-instance store is *correct* for a single-instance production app, so refusing it
    outright would break a deployment that is not wrong. But the failure mode when that
    stops being true is the worst kind — scaling to a second replica silently converts "this
    mutation runs once" into "this mutation runs once per worker a retry happens to land
    on", with no error, no failed request and nothing in the logs to connect the duplicate
    rows back to the `--scale` that caused them. The promise breaks; nothing announces it.

    So production states the property it is actually running with, and names the flag
    that turns it into a boot-time refusal. An author who reads this line before scaling
    has the whole problem; one who reads it afterwards has the explanation.
    """
    if require_shared_idempotency_store or is_shared_idempotency_store(idempotency_store):
        return
    _logger.warning(
        "idempotency keys are deduplicated PER WORKER in this deployment: the "
        "configured idempotency_store is not a shared, multi-instance backend. This is "
        "correct for a single instance; run more than one and a client's retry landing "
        "on another worker re-executes the mutation, silently. Wire a shared store "
        "marked via terp.core.mark_shared_idempotency_store(...) and pass "
        "create_app(require_shared_idempotency_store=True) to make that a boot-time "
        "guarantee instead of a warning."
    )


def _warn_unshared_throttle_in_production(
    throttle_store: ThrottleStore | None, require_shared_throttle_store: bool
) -> None:
    """Say out loud, once, that the rate limit and login lockout are per-worker here.

    The sibling of :func:`_warn_unshared_idempotency_in_production`, and it should
    always have been one. That function exists because a promise ("this mutation runs
    once") quietly becomes false on the second replica with nothing to announce it. The
    throttle store carries two promises of exactly that shape and had no such line: the
    request rate limit, and the per-account failed-login lockout. Both are counters in
    this store, so N workers enforce N times the configured allowance — a 5-attempt
    lockout becomes 5 × N attempts against one account, which is the control least able
    to afford a silent multiplier.

    It is a warning rather than a refusal for the same reason the idempotency one is: a
    per-instance store is *correct* for a single-instance deployment, and refusing it
    would break something that is not wrong. What was missing was the sentence that
    makes the property visible before someone scales, and names the flag that turns it
    into a boot-time guarantee.
    """
    if require_shared_throttle_store or is_shared_throttle_store(throttle_store):
        return
    _logger.warning(
        "the rate limit and the login lockout are counted PER WORKER in this "
        "deployment: the configured throttle_store is not a shared, multi-instance "
        "backend. This is correct for a single instance; run more than one and each "
        "worker enforces its own allowance, so the effective request cap and the "
        "per-account failed-login threshold are both multiplied by the worker count. "
        "Wire a shared store marked via terp.core.mark_shared_throttle_store(...) and "
        "pass create_app(require_shared_throttle_store=True) to make that a boot-time "
        "guarantee instead of a warning."
    )
