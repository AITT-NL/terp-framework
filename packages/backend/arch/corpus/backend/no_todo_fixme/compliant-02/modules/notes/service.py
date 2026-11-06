"""The exclusion this rule's own entry states, and nothing contracted it.

"Matching ignores identical text inside strings or docstrings" — so a checker that
greps for the four markers passes the minimal pair and fails here. That is exactly
the over-eager implementation the corpus exists to keep out, and until this case
nothing stopped it certifying.

Including this docstring: the word TODO in running prose is not a marker.
"""

#: Every marker the rule names, in a position where it is data rather than a comment.
MARKERS = ("TODO", "FIXME", "HACK", "XXX")

BANNER = "FIXME is the second marker this rule looks for"


def describe(kind: str) -> str:
    """Return a sentence about a marker without leaving one behind.

    A docstring is a string, and HACK inside one is prose about the rule, not an
    admission of unfinished work.
    """
    return f"{kind} marks work someone meant to come back to"


def run() -> str:
    return describe(MARKERS[0]) + " — XXX is the fourth"
