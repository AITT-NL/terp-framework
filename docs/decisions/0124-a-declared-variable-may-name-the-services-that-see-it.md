# 0124 — A declared variable may name the services that see it

- **Status:** Accepted
- **Date:** 2026-09-08
- **Relates:** [ADR 0103](0103-the-ideology-one-pattern-enforced-escapable-by-proof.md) (one pattern,
  enforced — the shape of the refusal here),
  [ADR 0106](0106-the-verify-profile-is-open-at-the-app-end.md) (the profile the check joins),
  [ADR 0110](0110-an-app-declares-which-parts-of-its-dev-topology-are-load-bearing.md) (the other
  file where an app states a truth about its own topology),
  [ADR 0116](0116-a-rule-may-run-ahead-of-its-published-catalog-entry.md) (a capability landing a
  release ahead of the half that consumes it — the same shape, a different counterpart)

---

## Context

An app declares its run-time variables in `environment.schema.json`. Terp Studio renders exactly
those declarations into a per-environment `.app.env`, and the compose profiles forward that one
file to every backend service through a shared anchor.

One file for the whole app is the problem. A variable exists because *some* service needs it, and
the services that do not need it get it anyway. Concretely: an app whose worker holds the
credentials for a foreign system — an ERP, a payment provider, a customer's SQL Server — also hands
those credentials to its `api`, `migrate` and `seed` containers, which have no use for them and a
much larger attack surface. The blast radius of a compromised api container is the whole set.

What apps did about it is the real evidence. They stopped using the seam: a second, hand-made env
file, forwarded to the one service that needed it, governed by no manifest, rendered by no tool,
visible to no check, and unmanageable from Studio. The seam that exists to be the single owner of a
value was routed around precisely for the values that matter most.

Two non-reasons, worth naming because they are the tempting ones:

**Not because one file per service is tidier.** It is not; it is more files. The reason is that
"which services see this value" is a real property of a variable that the manifest had no way to
state, so it was stated in a place nothing governs.

**Not to make Terp decide an app's topology.** The field names services the app has already
defined. This ADR adds no opinion about what services an app should have.

## Decisions

### 1. A declaration may carry `"services"`, and is then rendered per service

`{"type": "string", "services": ["worker"]}` is rendered into `.app.worker.env` instead of
`.app.env`. A declaration naming two services is rendered into **both** of their files, because
compose forwards one file per service and a value two services need has to exist in each. The name
is derived by `app_env_file_name`, and the routing rule is `rendered_files` — one function, shared
by the checker and the renderer, because two copies of that answer would be this seam's own
signature failure (a value rendered into one file and forwarded from another) with the disagreement
inside one repository instead of between two.

The dialect limits are `MAX_SERVICES = 10` and `MAX_SERVICE_NAME = 63`, with compose's own name
pattern. They are mirrored from Studio's reader like every other limit in that dialect.

### 2. The committed example stays ONE file

`.app.env.example` carries one entry per declared name, scoped or not. It is a template a **human**
maintains — the only artifact in this seam with no renderer behind it — whereas the per-service
split is a *rendering* concern. A committed example per service would multiply what a human
maintains without adding a statement, and would need its own gitignore negation to stay tracked.

The consequence is a workflow change for a scoped app, and it is the honest one: `cp
.app.env.example .app.env` produces only the shared file, so a scoped app uses `terp env init`,
which writes every file the declarations imply.

### 3. Two new offences, because they have different fixes

`unforwarded` — a service the variable is scoped to is defined but does not forward the file the
value is rendered into. The value exists and arrives nowhere. This one is easy to reach by
accident: **YAML merge does not concatenate sequences**, so a service that writes its own
`env_file:` *replaces* the shared anchor's list rather than adding to it. The template's anchor now
records that trap where an app will meet it.

`unknown-service` — the scope names a service no compose profile defines. There is nothing to
arrive at.

The second is judged across the **union** of the profiles on purpose. A service that exists only in
the workbench profile, and deliberately not in production, is correct rather than a defect — the
engine of such an app runs where the foreign system lives, not beside the control plane — and
flagging it would push the app straight back to the hand-made file this field exists to replace.

### 4. The field is refused until the deploy side can render it

This is the load-bearing decision and the reason this ADR exists rather than a changelog entry.

This repository is only ever the *reader* of a manifest. Studio renders one, and Studio pins this
framework by git ref rather than the other way round — so the dialect can grow a field here a
release before Studio can honour it. And Studio's reader **drops** a field it does not know rather
than refusing it.

Those two facts together make the naïve rollout worse than no feature. An app that scoped a
variable in that window would get a value that arrives in the workbench, where `terp env` renders
the per-service file, and silently never arrives in a Studio-managed environment, where every
declaration lands in the shared `.app.env` while the app's compose forwards a `.app.<service>.env`
that nothing wrote. Local green, production empty, nothing anywhere saying why — this seam's worst
failure mode, reached through the field added to prevent a lesser one.

So `env-seams` **refuses** a scoped declaration, by name and with the fix, while
`STUDIO_RENDERS_SCOPED_FILES` is `False`. The dialect, both checks and the whole renderer ship and
are exercised by tests; no app can depend on a path that does not exist end to end. Lifting the
window is one flag, and it may only move in the change that also:

1. moves Studio's `TERP_FRAMEWORK_REF` onto a framework release carrying this dialect, and
2. teaches Studio's three render sites — its reader's recognised-field list
   (`app_env_schema.py`), the hardcoded shared file name in its compose renderer
   (`deploy_compose.py`), and the exact-path filter its Portainer adapter strips the app env file
   by (`deploy_portainer.py`, which matches on the exact name and would therefore leave a
   `.app.<service>.env` in the compose it ships, pointing at a file nothing wrote). Whether
   Studio's other deploy targets need more than that is Studio's call to make against its own
   adapters, not a claim this ADR is in a position to enumerate.

The refusal deliberately does **not** live in `manifest_findings`. That function mirrors Studio's
reader case by case and documents itself as *every reason Studio's fail-closed reader would refuse
this manifest* — and Studio does not refuse this field, it drops it. A refusal there would make the
mirror lie about the half it mirrors. This is the framework's own gate holding an opinion Studio
does not hold, which is what a gate is for.

### 5. An app that ignores the field pays nothing

No new file, no new output, and a byte-identical green check. That is pinned by a test rather than
asserted here: a framework upgrade that reworded an app's passing gate sends its authors looking
for a change that never happened.

## Consequences

- A credential can be scoped to the service that needs it, through the governed seam, with a check
  that says so — instead of through a hand-made file no tool can see.
- `.gitignore` gains `.app.*.env` in both this repo and the template. `.app.env` is an exact name,
  not a glob: without the new line the one file that exists to hold a single worker's credentials
  would have been the one file in this seam that gets committed.
- `terp env init/set/unset/list/check` are multi-file. `set` routes by `rendered_files` rather than
  by which file a name currently sits in, so re-scoping a declaration moves its value instead of
  leaving a stale copy in the shared file; `unset` clears every file holding a name, because an
  unset whose value survives somewhere is a credential the developer believes they deleted; and
  `check` judges each name against its own file, or a correctly scoped app would read as broken in
  proportion to how many services it has.
- The window in decision 4 is visible in one constant and one test. It is the cost of the
  framework moving first, and it is bounded: the flag cannot be flipped without the Studio work,
  and the refusal names the ADR that says so.

## Alternatives considered

- **Ship the dialect without the refusal, and document the requirement.** Rejected: the failure it
  permits is silent and lands in production, and a boundary defended only by a document is one the
  next agent walks through (the lesson ADR 0110 recorded for `workbench.json`).
- **Refuse the field inside `manifest_findings`.** Rejected in decision 4 — it would break the
  one-to-one mirror with Studio's reader, which is the only thing keeping the two halves of that
  dialect honest.
- **A committed `.app.<service>.env.example` per service.** Rejected in decision 2: more files for
  a human to maintain, a gitignore negation to keep them tracked, and no statement the single
  example does not already make.
- **Let a service's `env_file:` merge with the anchor's.** Not ours to choose — compose's YAML
  merge does not concatenate sequences. Hence the `unforwarded` check and the template comment.
