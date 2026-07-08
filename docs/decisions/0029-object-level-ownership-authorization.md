# 0029 - Object-level (ownership) authorization: a per-row write gate

- **Status:** Accepted
- **Date:** 2026-06-27
- **Context phase:** Phase 2 (base profile), adversarial-review follow-ups
- **Relates:** [ADR 0016](0016-permission-in-policy-enforced-as-grant.md) (a named
  `Permission` enforced as a per-subject grant — the per-**endpoint** authority),
  [ADR 0017](0017-non-overridable-scope-predicate-and-registry.md) (the non-overridable
  `base_query` + the row-scope predicate registry — per-**row read visibility**),
  [ADR 0012](0012-actor-stamping-trait.md) (actor-stamping — the owner defaults to the
  creator), [ADR 0015](0015-runtime-write-guarded-session.md) (the audited write
  chokepoint this gate rides), [ADR 0006](0006-cross-cutting-controls-and-opinionation-policy.md)
  (the two-layer discipline + the Tier-A "quadruple"). Finding: object-level / ownership
  authorization is flagged in
  [docs/internal/reviews/2026-06-24-adversarial-design-review.md](../internal/reviews/2026-06-24-adversarial-design-review.md)
  and recorded as the open per-row complement in ADRs 0016 and 0017.

---

## Context

Terp's authorization was **coarse and per-endpoint**. The `create_app` guard checks the
caller's role rank by HTTP method, and ADR 0016 enforces a named `Permission` in a
`Policy` as a real per-subject grant — both decide "may this caller hit *this route*?".
ADR 0017 added the orthogonal, per-row **read** seam: `register_scope_predicate`
composes a `WHERE` clause into the non-overridable `base_query`, so a caller only *sees*
the rows a registered predicate admits.

What no seam answered is the classic object-level / BOLA question on the **write** side:
"may this principal change *this specific* record?" — ownership, team membership, a
record-level ACL. A `Policy(write=EDITOR)` lets *every* editor edit *every* row of a
module; the only way to restrict a write to the row's owner was to hand-roll it in the
service:

```python
entry = self.get(session, entry_id)
if entry.owner_id != principal.id:      # easy to forget; not enforced anywhere
    raise PermissionDeniedError()
```

That hand-rolled check is (a) easy to omit (nothing fails closed if you forget it),
(b) easy to get subtly wrong, and (c) a trap that invites a hand-written
`select(Model).where(owner_id == ...)` read — which *also* drops the soft-delete /
tenant row scope (the H2 footgun ADR 0017 closed for reads). The review flagged this as
the highest-value missing security pattern.

## Decision

Add a first-class, opt-in, fail-closed **per-row write authorization** seam — the
write-side mirror of the ADR 0017 read registry — composed centrally at the audited
`BaseService` chokepoint, so a module declares ownership on the model and writes **no**
authorization code.

1. **The mechanism split (why a *write* gate, not also a read filter).** Read
   visibility and write authorization are enforced by *different shapes* and must stay
   separate seams:
   - **Reads** are a *query filter* — `register_scope_predicate` (ADR 0017) adds a
     `WHERE` clause, so a non-visible row is simply never returned. This scales to
     `list` / pagination.
   - **Writes** are a *post-load boolean* on the **one** already-loaded target row —
     this ADR. A boolean cannot paginate a list, so it is the wrong tool for read
     scoping; but it is exactly right at the write chokepoint, where the framework holds
     the single row a mutation targets. Splitting by mechanism keeps each seam correct
     and composable: together with the endpoint gate they form the complete
     authorization matrix (endpoint = ADR 0016, row-read = ADR 0017, row-write = 0029).

2. **`OwnedMixin` — the model trait (core).** A model opts in by composing
   `terp.core.OwnedMixin`, which adds an FK-less, nullable, indexed `owner_id` (like the
   actor-stamp columns: the low core layer must not import a user table, and a principal
   may not be a user). Composing the trait is the whole declaration — there is no
   per-route or per-service wiring.

3. **Auto-stamped owner, auto-enforced write (core).** `BaseService._save` stamps
   `owner_id` to the request actor (`audit_actor_ctx`) **once on create** — the creator
   owns what they create — and authorizes **every update / delete of an existing row**:
   the actor must clear `apply_object_authz(...)` or the write fails closed with a typed
   `PermissionDeniedError` (403) *before* any persistence is staged — and, on `update`,
   *before* the optimistic-concurrency check, so a non-owner is refused 403 whatever
   version they sent (never a misleading 409). `_remove`
   (hard delete) and the soft-delete path both route through the same check, so every
   mutation of an owned row — through `create` / `update` / `delete` or a bespoke
   `_save` — is gated with zero module code. The check is keyed off the *entity*
   (`isinstance`), so a non-mapped hook stand-in is unaffected (as with actor-stamping).

4. **The object-authz registry (`terp.core.object_authz`).** The built-in policy
   (an `OwnedMixin` row may be written only by its `owner_id`) is the kernel's own,
   inlined just as soft-delete is the kernel's built-in row scope. Richer policies (team
   membership, a shared-with ACL) plug in through
   `register_object_authz_predicate(predicate)` — the write-side mirror of
   `register_scope_predicate` — so a capability contributes per-row authority **without
   the kernel importing it** (the layering rule). Predicates compose fail-closed
   (`AND`): a write is allowed only if the built-in *and* every registered predicate
   allow it, and each predicate no-ops (`True`) for a model it does not govern. The
   predicate is **action-aware** (it receives the `AuditAction`), so a policy can
   distinguish "the owner may edit but only an admin may delete"; the built-in ignores
   the action (the owner may perform any write).

5. **Owner relates to, but is distinct from, the creator (ADR 0012).** `owner_id`
   *defaults* to the same `audit_actor_ctx` actor that `ActorStampedMixin` stamps into
   `created_by_id`, so "the creator is the owner" by default. But it is a **separate,
   transferable** column: ownership can be reassigned without rewriting the immutable
   `created_by_id` provenance record. A model composes both traits to track *who created
   it* and *who may change it* independently; `OwnedMixin` alone gives just the gate. To
   restrict *reads* to the owner too, register a scope predicate keyed on `owner_id`
   (ADR 0017) — the two seams compose into a fully private resource.

6. **Anti over-posting (core + build).** `owner_id` joins the framework-managed input
   columns `BaseService` strips from every inbound payload, so a client can never
   forge or seize ownership through the request body. The build-time
   `input_schemas_exclude_managed_columns` rule covers it for free (an input schema may
   not declare `owner_id`).

7. **Two-layer enforcement (ADR 0006).** The runtime control is the fail-closed
   chokepoint check above. The build-time control is the new `terp.arch`
   **`no_manual_ownership_checks`** rule: it forbids a module from referencing the
   framework-managed `owner_id` column (to compare, filter, or set it) — catching the
   hand-rolled per-row check this seam replaces and pointing the author at `OwnedMixin` +
   the registry. `owner_id` is a *distinct* managed column from the actor stamps (which
   `no_manual_actor_stamping` already polices), so the new rule covers a genuinely new
   insecure pattern with no overlap. A read DTO may still *expose* `owner_id` (an
   annotation, not attribute access), exactly like the scope / actor columns. The rule
   is wired into `_ALL_RULES`, exported from `terp.arch` / `terp.arch.rules`, and paired
   with `test_no_manual_ownership_checks` (the self-completeness meta-test enforces the
   pairing).

8. **Opt-in, with a safe "no policy" path.** A model that composes no ownership trait
   and matches no registered predicate is **allowed** (`apply_object_authz` returns
   `True`) — object-authz is purely additive per-model, so it never silently denies a
   model that never opted in (no regression to existing modules). *Within* the opt-in it
   is fail-closed: an owned row with a real owner denies a non-owner — or an actor-less
   (out-of-request / unauthenticated) — write. An *unowned* row (`owner_id is None`, e.g.
   a system job with no bound actor) has no owner to protect, the same best-effort
   nullable boundary as the actor stamp (ADR 0012).

## Consequences

- A module gets per-row write authorization by composing one mixin; a non-owner write
  fails closed at the audited chokepoint, centrally, with no hand-rolled check to forget
  — and the hand-rolled pattern it replaces is now a build-time violation.
- The object-level / BOLA gap the review flagged is closed on the write side, completing
  the authorization matrix: endpoint authority (ADR 0016), per-row read visibility
  (ADR 0017), and per-row write authorization (this ADR), each a separate, composable
  seam.
- The kernel stays capability-agnostic: a richer ownership policy registers a predicate,
  exactly as tenancy registers a scope predicate — no `terp.core` import of a capability.
- The example app dogfoods it: the new owner-scoped **`journals`** module composes
  `OwnedMixin` and an end-to-end test proves two principals who clear the *same* role
  policy (both EDITORs) are distinguished by ownership — the owner may edit and delete an
  entry, a non-owner is refused 403 on update and delete (but may still read, since
  visibility is the separate seam). The example app and every capability stay
  arch-clean; budgets unchanged (`{}`).
- 440 tests, 100% framework line coverage.
- **Still open (sequenced):** required-vs-best-effort owner stamping for out-of-request
  writes (a future control-plane *how* knob, ADR 0011); an optional `OwnedMixin`-keyed
  read-visibility predicate shipped as sugar (today the consumer registers it
  explicitly); and a `terp inspect` view of which models are owner-scoped.
