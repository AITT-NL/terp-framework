# 0193 — Security boundaries hold across operation sequences

- **Status:** Accepted. Implemented and held by the regression suites linked in
  [security boundaries](../security-boundaries.md).
- **Date:** 2026-11-03
- **Relates:** extends [ADR 0084](0084-runtime-applicability-classification.md)
  (runtime evidence); amends [ADR 0016](0016-permission-in-policy-enforced-as-grant.md)
  and [ADR 0121](0121-a-module-role-is-an-assignment-not-a-policy.md)
  (consistent authority decisions), [ADR 0077](0077-idempotency-keys-for-unsafe-methods.md)
  (authorization of replay), and [ADR 0045](0045-durable-outbox.md)
  (transaction and claim ownership).

---

## Context

A source rule can reject a dangerous call without proving what remains after a failed
operation. An authorization exception does not prove that a dirty row cannot commit
later; a valid credential does not prove that its authority survived a concurrent
revocation; a claim check does not prove ownership when the final update executes.
The review found these gaps between individually plausible steps. The framework must
hold its guarantees across the sequence, including retries and competing transactions.

## Decision

**1. Runtime guarantees require evidence at the boundary they claim.** Source rules
continue to constrain application code. Regression tests additionally exercise real
HTTP routes, persistence, local transports and deterministic interleavings: deny a
write and then commit another operation; rotate while logout waits on another database
connection; reclaim work before the earlier worker finalizes it. The assertion concerns
the rows, disclosed response or delivered message after the sequence. Neither an
exception, a corpus score nor line coverage alone establishes that result.

**2. Authentication captures authority and its epoch together.** Epoch-aware
authenticators return an immutable authenticated snapshot, captured before work that
can refresh the identity record. Minting verifies that snapshot against current state;
it cannot attach a later epoch to an earlier role or credential proof. Refresh families
carry the authenticated epoch. A revoked family member remains a tombstone until the
family's absolute expiry, so a concurrent successor missed by a revocation statement
cannot later rotate. Cookie-only logout revokes the presented family; revoking a
separately held access token requires the access-epoch path. Browser OIDC callbacks also
require the initiating browser's transaction cookie. The additive migration and custom
callback contracts are in [authentication transitions](../authentication-transitions.md).

**3. A completed mutation does not confer continuing access to its response.** Replay
requires explicit `idempotent_replay(authorize=...)` adoption. Current authentication,
policy and all dependencies run under the persistence read-only guard before the stored
response is returned; the mutation handler is skipped. The authorizer must check access
to the original result, using `get_idempotency_response()` when mutable server defaults
could otherwise select a different resource. Without a suitable independent check,
replay stays refused and the completed record is retained. Credential issuance
declares `no_idempotency` and refuses keys before running its handler.

Request binding is deliberately conservative: all headers, with duplicate value order
preserved, and the request target, body and relevant connection selectors participate.
A header that usually serves tracing might select authority in another application.
Changed incidental headers may therefore conflict with a retry. Credential changes can
also move the caller's key scope; this remains an at-least-once contract. See
[idempotency authorization](../idempotency-authorization.md) for adoption and constraints.

**4. Every permission decision requires its role floor and its named grant.** Policy
guards, route dependencies and realtime channels share that decision; the access matrix
preserves dependency floors too. Legacy permission names resolve against the mounted
catalog or fail closed. Module elevation comes only from that request's declared
assignable module, never a permission's dotted name or another request's context.
Realtime redemption, frames and idle heartbeats recheck grants and audience in fresh
sessions. Identity expiry, account state and role/epoch freshness additionally require
`principal_validator`; the captured identity is otherwise unchanged for the connection.

**5. Database mutation and custody checks hold through completion.** Scope applies to
ORM relationship loads and aliases, while the narrow internal column-refresh exception
remains. A refused mutation must not leave an unauthorized dirty row to flush later.
File-reference assignment checks target visibility and authority in its transaction.
A job's service writes share one commit or rollback; durable attempt journals run
separately only after that transaction finishes. Sync source acquisition and heartbeats
use independent transactions on PostgreSQL, with the bundled database store fencing final
completion through the business commit and releasing custody afterward. SQLite retains
transaction-scoped custody because a second writer cannot renew while business work holds
its database-wide write lock; the [sync contract](../../packages/backend/capabilities/sync/README.md)
states that recovery limit. Outbox finalization conditionally
updates the expected pending claim in the database, so a stale worker cannot overwrite
its successor's state.

## Consequences and limits

Existing integrations must adopt the authentication migration, replay declaration and
permission floors; failures that previously succeeded now refuse. The linked migration
guides and [security boundaries](../security-boundaries.md) record the concrete changes
and their tests, including outbound HTTP, mail, webhook and logging compatibility.

These decisions do not close every risk in those classes. Synchronous operating-system
DNS resolution cannot be cancelled by the HTTP elapsed-time budget. Database rollback
cannot undo an external effect, and an outbox claim cannot fence the destination:
external writes needing custody guarantees require destination-enforced fencing, with
idempotency for retries. Replay dependencies must avoid external side effects. Realtime
revocation takes effect at the next check, subject to provider latency; it neither
cancels an already running handler nor recalls a delivered message. Those limits remain
explicit rather than inferred away from a passing suite.
