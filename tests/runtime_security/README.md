# Runtime security scenarios

`runtime-security.fixtures.json` holds the runtime security cases this framework proves by
running them, in the format `runtime-security.schema.json` defines. They came from the Terp
Standard (terp-spec 0.43.0) and live beside the tests that run them since ADR 0203.

A source rule establishes what a checker recognises. It does not establish that the running
framework preserves the authority or transaction boundary the rule describes. The cases do:

- **Every applicable case is executed.** A case names the capability that makes it
  applicable, the related source rules where they exist, setup and exercise steps,
  observable outcomes, and negative controls. A capability the framework does not offer is
  recorded as not applicable, with its reason; an implemented capability whose test was
  skipped, could not run or failed is never recorded as passed. An expected outcome is a
  requirement, not an invitation to replace a difficult behaviour with a source inspection.
- **Evidence names the case and a runnable test.** `docs/security-boundaries.md` is the index:
  a row per case, naming each test that runs it. `tests/architecture/test_runtime_security_evidence.py`
  holds the index to these cases in both directions and checks that every named test exists.
- **A denial is tested where it is visible.** At the externally visible boundary and, where it
  matters, against final persistent state: an exception followed by a later commit is one
  operation sequence. An interleaving may be scheduled deterministically, but it uses real
  persistence and service operations, never a mocked authorization decision or commit.
  External providers may be simulated at their transport boundary. Every refusal case keeps a
  valid control, so rejecting all work cannot pass.

A case's claim is no wider than the behaviour it pins. Where the framework does not promise
job-wide atomicity, it states its actual transaction and retry contract. A resolver that
cannot be cancelled states that limitation instead of claiming a hard elapsed bound. Custody
bookkeeping and destination fencing are separate claims: a lease token is validated atomically
at the protected transition, and a remote write needs a fence or equivalent serialization in
that destination.

This evidence is separate from line coverage. A case is added here, its row in the index and
its tests in the same change.
