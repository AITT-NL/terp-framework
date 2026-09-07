"""The two things that can go wrong on the way out, as typed errors.

Both are ``AppError`` subclasses, so a failed outbound call reaches a client through
the same envelope as every other failure rather than as whichever exception the
transport happened to raise. The distinction between them is who has to act: a refusal
is the application's own declaration saying no, and a failure is the far end.
"""

from __future__ import annotations

from terp.core import AppError


class EgressRefusedError(AppError):
    """502 — the declared egress policy refuses this target.

    Raised *before* any connection: a scheme the policy does not allow, a host that is
    not on the allowlist, a name that will not resolve, or an address inside a denied
    range. The status is 502 rather than 400 because the caller of the API did not do
    anything wrong — the application is declining to make a call it was configured not
    to make, which from the outside is an upstream that cannot be reached.
    """

    status_code = 502
    code = "egress_refused"
    default_message = "The outbound request was not permitted."


class EgressFailedError(AppError):
    """502 — the far end failed: a timeout, a refused connection, a transport error.

    Deliberately not a carrier for the transport's own message. What went wrong belongs
    in the log with the exception chained to it; what reaches the client is that an
    upstream call did not succeed. A driver's error string routinely names an internal
    host or a path, and an error response is exactly where that must not surface.
    """

    status_code = 502
    code = "egress_failed"
    default_message = "An outbound request did not complete."


__all__ = ["EgressFailedError", "EgressRefusedError"]
