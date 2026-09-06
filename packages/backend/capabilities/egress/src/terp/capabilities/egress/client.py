"""The seam the outbound-HTTP rule sends people to.

``no_raw_outbound_http`` refuses a raw HTTP client in application code and tells the
author to use "a declared capability with SSRF protection". This is that capability.
Everything the rule lists as a per-call-site choice — the allowlist, the SSRF check,
the timeout, the egress record — is a property of the client's :class:`EgressPolicy`
here, so a call site cannot make any of those decisions even by accident.

The order of the checks matters and is the design. A target is refused on the
declaration first (scheme, then allowlist), because those are cheap, total, and do not
touch the network: a host nobody declared never gets a DNS lookup, so a policy
violation cannot itself be used to probe what resolves. Only then is the name resolved
and every address it returns validated, and only the address that passed is connected
to — the connection is **pinned** to it, so a name that resolves safely during the
check and hostilely a millisecond later still cannot land on a private address.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from urllib.parse import urlsplit

from terp.capabilities.egress.errors import EgressFailedError, EgressRefusedError
from terp.capabilities.egress.policy import EgressAttempt, EgressPolicy, Observer
from terp.capabilities.egress.ssrf import (
    PinnedTarget,
    Resolver,
    as_ip_literal,
    is_denied_address,
    resolve_host,
)


_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class EgressResponse:
    """What came back: a status, headers, and a bounded body."""

    status_code: int
    headers: Mapping[str, str]
    content: bytes

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 300


#: The transport seam: given a pinned target and the request pieces, perform the call.
#: Injectable so the whole client is testable with no network at all, and so a
#: deployment that must route through a proxy replaces one function rather than
#: re-implementing the policy around it.
Sender = Callable[
    [PinnedTarget, str, bytes | None, Mapping[str, str], float, int], EgressResponse
]


def _httpx_sender(
    target: PinnedTarget,
    method: str,
    body: bytes | None,
    headers: Mapping[str, str],
    timeout_seconds: float,
    max_response_bytes: int,
) -> EgressResponse:
    """The default transport: ``httpx``, pinned to the validated address.

    The request is built from the original URL, so the ``Host`` header and path are
    right and TLS is verified against the hostname through the ``sni_hostname``
    extension; then the connection is repointed to the validated IP. Redirects are never
    followed — a followed redirect is a second, unvalidated target, which would put the
    SSRF check back at the mercy of the far end.
    """
    import httpx  # noqa: PLC0415 - the one place the platform's HTTP client is imported

    with httpx.Client(timeout=timeout_seconds, follow_redirects=False) as client:
        request = client.build_request(
            method,
            target.url,
            content=body,
            headers=dict(headers),
            extensions={"sni_hostname": target.host},
        )
        request.url = request.url.copy_with(host=target.ip)
        # `send(request)`, not `stream(method, url, ...)`: the request built above is the
        # one that must go out. Re-deriving it from a method and a URL silently drops the
        # body and the `sni_hostname` extension -- which would make every POST send
        # nothing and every TLS handshake verify against the pinned IP instead of the
        # hostname, i.e. break the safe half of the pinning this function exists for.
        response = client.send(request, stream=True)
        try:
            chunks: list[bytes] = []
            read = 0
            for chunk in response.iter_bytes():
                read += len(chunk)
                if read > max_response_bytes:
                    raise EgressFailedError(
                        "The upstream response was larger than this application accepts.",
                        log_context={"host": target.host, "limit": max_response_bytes},
                    )
                chunks.append(chunk)
            return EgressResponse(
                status_code=response.status_code,
                headers=dict(response.headers),
                content=b"".join(chunks),
            )
        finally:
            response.close()


class EgressClient:
    """A declared outbound HTTP client: one policy, every call held to it."""

    def __init__(
        self,
        policy: EgressPolicy,
        *,
        sender: Sender | None = None,
        resolve: Resolver | None = None,
        observer: Observer | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._policy = policy
        self._sender = sender if sender is not None else _httpx_sender
        self._resolve = resolve if resolve is not None else resolve_host
        self._observer = observer
        self._clock = clock if clock is not None else time.monotonic

    @property
    def policy(self) -> EgressPolicy:
        return self._policy

    def _pin(self, url: str) -> PinnedTarget:
        """Validate *url* against the policy and the denylist, and pin its address."""
        parts = urlsplit(url)
        if parts.scheme not in self._policy.allowed_schemes:
            raise EgressRefusedError(
                "The outbound request was not permitted.",
                log_context={"reason": "scheme", "scheme": parts.scheme, "url": url},
            )
        host = parts.hostname
        if not host:
            raise EgressRefusedError(
                "The outbound request was not permitted.",
                log_context={"reason": "no_host", "url": url},
            )
        if not self._policy.permits_host(host):
            raise EgressRefusedError(
                "The outbound request was not permitted.",
                log_context={"reason": "host_not_allowed", "host": host},
            )

        literal = as_ip_literal(host)
        if literal is not None:
            addresses = [literal]
        else:
            try:
                addresses = self._resolve(host)
            except OSError as exc:
                # The name did not resolve. Refused rather than attempted: a fallback
                # here is an ambiguous lookup at send time, which is the thing the pin
                # exists to prevent. The resolver's own message stays in the log.
                raise EgressRefusedError(
                    "The outbound request was not permitted.",
                    log_context={"reason": "unresolvable", "host": host, "cause": str(exc)},
                ) from exc
        if not addresses:
            raise EgressRefusedError(
                "The outbound request was not permitted.",
                log_context={"reason": "unresolvable", "host": host},
            )
        if not self._policy.allow_private_addresses:
            for address in addresses:
                if is_denied_address(address):
                    raise EgressRefusedError(
                        "The outbound request was not permitted.",
                        log_context={
                            "reason": "denied_address",
                            "host": host,
                            "address": address,
                        },
                    )
        return PinnedTarget(url=url, host=host, ip=addresses[0])

    def _observe(self, attempt: EgressAttempt) -> None:
        """Hand the attempt to the observer, if there is one.

        An observer that raises must not turn a completed call into a failed one, nor a
        refusal into a different error: metering is not allowed to change what happened.
        """
        if self._observer is None:
            return
        try:
            self._observer(attempt)
        except Exception:  # noqa: BLE001 - an observer never changes the outcome
            # Not silence: an observer that never works should be discoverable. It just
            # must not be discoverable by breaking the call it was watching.
            _log.debug("egress observer raised for %s", attempt.host, exc_info=True)

    def request(
        self,
        method: str,
        url: str,
        *,
        body: bytes | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> EgressResponse:
        """Perform one policy-checked, address-pinned, time-bounded request."""
        started = self._clock()
        try:
            target = self._pin(url)
        except EgressRefusedError:
            self._observe(
                EgressAttempt(
                    method=method.upper(),
                    host=urlsplit(url).hostname or "",
                    status_code=None,
                    duration_seconds=self._clock() - started,
                    response_bytes=0,
                    refused=True,
                )
            )
            raise

        try:
            response = self._sender(
                target,
                method.upper(),
                body,
                headers or {},
                self._policy.timeout_seconds,
                self._policy.max_response_bytes,
            )
        except EgressFailedError:
            self._observe(
                EgressAttempt(
                    method=method.upper(),
                    host=target.host,
                    status_code=None,
                    duration_seconds=self._clock() - started,
                    response_bytes=0,
                    refused=False,
                )
            )
            raise
        except Exception as exc:  # noqa: BLE001 - every transport error is one typed failure
            self._observe(
                EgressAttempt(
                    method=method.upper(),
                    host=target.host,
                    status_code=None,
                    duration_seconds=self._clock() - started,
                    response_bytes=0,
                    refused=False,
                )
            )
            # The transport's own text names hosts, ports and paths. It goes to the log
            # with the exception chained; the client sees a written sentence.
            raise EgressFailedError(
                "An outbound request did not complete.",
                log_context={"host": target.host, "method": method.upper()},
            ) from exc

        self._observe(
            EgressAttempt(
                method=method.upper(),
                host=target.host,
                status_code=response.status_code,
                duration_seconds=self._clock() - started,
                response_bytes=len(response.content),
                refused=False,
            )
        )
        return response

    def get(self, url: str, *, headers: Mapping[str, str] | None = None) -> EgressResponse:
        return self.request("GET", url, headers=headers)

    def post(
        self,
        url: str,
        *,
        body: bytes | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> EgressResponse:
        return self.request("POST", url, body=body, headers=headers)


__all__ = ["EgressClient", "EgressResponse", "Sender"]
