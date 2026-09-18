"""Scan state for a stored file, and the seam a deployment wires a scanner into.

A stored file is attacker-supplied bytes that somebody will later be handed back. This
capability already refuses what it can decide from the upload alone — a media type
outside the deployment's allowlist (ADR 0068), and bytes whose signature contradicts
their declared type (ADR 0076) — but neither of those is malware detection and neither
should be mistaken for it: a signature check proves a PNG is shaped like a PNG, not that
it is safe.

**What a platform can own is the state, not the scanner.** Which engine a deployment
runs, whether it has a licence for one at all, and what it costs per upload are
deployment questions; a capability that picked an answer would be forked by the first
consumer that needed a different one. So the verdict arrives from outside through
:func:`register_file_scanner`, and what lives here is the vocabulary, the registry and
the gate that reads it.

**A deployment that wires no scanner is unchanged**, and that is a decision rather than
an oversight. There is no safe default available: a file cannot be ``clean`` without
something having looked at it, so gating downloads on a verdict nothing will ever
produce would make every already-stored file permanently unreachable — the kind of
secure that gets reverted rather than configured. An unwired deployment stores
:data:`SCAN_NOT_SCANNED` and serves exactly as before.

**Rejected bytes are kept, not deleted.** A verdict of :data:`SCAN_REJECTED` stores the
row and leaves the blob where it is, flagged, and unservable — which is what the word
*quarantine* means. Deleting the evidence is the wrong reflex for a security control:
the operator wants to know what was uploaded, by whom and when, and the uploader is told
by the ``scan_state`` on the response rather than by a discarded error. It also keeps
the gate below honest: a state no reachable path can produce is a comment, not a
control.

**The asynchronous shape is deliberately absent, and the reason is not local.** Scanning
out-of-band means writing a verdict onto a row after it was created, by something that
is not its owner — a cross-owner maintenance write. The platform has no supported route
for one (``terp guide ownership``: *"Genuine cross-owner maintenance — NO SUPPORTED
ROUTE TODAY"*), because :class:`~terp.core.OwnedMixin` authorizes every write to an
existing row against the request actor and a background worker has none. A capability
shipping it anyway would have to either write outside the audited chokepoint or record
the owner as the author of a verdict they did not produce, and a security-relevant state
change is the last place to do either. So the scanner here is synchronous, and the
asynchronous case stays a platform gap that is visible rather than papered over.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import BinaryIO, Final

from terp.core import AppError

#: No scanner was registered when this file was stored. Not a clean bill of health — it
#: is the absence of one, and it is what every row predating a deployment's scanner
#: carries. Wiring a scanner does **not** retroactively scan: these rows keep this state
#: and keep being served, because the alternative is an upgrade that makes existing files
#: disappear. An operator who needs them covered can find them by this exact value.
SCAN_NOT_SCANNED: Final[str] = "not_scanned"

#: A registered scanner saw the stored bytes and raised nothing against them.
SCAN_CLEAN: Final[str] = "clean"

#: A registered scanner rejected the stored bytes. The row and the blob both survive, in
#: quarantine; the bytes are never served again through any path in this capability.
SCAN_REJECTED: Final[str] = "rejected"

#: Every state the column may hold. A scanner returning anything else is a wiring error
#: and is refused at the boundary rather than written to the row.
SCAN_STATES: Final[frozenset[str]] = frozenset(
    {SCAN_NOT_SCANNED, SCAN_CLEAN, SCAN_REJECTED}
)

#: The column cap, mirrored by the model. Comfortably above the longest state so a later
#: addition needs no migration for width alone.
SCAN_STATE_MAX: Final[int] = 32


class FileQuarantinedError(AppError):
    """403 — the file was rejected by the deployment's scanner and is never served.

    Deliberately not a 404. A caller who can already read the metadata knows the row
    exists, so hiding it would be a fiction they can see through; what they cannot do is
    obtain the bytes. The state is on the read DTO, so a client can say *why* rather than
    guessing from a status code.
    """

    status_code = 403
    code = "file_quarantined"
    default_message = "The file was rejected by a malware scan and cannot be downloaded."


#: Called once per upload, with the metadata about to be written and a callable that
#: opens the freshly stored bytes. Returns :data:`SCAN_CLEAN` or :data:`SCAN_REJECTED`.
#:
#: It is handed an *opener* rather than the bytes because a scanner that needs the whole
#: file can read it and one that only needs a head can stop early — and neither choice
#: should be this capability's to make on its behalf, on a path that has spent real care
#: never holding an upload in memory whole.
FileScanner = Callable[["ScanSubject"], str]


class ScanSubject:
    """What a scanner is told about one upload.

    Not the :class:`~terp.capabilities.files.File` row: at scan time there is no row yet
    (the verdict decides what its ``scan_state`` will be), and handing a scanner a
    half-built ORM object invites it to write to one.
    """

    __slots__ = ("content_type", "filename", "open_stream", "sha256", "size")

    def __init__(
        self,
        *,
        filename: str,
        content_type: str,
        size: int,
        sha256: str,
        open_stream: Callable[[], BinaryIO],
    ) -> None:
        self.filename = filename
        self.content_type = content_type
        self.size = size
        self.sha256 = sha256
        self.open_stream = open_stream


_scanner: FileScanner | None = None


def register_file_scanner(scanner: FileScanner) -> None:
    """Install the deployment's *scanner* (a composition-root line, like the storage seam).

    From here on every upload is scanned before its row is written, and the download gate
    has something to refuse. Registering a second scanner replaces the first — the same
    semantics as the storage registry, and for the same reason: two answers to *is this
    file safe* is not a question anybody wants to resolve at the call site.
    """
    global _scanner
    _scanner = scanner


def active_file_scanner() -> FileScanner | None:
    """The registered scanner, or ``None`` when the deployment wired none."""
    return _scanner


def reset_file_scanner() -> None:
    """Remove the registered scanner (the test-isolation reset, like the storage seam's)."""
    global _scanner
    _scanner = None


def scan(subject: ScanSubject) -> str:
    """The verdict for *subject*: the scanner's, or :data:`SCAN_NOT_SCANNED` if none is wired.

    A scanner returning something outside :data:`SCAN_STATES` is a wiring error, and it
    fails **closed** rather than being coerced: a typo returning ``"ok"`` must not be
    written to the row and read as a clean bill of health by the gate forever after. The
    ``ValueError`` surfaces during the upload that hit it, which is where a mis-wired
    composition root is cheapest to find.
    """
    scanner = _scanner
    if scanner is None:
        return SCAN_NOT_SCANNED
    verdict = scanner(subject)
    if verdict not in (SCAN_CLEAN, SCAN_REJECTED):
        raise ValueError(
            "a file scanner must return SCAN_CLEAN or SCAN_REJECTED, "
            f"not {verdict!r}"
        )
    return verdict


def ensure_servable(scan_state: str) -> None:
    """Fail closed unless a file in *scan_state* may have its bytes handed out.

    Enforced in the service's read chokepoint rather than on the download route, so the
    serve-through delegation read (``load_for``) and any programmatic ``load`` are covered
    by the same decision — a quarantined file is unreachable through every path this
    capability owns, not just the one with a URL.
    """
    if scan_state == SCAN_REJECTED:
        raise FileQuarantinedError(log_context={"scan_state": scan_state})


__all__ = [
    "SCAN_CLEAN",
    "SCAN_NOT_SCANNED",
    "SCAN_REJECTED",
    "SCAN_STATES",
    "SCAN_STATE_MAX",
    "FileQuarantinedError",
    "FileScanner",
    "ScanSubject",
    "active_file_scanner",
    "ensure_servable",
    "register_file_scanner",
    "reset_file_scanner",
    "scan",
]
