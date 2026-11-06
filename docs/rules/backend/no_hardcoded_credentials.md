# `backend/no_hardcoded_credentials`

**App modules do not hard-code credentials or recognizable secret tokens**

> Generated from the catalog by `tools/generate_rule_docs.py` — do not
> edit by hand; the parity test holds this page to
> `packages/backend/arch/src/terp/arch/catalog/backend/no_hardcoded_credentials.json`.

## Why this rule exists

A credential-shaped assignment to a non-empty string literal is almost always a secret that should come from sealed config / environment wiring, not source. The rule also rejects common high-confidence secret literal formats anywhere in a module so leaked keys are caught even when assigned to a bland variable name. As a security rule this also scans test and migration files inside a module — a real secret is a leak wherever it is committed. Four shapes are exempt, and each is decided on the VALUE rather than by softening the name list — narrowing the names would lose real findings. (1) An enum member whose literal is its own name (SECRET_REFERENCE = "secret_reference") is vocabulary, not secret material. (2) A name the module itself uses as an environment key (TOKEN_ENV = "SOME_API_TOKEN", then os.environ[TOKEN_ENV]) is the NAME of a credential, stated in code. (3) A _ENV / _PATH / _HEADER name whose value matches the grammar that suffix implies, where each grammar must REFUSE a password to qualify: an environment variable's name is multi-word, a path starts at a root, and a header's name is either hyphenated or one of the registered single words (Authorization, Authentication, Cookie, Origin, Referer) — a password does not happen to equal one, and excluding them refused the header an app wiring a client actually names. A plain identifier pattern does not qualify, because hunter2 is a valid identifier. (4) A _FIELD / _COLUMN / _PARAM / _REFERENCE name whose value spells the name itself (CLIENT_SECRET_FIELD = "client_secret") — the enum case generalised, because a field name and a password are the same shape and only the equality is evidence. (5) A _FORMAT / _TEMPLATE / _PATTERN name whose value carries a substitution slot is a wire format: the part that would be secret is the part that is not there. The SUFFIX is required and the value alone is not enough — a generated password or a pasted service-account JSON contains a brace pair too, so a value-only test exempts the secrets it was meant to catch. None of them weakens the literal-format scan, which reads every string whatever name it is bound to, so a real key inside any of these shapes is still caught.

## If you really need an exception

Add a justified marker on (or immediately above) the line, and record it
in your app's escape-hatch budget:

```
# arch-allow-no-hardcoded-credentials: <reason>
```

An unjustified marker is itself a violation, and marker counts must
exactly match the checked-in budget (which can only shrink).

## Enforcement

- Checked while the app runs? No — this is a property of the written source only; the build-time check is the control, by recorded decision.
- `build-time`: `terp.arch` — `check_no_hardcoded_credentials`
