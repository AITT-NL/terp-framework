# 0163 — A test suite signs with a key nobody wrote down

- **Status:** Accepted and implemented. `terp.core.testing` ships `terp_signing_key`, an
  autouse session fixture. Held by `tests/architecture/test_signing_key_fixture.py`.
- **Date:** 2026-09-28
- **Relates:** [ADR 0076](0076-webhook-secret-sealing-jwt-rotation-audit-append-only-and-upload-sniffing.md) (the `SECRET_KEY` it stands in for
  during a test run), [ADR 0069](0069-verified-database-dialects-and-schema-direction.md) (the other
  fixtures this plugin ships so an app's suite gets them without writing them)

---

## Context

The development `SECRET_KEY` is `"changethis"`, ten bytes. That is deliberate: production
refuses it both by name and by length, so the default can never be the key a deployment signs
with. But pyjwt 2.13 warns on every token signed with an HMAC key under 32 bytes, so a suite
that signs tokens is a suite full of `InsecureKeyLengthWarning`, and a project that turns
warnings into errors cannot run it at all.

Every suite that signs tokens therefore set a key of its own — the framework's example app at
import time, with a comment explaining the warning, and an app built on Terp in each of its
signing test packages. A key written into a test file is a credential-shaped literal, and the
template's secret scan flagged exactly that in an app, which then carried a
`.gitleaksignore` entry for a value that authenticates nothing. The framework's own repository
carries entries of the same kind.

## Decision

**The shipped pytest plugin installs a random key for the session.** `terp_signing_key` is an
autouse fixture of session scope in `terp.core.testing`, so every project that depends on
`terp-core` gets it with no conftest line, as it gets runtime isolation. At session start, if
`settings.SECRET_KEY` is still a placeholder, it is replaced with `secrets.token_urlsafe(48)`;
at session end the original is put back.

- **Random, not a fixed long literal**, because a literal anywhere in a repository is what the
  scan flags, and because nothing may depend on the key's value.
- **Only while the default is in place.** A key the environment sets is the suite's own
  decision and is left alone, as is one a test later sets with `monkeypatch`, which runs after
  the session fixture and wins.
- **Session scope**, so a session-scoped fixture that mints a token signs with the same key a
  test later verifies with.

**Not taken: lengthening the default.** A 32-byte placeholder would silence pyjwt in every
process, not only in tests, and production would then refuse it by name alone. Two independent
reasons to refuse the default are worth more than a quiet development log.

**Not taken: an opt-in fixture.** One the suite has to request is one an agent does not know to
request, and the next suite would copy the example app's hard-coded key, which is the pattern
this removes.

## Consequences

- An app's suite can delete a key it set only to silence the warning, and the `.gitleaksignore`
  entry that key needed.
- The framework's example app and its full-stack test no longer set one. Tests that need a
  *known* key — to hand-craft a token, or to exercise rotation — still set their own.
- What it does not cover: a token minted at import time, before the session starts, is signed
  with whatever key was in force then. Nothing in the framework's suites does that.
