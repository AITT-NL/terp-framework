"""What THIS app's own routes do — the half of the catalog the template never rewrites.

Declare an operation per route you build, and the catalog in
:mod:`control_plane.operations` folds them all in by splatting ``APP_OPERATIONS``.

**Why this is a file of its own.** The catalog next door is template-owned: a release
that adds a capability, corrects the folding rule or improves that docstring reaches
this app through a re-render. Its content used to include *your* operations too, so
every ``copier update`` produced a merge conflict in it — in an app with any routes of
its own, guaranteed, every single time. Splitting the app's half out is what makes the
re-render a delivery rather than a negotiation (ADR 0130).

Nothing here is rewritten by an upgrade, so this file is yours: order it, group it,
comment it however the app reads best.
"""

from __future__ import annotations

from terp.core import OperationDefinition

# One per route, id first: the id is the identity and the translation key (dotted,
# like an event name — `invoices.approve`), the label is the source-language
# fallback shown when the active language has no translation for it.
#
# Example, for when the first module arrives:
#
#     INVOICES_APPROVE = OperationDefinition(
#         id="invoices.approve", label="Approve an invoice"
#     )

#: Every operation this app's own routes declare. Splatted into the one catalog by
#: :mod:`control_plane.operations` — so this stays a flat tuple, and a route that
#: declares an operation missing from it is refused at boot with the id it wanted.
APP_OPERATIONS: tuple[OperationDefinition, ...] = ()

__all__ = ["APP_OPERATIONS"]
