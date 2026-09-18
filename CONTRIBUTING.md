# Contributing to Terp

Thanks for taking the time. Two things are worth reading before a first pull
request: how a change is proven here, and how a contribution's provenance is
recorded.

## This repository is public

Terp is public on GitHub and every backend distribution and frontend package
publishes to PyPI and npm.

**Never name an application built on Terp, its owner, or its client** — not in
code, comments, identifiers, tests, docs, ADRs, the CHANGELOG, a commit subject
or body, or a pull request title or description. Write the friction and the
evidence, never the reporter: "an app whose worker speaks to a legacy database",
not the project or the person who found it. A neutral example is never weaker,
and usually clearer, because it describes the mistake instead of the person.

Get it right the first time. Git history keeps the original text even after a
scrub, and a name that reaches a published package cannot be edited out of it at
all — only the whole release can be withdrawn.

[`AGENTS.md`](AGENTS.md) carries the full rule and the four places it actually
gets in. It applies to people as well as to agents.

## Sign your work (Developer Certificate of Origin)

Terp uses the [Developer Certificate of Origin](https://developercertificate.org)
rather than a contributor licence agreement. The DCO is a statement that you
have the right to submit the change — it asks for no copyright assignment and
grants nothing beyond the Apache-2.0 licence this repository already carries, so
your contribution is under the same terms as the rest of the work
(Apache-2.0 §5).

Add a `Signed-off-by` line to each commit:

```
Signed-off-by: Your Name <your.email@example.com>
```

`git commit -s` writes it for you. The name must be your real name and the email
one you can be reached at.

If you are contributing on behalf of your employer, make sure they are aware —
the DCO's clause (b) is exactly about having the right to submit.

## How a change is proven

Terp's own bar is the one it sells: a rule whose invariant the running system
can observe pairs a build-time check with a fail-closed runtime control, and a
test is never the only control for such a rule.

```bash
uv run coverage run -m pytest   # the gate, first half: the suite
uv run coverage report          # second half: the 100% bar (a separate control --
                                # a plain `pytest` run is green without it)
uv run ruff check .             # the AppSec baseline (bandit `S` rules)
terp fmt             # formats the files YOU touched; formatting is not gated
```

A few expectations that save a review round:

- **Never weaken a guard to make a change pass.** If a rule is wrong, change the
  rule deliberately, with its reasoning and its tests — that is a welcome pull
  request, and a different one from the change that hit it.
- **Prove a test can fail.** A test that passes against broken code is not
  evidence. Break the thing on purpose once, watch the test go red, and say so
  in the pull request.
- **A new rule ships its catalog entry** in
  [AITT-NL/terp-spec](https://github.com/AITT-NL/terp-spec), and its corpus
  samples. The two repositories' CIs are circularly coupled — `AGENTS.md`
  explains the push order.
- **Keep the scope to the change.** A formatting pass over unrelated files makes
  a diff unreviewable, which is why `terp fmt` defaults to `--changed`.

## Reporting a vulnerability

Do not open a public issue for a security problem. Report it privately through
GitHub's security advisories for this repository, so a fix can ship before the
detail does.
