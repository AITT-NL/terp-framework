"""What a module's `Policy` call says, read out of the source.

Split out of ``authz.py`` when that module crossed the 500-line cap. These eight
definitions are the group the size rule itself named: they answer one question --
what does this module declare about who may do what -- and nothing outside the authz
rules asks it, so the cut leaves no dangling name behind.

The rank table is the *default* ladder, deliberately. A build-time check reads source
and cannot resolve an application's own `role_ranks`, so it reasons about the rungs
Terp ships and defers the rest to the boot-time control (`validate_policy_write_tiers`),
which sees the resolved ranks. This module is the early warning; that one is the gate.
"""

from __future__ import annotations

import ast

from terp.arch._ast import base_name
from terp.arch.rules._support import (
    _MUTATING_HTTP_METHODS,
    iter_route_registrations,
)

__all__ = [
    "DEFAULT_ROLE_RANKS",
    "has_mutating_route",
    "methods_kwarg_has_mutation",
    "module_policy_calls",
    "policy_kwarg",
    "static_default_rank",
]


def methods_kwarg_has_mutation(keywords: list[ast.keyword]) -> bool:
    """True when a route call's ``methods=[...]`` lists a write verb."""
    for keyword in keywords:
        if keyword.arg == "methods" and isinstance(keyword.value, ast.List | ast.Tuple):
            if any(
                isinstance(element, ast.Constant)
                and isinstance(element.value, str)
                and element.value.lower() in _MUTATING_HTTP_METHODS
                for element in keyword.value.elts
            ):
                return True
    return False


def has_mutating_route(tree: ast.Module) -> bool:
    """True when *tree* declares a write route (``post`` / ``put`` / ``patch`` / ``delete``).

    Catches the verb decorators (``@router.post``), a generic ``@router.api_route`` /
    imperative ``add_api_route`` with ``methods=`` listing a write verb, so a write
    surface cannot dodge the policy check by its registration spelling.

    Migrated onto ``iter_route_registrations``: the pre-migration walk additionally
    matched *any* ``Call`` node whose attribute was ``add_api_route`` / ``api_route``,
    independent of whether it was a decorator or a registration at all. That caught
    every real registration twice (once as the decorator, once as the same node
    revisited by the generic walk) and, in principle, a bare non-decorator
    ``router.api_route(...)`` call applied to nothing — a shape FastAPI's own API
    does not produce and that no test or corpus case exercises. Dropping it changes
    no observable behaviour: every registration this rule must see still reaches it
    through the decorator or the imperative form below.
    """
    for route in iter_route_registrations(tree):
        if route.verb in _MUTATING_HTTP_METHODS:
            return True
        if (route.verb == "api_route" or route.imperative) and methods_kwarg_has_mutation(
            list(route.keywords)
        ):
            return True
    return False


def module_policy_calls(tree: ast.Module) -> list[ast.Call]:
    """The ``Policy(...)`` / ``Policy.tiers(...)`` expressions bound to a ``ModuleSpec.policy``.

    Only the policy actually handed to ``ModuleSpec(policy=...)`` is returned, so an
    unrelated weak ``Policy(...)`` sitting elsewhere in the file is never mistaken for
    the module's posture.
    """
    calls: list[ast.Call] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or base_name(node.func) != "ModuleSpec":
            continue
        for keyword in node.keywords:
            value = keyword.value
            if keyword.arg == "policy" and isinstance(value, ast.Call):
                func = value.func
                rooted_at_policy = (isinstance(func, ast.Name) and func.id == "Policy") or (
                    isinstance(func, ast.Attribute)
                    and isinstance(func.value, ast.Name)
                    and func.value.id == "Policy"
                )
                if rooted_at_policy:
                    calls.append(value)
    return calls


# The default role ladder's ranks, so the build rule can compare a statically
# resolvable read/write tier (``Roles.VIEWER`` / the ``VIEWER`` constant / ``x.ADMIN``).
# A *custom* role's rank is not knowable from a source scan, so those are compared by
# their resolved rank at boot (``create_app`` -> ``validate_policy_write_tiers``); this
# rule is the early-warning build-time half.
DEFAULT_ROLE_RANKS: dict[str, int] = {"VIEWER": 10, "EDITOR": 20, "ADMIN": 30}


def policy_kwarg(call: ast.Call, *names: str) -> ast.expr | None:
    """Return the first present keyword value among *names* on *call*, else ``None``."""
    for keyword in call.keywords:
        if keyword.arg in names:
            return keyword.value
    return None


def static_default_rank(node: ast.expr | None, *, absent: int) -> int | None:
    """Statically resolve a role reference to its rank.

    ``None`` node -> *absent* (the framework default: read omits to ``VIEWER``, write to
    ``EDITOR``). A default-ladder reference (``Roles.ADMIN`` / ``ADMIN``) -> its rank. A
    custom role whose rank a scan cannot know -> ``None`` (the boot check compares it).
    """
    if node is None:
        return absent
    return DEFAULT_ROLE_RANKS.get(base_name(node))
