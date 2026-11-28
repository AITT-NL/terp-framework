"""The ``terp guide design`` topic: the brief a frontend starts from, the screens it names,
the direction the app takes, and the review against it.

Its own module, as the security, testing and theming topics are: ``terp/cli/__init__.py`` is
over the size cap and recorded in ``packages/backend/OVERSIZED.json``, a shrink-only ratchet.
"""

from __future__ import annotations

TOPIC = """\
Designing an app's screens (the brief, the direction, the review)

- THE BRIEF COMES FIRST. Before the first screen exists, write frontend/DESIGN.md. The
  template ships it with its sections and the line "Status: not written yet", and every
  screen after that is built against it:

      Who uses it    the people, and the two or three tasks they open the app for
      Screens        one line per screen: its route, its archetype, its one primary
                     action, its headline figure if it has one, what its body shows
      Direction      the look, stated as tokens: the house style the app inherits, and
                     what it sets itself in frontend/src/theme.css and
                     frontend/layout-contract.json (the heading face and weight, the
                     corners of controls and containers, the palette it opens on,
                     density, where the navigation sits, the content width)
      Not this       what the app must not look like, in a sentence or two

  Offer the person a short choice between two or three directions that suit the work (a
  console people work in all day is dense, square and quiet; a portal visited once a month
  is roomy, rounded and calm) and record the one they pick, with the reason, in the brief.
  An app that already has screens of its own (the template's start page at / does not
  count) has a direction already: write down the one its screens have, and ask the person
  before changing it. Replace the status line with the date when the brief is written. When the design changes, change the brief in the same change as the screens:
  it is reviewed in the diff like the code.

- FROM TASK TO SCREEN. A screen's archetype follows its job:
      OverviewPage   many of one thing, to find and act on (a DataView)
      DetailPage     one record and its parts
      FormPage       creating or editing one thing
      HubPage        the areas of the app, a HubCard each
      DashboardPage  how the whole is doing, in figures and charts
      SplitPage      a list beside the record it opens
      WorkspacePage  work done on a surface: a diagram, a plan, a board
      SettingsPage   preferences, in sections
      Page           a composition of the app's own, from a CSS Module
  Then compose the body from the shape of its data (terp guide layouts): the figures it is
  about in the summary band, a collection as a DataView, a record's facts as a DetailList.

- HIERARCHY IS RATIONED, so spend it on the task: one primary action per screen, at most one
  headline figure, sections spaced wider than the blocks inside them, and type and space
  before boxes (not every group of things needs a Card). Never a colour of your own to make
  something stand out: emphasis is a ranking the framework owns.

- THE DIRECTION IS APP-WIDE. It is set once, in tokens (terp guide theming): a heading face
  and weight, the corners of controls and of containers, the palette and its brand colour,
  density, where the navigation sits, the content width. Never a variant per block: a Card
  looks the same on every screen of an app, and the app as a whole looks like its own.

- REVIEW THE SCREENS AGAINST THE BRIEF before you call them done. It is advice, not a gate:
  no check can tell a good layout from a poor one, so this is a look, written down. For each
  screen the brief names, look at it 1280 and 390 pixels wide, in the palette the app opens
  on and in a dark one, and check that
      - the primary action is the first thing the eye finds, and Tab reaches it
      - the headline, if the screen has one, is the one figure that stands out
      - every block starts on the content's left edge, and nothing clips at 390 wide
        (hold the task's controls to expectControlFitsHorizontally from @terpjs/conformance)
      - an empty list and a failed load each say what happened and what to do next
      - the direction shows: the heading face, the corners, the density the brief names
  Say what you found, and fix what is the app's own.
"""
