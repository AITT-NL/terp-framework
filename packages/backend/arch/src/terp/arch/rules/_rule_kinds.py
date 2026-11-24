"""Rules by the way out they have, or have not (the registry's classification).

Moved out of :mod:`terp.arch.rules`, the registry, unchanged: it sat on its size record, and
these are three facts about rules rather than the list of them. The registry imports them
back, so its importers ask where they always did.
"""

from __future__ import annotations


#: Rules that read the PROJECT root -- the directory holding the app root, where
#: ``deployment.json`` and its profile live -- rather than the app package itself.
#: :func:`check_app` hands each of them the parent of the root it scans.
PROJECT_ROOT_RULES: frozenset[str] = frozenset(
    {
        "deployment_declaration_is_readable",
        "deployment_declaration_tells_the_truth",
        "deployment_generated_files_match_their_render",
    }
)

#: Rules whose subject is a checked-in declaration that cannot carry an inline marker
#: (a JSON file has no comments). Their one way out is a state of the declaration
#: itself, so no ``# arch-allow-*`` token names them and none may be budgeted. Mirrors
#: the Terp Standard's own list (its catalog field ``escape`` replaces ``opt_out``).
RULES_ESCAPED_BY_THEIR_DECLARATION: frozenset[str] = PROJECT_ROOT_RULES

#: Rules with no way out at all, because the way out is the rule's own subject. A revision
#: marked ``expand_only = True`` that needs an operation off the expand list is a contract
#: revision, and saying so (``expand_only = False``) costs only restore-free rollback for
#: its release (ADR 0185). So no ``# arch-allow-*`` marker suppresses one of these, and
#: the budget refuses a token naming one. Mirrors the Terp Standard's own list (the
#: catalog entry declares neither ``opt_out`` nor ``escape``).
RULES_WITHOUT_AN_OPT_OUT: frozenset[str] = frozenset({"expand_revisions_only_expand"})
