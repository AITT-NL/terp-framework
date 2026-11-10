"""The Terp Standard release a carried declaration names, as ``terp promote`` reads it.

The reader (:mod:`terp.arch.deployment.reader`) holds one schema, its own release's
(:data:`~terp.arch.deployment.reader.SPEC_RELEASE`), and ``terp promote`` reads every release up
to it with that schema (ADR 0187 decision 6, amended). Two things that one schema cannot say are
answered here: the SHA-256 of the schema this ``terp-arch`` holds, which a release named as this
one must record, and the words the Terp Standard added after the oldest release a signed release
can name, which a declaration written against an older release must not use. An executor that
carries several releases reads each with its own schema; one that carries one asks these.
"""

from __future__ import annotations

import functools
import hashlib
import pathlib
import re

from terp.arch.deployment.reader import SCHEMA_FILE

#: The words the Terp Standard added to the declaration after terp-spec 0.40.0, the release the
#: signer's floor (terp-arch 0.35.0) mirrors and so the oldest a signed release can name, by
#: their path in the file, with the release that introduced each. Read with this reader's newer
#: schema, a word an older release does not have would be honoured where that release's own
#: reader refuses it; :func:`words_newer_than` finds one, and ``terp promote`` refuses the
#: release. A word the schema gains is added here in the change that mirrors it. A test holds
#: that for the generator block alone (``test_deployment_schema_mirror``: the table's generator
#: words are the reader's newer ones); a word added anywhere else in the schema has none.
WORDS_SINCE: dict[str, str] = {"generator.recipes": "0.45.0"}

#: What a path that leads nowhere in a declaration reads as.
_ABSENT = object()


@functools.cache
def schema_sha256() -> str:
    """The SHA-256 of the mirrored schema's bytes: what ``sign`` records of the pinned wheel's."""
    return hashlib.sha256(pathlib.Path(__file__).with_name(SCHEMA_FILE).read_bytes()).hexdigest()


def _release(number: str) -> tuple[int, ...]:
    if re.fullmatch(r"[0-9]+(?:\.[0-9]+)*", number) is None:
        raise ValueError(f"{number!r} is not a Terp Standard release number")
    return tuple(int(part) for part in number.split("."))


def words_newer_than(raw: object, release: str) -> list[str]:
    """Each word of :data:`WORDS_SINCE` that *raw* uses and Terp Standard *release* does not have.

    As ``path (terp-spec <release that introduced it>)``, in the table's order. A word is used
    when its key is present, whatever it holds: an older reader refuses the key itself.
    """
    found: list[str] = []
    for path, introduced in WORDS_SINCE.items():
        node: object = raw
        for key in path.split("."):
            node = node.get(key, _ABSENT) if isinstance(node, dict) else _ABSENT
        if node is not _ABSENT and _release(release) < _release(introduced):
            found.append(f"{path} (terp-spec {introduced})")
    return found


__all__ = ["WORDS_SINCE", "schema_sha256", "words_newer_than"]
