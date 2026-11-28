# 0224 — A frontend starts from a design brief

- **Status:** Proposed on 2026-11-28. Held by `tests/architecture/test_cli_guide.py` (the
  `design` topic names the brief, its sections and the review, and the theming and layouts
  topics it leans on), `tests/architecture/test_template.py` (the template ships
  `frontend/DESIGN.md` with its sections and its status line, copier seeds it once, and the
  app's AGENTS.md sends the agent to it before the first screen),
  `tests/architecture/test_cli_version.py` (the upgrade report lists it among the files a
  re-render leaves alone) and `tests/architecture/test_docs_parity.py` (the delivered AGENTS.md
  lists the topic).
- **Date:** 2026-11-28.
- **Relates:** [ADR 0223](0223-type-and-shape-have-roles-as-colour-does.md) (the type and shape
  roles a direction is stated in), [ADR 0169](0169-a-page-is-composed-from-the-shape-of-its-data.md)
  (composing a page from the shape of its data, and rationing emphasis),
  [ADR 0217](0217-app-components-can-own-a-scoped-stylesheet.md) (a layout an app owns),
  [ADR 0103](0103-the-ideology-one-pattern-enforced-escapable-by-proof.md) (a rule with no
  failure it can observe is ceremony), and in terp-studio the intake that settles what an app is
  for and leaves its screens to the project's agent.

## Context

Apps built on Terp take the default path, and the instructions an agent reads are why. The
template's AGENTS.md told it to "start a frontend with the user's main task and the standard
component that serves it" and to "use the existing app or house design as the baseline", and to
compare an unusual layout with the standard composition before making it the default. Nothing
before that sentence decided what the app should look like: no step names its screens, their
jobs or the direction the app takes, so the agent fills the gap with the defaults it was pointed
at. Every app comes out as the same shell with the same pages in a different colour.

The vocabulary was not the only limit. ADR 0223 gave type and shape roles, so an app can now
look like its own; what was missing is the moment where someone decides how.

## Decision

### 1. The brief is a file the app ships, and the first thing written into it

The template ships `frontend/DESIGN.md` with four sections and the line
`Status: not written yet`:

- **Who uses it**: the people, and the two or three tasks they open the app for.
- **Screens**: a line per screen, with its route, its archetype, its one primary action, its
  headline figure if it has one, and what its body shows.
- **Direction**: the look, stated as tokens: the house style the app inherits and what it sets
  itself in `theme.css` and `layout-contract.json`.
- **Not this**: what the app must not look like.

A file rather than a declaration with a schema, because its readers are a person and an agent,
not a program: nothing in the framework or the Studio parses it, and a schema for prose would be
a contract with no consumer to hold it (ADR 0099's test). It sits in `frontend/`, beside the code
it describes, so an app rendered without screens of its own never gets one, and it changes in
the same diff as the screens. Copier seeds it once and never overwrites it, like `theme.css`:
after the first render it is the app's own account of its screens and its look.

### 2. The agent writes the brief before the first screen, and asks before it builds

The delivered AGENTS.md now opens the frontend section with the brief: while
`frontend/DESIGN.md` still says it is not written, the agent writes it before any screen, offers
the person a short choice between two or three directions that suit the work, records the one
they pick with its reason, and then builds each screen to it from the standard components that
serve its task. The checks
that followed (desktop and phone widths, every shipped palette, the keyboard, controls that fit)
are unchanged. `terp guide design` is the recipe: the brief's sections, an archetype per job,
how hierarchy is rationed, why a direction is app-wide, and the review below.

### 3. The review against the brief is advice, and says so

For each screen the brief names, the agent looks at it at two widths and in two palettes and
checks a short, fixed list: the primary action is found first and reached by Tab, the headline
is the one figure that stands out, blocks share the content's edge and nothing clips, empty and
failed states say what to do, and the direction shows. None of that is a gate. Whether a layout
is good has no failure a check can observe, and ADR 0103 calls a rule without one ceremony; the
parts that can be observed already have their controls (`expectControlFitsHorizontally`, the
contrast gate, the layout contract, one headline per page).

## What it does not do

- **It does not check the brief.** No test fails on an app whose `frontend/DESIGN.md` is missing
  or still says it is not written: that is instruction, recorded as such, not a control.
- **It does not choose for the app.** The brief names a direction in tokens the app already has;
  it adds none, and no direction is preferred.
- **It does not touch the intake.** What an app is for, who uses it and how they sign in are
  settled when it is created; its screens and its look start here.

## Consequences

- An app generated from this template carries `frontend/DESIGN.md` from its first commit, and
  the agent's instructions send it there before anything else in the frontend.
- `terp/cli/__init__.py` and `terp/cli/version.py` are on the shrink-only size record, so the
  `layouts` topic moved to its own module and the upgrade report's two file lists to
  `scaffold_files.py`, both unchanged, to make room for the topic and the new seeded file.
- An app generated earlier gets the brief, still unwritten, on its next template update: copier
  never overwrites the file, but it does create one it finds missing. Until then
  `terp guide design` serves the app the same way.
