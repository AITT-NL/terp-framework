# 0165 — The test client drives httpx2, and the egress rule refuses it

- **Status:** Accepted and implemented. The template's and the repository's test dependencies
  install `httpx2`; `no_raw_outbound_http` refuses it. Held by
  `tests/architecture/test_arch_harness.py`. The terp-spec catalog entry's wording and a corpus
  case follow in that repository (see Consequences).
- **Date:** 2026-09-28
- **Relates:** [ADR 0117](0117-the-egress-capability-the-rule-was-already-naming.md) (the egress
  capability, and `httpx` as the dependency of exactly one distribution),
  [ADR 0136](0136-a-security-rule-does-not-stop-at-the-module-tree.md) (the rule's reach, tests
  included)

---

## Context

`httpx2` is the continuation of `httpx` under a new name, maintained by Pydantic because the
original has seen little recent activity, security updates included. Starlette 1.3 moved its
test client to it: `starlette.testclient` imports `httpx2` first and falls back to `httpx` with
a `StarletteDeprecationWarning`, and says the fallback will go. The template's test dependencies
installed `httpx`, so every generated project printed that warning on every run — and would
fail to import FastAPI's `TestClient` at all once a lockfile refresh pulled in a starlette
without the fallback. `terp-core` asks for `fastapi>=0.115` with no ceiling, so that refresh is
ordinary.

Moving the test client to `httpx2` exposed a gap the other way. `no_raw_outbound_http` refuses
`httpx`, `requests`, `urllib3`, `aiohttp`, `socket` and the standard library's HTTP and mail
clients, and not `httpx2`: the same client, API for API — starlette imports it as
`import httpx2 as httpx` — under a name the rule had never heard of. With the template now
installing it, it would be in every generated project's environment, one import away from
the network with no allowlist, no SSRF check and no timeout policy.

## Decision

1. **Test dependencies install `httpx2`.** The template's dev group lists `httpx2>=2.0`, the
   floor starlette's own `full` extra names, instead of `httpx`. This repository's dev group
   adds `httpx2` beside `httpx`, which stays because a release tool and several tests call
   `httpx` directly.
2. **`no_raw_outbound_http` refuses `httpx2`** as it refuses `httpx`, root and submodules, with
   the same remedy: the egress capability.

## Consequences

- A generated project's suite runs without the deprecation warning, and keeps importing
  `TestClient` when starlette removes the fallback.
- An app module that imports `httpx2` is refused where it was silently allowed. That is a
  refusal of a posture an app could already hold, and the release notes say so.
- **In terp-spec:** the catalog entry's `reference` names the refused clients, so it gains
  `httpx2`, and a violation case holds the implementation to it. The framework's pinned spec
  release does not carry that case until the spec releases, and the spec's certification pin
  must move to the framework commit that refuses it — the circular procedure `docs/RELEASING.md`
  describes.
- **Recorded, not decided:** the egress capability itself still drives `httpx` at runtime. It
  is the one distribution on the outbound path, and `httpx2` exists because upstream `httpx`
  has slowed down, security fixes included. Moving the capability is a change to the transport
  every outbound call goes through, with its own pinning and redirect behaviour to re-verify,
  and it is a separate decision rather than part of a test-dependency fix.
