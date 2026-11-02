"""The one host this app may call, declared once (``terp-cap-egress``).

``no_raw_outbound_http`` refuses a raw HTTP client in app code, so the call goes through
an :class:`EgressClient` held to this :class:`EgressPolicy`: one exact host, HTTPS only,
a timeout and a response cap with no per-call override, every resolved address checked
against the SSRF denylist and the connection pinned to the one that passed.

``example.com`` is the domain reserved for documentation (RFC 2606), which is what makes
it the right upstream for an app whose whole purpose is to be run by anyone, anywhere,
naming no real party. The address is code, not configuration: the allowlist is the
declaration, and a value a caller or an environment could change is not one.
"""

from __future__ import annotations

from typing import Final

from terp.capabilities.egress import EgressClient, EgressPolicy

UPSTREAM_URL: Final = "https://example.com/"

UPSTREAM_POLICY: Final = EgressPolicy(
    allowed_hosts=("example.com",),
    timeout_seconds=10.0,
    max_response_bytes=1024 * 1024,
)

#: The client every fetch goes through. A module attribute rather than a local, so a test
#: can hand it a sender that never touches the network while keeping the policy above.
client = EgressClient(UPSTREAM_POLICY)
