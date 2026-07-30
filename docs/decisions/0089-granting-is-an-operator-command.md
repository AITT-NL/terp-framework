# 0089 — Granting a permission is an operator command, not an API call

Status: accepted

## Context

Terp has had per-subject permission grants since [ADR 0013](0013-permission-grants.md).
In practice almost nobody uses them. Apps built on the platform reach for the role
ladder instead: an integration that needs to export invoices gets made an admin.

That is not a preference for broad roles. It is a rational response to cost. Creating a
grant required three things at once:

- **an admin token** — so to avoid needing an admin you first had to be one, or ask
  someone who was;
- **the subject's UUID** — grants are keyed by a bare `subject_id` with no foreign key
  (deliberately, so a user, a service account and a group are all grantable the same
  way), and nobody has a UUID to hand. People have an email address, or the name of an
  integration;
- **the exact permission string** — and nothing anywhere would tell you which strings
  the app actually enforces. `terp inspect control-plane` shows the catalog, but only
  if you already knew to look, and it does not connect to a write path.

Against that, `--role admin` is one flag. Least privilege loses to a ten-second
workaround every time, and the platform's own dogfood app did exactly this.

The failure is not in the grant model. It is that the *secure* option was the
expensive one.

## Decision

Ship `terp grant add | revoke | list` as a first-class operator command, sitting
directly on the audited service rather than on the HTTP surface.

1. **A subject is named the way operators name it.** `add` / `revoke` / `list` accept a
   user email, a service-account name, or a subject UUID, and resolve it themselves.
   The UUID stays the storage key; it stops being the interface.

2. **The permission is validated against the app's own control plane**, read off the
   composed app rather than a static list — so the command can only ever offer
   permissions this app really enforces. An unknown permission is refused *with the
   whole catalog printed*, each entry annotated with its minimum role.

3. **There is no `--force`.** A grant of a string the app never checks is not a lenient
   grant, it is a silent no-op, and the person who wrote it will believe the
   integration is authorized until the moment it is not.

4. **A grant below the permission's minimum role warns loudly.** The guard checks rank
   before it checks grants, so such a row is stored but can never fire — the same
   silent no-op in a different disguise. The command says so on the spot.

5. **`revoke` deliberately does *not* validate against the catalog.** A permission the
   app has since stopped declaring is precisely the stale grant you most need to remove;
   insisting it still exists would make it unreachable. `list` marks such entries
   `[stale]` rather than hiding them.

6. **`list` includes group-inherited grants.** The question being asked is "why can this
   subject do that?", not "which rows happen to name it".

The write goes through `AccessService`, so it is audited and idempotent on the same
terms as every other mutation. No new authorization path exists: this is an out-of-band
operator seam, the same shape as `terp user create` minting the first admin.

## Consequences

- Narrowing an over-privileged integration is now cheaper than widening it, which is the
  only durable way to make least privilege stick.
- Permission strings become discoverable at the moment of use, not only by grepping.
- Two classes of silently-ineffective grant (unknown permission; rank shortfall) are
  reported instead of stored quietly.
- The command needs the app importable and the database reachable — it is an operator
  tool run next to the deployment, not a remote administration surface. That is
  intentional: it is the same trust position as running a migration.
- `ServiceAccountService.get_by_name` exists for this lookup only. Service-account names
  are not unique, so it is explicitly not a credential lookup — authentication remains
  keyed by client id.

## Alternatives rejected

- **Just document the existing API better.** The cost was never comprehension; it was
  that using it required an admin token, a UUID, and a string you could not discover.
  Documentation removes none of the three.
- **Make the HTTP endpoint nicer (accept an email, list permissions on 400).** Leaves
  the admin-token bootstrap intact, which is the cost that matters most for the first
  grant on a fresh deployment.
- **Infer grants from module specs automatically.** Turns an authorization decision into
  a guess. Who may do what is exactly the thing that should require someone to say so.
- **Refuse a grant that sits below the permission's minimum role.** Tempting, but wrong:
  granting ahead of a planned role change is legitimate, and refusing it would push
  people back to raising the role first — the behaviour this ADR exists to avoid.
  Warning keeps the operator informed without deciding for them.

Relates to ADRs 0013 (permission grants), 0016 (deny-by-default policy), 0022 (audited
write chokepoint), 0088 (service-principal credentials).
