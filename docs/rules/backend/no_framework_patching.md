# `backend/no_framework_patching`

**App code does not replace the framework's own functions**

> Generated from the catalog by `tools/generate_rule_docs.py` — do not
> edit by hand; the parity test holds this page to
> `packages/backend/arch/src/terp/arch/catalog/backend/no_framework_patching.json`.

## Why this rule exists

A check that runs the framework's code is worth what that code is: the comparison an app makes with its record of who can reach what before it serves, the guard on every route, a refusal at composition. Each can be turned off from inside the app by replacing the function that performs it, in one statement and with every other check still green, because the checks run the replaced code too. The rule refuses the statements that put something else in a function's place, for the framework and for the web stack whose route table the framework reads: an assignment to or a deletion of an attribute reached through an imported name, the same through the module registry, a looked-up module or an object's namespace, a module replaced in the registry, setting or deleting an attribute by name, and a patcher from the test toolbox. It follows a name through plain assignments in the file. Test directories are not read: replacing a function there is how a test is written.

## How Terp realises this

Behaviour is changed through the seams the framework gives: a create_app parameter (principal_provider=, middleware=, lease_store=), a ModuleSpec and its Policy, a registered scope or object-authorization predicate, a control plane. An attribute set on the app's own objects, on the result of a call (router = APIRouter(); router.tags = [...]), or on a library the framework does not read is not this rule's subject. In a test, monkeypatch.setattr and mock.patch stay the way to replace a function.

## If you really need an exception

Add a justified marker on (or immediately above) the line, and record it
in your app's escape-hatch budget:

```
# arch-allow-no-framework-patching: <reason>
```

An unjustified marker is itself a violation, and marker counts must
exactly match the checked-in budget (which can only shrink).

## What the check is not required to catch

A check precise enough to have no false positives has limits. This
rule's limits are recorded as data (its corpus's `RESIDUALS.json`), so
where detection ends is a statement rather than a guess:

- a name bound to the framework in another file (`from app.wiring import kernel`, where `kernel` is `terp.core.app`) is not required to be followed: the rule reads one file at a time, and follows a name only through plain assignments
- a reference reached through a call (`getattr(terp.core, 'app').create_app = ...`, a function that returns the module) is not required to be seen
- a module replaced in `sys.modules` under a key that is not a string literal is not required to be seen
- a file under a `tests` directory is not read, so a replacement made there and imported by app code is not required to be seen
- a change to what the framework reads instead of to its functions (`os.environ['ENVIRONMENT'] = 'local'` before the settings are read, `os.chdir` before the app is composed) is not this rule's subject
- a function changed without an assignment the source shows (through `ctypes`, or through the garbage collector's references) is not required to be seen

**These are not exemptions.** The rule governs those forms exactly as it
governs any other — a checker is simply not required to find them, so
review is the control there. The list only shrinks: closing one means
adding the corpus case that contracts it.

## Enforcement

- Checked while the app runs? No — this is a property of the written source only; the build-time check is the control, by recorded decision.
- `build-time`: `terp.arch` — `check_no_framework_patching`
