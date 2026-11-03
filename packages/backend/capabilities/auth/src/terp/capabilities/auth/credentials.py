"""A route that mints a credential accepts no ``Idempotency-Key`` (ADR 0195).

The idempotency middleware stores a completed response and replays it to a retry of the
same key, before the route runs. On an ordinary write that is the point. On a route that
mints a credential it is two defects at once: the stored response is a live credential
sitting in the replay store for a day, and a replay hands it out again without running the
route, so the single-use rotation that detects a stolen refresh token never sees the reuse.
A captured refresh request, key included, would keep working for as long as the replay
lasts.

So ``/login``, ``/token``, ``/refresh`` and the native routes refuse the header outright.
The middleware then stores the refusal, which is harmless to replay, and never a token. A
client retries one of these routes by sending the request again without a key: a sign-in
is safe to repeat, and a refresh repeated within the grace window is the benign race ADR
0054 already allows for.
"""

from __future__ import annotations

from fastapi import Request

from terp.core import AppError


class ReplayKeyOnCredentialRouteError(AppError):
    """400 — an ``Idempotency-Key`` was sent to a route that mints a credential."""

    status_code = 400
    code = "idempotency_key_not_accepted"
    default_message = (
        "This route signs you in or renews a session, so it does not accept an "
        "Idempotency-Key. Send the request again without that header."
    )


def refuse_replay_key(request: Request) -> None:
    """Refuse a request to a credential-minting route that carries an ``Idempotency-Key``."""
    if "idempotency-key" in request.headers:
        raise ReplayKeyOnCredentialRouteError()


__all__ = ["ReplayKeyOnCredentialRouteError", "refuse_replay_key"]
