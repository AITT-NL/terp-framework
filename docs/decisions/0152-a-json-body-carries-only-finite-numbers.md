# 0152 — A JSON body carries only finite numbers

- **Status:** Accepted and implemented. `NonFiniteJsonMiddleware` is installed by
  `create_app` as the innermost layer of the security stack. Held by
  `tests/architecture/test_non_finite_json.py`.
- **Date:** 2026-09-27
- **Relates:** [ADR 0067](0067-per-module-request-size-allowances.md) (the size cap that
  bounds what this layer reads),
  [ADR 0103](0103-the-ideology-one-pattern-enforced-escapable-by-proof.md) (the default is
  the most enforced standard)

---

## Context

JSON has no non-finite numbers: RFC 8259 §6 allows neither `NaN` nor `Infinity`. Python's
decoder accepts `NaN`, `Infinity` and `-Infinity` anyway, and nothing between it and a
module's service refused them. Reproduced against a composed app:

- `{"limit": NaN}` sent to a field declared `Field(gt=0)` was refused by pydantic — and
  answered with a **500**. The validation error quotes the offending value back, and
  FastAPI's renderer encodes with `allow_nan=False`, so the 422 the client was owed could
  not be written.
- `{"amount": Infinity}` sent to a plain `float` field was **accepted**. pydantic's
  default is `allow_inf_nan=True`, and nothing in `BaseSchema` changed it.
- `{"details": {"floor": -Infinity}}` in a `dict[str, Any]` field reached the handler
  untouched, since no field type ever looked at it.

A value that gets in does damage past the request that carried it. Under IEEE 754, `NaN`
compares false against everything, so a service check written as "refuse when larger than
the limit" waves it through. And the first place it is encoded again — the response, a
JSON column, an outbound call — refuses it, which turns an accepted request into a 500 at
some later point.

Setting `allow_inf_nan=False` on `BaseSchema` was measured and is not enough on its own: it
refuses the value in a `float` field, but the refusal still quotes the value back, so the
answer is still a 500, and a `dict[str, Any]` field is untouched by it.

## Decision

**The API speaks RFC 8259 JSON, and the refusal happens before anything is decoded for the
route.** A pure ASGI middleware, `NonFiniteJsonMiddleware`, reads every request body
declared as JSON — `application/json` or `application/*+json`, the same test FastAPI
applies before it decodes — parses it with a `parse_constant` hook, and answers any body
that uses one of the three constants with a typed 422 in the platform envelope:

```json
{"code": "non_finite_number",
 "detail": "The request body contains NaN, which is not a JSON number. Send a finite number, or null where there is no value.",
 "request_id": "…"}
```

The detail names the constant and the fix, because for an app built by an agent the error
message is what gets read.

**Why a middleware rather than the schema or a route class.** The schema cannot see a
`dict[str, Any]` field's contents and cannot stop its own refusal from being unencodable.
A custom `APIRoute` class would have to be adopted by every router a module builds, which
is a second thing an author must remember and a place for one to be missed. The middleware
sits where the other body-level controls already sit — innermost, inside the request-size
cap — so it holds for every route with no declaration and no escape.

**What it costs.** One strict parse per JSON body, on top of FastAPI's own. The body is
already bounded by the size cap outside this layer. The parse is not skipped by a cheaper
byte scan for `NaN`, because the decoder also accepts UTF-16 and UTF-32 JSON, where those
bytes never appear; a prefilter would have been a bypass. A test holds that.

**What it leaves alone.** Malformed JSON is still FastAPI's to answer, in the
`json_invalid` shape clients already handle. A body not declared as JSON is not read. A
request whose client disconnected mid-body is handed on as it arrived, not judged on a
fragment.

## Consequences

- An app gains the refusal on upgrade with no change. A client that was sending `NaN` or
  `Infinity` was relying on a non-standard extension; it now gets a 422 that says so.
- The frontend half needs nothing: `JSON.stringify` already writes `NaN` and `Infinity` as
  `null`, so the typed client cannot produce the refused form.
- **Not covered, and recorded rather than implied:** a `float` *query or path* parameter
  still accepts the strings `inf` and `nan` — `?amount=inf` reaches the handler as
  `float("inf")`. The value arrives as a string, so its validation errors quote the string
  and encode fine; the 500 does not occur there. But the acceptance does. Closing it needs
  `allow_inf_nan=False` on each such parameter (FastAPI's `Query(allow_inf_nan=False)`),
  and there is no single place the framework can set that for parameters an app declares.
  That is a separate decision, and it is not taken here.
