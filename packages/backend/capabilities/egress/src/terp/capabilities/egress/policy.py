"""What an application may talk to, declared once instead of decided per call site.

The rule this capability exists to serve (``no_raw_outbound_http``) refuses a raw HTTP
client in application code because it makes SSRF protection, allowlists, egress
auditing and timeout policy a choice at every call site. Moving the client behind a
seam only helps if those four things stop being choices, so they are all declaration
here and none of them is an argument to a request.

Deny by default, like every other declaration in the platform: an :class:`EgressPolicy`
with no hosts permits nothing at all.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class EgressPolicy:
    """The declared outbound surface of one application.

    ``allowed_hosts`` is an exact-match allowlist of hostnames. Exact rather than
    suffix or pattern: ``api.example.com`` does not admit ``evil-api.example.com``, and
    a wildcard is the shape that turns an allowlist into a formality. An empty tuple
    permits nothing, so a policy nobody has filled in fails closed instead of open.

    ``timeout_seconds`` bounds every request and has no per-call override. An outbound
    call with no bound is how one slow third party takes a worker pool with it, and the
    call site is exactly the place that is tempted to raise it "just here".

    ``max_response_bytes`` bounds what is read back, for the same reason the platform
    bounds an inbound body: a response is attacker-influenced input and an unbounded
    read is an unbounded allocation.

    ``allow_private_addresses`` opens the SSRF denylist, and is the one field that
    should give a reader pause. It exists because a sanctioned internal target — a
    service on the same private network — is a real deployment shape, and the honest
    way to serve it is a declaration that says so in the composition root rather than a
    quiet exception inside the client. It applies to every host in the policy, so a
    policy that needs it for one target relaxes it for all of them; if that is too
    coarse, the answer is two clients with two policies, not a per-call flag.
    """

    allowed_hosts: tuple[str, ...] = ()
    timeout_seconds: float = 10.0
    max_response_bytes: int = 8 * 1024 * 1024
    allow_private_addresses: bool = False
    allowed_schemes: tuple[str, ...] = ("https",)

    def __post_init__(self) -> None:
        if self.timeout_seconds <= 0:
            raise ValueError("EgressPolicy.timeout_seconds must be positive")
        if self.max_response_bytes <= 0:
            raise ValueError("EgressPolicy.max_response_bytes must be positive")
        if not self.allowed_schemes:
            raise ValueError("EgressPolicy.allowed_schemes must name at least one scheme")
        for host in self.allowed_hosts:
            if not host or host.strip() != host or host != host.lower():
                raise ValueError(
                    "EgressPolicy.allowed_hosts entries are bare lowercase hostnames "
                    f"without surrounding whitespace: {host!r}"
                )
            if "*" in host:
                raise ValueError(
                    "EgressPolicy.allowed_hosts takes exact hostnames, not patterns — a "
                    f"wildcard makes the allowlist a formality: {host!r}"
                )

    def permits_host(self, host: str) -> bool:
        """Whether *host* is on the allowlist, compared case-insensitively."""
        return host.lower() in self.allowed_hosts

    @property
    def permits_anything(self) -> bool:
        """False for a policy nobody filled in — the deny-by-default state."""
        return bool(self.allowed_hosts)


@dataclass(frozen=True)
class EgressAttempt:
    """One outbound call, as the observability seam sees it.

    This is the hook the platform's own metering and egress auditing hang off, and the
    reason it carries no request or response body: what is worth recording about an
    outbound call is that it happened, to whom, and what it cost. A seam that handed
    over the payload would become a second place secrets are read.
    """

    method: str
    host: str
    status_code: int | None
    duration_seconds: float
    response_bytes: int
    refused: bool = False


#: Called once per attempt, successful or not. Deliberately fire-and-forget: an
#: observer that raises must not turn a completed call into a failed one, so what to do
#: with an observer's own error is the client's decision, not the observer's.
Observer = Callable[[EgressAttempt], None]


__all__ = ["EgressAttempt", "EgressPolicy", "Observer"]
