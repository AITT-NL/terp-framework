"""How a copy of a Terp Standard file is held to the pinned terp-spec, for every copy this repository carries.

terp-spec is consumed as a pinned, published package (ADR 0082), and a file the framework copies
from it can be ahead of the pin: the copies are of the release their ``SPEC_RELEASE`` names, which
may not be published yet. Each group of copies sharing one ``SPEC_RELEASE`` is held by how the
pinned release stands to that one, and no case skips:

* **the pin is that release**: the pinned spec carries every file, and each copy equals it byte
  for byte;
* **the pin is older**: the copies are ahead of it, so the pinned spec cannot carry them all as
  they are. Each may be absent from it, or another version of it (a later schema change), but
  not every copy may equal the pinned file: then the pinned release is the one they came from,
  and ``SPEC_RELEASE`` names the wrong one;
* **the pin is newer**: the pin moved and the copies' release did not, which is never right.
"""

from __future__ import annotations

import pathlib


def version(text: str) -> tuple[int, ...]:
    return tuple(int(part) for part in text.split("."))


def findings(copies: dict[str, bytes], spec_dir: pathlib.Path, pinned: str, release: str) -> list[str]:
    """Every way *copies* (file name to bytes) disagree with terp-spec *pinned*, for *release*."""
    if version(pinned) > version(release):
        return [
            f"terp-spec {pinned} is pinned, newer than SPEC_RELEASE {release}: copy its "
            f"{', '.join(sorted(copies))} over these and move SPEC_RELEASE to {pinned}"
        ]
    published = {name: spec_dir / name for name in copies}
    if version(pinned) == version(release):
        found = [f"terp-spec {pinned} ships no {name}" for name, path in published.items() if not path.is_file()]
        found += [
            f"this repository's {name} differs from terp-spec {pinned}'s: copy the spec's file over "
            "it, then make the reader honour whatever changed"
            for name, path in published.items()
            if path.is_file() and path.read_bytes() != copies[name]
        ]
        return found
    if all(path.is_file() and path.read_bytes() == copies[name] for name, path in published.items()):
        return [
            f"terp-spec {pinned} already carries {', '.join(sorted(copies))} as they are here: "
            f"move SPEC_RELEASE to {pinned}"
        ]
    return []


__all__ = ["findings", "version"]
