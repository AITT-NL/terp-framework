# 0212 — An app compares the routes it serves with its record before it serves

- **Status:** Proposed on 2026-11-11. The owner approved building it on 2026-11-11, with
  the rule that app code may not patch the framework's own functions as the change after
  it, and a cross-check that reads the source without running it left for later.
- **Date:** 2026-11-11.
- **Amends:** [ADR 0139](0139-who-can-reach-what-is-pinned-not-merely-reportable.md) and
  [ADR 0209](0209-a-new-app-pins-who-can-reach-what-and-the-check-names-each-widening.md):
  the committed record gains a second reader, the running app.
  [ADR 0211](0211-the-modules-an-app-mounts-do-not-depend-on-a-setting.md): the runtime half
  it deferred is this one. [ADR 0187](0187-in-the-generated-state-the-framework-renders-the-build-files.md):
  the backend image carries one file outside its two source roots and its environment.
- **Relates:** [ADR 0208](0208-a-route-holds-every-timestamp-it-reads-to-its-offset.md)
  (route registration is frozen after composition, so what is compared is what is served)
  and [ADR 0121](0121-a-module-role-is-an-assignment-not-a-policy.md) (every allowance in
  the access model is the guard's own answer, replayed).

## Decision

When `create_app` has composed an app and frozen its routes, it reduces those routes with
the reduction the `authz-surface` check uses and compares the result with
`authz-surface.json` in the working directory. Outside `ENVIRONMENT=local` any difference
is a `BootError` and the app does not serve. In local development it is a warning. The
production image the deployment generator writes carries the record, and `sign` holds it
to the tree.

## Context

The check before release (`terp verify --only authz-surface`) judges an app by running it:
it imports the app, composes it, and compares what it composed with the committed record.
The code being judged runs during its own judgement. A change can notice that it is being
inspected, by the command line, an environment variable or a database that is not there,
and leave a route out or loosen a policy only then. The check reports that nothing
widened, and the deployed app serves more.

That takes deliberately deceptive code, from a malicious contributor or from an agent
tricked into writing it, and the code is visible in the diff. The honest form of the same
gap, a module mounted only where a setting is present, was removed by ADR 0211. What
remained is that nothing compared the record with the app that actually runs.

Every check that runs the app's own code shares this weakness. The one place where the
code cannot show something other than what it serves is the process that serves it.

## What changes

1. **The surface belongs to the core.** `terp.core.authz_surface` holds the record's name,
   the reduction (`authz_surface`), the walk over the composed route table
   (`served_routes`), the routes a record cannot hold (`unplaced_routes`, `unseen_routes`)
   and the comparison at startup. `terp.core.authz_changes` holds the sentences that name
   each difference and whether it widens. Both were in `terp-cli`; the command line keeps
   the verdict `terp verify` gives and the access graph `terp inspect access` prints. One
   reduction serves both halves, because a second one would be a second answer to "what
   does this app serve".
2. **`create_app` compares, last.** After the routes are frozen, so nothing can be added
   behind the comparison. It refuses on:
   - any difference between the record and the composed surface, in either direction: a
     route the record does not hold, a route the app no longer serves, a changed
     requirement, a changed module policy, a changed role ladder or permission floor;
   - a route the record cannot hold: one on a router included inside a module's router,
     and a method and path that two routes serve. The check before release refuses these
     for the same reason, with the same sentences;
   - a record that cannot be read as a surface.

   The refusal names the first five differences, widenings first, and counts the rest. It
   names both ways out: write the record again in a change a reviewer sees, or find what
   composes the app differently where it is deployed.
3. **In local development it warns.** A developer who adds a route serves it at once and
   writes the record in the same change. An empty record is passed over there without a
   word, because the command that writes the record redirects into it and the shell empties
   the file before that command composes the app. Everywhere else an empty record is an
   unreadable one, and refused.
4. **An app without a record is not compared**, as the check before release skips an app
   that never adopted it. Outside local the log says so, and it says so when the record
   matches, so a process that was not compared does not read as one that was.
5. **The image carries the record.** `Dockerfile.prod` copies `authz-surface.json` to
   `/srv`, the working directory of every process of the image, with a pattern so an app
   that has no record copies nothing. `sign` accepts that one file in `/srv` outside the
   source roots and the environment only when it is the tree's, byte for byte. It refuses
   an image that lacks the record when the tree holds one and the image's own Dockerfile
   copies it: a line in `.dockerignore` would otherwise turn the comparison off with every
   other answer unchanged.
6. **`module_list_is_unconditional` has its runtime half.** The catalog recorded it as
   `deferred`, naming this seam. It is now `required`, with this comparison as the control.

## What it costs

One walk over the composed routes and the role ladder. Measured on the reference app, 8
modules and 41 endpoints: 1.1 ms for the comparison, against about 1.3 s to import and
compose the app.

## What it does not do

- **It does not stop code that sets out to defeat it from inside the process.** The
  comparison runs in the app's own process, so code that changes the working directory
  before it composes, removes the record, or replaces the comparison can still get through.
  Each is visible in the diff. A rule that refuses app code patching the framework's own
  functions is the next change. A cross-check that lists the routes the source declares
  without running it would close more, at the price of refusing dynamic ways to declare
  routes, and is deferred.
- **It does not check an image that was built without the record.** A Dockerfile rendered
  before this release, or an app's own, builds an image that starts as it did before. The
  log line of point 4 is what tells the two apart.
- **It does not keep the check before release itemised outside local.** Where
  `ENVIRONMENT` is not `local`, composing an app that differs from its record refuses
  first, so `terp verify` reports that the app could not be composed, with the differences
  in the refusal. The check runs under local, the default, wherever it is run today.
- **It compares authority, not behaviour.** What a route does, and the kernel routes
  outside `/api/v1`, are not in the record.

## Consequences

- A deploy whose record does not match what the app serves fails to start, where before it
  ran. A tool that keeps the record in step with every change sees this only on real drift
  or deception. An app maintained by hand keeps its record current, which the check before
  release already requires.
- Every process of the image composes the app, so a worker or a scheduler refuses on the
  same difference as the API.
- An existing app gets the `COPY` line by rendering `Dockerfile.prod` again or with
  `copier update`; until then the `deployment-generated` check is red on the difference.
- A signer older than this release refuses an image that carries the record, as a file in
  `/srv` it holds to nothing. The tool that signs moves to this release before an app
  rendered with it is released.
- The record is written where the app is developed. Outside local the command that writes
  it meets the emptied file and refuses.
