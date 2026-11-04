# Idempotency replay authorization

An idempotency key prevents a repeated mutation; it does not grant continuing access
to that mutation's response. A retry now authenticates the current credential and
checks the current module/route policy before any stored response can be returned.
Completed requests keep their deduplication record when authorization fails.

## Migrating existing routes

Unmarked routes still execute an initial request with an `Idempotency-Key`. A retry
of its completed key receives `409 idempotency_replay_not_authorized`; it does not
execute the endpoint again. Applications must explicitly adopt replay on each route
whose authorization can be checked independently of its mutation. Do not recover
from this refusal by automatically assigning a fresh key: that can repeat the work.

Use the public `idempotent_replay(authorize=...)` decorator below the FastAPI route
decorator. Its required callable is a normal FastAPI dependency. It runs on initial
requests and retries, can receive path/query/body inputs and other dependencies,
and must raise a typed error when disclosure of the stored response is no longer
allowed. For example, an application's resource service can supply a read-only
check shared with the endpoint's normal authorization:

```python
from uuid import UUID
from fastapi import Depends
from terp.core import get_principal, get_session, idempotent_replay


def authorize_result(
    record_id: UUID,
    principal=Depends(get_principal),
    session=Depends(get_session),
):
    # Application-defined: check current visibility/ownership/tenant/resource grants.
    records.require_result_access(session, principal, record_id)


@router.post("/{record_id}/snapshot", response_model=SnapshotRead)
@idempotent_replay(authorize=authorize_result)
def snapshot(record_id: UUID, session=Depends(get_session)):
    return records.create_snapshot(session, record_id)
```

After authentication, policy, and **all** route dependencies succeed, the framework
returns the stored response with `Idempotency-Replayed: true`, skipping the endpoint
function entirely. This includes dependencies declared in endpoint parameters,
router dependencies, and nested dependencies. Yield dependencies retain normal
FastAPI cleanup behavior. Nested routers and repeated app composition preserve the
boundary. Generator/streaming endpoints cannot opt in.

If the existing policy and dependencies are the complete authority for a route
with no additional resource access conditions, its explicit authorizer can simply
return after documenting that fact. Do not use such an authorizer for a handler
that checks ownership, tenant membership, an object's status, or another resource
condition only inside the mutation. Those checks need a read-only equivalent in the
authorizer, or the route must keep the default refusal. A framework cannot safely
rerun arbitrary in-handler authorization without also rerunning its side effects.

Replay authentication and dependencies execute under the persistence read-only
control, including for `POST`, `PUT`, `PATCH`, and `DELETE`. Writes through the
framework's session/service boundary fail closed. **All dependencies of a route
that opts in must be free of external side effects too**: do not send messages,
make mutating network calls, or enqueue background work during authorization. The
persistence guard cannot undo arbitrary external I/O performed by application code.
Checks observe current authority when they run; normal concurrent changes after an
authorization decision have the same limits as an ordinary request.

## Bind authorization to the original result

The fingerprint now binds method, path, raw path, query, body, scheme, server,
mount root, client host, and **every request header**. Header names are
case-insensitive; duplicate values keep their order. Fields use unambiguous
serialization. A resource/tenant selector cannot be changed between the initial
request and its retry to authorize resource B while retrieving resource A's result.
Changes to tracing/request-id headers, host, content type, or other headers can
therefore produce a conservative `422 idempotency_key_mismatch`. Clients and proxies
need to preserve these inputs for a valid retry. Existing stored fingerprints from
older releases also mismatch until they expire; denial does not discard them.

Some handlers select a resource from mutable server state, such as the caller's
current default tenant, or generate its identity during the mutation. In that case,
checking only today's default does not authorize the original result. The public
`get_idempotency_response()` dependency returns the immutable `StoredResponse`
(status, headers, body) during replay and `None` during initial execution. An
authorizer can depend on it, parse the original result using its response schema,
and check current access to **that** resource. This also covers results containing
multiple resources. Authorize every disclosure condition of the stored result;
when its identity cannot be recovered or independently checked, keep replay
disabled. The framework does not infer resource authority from an arbitrary body.

## Credential endpoints

Use the public `@no_idempotency` decorator for routes that issue credentials or
other one-time secrets. Such a route rejects `Idempotency-Key` with
`400 idempotency_not_supported` before its handler runs. The bundled password/SSO
login, client-credentials token, refresh rotation, OIDC callback, MFA enrolment,
and realtime-ticket issuance routes declare this behavior. Clients must omit the
header on these endpoints. A cached access token or refresh cookie must not bypass
credential verification or revive a spent authentication flow.

The two decorators are mutually exclusive. They are enforced by `create_app`'s
composition boundary. Bare `IdempotencyMiddleware` refuses completed-key replay
without that boundary; a custom ASGI integration must not enable its internal
composition flag without equivalent route enforcement.

## Storage semantics

Caller/credential scoping and request fingerprint matching remain in effect.
Authorization denial never releases or replaces a completed key. Store outages
still fail closed before an initial mutation. Incomplete/disconnected bodies never
execute without a claim. Existing lease expiry, TTL, capacity eviction, oversized
responses, and server-error behavior still mean the store provides its documented
at-least-once retry semantics, not a permanent exactly-once guarantee.
