# 0172 — A block at rest is flat, and a shadow means a layer

- **Status:** Accepted and implemented (2026-10-05). Amends
  [ADR 0169](0169-a-page-is-composed-from-the-shape-of-its-data.md) §3, whose "Where data is read"
  rung raised the DataView frame to `--shadow-md`. Held by `styles.test.ts` ("flat at rest"), which
  allows exactly the six layers below to read a shadow token, by the workbench's computed lane,
  and by both baseline sets.
- **Date:** 2026-10-05
- **Relates:** [ADR 0169](0169-a-page-is-composed-from-the-shape-of-its-data.md) (the surface
  ladder, whose fills are kept), [ADR 0093](0093-semantic-token-layer-and-named-themes.md) (the
  shadow tokens, kept in the contract), [ADR 0094](0094-attribute-keyed-styling.md) (how the sheet
  reads them)

---

## Context

The sheet used its three shadow tokens for three different things on one scale.

- **Importance.** ADR 0169 raised the DataView frame to `--shadow-md`, and the headline figure took
  `--shadow-md` too.
- **Being a block.** Every other content surface took `--shadow-sm`: a card, a hub card, a figure,
  the proportion bar, a dataview card, the primary button. The login card took `--shadow-md`.
- **Being a layer.** A tooltip, a toast, a popover, the combobox list, a dialog and the phone's
  nav drawer each took `md` or `lg`.

The chrome took none: the app header, the sidebar and the page band are drawn with hairlines.

So on one screen the table floated above the cards beside it, the cards floated a little, and the
frame around them did not float at all. Reviewing apps built on the framework, the owner saw no
rule in that: "the table seems to have it much more than other cards, and the headers and
sidebar don't use it at all". That is because there was no single rule. Two of the three meanings
are carried by something else already. Importance is ADR 0169's fills: the table's surface rung
and the headline's brand fill. A block's edge is its 1px hairline, which every one of them has.

## Decision

**A block at rest is flat.** Nothing that sits on the page casts a shadow. That covers a card, a
hub card, a figure (headline included), a chart's frame, a dataview card, the table frame, the
primary button and the login card. Each is told apart by its fill (ADR 0169's ladder) and its
hairline.

**A shadow means a layer**: something over the page, which the page continues under. Exactly
these:

| Layer | Token |
|---|---|
| Tooltip, toast | `--shadow-md` |
| Popover panel, combobox list, dialog, the phone's nav drawer | `--shadow-lg` |

The chrome was flat already, and stays so.

**Interaction is not elevation.** A clickable card answers a pointer with its border's colour, as
the hub card already did since its lift was removed, never with a shadow that arrives on hover.

The three shadow tokens stay in the contract. `--shadow-sm` is now read by nothing in the sheet.
Retiring it is a terp-spec vocabulary change, and this decision does not need one.

## Consequences

- Every app's look changes, and that is the point. Cards, figures and the table lose their resting
  shadow and keep their hairline. In the light palettes a card on the canvas is carried by its
  border and the subtle fill. Both workbench baseline sets are re-recorded in the same change.
- Three rules existed only to cancel a resting shadow, and they are gone with it: the plain card,
  a figure inside a boxed card, and a figure in a hub card's stat row. The figure group's 1px
  dividers are drawn with `box-shadow` and are not elevation, so they stay. So do the detail
  list's grid rules.
- A theme cannot bring resting shadows back. A theme sets tokens, and no rule reads a shadow
  token at rest. If an owner ever wants raised blocks, that is a token of its own (a resting
  elevation, `none` by default), decided then, not a token re-pointed now.

## Alternatives considered

**One resting shadow for every block (`--shadow-sm`), the chrome flat, layers above.** That is
consistent too, and it keeps a little separation on the light palettes. The owner chose flat. A
resting shadow is depth that means nothing about the page's layers. On a dense dashboard it is
also forty soft edges where hairlines already say the same thing.

**Keeping the data rung raised (ADR 0169 as written).** That gives the table depth for being
important, which is the meaning that made the scale unreadable. The table's brightest fill
already says it.
