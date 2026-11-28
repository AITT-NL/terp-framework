# Design brief

Status: not written yet

Write this before the first screen, or, in an app that already has screens, from the screens it
has, and keep it true: every screen is built against it, and a change to the design changes this
file in the same diff. When it is written, replace the status line above with the date you wrote
it. `uv run terp guide design` is the recipe.

## Who uses it

The people who open this app, and the two or three tasks they open it for.

## Screens

One line per screen: its route, its archetype (OverviewPage, DetailPage, FormPage, HubPage,
DashboardPage, SplitPage, WorkspacePage, SettingsPage, or a Page of its own), its one primary
action, its headline figure if it has one, and what its body shows.

## Direction

The look, stated as tokens: the house style this app inherits, and what it sets itself in
`frontend/src/theme.css` (the heading face and weight, the corners of controls and of
containers, the palette's brand colour) and in `frontend/layout-contract.json` (the palette it
opens on, density, where the navigation sits, the content width). Note the directions that
were offered, the one that was picked, and why.

## Not this

What this app must not look like, in a sentence or two.
