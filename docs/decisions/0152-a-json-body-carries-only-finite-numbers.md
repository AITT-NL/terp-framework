# 0152 — A JSON body carries only finite numbers

- **Status:** Accepted and implemented. `NonFiniteJsonMiddleware` is installed by
  `create_app` as the innermost layer of the security stack. Held by
  `tests/architecture/test_non_finite_json.py`. Amended 2026-09-28: the decision as first
  implemented refused the three constants only, and a number too large for a double still
  got in (see the amendment).
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

## Amendment (2026-09-28): a number too large for a double is the same value

The title of this ADR was not true when it was written. The middleware refused a body that
*spelled* a non-finite number, and that is only one of the two ways a body carries one. The
other is a legal JSON number too large for a double: `1e400` matches RFC 8259's number
grammar, and Python's decoder reads it as `inf` without `parse_constant` ever being called.
Reproduced against the same composed app the Context section used:

- `{"amount": 1e400}` sent to a plain `float` field was **accepted**, and so was
  `{"limit": 1e400}` sent to `Field(gt=0)`, since infinity is greater than zero.
- `{"limit": -1e400}` sent to that field was refused and answered with a **500** — the
  unencodable quote-back this ADR was written to close.
- `{"details": {"x": 1e400}}` reached the handler untouched.

So the first bullet of the Consequences was also wrong in its promise: a client that sends
`1e400` is not relying on an extension, it is sending standard JSON, and it got past the
control.

**The fix is the same control, looking at the other hook.** The strict parse now passes
`parse_float` as well as `parse_constant`. The decoder calls it with the source text of
every number that has a fraction or an exponent, which is every number that can overflow:
an integer literal decodes to an exact `int`, and pydantic refuses one too large for a
`float` field (quoting an `int`, which encodes) rather than rounding it to infinity. A
literal whose float value is infinite is answered with the same typed 422,
`non_finite_number`, whose detail names the literal — its first 24 characters, because the
size cap bounds a literal only at the size of the whole body — and says the number is too
large to represent.

**Considered and not taken: making the validation error encodable instead.** The request
that surfaced this proposed fixing the 422 renderer so that any quoted input encodes,
whatever produced it, instead of refusing inputs one kind at a time. That removes the 500
and nothing else: the plain `float` field and the untyped mapping still accept the value,
which is the harm this ADR exists to prevent. The objection that refusing inputs kind by
kind is incomplete does not hold here either, because the hook is not a kind — it is the
single place the decoder turns a literal into a float, so no number reaches a field without
passing it. And once the body is closed, no input can reach the renderer non-finite, so a
guard there would be a branch no test could reach.

Still not covered, as before: a `float` query or path parameter accepts `inf`, `nan` and
`1e400` alike, for the reason the Consequences give.
