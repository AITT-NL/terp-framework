"""``terp.core._internal`` — implementation details, import-forbidden outside core.

Nothing here is part of the semver public surface. Modules (and capabilities
that did not declare it) must import from :mod:`terp.core` instead. The
architecture suite fails the build on any ``terp.core._internal`` import from a
module or sibling.
"""

from __future__ import annotations

__all__: list[str] = []
