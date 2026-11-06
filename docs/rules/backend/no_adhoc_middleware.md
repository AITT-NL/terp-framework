# `backend/no_adhoc_middleware`

**App code never wires HTTP middleware itself; security is centralized**

> Generated from the catalog by `tools/generate_rule_docs.py` — do not
> edit by hand; the parity test holds this page to
> `packages/backend/arch/src/terp/arch/catalog/backend/no_adhoc_middleware.json`.

## Why this rule exists

Cross-cutting HTTP security (headers, CORS, rate-limit, body-size, request-id) is declared once as central security configuration and installed at composition. A module that registers middleware itself — by call, decorator, or subclassing — is assembling a security posture outside that single control plane.

## How Terp realises this

SecurityConfig declared once and installed by create_app; add_middleware(...), the @app.middleware("http") decorator, and BaseHTTPMiddleware subclasses are refused in app modules. On the composed app both registration spellings raise BootError at runtime; create_app's middleware parameter is the one sanctioned composition seam.

## If you really need an exception

Add a justified marker on (or immediately above) the line, and record it
in your app's escape-hatch budget:

```
# arch-allow-no-adhoc-middleware: <reason>
```

An unjustified marker is itself a violation, and marker counts must
exactly match the checked-in budget (which can only shrink).

## Enforcement

- Checked while the app runs? Yes — the framework also enforces this while the app runs (fail closed).
- `build-time`: `terp.arch` — `check_no_adhoc_middleware`
- `runtime`: `terp.core` — `freeze_app_middleware_registration`
