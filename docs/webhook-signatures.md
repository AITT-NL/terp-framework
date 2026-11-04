# Webhook signature version 2

Terp signs each webhook's event name, delivery identifier, timestamp and exact request
body. A receiver must authenticate all four before using the event to route work or the
delivery identifier to deduplicate it. The JSON body remains the event's data object.

The sender supplies these headers:

| Header | Value |
|---|---|
| `X-Terp-Webhook-Timestamp` | Decimal Unix seconds, refreshed for each attempt |
| `X-Terp-Delivery-Id` | UUID string, stable across retries of one delivery |
| `X-Terp-Event` | Catalog event name |
| `X-Terp-Signature` | `v2=` followed by the lowercase hexadecimal HMAC-SHA256 digest |

Construct the authenticated bytes in this order:

1. The ASCII bytes `terp-webhook-v2` followed by one newline (`0a`).
2. A compact JSON array of the three **header strings**, in order: timestamp,
   delivery identifier, event. Use comma separators without whitespace and ASCII
   JSON escaping (Python `ensure_ascii=True`). Do not parse the timestamp as a JSON
   number or normalize the delivery identifier before signing.
3. One newline, followed by the exact raw HTTP request body bytes.

Compute HMAC-SHA256 over these bytes using the subscription secret encoded as UTF-8.
Compare the complete expected `v2=<digest>` value in constant time. Reject duplicate or
missing security headers, an unsupported signature version, an invalid timestamp or
identifier, a signature mismatch, and a timestamp outside the receiver's bounded age
window (including unreasonable future timestamps). Only then use the authenticated
delivery identifier for durable deduplication. A matching signature does not itself
make a repeated delivery new.

For example, a Python receiver builds the signed input as follows, before applying its
timestamp and deduplication policy:

```python
metadata = json.dumps(
    [timestamp_header, delivery_id_header, event_header],
    separators=(",", ":"), ensure_ascii=True,
).encode("utf-8")
signed = b"terp-webhook-v2\n" + metadata + b"\n" + raw_body
expected = "v2=" + hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()
if not hmac.compare_digest(expected, signature_header):
    reject_request()
```

This is a protocol change. Earlier senders emitted `sha256=<digest>` over
`timestamp.body`, leaving event and delivery-ID headers unauthenticated. Update
receivers to understand v2 before deploying the new sender, then require v2. The new
sender emits no legacy signature, and receivers must not fall back to the old format
after a failed v2 verification. Existing subscriptions and queued delivery identifiers
need no database migration; retried deliveries use v2 after the sender is upgraded.
