# `backend/no_manual_lease_columns`

**Application tables do not re-derive leases; expiring custody of work is a platform primitive**

> Generated from the catalog by `tools/generate_rule_docs.py` — do not
> edit by hand; the parity test holds this page to
> `packages/backend/arch/src/terp/arch/catalog/backend/no_manual_lease_columns.json`.

## Why this rule exists

Exclusive, time-bounded custody of a unit of work belongs to the platform, not to each table that needs it. An application table must not declare its own lease bookkeeping — a holder column paired with an expiry, a heartbeat stamp, or an equivalent claim deadline — because the hand-rolled form reliably omits the part that makes a lease safe. Expiry alone establishes that a holder may have died; it does not prevent that holder, if it merely paused, from waking after its deadline and completing work a successor has already taken over. A conformant platform supplies custody that is fenced (a monotonic grant token every write is matched against, so a superseded holder is refused rather than trusted), taken atomically with the state change it guards, renewable by a heartbeat that fails closed when the grant is lost, and recoverable — an expired grant must trigger the owning domain's declared recovery, so work a crashed holder abandoned returns to a retryable state instead of requiring manual repair. Platform-owned delivery infrastructure that claims batches of its own rows, and needs no domain recovery, is a reviewed exception rather than an application pattern.

## How Terp realises this

LeaseResource names the leased row or domain mutex; hold_lease / acquire_lease take it through the configured LeaseStore, LeaseGuard.heartbeat renews it and raises when the grant was lost, and register_lease_reaper declares the per-kind recovery an expiry triggers. terp-cap-leases keeps the grants in the app's own database so a claim commits with the row change it protects.

## If you really need an exception

Add a justified marker on (or immediately above) the line, and record it
in your app's escape-hatch budget:

```
# arch-allow-no-manual-lease-columns: <reason>
```

An unjustified marker is itself a violation, and marker counts must
exactly match the checked-in budget (which can only shrink).

## What the check is not required to catch

A check precise enough to have no false positives has limits. This
rule's limits are recorded as data (its corpus's `RESIDUALS.json`), so
where detection ends is a statement rather than a guess:

- a holder/heartbeat pair under other column names (`worker_id` + `last_seen_at`) is not required to be recognised as a hand-rolled lease: the check matches a fixed set of column spellings on a table model, not the custody shape

**These are not exemptions.** The rule governs those forms exactly as it
governs any other — a checker is simply not required to find them, so
review is the control there. The list only shrinks: closing one means
adding the corpus case that contracts it.

## Enforcement

- Checked while the app runs? No — this is a property of the written source only; the build-time check is the control, by recorded decision.
- `build-time`: `terp.arch` — `check_no_manual_lease_columns`
