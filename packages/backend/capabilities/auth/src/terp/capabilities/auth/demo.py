"""The one password every development seed signs in with.

A generated app's ``app/seed.py`` provisions a first administrator so the app can be
signed in to at all, and the dev sign-in screen fills the same login in with one click.
That password is the one credential whose whole purpose is to be printed, shared and
known, and it is meaningless outside a throwaway development database: ``terp seed``
refuses to run when ``ENVIRONMENT=production``, and a real deployment bootstraps its
first administrator with ``terp user create``.

It lives here, and not as a literal in the seed, because of who pays for the literal.
``no_hardcoded_credentials`` reads every file of an app's root (ADR 0136), so a literal
in the seed needs a governed marker, and the marker needs a count in the app's
``escape-hatch-budget.json``. The seed is the template's and reaches an app on every
update; the budget is the app's and never does. So an app rendered before the marker
existed received the marker without the count, and every upgraded app needed a person
to approve an exception for a line the framework wrote. Held here, the exception is
counted once, in this capability's own budget, and an app's seed holds no literal.
"""

from __future__ import annotations

from typing import Final

#: The development seed's shared password. It satisfies the default ``PasswordPolicy``,
#: so the seed's ``UserProvision`` passes the same check a real sign-up does.
DEMO_PASSWORD: Final[str] = "correct horse battery staple"  # noqa: S105 - dev seed, not a real secret  # arch-allow-no-hardcoded-credentials: the demo login every development seed provisions, held once here so no app's seed holds the literal; `terp seed` refuses to run in production, and the whole point is that it is printed, shared and known
