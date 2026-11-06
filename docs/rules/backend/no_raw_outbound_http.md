# `backend/no_raw_outbound_http`

**App modules do not import raw HTTP clients; outbound calls use a capability**

> Generated from the catalog by `tools/generate_rule_docs.py` — do not
> edit by hand; the parity test holds this page to
> `packages/backend/arch/src/terp/arch/catalog/backend/no_raw_outbound_http.json`.

## Why this rule exists

Directly importing an HTTP client library — or the lower-level socket / protocol primitives that reach the same network, the standard library's mail client among them — makes SSRF protection, allowlists, encryption and certificate checks, egress auditing, and timeout policy a per-call-site choice. Outbound traffic belongs behind a declared capability that centralizes those controls. As a security rule this also scans test and migration files inside a module — they are importable code, so they are application surface too.

## How Terp realises this

httpx / httpx2 / requests / urllib.request / urllib3 / aiohttp imports and the socket / http.client escape routes are refused in app modules, and so is smtplib; outbound HTTP goes through a declared egress capability, and outbound mail through a declared mail capability.

## If you really need an exception

Add a justified marker on (or immediately above) the line, and record it
in your app's escape-hatch budget:

```
# arch-allow-no-raw-outbound-http: <reason>
```

An unjustified marker is itself a violation, and marker counts must
exactly match the checked-in budget (which can only shrink).

## What the check is not required to catch

A check precise enough to have no false positives has limits. This
rule's limits are recorded as data (its corpus's `RESIDUALS.json`), so
where detection ends is a statement rather than a guess:

- dynamic import (`importlib.import_module("httpx")`) is not required to be seen as an import

**These are not exemptions.** The rule governs those forms exactly as it
governs any other — a checker is simply not required to find them, so
review is the control there. The list only shrinks: closing one means
adding the corpus case that contracts it.

## Enforcement

- Checked while the app runs? No — this is a property of the written source only; the build-time check is the control, by recorded decision.
- `build-time`: `terp.arch` — `check_no_raw_outbound_http`
