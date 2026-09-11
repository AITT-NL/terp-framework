"""``terp ports`` — the host ports a checkout owns, recorded where every starter reads them.

The dev compose file publishes its host ports through interpolated names, and it
used to default them to a fixed pair. A default is right when any value will do;
a host port is exactly the case where it will not, and the defaults were the
first pair a workbench hands out. So a start that did not come from that
workbench — a shell in the project folder, an editor task, an agent bringing the
app up to look at it, ``terp docker dev`` — ran the same compose file with the
names unset, landed on the defaults, and (the compose project name being pinned)
took over *the same containers* as whichever checkout held the first pair.

Recording the assignment is therefore not a convenience. It is what makes two
checkouts able to run at once, and what makes the address a workbench watches the
address the app actually answers on.

**The ledger is machine-scoped.** The resource being allocated belongs to the
host, so a record inside one checkout cannot stop a second checkout claiming the
same port, and a record inside one workbench cannot be read by a starter that is
not that workbench — which is the whole defect. It lives in ``~/.terp/ports.json``
(``TERP_HOME`` moves it), keyed by the checkout's absolute path.

**Assigning and publishing are one act.** The defect was never a missing
mechanism; it was that a tool could assign a pair and not publish it, leaving the
number real to itself and absent everywhere else. :func:`assign` claims and writes
in one call, and there is no way to reach the first half alone.

**What is already published wins over a fresh pick.** Consulted in order: a claim
this ledger already holds, then the names this checkout's ``.env`` already sets,
then a free pair. The middle step is what makes this safe to run against a
checkout some other tool already assigned — it adopts that answer instead of
picking a second one and moving the ports of a stack that may be up. Forcing a
new pair is an explicit ``--reassign``.

**A block, not the file.** ``.env`` is the app's, it predates any tooling, and in
a real checkout it holds secrets. So this owns a delimited block, rewritten where
it stands, and leaves every other line alone.

**And git must not see it.** A file git reports is a file that shows up in review
and blocks ``copier update``, which fails closed on a dirty workspace. The
template gitignores ``.env`` already; where it is not ignored the write is
preceded by a local ``.git/info/exclude`` entry, and where even that is
impossible it does not happen. A machine's ports do not belong in an app's
history, and a convenience is never worth making a checkout unreviewable.
"""

from __future__ import annotations

import contextlib
import json
import os
import pathlib
import socket
import subprocess
import time
from collections.abc import Iterator, Mapping

from terp.cli import workbench

#: The dev pair's bases. Deliberately far from 5173 / 8000 / 3000, which is where
#: a developer's *other* applications live.
WEB_BASE = 21100
API_BASE = 22100

#: How far to count from the bases before giving up.
SPAN = 1000

#: Bumped only for a change a previous reader could not survive.
SCHEMA_VERSION = 1

DEFAULT_WEB_PORT_ENV = "WEB_PORT"
DEFAULT_API_PORT_ENV = "API_PORT"

#: The block's fences. Greppable, and they say who wrote them, because a
#: developer who finds unexplained lines in their own ``.env`` is right to
#: distrust them.
BLOCK_BEGIN = "# >>> terp: host ports for this checkout (managed)"
BLOCK_END = "# <<< terp"

_PREAMBLE = (
    "# Written by `terp ports assign`. Compose loads this file from the project\n"
    "# directory automatically, so a stack started from a shell, an editor task or\n"
    "# an agent lands on the same ports as one started from a workbench. Values\n"
    "# passed on the command line still win. Edits inside this block are replaced\n"
    "# on the next assign; `terp ports release` removes it.\n"
)


class PortsError(RuntimeError):
    """The assignment cannot be made or recorded, with the reason for a reader."""


# --------------------------------------------------------------------------- #
# The ledger
# --------------------------------------------------------------------------- #


def home() -> pathlib.Path:
    """The CLI's machine-scoped home. ``TERP_HOME`` overrides it."""
    override = os.environ.get("TERP_HOME", "").strip()
    if override:
        return pathlib.Path(override).expanduser()
    return pathlib.Path.home() / ".terp"


def ledger_path() -> pathlib.Path:
    """Where every host-port claim on this machine is recorded."""
    return home() / "ports.json"


def _empty() -> dict:
    return {"schemaVersion": SCHEMA_VERSION, "claims": []}


def _load(path: pathlib.Path) -> dict:
    """The ledger, or an empty one. A corrupt file is not a reason to refuse.

    A ledger that cannot be parsed is treated as empty rather than fatal: the
    worst case is a second checkout picking a port the first holds, which the
    host probe still catches, and the alternative is a developer unable to start
    anything until they hand-repair a file they did not know existed.

    A version it *can* read is carried through untouched, so the write path can
    tell a ledger this reader understands from one written by a newer `terp`.
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return _empty()
    if not isinstance(raw, dict) or not isinstance(raw.get("claims"), list):
        return _empty()
    return raw


def _refuse_a_newer_ledger(data: dict) -> None:
    """Never rewrite a ledger a newer ``terp`` wrote.

    Every write here replaces the claim list wholesale, and :func:`claims` drops
    what it cannot model — so an older reader rewriting a newer file would
    silently delete claims it merely failed to understand, and hand out ports
    another checkout holds. Reading one is fine; owning it is not.
    """
    version = data.get("schemaVersion")
    if isinstance(version, int) and version > SCHEMA_VERSION:
        raise PortsError(
            f"{ledger_path()} was written by a newer terp (ledger schema "
            f"{version}; this one understands {SCHEMA_VERSION}). Upgrade terp "
            f"rather than let an older one rewrite it — it would drop the "
            f"claims it cannot read."
        )


def _lock_age(lock: pathlib.Path) -> float:
    """How long *lock* has been held, or ``0.0`` if it has just gone.

    A lock that vanished between the failed create and this question was
    released by its holder, so it is not stale — it is finished, and the next
    attempt to create it will succeed. Reporting an age of zero rather than
    treating the missing file as ancient is what keeps this from breaking a lock
    somebody else is about to take.
    """
    try:
        return time.time() - lock.stat().st_mtime
    except OSError:
        return 0.0


@contextlib.contextmanager
def _ledger_lock(*, timeout: float = 5.0, stale_after: float = 30.0) -> Iterator[None]:
    """Hold the ledger for a read-modify-write.

    Every write is read-compute-replace, so two of them at once lose a claim —
    and a lost claim is a port handed to a second checkout, which is the one
    thing this file exists to prevent. Two conversations each starting their own
    project is the ordinary case rather than a rare one, so the window is real.

    An exclusive create is the lock, because it is the one primitive that behaves
    the same on every platform this runs on. A lock older than *stale_after* is
    broken rather than waited on: the alternative is a crashed process making a
    developer's machine permanently unable to assign a port, and the cost of
    breaking one early is the race we already tolerate today.
    """
    path = ledger_path()
    lock = path.with_name(path.name + ".lock")
    deadline = time.monotonic() + timeout
    handle = None
    while True:
        try:
            lock.parent.mkdir(parents=True, exist_ok=True)
            handle = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except FileExistsError:
            if _lock_age(lock) > stale_after:
                with contextlib.suppress(OSError):
                    lock.unlink()
                continue
            if time.monotonic() >= deadline:
                # Not fatal: the caller still gets a correct-looking assignment,
                # and saying so is better than blocking a start indefinitely.
                break
            time.sleep(0.05)
        except OSError:
            # A home directory that cannot hold a lock file cannot hold a ledger
            # either; the write path reports that with its own message.
            break
    try:
        yield
    finally:
        if handle is not None:
            with contextlib.suppress(OSError):
                os.close(handle)
            with contextlib.suppress(OSError):
                lock.unlink()


def _store(path: pathlib.Path, data: dict) -> None:
    """Replace the ledger, via a temp file in the same directory.

    Written beside the target and renamed over it, so a reader never sees a
    half-written ledger and a failed write leaves the previous one intact.
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
        temp.write_text(
            json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        os.replace(temp, path)
    except OSError as exc:
        raise PortsError(f"Cannot write the port ledger at {path}: {exc}") from exc


def _key(root: pathlib.Path) -> str:
    """A checkout's ledger key: its absolute path, resolved."""
    return str(root.resolve())


def claims(data: dict) -> list[dict]:
    """Every well-formed claim in *data*, ignoring anything it cannot read."""
    out = []
    for claim in data.get("claims", []):
        if not isinstance(claim, dict):
            continue
        if not isinstance(claim.get("path"), str):
            continue
        ports = claim.get("ports")
        if not isinstance(ports, dict):
            continue
        if not all(isinstance(value, int) for value in ports.values()):
            continue
        out.append(claim)
    return out


def claim_for(data: dict, root: pathlib.Path, scope: str = "dev") -> dict | None:
    """This checkout's claim in *scope*, or ``None``."""
    key = _key(root)
    for claim in claims(data):
        if claim["path"] == key and claim.get("scope", "dev") == scope:
            return claim
    return None


def taken_by_others(data: dict, root: pathlib.Path) -> set[int]:
    """Every port some *other* checkout holds.

    Every claim, not only the dev ones: a deployed environment's published port
    is a claim on the same host over the same resource, and two allocators that
    disagree about what is taken is how the gap between the bases became the only
    thing keeping them apart.
    """
    key = _key(root)
    return {
        port
        for claim in claims(data)
        if claim["path"] != key
        for port in claim["ports"].values()
    }


# --------------------------------------------------------------------------- #
# The host
# --------------------------------------------------------------------------- #


def port_is_free(port: int) -> bool:
    """Can this process bind *port* on the loopback interface right now?

    A probe, not a reservation: something can take the port between this answer
    and the bind that matters. It is still worth asking — it skips the ports
    foreign applications are already holding, which would otherwise surface much
    later as an opaque compose bind failure.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


# --------------------------------------------------------------------------- #
# What this app calls its ports
# --------------------------------------------------------------------------- #


class Seams:
    """What this app says about its host-port names, and whether to believe it.

    :attr:`problems` is the half the first version of this module did not have.
    ``workbench.load`` answers ``(None, findings)`` for a declaration it cannot
    *read* — broken JSON, an unsupported ``schemaVersion``, an ``unmanaged``
    without a reason — and that is indistinguishable, at the type level, from an
    app that simply has no declaration. Treating the two the same means an app
    that renamed its port seam and then broke its JSON gets the default name
    published: a name its compose file never reads, so the stack binds the
    compose default and collides with another checkout. Which is the exact
    failure this module exists to remove, reintroduced by guessing.
    """

    __slots__ = ("api", "problems", "reason", "unmanaged", "web")

    def __init__(
        self,
        *,
        web: str,
        api: str,
        unmanaged: bool = False,
        reason: str = "",
        problems: tuple[str, ...] = (),
    ) -> None:
        self.web = web
        self.api = api
        self.unmanaged = unmanaged
        self.reason = reason
        self.problems = problems


def read_seams(root: pathlib.Path) -> Seams:
    """Read the port seams from ``workbench.json``, keeping why they are unsure.

    An app with no declaration is served by the defaults — ADR 0110 decision 7,
    and the whole template is that shape. An app with a declaration this reader
    cannot parse is *not* served by the defaults; it gets :attr:`Seams.problems`,
    and the caller refuses.
    """
    declared, findings = workbench.load(root)
    web, api = DEFAULT_WEB_PORT_ENV, DEFAULT_API_PORT_ENV
    if declared is None:
        problems = tuple(
            f"{finding.message} {finding.remedy}".strip() for finding in findings
        )
        return Seams(web=web, api=api, problems=problems)
    if declared.unmanaged:
        return Seams(web=web, api=api, unmanaged=True, reason=declared.reason)
    for entry in declared.services:
        name = entry.get("hostPortEnv")
        if not isinstance(name, str) or not name:
            continue
        if entry.get("role") == "web":
            web = name
        elif entry.get("role") == "api":
            api = name
    return Seams(web=web, api=api)


def declared_names(root: pathlib.Path) -> tuple[str, str]:
    """The names this app publishes its web and api host ports through."""
    seams = read_seams(root)
    return seams.web, seams.api


def is_unmanaged(root: pathlib.Path) -> tuple[bool, str]:
    """Has this app opted out of being driven? ``(True, reason)`` if so."""
    seams = read_seams(root)
    return seams.unmanaged, seams.reason


def published_by_someone_else(root: pathlib.Path, names: tuple[str, ...]) -> bool:
    """Does ``.env`` define *names* outside this command's own managed block?

    The question that keeps two managed blocks from both defining one port. A
    workbench writes its assignment into the same file under its own fences, and
    Compose takes the *last* definition of a name — so a second block asserting
    the same names is a divergence waiting for one of the two writers to change
    its mind. Whichever it was, the reader would then be watching one port while
    the stack published the other, silently, which is the defect this whole
    module exists to remove.

    So when somebody else is already publishing these names, :func:`assign`
    adopts the values and leaves the file alone: one definition, owned by
    whoever wrote it.
    """
    path = root / ".env"
    try:
        text = path.read_text(encoding="utf-8", newline="")
    except OSError:
        return False
    # Everything except our own block, so our own previous write never reads as
    # somebody else's claim on the name.
    outside = merge_block(text, "")
    return bool(_values_in(outside, names))


def _values_in(text: str, names: tuple[str, ...]) -> dict[str, int]:
    """The integer values *text* assigns to *names*, last assignment winning."""
    found: dict[str, int] = {}
    wanted = set(names)
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, _, value = stripped.partition("=")
        if name.strip() not in wanted:
            continue
        try:
            found[name.strip()] = int(value.strip())
        except ValueError:
            continue
    return found


def published(root: pathlib.Path, names: tuple[str, ...]) -> dict[str, int]:
    """The integer values ``.env`` already sets for *names*.

    The last assignment of a name wins, which is how Compose reads the file, and
    a non-integer is ignored rather than repaired: this function answers "is
    there already an answer here", and a malformed one is not an answer.
    """
    path = root / ".env"
    try:
        return _values_in(path.read_text(encoding="utf-8"), names)
    except OSError:
        return {}


# --------------------------------------------------------------------------- #
# Publication
# --------------------------------------------------------------------------- #


def render_block(values: Mapping[str, int]) -> str:
    """The managed block for *values*, fences included, or ``""`` for nothing."""
    lines = [f"{name}={value}" for name, value in sorted(values.items())]
    if not lines:
        return ""
    return "\n".join([BLOCK_BEGIN, _PREAMBLE.rstrip("\n"), *lines, BLOCK_END]) + "\n"


def _newline(text: str) -> str:
    """The file's own line ending, so a managed block does not mix styles."""
    return "\r\n" if "\r\n" in text else "\n"


def merge_block(existing: str, block: str) -> str:
    """*existing* with the managed block replaced, appended, or removed.

    Replacement is positional: a block already in the file is rewritten where it
    stands, because a diff that walks down the file on every run is a diff nobody
    reads. An opening fence with no close — a truncated write, or a hand edit —
    is treated as running to the end of the file and replaced, since leaving it
    would mean the next run appends a second block and Compose reads whichever
    came last. An empty *block* removes it, which is the only case here that
    takes something away: no assignment is better said by an absent block than by
    one asserting ports that are no longer current.
    """
    newline = _newline(existing) if existing else "\n"
    body = block.replace("\n", newline) if newline != "\n" else block
    start = existing.find(BLOCK_BEGIN)
    if start == -1:
        if not block:
            return existing
        head = existing.rstrip("\r\n")
        if not head:
            return body
        return f"{head}{newline}{newline}{body}"
    end = existing.find(BLOCK_END, start)
    if end == -1:
        tail = ""
    else:
        after = existing.find(newline, end)
        tail = "" if after == -1 else existing[after + len(newline) :]
    head = existing[:start]
    if not body:
        head = head.rstrip("\r\n")
        return f"{head}{newline}{tail}" if head else tail
    return f"{head}{body}{tail}"


def _git(root: pathlib.Path, *argv: str) -> subprocess.CompletedProcess[str] | None:
    """``git`` in *root*, or ``None`` when it cannot be run at all."""
    try:
        return subprocess.run(  # noqa: S603 - fixed argv, no shell
            ["git", *argv],  # noqa: S607
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None


def _is_repo(root: pathlib.Path) -> bool:
    result = _git(root, "rev-parse", "--is-inside-work-tree")
    return result is not None and result.returncode == 0


def _is_tracked(root: pathlib.Path, name: str) -> bool:
    result = _git(root, "ls-files", "--error-unmatch", name)
    return result is not None and result.returncode == 0


def _is_ignored(root: pathlib.Path, name: str) -> bool:
    result = _git(root, "check-ignore", "-q", name)
    return result is not None and result.returncode == 0


def hide_from_git(root: pathlib.Path, name: str = ".env") -> bool:
    """Make git ignore *name* in this checkout, locally. ``True`` if it now does.

    ``.git/info/exclude`` rather than the app's ``.gitignore``: the app's file is
    the app's to write, and appending to it would put a tooling decision in a
    diff, in a commit, and in every other developer's checkout. The exclude is
    per-clone and uncommittable, which is exactly the scope of the fact being
    recorded — *this* checkout has a managed ``.env``.

    ``git rev-parse --git-path`` resolves it, because ``root / ".git" / "info"``
    is wrong in a linked worktree: there ``.git`` is a file and the real
    directory belongs to the main checkout.
    """
    if _is_ignored(root, name):
        return True
    located = _git(root, "rev-parse", "--git-path", "info/exclude")
    if located is None or located.returncode != 0:
        return False
    exclude = pathlib.Path(located.stdout.strip())
    if not exclude.is_absolute():
        exclude = root / exclude
    try:
        current = exclude.read_text(encoding="utf-8") if exclude.exists() else ""
        if any(line.strip() == name for line in current.splitlines()):
            # Already listed and still not ignored: something else is un-ignoring
            # it (a negation in .gitignore), and a second copy would not change
            # that.
            return False
        separator = "" if not current or current.endswith("\n") else "\n"
        exclude.parent.mkdir(parents=True, exist_ok=True)
        exclude.write_text(
            f"{current}{separator}# `terp ports` writes this checkout's host ports here.\n{name}\n",
            encoding="utf-8",
        )
    except OSError:
        return False
    return _is_ignored(root, name)


def publish(root: pathlib.Path, values: Mapping[str, int]) -> tuple[bool, str]:
    """Put *values* in ``<root>/.env``'s managed block. ``(written, why not)``.

    Refused rather than attempted when git would see the result — see the module
    docstring. Otherwise best effort: a read-only checkout or a file someone
    holds open is a reason to say so, never a reason to fail the caller, because
    the assignment is still recorded and still passable on a command line.
    """
    if _is_repo(root):
        if _is_tracked(root, ".env"):
            return False, (
                "this checkout tracks .env, and a machine's ports do not belong "
                "in an app's history — a start from outside will fall back to "
                "whatever the compose file does when the names are unset"
            )
        if not hide_from_git(root):
            return False, (
                "git would report the written .env, so it was not written: it "
                "would sit in every review and refuse every template upgrade. "
                "Add .env to this project's .gitignore to get the assignment "
                "published"
            )
    path = root / ".env"
    block = render_block(values)
    if not block and not path.exists():
        # Nothing to say and no file to say it in. Writing here would create an
        # empty `.env` that the checkout never had, which a release must not do:
        # tidying up is not the same as leaving something behind.
        return True, ""
    try:
        existing = path.read_text(encoding="utf-8", newline="") if path.exists() else ""
        path.write_text(merge_block(existing, block), encoding="utf-8", newline="")
    except OSError as exc:
        return False, f"{path} could not be written ({exc})"
    return True, ""


# --------------------------------------------------------------------------- #
# Assignment
# --------------------------------------------------------------------------- #


def _pick(data: dict, root: pathlib.Path) -> tuple[int, int]:
    """The first free pair no other checkout holds."""
    taken = taken_by_others(data, root)
    for offset in range(SPAN):
        web, api = WEB_BASE + offset, API_BASE + offset
        if web in taken or api in taken:
            continue
        if port_is_free(web) and port_is_free(api):
            return web, api
    raise PortsError(
        f"No free port pair between {WEB_BASE}/{API_BASE} and "
        f"{WEB_BASE + SPAN}/{API_BASE + SPAN}. Release a claim you no longer "
        f"need with `terp ports release --root <path>`."
    )


def assign(
    root: pathlib.Path, *, reassign: bool = False
) -> tuple[dict[str, int], str, str]:
    """Claim a pair for *root* and publish it. ``(values, source, why not)``.

    *source* is where the answer came from — ``ledger``, ``published``,
    ``adopted`` or ``fresh`` — because "nothing changed", "somebody else owns
    this" and "you have new ports" are three different outcomes and a caller
    should be able to say which happened. ``adopted`` additionally means nothing
    was written: see the end of this function.

    Order matters and is the safety property: a claim already recorded is reused,
    then a value this checkout's ``.env`` already sets is *adopted*, and only
    then is a new pair picked. Adopting is what makes this safe to run against a
    checkout another tool already assigned — the alternative is picking a second
    answer and moving the ports of a stack that may well be up.
    """
    seams = read_seams(root)
    if seams.problems:
        raise PortsError(
            "This app's workbench.json cannot be read, so the names it "
            "publishes its ports through are unknown:\n  "
            + "\n  ".join(seams.problems)
            + "\nNothing was assigned. Publishing the default names instead "
            "would put values in .env that this app's compose file may never "
            "read, which is the collision this command exists to prevent. Run "
            "`terp verify --only workbench` for the full report."
        )
    if seams.unmanaged:
        raise PortsError(
            f"workbench.json declares this app unmanaged: {seams.reason}. "
            "An app that drives its own development loop names its own ports."
        )
    web_env, api_env = seams.web, seams.api
    path = ledger_path()
    with _ledger_lock():
        return _assign_locked(root, path, web_env, api_env, reassign=reassign)


def _assign_locked(
    root: pathlib.Path,
    path: pathlib.Path,
    web_env: str,
    api_env: str,
    *,
    reassign: bool,
) -> tuple[dict[str, int], str, str]:
    """The read-compute-replace half of :func:`assign`, under the ledger lock."""
    data = _load(path)
    _refuse_a_newer_ledger(data)

    source = "fresh"
    values: dict[str, int] | None = None
    existing = None if reassign else claim_for(data, root)
    if existing is not None:
        ports = existing["ports"]
        if web_env in ports and api_env in ports:
            source = "ledger"
            values = {web_env: ports[web_env], api_env: ports[api_env]}
        elif len(set(ports.values())) >= 2:
            # The app renamed its port seams since the claim was recorded. The
            # numbers are still this checkout's to keep; only the names move, and
            # the lower of the two is the web one — that is what the bases mean.
            recorded = sorted(set(ports.values()))
            source = "ledger"
            values = {web_env: recorded[0], api_env: recorded[-1]}
    if values is None and not reassign:
        adopted = published(root, (web_env, api_env))
        if len(adopted) == 2:
            source = "published"
            values = dict(adopted)
    if values is None:
        web, api = _pick(data, root)
        values = {web_env: web, api_env: api}

    data["schemaVersion"] = SCHEMA_VERSION
    data["claims"] = [
        claim
        for claim in claims(data)
        if not (claim["path"] == _key(root) and claim.get("scope", "dev") == "dev")
    ]
    data["claims"].append({"path": _key(root), "scope": "dev", "ports": values})
    _store(path, data)

    if source == "published" and published_by_someone_else(
        root, (web_env, api_env)
    ):
        # Adopted from a definition this command does not own — a workbench's
        # managed block, or a line somebody wrote by hand. Writing our own block
        # too would put two definitions of one port in one file, and Compose
        # takes the last: the moment either writer changed its mind, the reader
        # would watch one port while the stack published the other. One
        # definition, owned by whoever wrote it.
        return values, "adopted", ""
    _, why_not = publish(root, values)
    return values, source, why_not


def ensure_assigned(root: pathlib.Path) -> tuple[dict[str, int], str]:
    """Make sure this checkout has a published assignment. ``(values, note)``.

    The start-path entry point, and the reason :func:`assign` is not called
    directly from one: **this never raises.** A developer running the app is not
    in a position to care that a ledger could not be written or that a
    declaration is unreadable, and a start that dies because the assignment
    could not be arranged is worse than one that proceeds and lets the compose
    file say what it needs. So every refusal comes back as *note* — something to
    print — and the caller goes on to run the stack.

    An app that declared itself unmanaged gets nothing and is told nothing: it
    said its development loop is its own, and a line of output about ports it
    does not use would be this tool insisting anyway.
    """
    seams = read_seams(root)
    if seams.unmanaged:
        return {}, ""
    try:
        values, source, why_not = assign(root)
    except PortsError as exc:
        return {}, str(exc)
    notes = []
    if source == "fresh":
        listing = ", ".join(f"{n}={v}" for n, v in sorted(values.items()))
        notes.append(f"terp ports: assigned {listing} and published them in .env")
    if why_not:
        notes.append(f"terp ports: the assignment was not published — {why_not}")
    return values, "\n".join(notes)


def release(root: pathlib.Path) -> bool:
    """Drop this checkout's dev claim and its published block. ``True`` if held."""
    path = ledger_path()
    with _ledger_lock():
        data = _load(path)
        _refuse_a_newer_ledger(data)
        held = claim_for(data, root) is not None
        data["schemaVersion"] = SCHEMA_VERSION
        data["claims"] = [
            claim
            for claim in claims(data)
            if not (claim["path"] == _key(root) and claim.get("scope", "dev") == "dev")
        ]
        _store(path, data)
    publish(root, {})
    return held


# --------------------------------------------------------------------------- #
# The command
# --------------------------------------------------------------------------- #


def run_ports_command(*, action: str, root: str = ".", reassign: bool = False) -> int:
    """Run one ``terp ports`` subcommand; returns the process exit code."""
    project_root = pathlib.Path(root).expanduser().resolve()
    if action == "list":
        return _render_list()
    if not project_root.is_dir():
        print(f"No such directory: {project_root}")
        return 2
    if action == "show":
        return _render_show(project_root)
    if action == "assign":
        return _render_assign(project_root, reassign=reassign)
    if action == "release":
        return _render_release(project_root)
    print(f"Unknown ports action: {action}")
    return 2


def _render_list() -> int:
    path = ledger_path()
    recorded = claims(_load(path))
    if not recorded:
        print(f"No host-port claims recorded in {path}.")
        return 0
    print(f"Host-port claims on this machine ({path}):")
    for claim in sorted(recorded, key=lambda c: (c["path"], c.get("scope", "dev"))):
        ports = ", ".join(
            f"{name}={value}" for name, value in sorted(claim["ports"].items())
        )
        print(f"  {claim['path']}  [{claim.get('scope', 'dev')}]  {ports}")
    return 0


def _render_show(root: pathlib.Path) -> int:
    seams = read_seams(root)
    if seams.unmanaged:
        print(
            f"workbench.json declares this app unmanaged: {seams.reason}\n"
            "`terp ports` does not assign for it — the app names its own ports."
        )
        return 0
    if seams.problems:
        print(
            "This app's workbench.json cannot be read, so which names it "
            "publishes its ports through is unknown:\n  "
            + "\n  ".join(seams.problems)
            + "\nRun `terp verify --only workbench` for the full report."
        )
        return 1
    web_env, api_env = seams.web, seams.api
    claim = claim_for(_load(ledger_path()), root)
    if claim is None:
        print(
            f"No host ports claimed for {root}.\n"
            f"Run `terp ports assign` to claim a pair and publish it as "
            f"{web_env}/{api_env} in .env."
        )
        return 0
    for name, value in sorted(claim["ports"].items()):
        print(f"{name}={value}")
    in_file = published(root, (web_env, api_env))
    if in_file != claim["ports"]:
        print(
            "\n.env does not publish this claim. A start from outside a workbench "
            "will not land on these ports — run `terp ports assign` to publish it."
        )
    return 0


def _render_assign(root: pathlib.Path, *, reassign: bool) -> int:
    unmanaged, reason = is_unmanaged(root)
    if unmanaged:
        # Not an error: the app said its loop is its own, and it is. Exit 0 so a
        # caller that assigns before starting is not broken by an opt-out.
        print(
            f"workbench.json declares this app unmanaged: {reason}\n"
            "Nothing assigned: an app that drives its own development loop names "
            "its own ports, and guessing which names would be this tool deciding "
            "something the app has said is its own."
        )
        return 0
    try:
        values, source, why_not = assign(root, reassign=reassign)
    except PortsError as exc:
        print(str(exc))
        return 1
    for name, value in sorted(values.items()):
        print(f"{name}={value}")
    if source == "adopted":
        print(
            "\nAdopted the pair another writer already publishes in .env, and "
            "left its file alone — two definitions of one port would diverge the "
            "moment either of us changed our mind."
        )
    elif source == "published":
        print("\nAdopted the pair this checkout's .env already set.")
    elif source == "ledger":
        print("\nAlready claimed; re-published unchanged.")
    if why_not:
        print(f"\nNot published: {why_not}.")
        return 1
    return 0


def _render_release(root: pathlib.Path) -> int:
    if release(root):
        print(f"Released the host ports claimed for {root}.")
    else:
        print(f"No host ports were claimed for {root}; removed any published block.")
    return 0


__all__ = [
    "API_BASE",
    "BLOCK_BEGIN",
    "BLOCK_END",
    "SCHEMA_VERSION",
    "SPAN",
    "WEB_BASE",
    "PortsError",
    "Seams",
    "assign",
    "claim_for",
    "claims",
    "declared_names",
    "hide_from_git",
    "home",
    "is_unmanaged",
    "ledger_path",
    "merge_block",
    "port_is_free",
    "publish",
    "published",
    "published_by_someone_else",
    "release",
    "read_seams",
    "render_block",
    "run_ports_command",
    "taken_by_others",
]
