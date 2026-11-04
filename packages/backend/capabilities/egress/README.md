# Egress resource limits

`EgressPolicy.timeout_seconds` supplies one elapsed-time budget for the default HTTP
transport. TCP connection, TLS negotiation, request writes, response headers and every
response read share that budget. An upstream sending occasional bytes cannot restart
it. Socket operations use the remaining budget and close on failure; no detached HTTP
worker continues the request after the caller times out.

Resolution time reduces the remaining transport budget. If a resolver returns after
the budget expires, no connection is opened. The synchronous operating-system
`getaddrinfo` call is not cancellable through this API, so this is not a hard deadline
for a blocked system resolver. Configure the resolver's own timeout or supply a bounded
resolver. Custom resolver and sender seams must preserve these resource guarantees.

The default transport sends `Accept-Encoding: identity`, overriding a supplied encoding
header, and rejects any other response content encoding before reading its body. It
never passes compressed input through an unbounded decoder. `max_response_bytes` limits
raw identity bytes accumulated in a byte buffer; headers and network framing have the
HTTP parser's separate bounds. Upstreams that require compression need to support
identity encoding before adopting this transport behavior.

Address pinning, the original TLS hostname, certificate verification and disabled
redirects remain enforced. Ambient proxy environment variables are not used by the
default transport: a proxy requires an explicitly supplied sender that preserves the
declared policy and verified target. Verified CA selection through `SSL_CERT_FILE` or
`SSL_CERT_DIR` is preserved. Timeout values must be finite and positive; the
response cap must be a positive integer.
