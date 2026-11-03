---
name: terp-review
description: >-
  Review a change in a Terp repository before it is pushed or merged. Covers
  correctness, the repository's own AGENTS.md rules, a weakened guard or
  ratchet, a test that cannot fail, and a downstream application's name in the
  diff, a commit message or a pull request. Use for the current branch,
  uncommitted work, a commit range or a pull request.
argument-hint: "[PR number or URL | branch | commit range | path] [focus]"
allowed-tools:
  - Bash(git status *)
  - Bash(git diff *)
  - Bash(git log *)
  - Bash(git show *)
  - Bash(git fetch *)
  - Bash(git merge-base *)
  - Bash(git rev-parse *)
  - Bash(git branch *)
  - Bash(git ls-files *)
  - Bash(git grep *)
  - Bash(gh pr view *)
  - Bash(gh pr diff *)
---

<!-- Kept identical in every Terp repository that carries it; change them together. -->

# Terp review

Review a change against the rules of the repository it lands in. Those rules are
the repository's AGENTS.md (CLAUDE.md imports it) and CONTRIBUTING.md where there
is one. This skill adds no rules; it is the procedure for checking a change
against them. Read the AGENTS.md of each repository under review if it is not
already in context.

This is a review. Do not change the code under review, commit, push or post
anything unless asked after the report.

Arguments: $ARGUMENTS

## 1. Pin down the change

The arguments name a target: a PR number or URL, a branch, a commit range, or a
path. Any other words are the user's focus. With no target, review the work not
yet on `main` in the repository you are working in: its commits, and its staged,
unstaged and untracked changes. When the session spans several Terp repositories,
review every one that has such work, together: a change split across repositories
is one change. A bare PR number is then ambiguous, so ask which repository.

- Run `git fetch origin main` first. A local `origin/main` can be far behind, and
  then merged work reads as new. If a shallow clone has no merge base, deepen it
  (`git fetch --deepen=200 origin main`) and retry.
- Local work: the base is `git merge-base origin/main HEAD`. Read
  `git log --format='%h %s%n%n%b' <base>..HEAD`, `git status --short`, then
  `git diff <base>`, which holds committed and uncommitted changes together. Open
  untracked files directly.
- A pull request: read its title, description, base and commits (`gh pr view <n>`,
  or the GitHub tools this session has). Fetch it with
  `git fetch origin <base-branch> pull/<n>/head:refs/pr/<n>`, take the base from
  `git merge-base origin/<base-branch> refs/pr/<n>`, and diff `<base> refs/pr/<n>`.
- A path: its changes in that range; if it has none, the file as it stands.

Below, `<range>` is whatever you diff: `<base>` for local work, `<base> refs/pr/<n>`
for a pull request. Skip lockfiles and generated files, except to check that the
change explains why they moved. Read past the hunk: the callers of a changed
function, the tests that cover it, the doc that describes it.

## 2. Check

**Downstream names (always Blocking).** Every Terp repository's AGENTS.md forbids
naming an application built on Terp, its owner or its client.
- Read every added line, every commit subject and body in the range, the branch
  name, and a PR's title and description. Look hardest where it gets in: CHANGELOG
  entries, ADR Context sections, test docstrings and fixtures, a comment quoting a
  real log line or config.
- Flag any product, company, client or person; any real-looking host, domain,
  address, container, database or environment-variable prefix; and any "reported
  while building ..." narrative. Terp's own names and the third-party software it
  uses are not downstream, and authorship trailers are not findings. The fix is an
  invented placeholder (`example-app`, `SOME_API_BASE_URL`). When unsure, list it
  as a question rather than wave it through.
- If the session also has a repository open that is not a Terp repository (an
  application built on Terp), collect its distinctive names (repository, package,
  product, environment-variable prefixes, services, containers) and search the
  diff and every message for each. This is how the leak happens.
- A commit message is fixed by rewriting it before it is pushed or merged. If the
  text is already pushed, say so: the history rewrite is the owner's call.

**Weakened guards (Blocking unless explained).** Changing a rule is its own
change, with its reasoning and tests, never the side effect of the change that
hit it. Scan the added lines:

```bash
git diff -U0 <range> | grep -E '^\+\+\+ |^\+.*(pragma: no cover|noqa|nosec|type: ignore|eslint-disable|@ts-(ignore|expect-error)|(istanbul|c8|v8) ignore|terp-allow-|arch-allow|pytest\.mark\.(skip|xfail)|pytest\.skip\(|(it|test|describe)\.(skip|only)\(|continue-on-error)'
```

Each hit is a suppression that needs a reason on the line or in the change; an
unexplained one on a security, coverage or Terp-rule check is Blocking. Then look
for:
- a deleted or loosened test or assertion;
- a ratchet, budget or baseline that grew (anything AGENTS.md says only shrinks);
- coverage settings (`fail_under`, `omit`, exclusions), or lint and scanner
  ignores (ruff configuration, `.gitleaksignore`, `.trivyignore`);
- a CI step removed, narrowed by `if:` or `paths:`, or turned from a required
  lane into a skip;
- a rule's runtime classification moved off `required`;
- a fail-closed path that now logs and continues.

**Correctness.** For each hunk, establish what it is meant to do, then try to
break it: edge inputs (empty, None, boundaries, Unicode, time zones), error paths
that fail open, concurrency and retries, cleanup, authorization, injection, and a
secret reaching a log, error, event or response. A changed contract (an API, a
schema or wire message, a migration, a published package's surface) needs what the
repository asks for it: a version bump, a CHANGELOG entry, an ADR, the other
repository's half. A commit message, PR description, CHANGELOG entry or ADR that
claims what the code does not do is a finding.

**Tests.** Every behavioural change is pinned by a test that fails without it,
including the refusals (the denied, expired, replayed or tampered case). Run the
tests that cover the change. When a test's power is doubtful and it matters, prove
it in a scratch worktree outside the repository: revert the non-test change, run
the test, expect red, then remove the worktree.

**The repository's own rules.** Walk AGENTS.md section by section and check each
rule the change touches. Where it couples this repository to another (a pinned
release, a spec entry that must land first), check that the other half exists and
state the order they must land in.

**Scope.** Unrelated reformatting or drive-by edits make a diff unreviewable. A
guard change bundled with a feature is two changes.

Run what proves or disproves a finding: targeted tests, the linter, a ratchet
script. Do not run the whole gate unless asked, and never call the gate green
unless you ran it exactly as AGENTS.md defines it.

## 3. Verify, then report

Re-check every finding before you report it: re-read the lines it cites and
confirm the failure can happen. Drop what does not survive; a wrong finding costs
the reader more than a missed nit. For a large change you may split the reading
across subagents, but verify what they return yourself.

```markdown
## Review: <repository> <range or PR>

**Verdict:** Ready | Not ready (<one line>)

1. **Blocking: <the defect>** `path:line`
   <What is wrong, and the concrete failure: input or state, then the wrong
   outcome. For a rule, quote it from AGENTS.md.>
   Evidence: <the line, or the command and its output>
   Fix: <the direction, not a patch>

**Checked, nothing found:** <one line per area, saying what it covered, e.g.
"names: 6 commit messages, the CHANGELOG entry, 2 ADRs">
**Not checked:** <what you did not run or could not see>
```

Severities are **Blocking** (fix before merge), **Should fix** and **Nit** (only
when certain and cheap, at most five). Order the findings most severe first. A
review with no findings is valid; say so.

When a report will be posted where others read it (a PR comment, an issue), give a
naming finding by its location only. Repeating the name there publishes it.
