# 0213 — App code does not replace the framework's own functions

- **Status:** Proposed on 2026-11-11. The owner approved building it on 2026-11-11, as the
  change after the startup comparison (ADR 0212).
- **Date:** 2026-11-11.
- **Relates:** [ADR 0212](0212-an-app-compares-the-routes-it-serves-with-its-record-before-it-serves.md)
  (the comparison this protects, and where it says what it leaves open),
  [ADR 0208](0208-a-route-holds-every-timestamp-it-reads-to-its-offset.md) (route
  registration is frozen after composition) and
  [ADR 0084](0084-runtime-applicability-classification.md) (a rule's runtime half is
  classified).

## Decision

A rule, `no_framework_patching`, refuses the statements in app code that put something else
in the place of a function of the framework, or of the web stack whose route table the
framework reads. It holds for every root that ships, an app and a companion alike, and it
does not read test directories.

## Context

A check that runs the framework's code is worth what that code is. The comparison an app
makes with its `authz-surface.json` before it serves (ADR 0212) runs in the app's own
process, and so does every guard and every boot refusal. Python lets any module rebind a
name in any other: `surface.startup_refusal = lambda *args, **kwargs: None` is one line,
and after it the app starts whatever it serves. The check before release composes the same
app, runs the same replaced function, and stays green.

That is deliberately deceptive code and it is visible in the diff. A reviewer, or an agent
reading a diff, should not have to recognise it by eye among the changes around it.

## What changes

1. **The rule.** It refuses, in a file under an app or companion root:
   - an assignment to, or a deletion of, an attribute reached through a name the file
     imports from `terp`, `fastapi` or `starlette`: a module's function, a class's method,
     a function's `__code__`, the framework's settings object;
   - the same through `sys.modules[...]`, `importlib.import_module(...)`, `__import__(...)`,
     an object's `__dict__` or `vars(...)`;
   - a module of those packages put into, or taken out of, `sys.modules`;
   - `setattr`, `delattr` and their `__setattr__` forms on such a name;
   - `mock.patch` of such a name, and a patcher's own `setattr` given one as a dotted
     string.

   It follows a name through plain assignments in the file (`kernel = terp.core.app`), in
   any order. The result of a call is not the framework: `router = APIRouter()` then
   `router.tags = [...]` is not refused, nor is state set on the composed app.
2. **The web stack is included** because the startup comparison walks FastAPI's route
   table with FastAPI's own function. Replacing that function hides a route from both
   halves as surely as replacing the comparison.
3. **Test directories are not read.** Replacing a function there, with `monkeypatch` or
   `mock.patch`, is how a test is written, and the framework keeps that seam open on
   purpose (the dependency-override map stays writable in local for the same reason).
4. **It ships whole:** the check, its catalog entry, six violation and two compliant corpus
   cases, its residuals, its rule page and its recipe in `terp guide capability`. It has
   the usual marker and budget.
5. **Its runtime half is not applicable, with the reason recorded.** The running system
   cannot tell the function that shipped from its replacement without a second copy to
   compare it with, and whatever compared them would be as replaceable. The evidence that
   the shipped code is what runs is outside the process: `sign` holds a release's image to
   the tree file by file and to the lock distribution by distribution (ADR 0187), and the
   tree is what this rule reads.

## What it does not do

The rule's residuals, recorded with its corpus:

- It does not follow a name into another file, or through a call that returns the module.
- It does not see a module replaced in `sys.modules` under a key that is not a literal.
- It does not read a `tests` directory, so a replacement made there and imported by app
  code is outside it.
- It does not refuse a change to what the framework reads instead of to its functions:
  `os.environ["ENVIRONMENT"] = "local"` before the settings are read, or `os.chdir` before
  the app is composed, both turn the startup comparison off. Whether app code may write the
  framework's own environment variables or change the working directory is a rule of its
  own, not decided here.
- It does not see a function changed without an assignment the source shows.

A cross-check that reads the routes the source declares without running it (ADR 0212,
*What it does not do*) stays deferred.

## Consequences

- An existing app that replaces a framework function outside its tests turns red on this
  release, with the seam to use in the message. None of the template, the example app and
  the reference app does.
- The rule registry may not grow, so the root-kind definitions move to
  `terp.arch.rules._root_kinds`; the table of which rule is held over which root stays in
  the registry, one row per rule.
