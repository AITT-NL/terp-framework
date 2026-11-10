# `backend/module_list_is_unconditional`

**The modules an app is composed of are not decided under a condition**

> Generated from the catalog by `tools/generate_rule_docs.py` — do not
> edit by hand; the parity test holds this page to
> `packages/backend/arch/src/terp/arch/catalog/backend/module_list_is_unconditional.json`.

## Why this rule exists

An app is composed from a list of modules, and the access check records who can reach each route by composing the app wherever the check runs. A module added to that list under a condition (an environment variable, a setting, whether an object is absent) is mounted where the condition holds and nowhere else, so the app serves routes in one environment that the check, run in another, never saw: the surface a reviewer approved is not the surface deployed. The rule follows the list the composition is handed back through the file that builds it and refuses each place it is decided under a condition: a conditional expression among its elements, a change to it under a branch, a loop or an error handler, a comprehension or a filter that drops elements, a helper that returns it under a condition, and the same through a parameter to the function's callers in that file. The compliant form mounts the module always and lets its routes refuse while it is not configured.

## How Terp realises this

create_app([login_module, me_module, oidc_module], ...) with every module named in every environment; a module whose configuration is per environment is built always (build_oidc_module(providers, ..., allow_no_provider=True)) and answers a typed refusal while it has none.

## If you really need an exception

Add a justified marker on (or immediately above) the line, and record it
in your app's escape-hatch budget:

```
# arch-allow-module-list-is-unconditional: <reason>
```

An unjustified marker is itself a violation, and marker counts must
exactly match the checked-in budget (which can only shrink).

## What the check is not required to catch

A check precise enough to have no false positives has limits. This
rule's limits are recorded as data (its corpus's `RESIDUALS.json`), so
where detection ends is a statement rather than a guess:

- a module list built in another file than the one that calls `create_app` (imported as a name, or returned by an imported function) is not required to be followed: the rule reads one file at a time
- a module object that is itself `None` under a condition (`oidc_module = build(...) if ISSUER else None` in another file) and is then named unconditionally is not required to be seen: `create_app` refuses a list entry that is no module, so the form fails at composition where the condition does not hold
- a list chosen by a boolean operator (`modules or defaults`) or by an index into a table of lists is not required to be seen

**These are not exemptions.** The rule governs those forms exactly as it
governs any other — a checker is simply not required to find them, so
review is the control there. The list only shrinks: closing one means
adding the corpus case that contracts it.

## Enforcement

- Checked while the app runs? Not yet — a runtime control is planned; the gap is explicit and tracked.
- `build-time`: `terp.arch` — `check_module_list_is_unconditional`
