"""The near-misses for a rule whose subject is one import FORM.

A checker matching the substring `import *` flags the string and the comment below
while passing the minimal pair. The rule is about the statement, not the characters.
"""

from os.path import dirname, join

#: The form this rule refuses, as documentation rather than as an import.
REFUSED_FORM = "from <module> import *"

# A star in a comment: `from os.path import *` is what NOT to write.


def run() -> str:
    return join(dirname(REFUSED_FORM), "notes")
