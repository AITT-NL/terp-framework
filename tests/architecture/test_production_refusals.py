"""Every production-only refusal is either reached by the gate or recorded as not.

ADR 0128 put a lane in ``terp verify`` for one failure: a tree whose pre-ship gate is
green and whose production boot is refused. The lane reads exactly three surfaces off
the declared ``ControlPlane``, and that scope is right — it costs one module import and
needs no environment, no database and no request.

What had no control at all was the SET. A production-only refusal written anywhere else
joins a class the lane models without joining the lane, silently, and the next reader of
``verify.py`` has no way to tell a deliberate carve-out from one nobody noticed. The
federated-identity allowlist refusal shipped six days after ADR 0128 was accepted, and
`OIDCProviderConfig`'s plaintext refusal predates the security wave entirely; neither was
named anywhere as an accepted gap.

So the set is written down. A new ``settings.is_production``-conditional raise fails this
test until someone classifies it — reached by the lane, or recorded with the reason it
cannot be. That is the whole mechanism: the gate's coverage of this class stops being
folklore, and the list starts honest rather than as a blanket exemption, because the
carve-out ``verify.py`` already documents in prose is its first entry.
"""

from __future__ import annotations

import ast
import pathlib

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_BACKEND = _REPO_ROOT / "packages" / "backend"

#: The lane reads this refusal off the declared control plane, so a red gate precedes
#: the refused boot. `_run_production_readiness`, packages/backend/cli/src/terp/cli/verify.py.
_REACHED = "production-readiness reads it from the declared ControlPlane"

#: Every ``settings.is_production``-conditional ``raise`` under ``packages/backend/``,
#: by the scope that holds it, with one entry per raise IN SOURCE ORDER.
#:
#: The count is part of the contract: adding a refusal to a scope already listed here is
#: as much a change to the gate's coverage as adding one to a new scope, and the audit
#: carve-out — a refusal inside ``create_app``, which the lane otherwise models
#: completely — is exactly the case a per-scope record would have hidden.
_PRODUCTION_REFUSALS: dict[str, tuple[tuple[str, str], ...]] = {
    "terp/core/app.py::create_app": (
        ("insecure security config", _REACHED),
        ("password policy with no strength floor", _REACHED),
        (
            "audit enabled with no durable sink",
            "decided by create_app(audit_sink=...), a RUNTIME ARGUMENT the lane cannot "
            "see — it reads the declared plane and never builds the app. Documented as "
            "a deliberate gap in _run_production_readiness's docstring and at "
            "verify.py's audit carve-out: a check that pretended to cover this would be "
            "worse than the gap.",
        ),
        ("unattributable background writes", _REACHED),
    ),
    "terp/capabilities/identity/federated.py::FederatedIdentityService.__init__": (
        (
            "JIT provisioning with no identity allowlist",
            "a CAPABILITY OBJECT the app constructs itself; ControlPlane has no field "
            "that reaches it, so the lane cannot ask. Mitigated rather than closed: "
            "`production_problems()` makes the verdict answerable off the production "
            "host, and the state warns on every non-production boot instead of being "
            "silent until the deploy.",
        ),
    ),
    "terp/capabilities/oidc/config.py::OIDCProviderConfig.__post_init__": (
        (
            "plaintext issuer or redirect_uri",
            "a CAPABILITY OBJECT the app constructs itself; ControlPlane has no field "
            "that reaches it, so the lane cannot ask. Mitigated the same way as the "
            "federated refusal above: an environment-independent `production_problems()` "
            "and a warning on every non-production boot.",
        ),
    ),
}


def _scope_of(path: pathlib.Path, names: list[str]) -> str:
    """``<module path relative to its src root>::<dotted scope>``."""
    parts = path.parts
    index = parts.index("src") if "src" in parts else 0
    module = "/".join(parts[index + 1 :])
    return f"{module}::{'.'.join(names)}"


def _production_conditional_raises() -> dict[str, list[int]]:
    """Scope -> line numbers of each ``raise`` under a ``settings.is_production`` test."""
    found: dict[str, list[int]] = {}

    def walk(node: ast.AST, gated: bool, names: list[str], path: pathlib.Path) -> None:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            names = [*names, node.name]
        if gated and isinstance(node, ast.Raise):
            found.setdefault(_scope_of(path, names), []).append(node.lineno)
        for child in ast.iter_child_nodes(node):
            child_gated = gated
            if isinstance(node, ast.If) and child in node.body:
                child_gated = gated or any(
                    isinstance(inner, ast.Attribute) and inner.attr == "is_production"
                    for inner in ast.walk(node.test)
                )
            walk(child, child_gated, names, path)

    for path in sorted(_BACKEND.rglob("*.py")):
        if "__pycache__" in path.parts or "tests" in path.parts:
            continue
        walk(ast.parse(path.read_text(encoding="utf-8")), False, [], path)
    return found


def test_every_production_only_refusal_is_classified() -> None:
    found = _production_conditional_raises()

    unrecorded = sorted(set(found) - set(_PRODUCTION_REFUSALS))
    assert not unrecorded, (
        "these refuse a production boot and nothing classifies them:\n"
        + "".join(f"  - {scope} (line(s) {found[scope]})\n" for scope in unrecorded)
        + "\nAdd each to _PRODUCTION_REFUSALS in this file. If the pre-ship gate reaches "
        "it, say so; if it cannot, say WHY — that entry is the record a later reader uses "
        "to tell a deliberate carve-out from one nobody noticed."
    )

    stale = sorted(set(_PRODUCTION_REFUSALS) - set(found))
    assert not stale, (
        "these are recorded as production-only refusals and no longer are: "
        f"{stale}. Remove them — a record that outlives its subject rots into a blanket "
        "exemption, which is the shape this list exists to avoid."
    )

    miscounted = {
        scope: (len(found[scope]), len(_PRODUCTION_REFUSALS[scope]))
        for scope in found
        if len(found[scope]) != len(_PRODUCTION_REFUSALS[scope])
    }
    assert not miscounted, (
        "the number of production-only refusals in these scopes does not match the "
        f"record (found, recorded): {miscounted}. A refusal added to a scope already "
        "listed here changes the gate's coverage exactly as much as one in a new scope; "
        "the audit-sink carve-out lives inside create_app, which the lane otherwise "
        "models completely."
    )


def test_the_record_says_something_about_every_entry() -> None:
    """A blank reason is the rot this list exists to prevent."""
    for scope, refusals in _PRODUCTION_REFUSALS.items():
        for label, reason in refusals:
            assert label.strip(), f"{scope}: a refusal with no label"
            assert len(reason.strip()) > 40, (
                f"{scope} / {label!r}: the reason must actually say something — either "
                f"{_REACHED!r} or why the lane cannot reach it"
            )


def test_the_lane_reaches_everything_the_control_plane_declares() -> None:
    """The three surfaces the record calls reached are the three the lane reads.

    Keeps the record honest from the other side: if the lane stopped reading one of
    these, every entry claiming to be reached by it would still read as fine.
    """
    verify_source = (
        _REPO_ROOT
        / "packages"
        / "backend"
        / "cli"
        / "src"
        / "terp"
        / "cli"
        / "verify.py"
    ).read_text(encoding="utf-8")
    for surface in (
        "plane.security.production_problems()",
        "plane.passwords.production_problems()",
        "plane.production_problems()",
    ):
        assert surface in verify_source, (
            f"production-readiness no longer reads {surface}, so the entries in "
            "_PRODUCTION_REFUSALS that claim it does are now false"
        )
