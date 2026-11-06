# `backend/errors_use_the_typed_envelope`

**An application raises the platform's typed errors, not the web framework's raw HTTP error**

> Generated from the catalog by `tools/generate_rule_docs.py` — do not
> edit by hand; the parity test holds this page to
> `packages/backend/arch/src/terp/arch/catalog/backend/errors_use_the_typed_envelope.json`.

## Why this rule exists

A platform that promises one error envelope has to be the only thing that builds it. When a module raises the web framework's own HTTP error type it names a status code and a message directly, and the envelope the platform assembles for every other failure - a stable machine-readable code, a consistent body shape, a single place where messages are worded and localized - is bypassed for that one response. The client then sees two error formats from one API and cannot tell which it is holding, so it either parses both or handles neither. The damage is cumulative rather than dramatic: each improvised status/message pair is defensible on its own, and together they are an undocumented second contract that no schema describes and no test covers. Raising the platform's typed error instead keeps the status, the code and the body in one place, where they can be changed once.

## How Terp realises this

Application modules raise a terp.core.errors.AppError subclass (NotFoundError, ConflictError, PermissionDeniedError, ValidationFailedError, ...); `raise HTTPException(...)` - FastAPI's or Starlette's - is refused. A route that must attach a response header the envelope does not carry (a WWW-Authenticate challenge, say) takes the opt-out marker with that reason.

## If you really need an exception

Add a justified marker on (or immediately above) the line, and record it
in your app's escape-hatch budget:

```
# arch-allow-errors-use-the-typed-envelope: <reason>
```

An unjustified marker is itself a violation, and marker counts must
exactly match the checked-in budget (which can only shrink).

## What the check is not required to catch

A check precise enough to have no false positives has limits. This
rule's limits are recorded as data (its corpus's `RESIDUALS.json`), so
where detection ends is a statement rather than a guess:

- an error constructed under an alias (`from fastapi import HTTPException as ApiError`) is not required to be resolved back to the framework's HTTP error

**These are not exemptions.** The rule governs those forms exactly as it
governs any other — a checker is simply not required to find them, so
review is the control there. The list only shrinks: closing one means
adding the corpus case that contracts it.

## Enforcement

- Checked while the app runs? No — this is a property of the written source only; the build-time check is the control, by recorded decision.
- `build-time`: `terp.arch` — `check_errors_use_the_typed_envelope`
