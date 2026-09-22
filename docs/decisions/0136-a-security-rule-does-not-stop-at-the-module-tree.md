# 0136 — A security rule does not stop at the module tree

- **Status:** Accepted and implemented. `no_hardcoded_credentials`, `no_dynamic_sql`,
  `no_raw_outbound_http` and `no_manual_table_schema` iterate the whole scanned root;
  `_module_under` documents that it is a *shape* filter and not a scope; each rule's
  harness test pins a violation placed outside `modules/`. Held by
  `tests/architecture/test_arch_harness.py` and `tests/architecture/test_capability_arch.py`.
- **Date:** 2026-09-15
- **Relates:** [ADR 0006](0006-two-layer-enforcement.md) (two-layer enforcement, whose
  build-time half this is), [ADR 0084](0084-runtime-applicability-is-recorded-not-folklore.md)
  (a rule's properties are recorded, not assumed), [ADR 0103](0103-the-ideology-one-pattern-enforced-escapable-by-proof.md)
  (escapable by proof — which is how the four legitimate cases this surfaced are handled)

## Context

Four rules opened with the same line:

```python
for path in iter_python_files(root, skip_dirs=_SECURITY_SKIP_DIRS):
    if _module_under(path, package) is None:
        continue
```

`_module_under` returns the `modules/<name>` a file belongs to. It reads like a package
filter — it even takes `package` — but it consults only the `modules/` path segment and
ignores the argument entirely. So the line means *skip every file that is not inside a
module*, and the four rules it guarded were:

- `no_hardcoded_credentials`, whose docstring says "a real secret is a leak wherever it
  is committed";
- `no_dynamic_sql`, the SQL-injection guard;
- `no_raw_outbound_http`, the SSRF guard that sends authors to the egress capability;
- `no_manual_table_schema`, whose sibling `table_models_use_base_table` has always
  scanned the whole tree.

Each had reasoned carefully about one scope question and got it right — all four opt into
`_SECURITY_SKIP_DIRS`, so they descend into `tests/` and `migrations/` on the argument
that those are importable Python and therefore application surface. That argument does
not stop at `modules/`, and the copied preamble did.

Two consequences, and the second is the one that made this worth an ADR.

**In an application**, everything outside the module tree was exempt: the composition
root, a shared helper package, a sibling deployable — a worker, a publisher, a CLI. That
is not a marginal remainder. It is where a raw HTTP client is actually reached for, where
a bootstrap credential is actually written, and where SQL is actually assembled by hand,
precisely because those files are not the ones anybody thinks of as "a module".

**In this repository**, `tests/architecture/test_capability_arch.py` runs the consumer
harness over every shipped capability and asserts `check_app(cap_root) == []`. No
capability path contains a `modules/` segment. So for these four rules the assertion
passed over an empty file set — a green assertion that proved nothing, in the suite
written to stop capabilities escaping the harness. Widening the scope found four real
things immediately: the egress client and the OIDC client import `httpx`, the webhooks
delivery job imports `httpx`, and the example app's dev seed holds a demo password —
each of which had been true and unreported for as long as the suite had existed.

The harness tests had gone further than silence. Three of them asserted the gap as
intended behaviour:

```python
# The rule follows app-module scope, not arbitrary helper files.
_write(app, "helpers/sql.py", "stmt = text(query)\n")
assert check_no_dynamic_sql(app) == []
```

A test can only defend the behaviour it describes, and this one described the hole.

## Decision

**A rule's scope follows what it is about, and a security rule is not about a
directory.** The four rules drop the `modules/` gate and iterate the whole scanned root.
`_module_under` stays exactly as it is for the rules that are genuinely about a module's
*shape* — one module may not import another; a grantable module must be named; a
module's tables need its migrations — because for those, "not in a module" is the right
answer rather than a skipped file.

**`_module_under` says what it is.** Its docstring now states that `package` is accepted
for call-shape uniformity and deliberately not consulted, names the two kinds of rule,
and records which four misread it. The parameter stays: removing it would touch every
call site to no benefit, and the misreading was of the *semantics*, which is what the
docstring now fixes.

**Every widened rule pins a violation outside `modules/`.** The three tests that asserted
the gap now assert the opposite, and `no_manual_table_schema` gains the case it never
had. That is the assertion that would have caught this, so it is the assertion that has
to exist.

**The four things this surfaced are escaped by proof, not by narrowing the rule.** The
egress client is the seam the rule names and cannot reach the network through itself; its
`ssrf.py` resolves names in order to *check* them; the OIDC client speaks a protocol to an
operator-configured endpoint; the webhooks sender receives a target the egress capability
has already resolved and pinned; the example seed's password is meant to be published.
Each carries a justified `# arch-allow-no-raw-outbound-http` / `-no-hardcoded-credentials`
marker under its own checked-in budget. `egress` and `oidc` therefore leave
`_CLEAN_CAPS` for `_BUDGETED_CAPS` — not because they got worse, but because the harness
can now see them at all.

## Consequences

**Adopting this release will fail some applications' gate, and that is the point.** A
credential in a seed script, a `httpx` import in a worker, an f-string `text(...)` in a
composition root: all were always violations of a rule the app declared it was holding
itself to, and none were reported. The fix is the same one the framework has always
offered — move the code behind the seam, or justify the exception with a marker and
budget it.

**The name-shaped rules will produce false positives at the new reach.**
`no_hardcoded_credentials` matches on a credential-shaped *name*, so `token_type =
"bearer"` and `TOKEN_ISSUER = "terp.auth"` — an OAuth 2.0 response field and a public
registered claim value — are both flagged, and both are in this repository's own auth
capability. They take markers. Loosening the heuristic to recognise "a property *of* a
token rather than a token" was considered and refused: a narrower matcher is a weaker
guard everywhere, and the governed opt-out already exists for exactly this and leaves the
judgement visible in the diff.

**The capability suite's assertion means something now.** `check_app(cap_root) == []`
covers every rule for every capability rather than every rule except the four that
mattered most.
