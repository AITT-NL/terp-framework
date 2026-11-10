"""Each change to who can reach what, labelled a widening or a narrowing (ADR 0209).

The ``authz-surface`` check compares an app's composed surface with its committed baseline
(ADR 0139). This module says what each difference is: one entry per changed endpoint,
module, role ladder or permission set, each carrying ``widens``.

A change is a narrowing only when the guard's own replayed answers prove that nobody gains
reach; everything else is a widening, including a difference this module cannot itemise.
It is set inclusion over the answers ``decide`` already gives, never a judgement of which
change is dangerous: that would be a second authorization model, which ADR 0121 exists to
prevent. A tool can then put the widenings, and only those, in front of a person.
"""

from __future__ import annotations

from typing import Any

#: How far one rung's answer reaches. A ``grant`` reaches whoever holds the permission. Every
#: answer not named here (``rank``, ``no_policy``, ``unknown_permission``,
#: ``unauthenticated``, ``unregistered_role``) refuses, and reaches nobody.
_REACH = {"public": 3, "allowed": 2, "allowed_in_module": 2, "grant": 1}

Key = tuple[str, str]


def _reach(answer: object) -> int:
    return _REACH.get(answer, 0) if isinstance(answer, str) else 0


def endpoint_key(endpoint: dict[str, Any]) -> Key:
    """``(path, methods)``: the identity a baseline and a surface compare endpoints on."""
    return endpoint["path"], ",".join(endpoint.get("methods", ())) or "WS"


def _endpoints(surface: dict[str, Any]) -> dict[Key, tuple[str, dict[str, Any]]]:
    return {
        endpoint_key(endpoint): (module["name"], endpoint)
        for module in surface.get("modules", ())
        for endpoint in module.get("endpoints", ())
    }


def _labels(graph: dict[str, Any] | None) -> tuple[dict[Key, Any], dict[str, Any]]:
    """Each endpoint's declared operation, and each permission's label, from the graph."""
    operations: dict[Key, Any] = {}
    permissions: dict[str, Any] = {}
    for module in (graph or {}).get("modules", ()):
        for endpoint in module.get("endpoints", ()):
            operations[endpoint_key(endpoint)] = endpoint.get("operation")
    for permission in (graph or {}).get("permissions", ()):
        permissions[permission["name"]] = permission.get("label")
    return operations, permissions


def _entry(subject: str, change: str, widens: bool, **detail: Any) -> dict[str, Any]:
    methods = detail.get("methods")
    return {
        "subject": subject,
        "module": detail.get("module"),
        "methods": methods.split(",") if methods else [],
        "path": detail.get("path"),
        "operation": detail.get("operation"),
        "gains": sorted(detail.get("gains", ())),
        "loses": sorted(detail.get("loses", ())),
        "anonymous": bool(detail.get("anonymous")),
        "permissions": detail.get("permissions", []),
        "change": change,
        "widens": widens,
    }


def _permissions_involved(
    names: set[str], permission_labels: dict[str, Any]
) -> list[dict[str, Any]]:
    return [{"name": name, "label": permission_labels.get(name)} for name in sorted(names)]


def _named_permissions(*endpoints: dict[str, Any]) -> set[str]:
    names: set[str] = set()
    for endpoint in endpoints:
        kind, _, name = str(endpoint.get("requirement", "")).partition(":")
        if kind == "permission":
            names.add(name)
        names.update(endpoint.get("extra_permissions") or ())
    return names


def _endpoint_change(
    key: Key,
    module: str,
    was: dict[str, Any],
    now: dict[str, Any],
    operation: Any,
    permission_labels: dict[str, Any],
) -> dict[str, Any] | None:
    path, methods = key
    before, after = was.get("by_role", {}), now.get("by_role", {})
    rungs = sorted(set(before) | set(after))
    gains = [rung for rung in rungs if _reach(after.get(rung)) > _reach(before.get(rung))]
    loses = [rung for rung in rungs if _reach(after.get(rung)) < _reach(before.get(rung))]
    was_grants = list(was.get("extra_permissions") or ())
    now_grants = list(now.get("extra_permissions") or ())
    parts: list[str] = []
    if was["requirement"] != now["requirement"]:
        parts.append(f"requirement {was['requirement']!r} -> {now['requirement']!r}")
    if was_grants != now_grants:
        parts.append(f"required grants {was_grants} -> {now_grants}")
    newly = [rung for rung in gains if _reach(before.get(rung)) == 0]
    if newly:
        parts.append(f"now reachable by {newly} (it was not before)")
    if wider := [rung for rung in gains if rung not in newly]:
        parts.append(f"reachable more widely by {wider}")
    if loses:
        parts.append(f"reachable less widely by {loses}")
    if not parts:
        if before == after:
            return None
        parts.append(f"the answers per rung changed: {before} -> {after}")
    # A grant on both sides of a changed requirement names another permission, so the
    # people who hold it may differ; fewer required grants admit more of them.
    regranted = was["requirement"] != now["requirement"] and any(
        before.get(rung) == "grant" and after.get(rung) == "grant" for rung in rungs
    )
    widens = bool(gains) or regranted or not set(was_grants) <= set(now_grants)
    return _entry(
        "endpoint",
        f"{methods} {path}: " + "; ".join(parts),
        widens,
        module=module,
        methods=methods,
        path=path,
        operation=operation,
        gains=gains,
        loses=loses,
        anonymous=any(answer == "public" for answer in after.values()),
        permissions=_permissions_involved(_named_permissions(was, now), permission_labels),
    )


def _floor(requirement: object, surface: dict[str, Any]) -> tuple[int, bool] | None:
    """``(rank, needs a grant)`` for a ``role:`` or ``permission:`` requirement, or ``None``."""
    kind, _, name = str(requirement).partition(":")
    ranks = {role["name"]: role["rank"] for role in surface.get("roles", ())}
    if kind == "role":
        return (ranks[name], False) if name in ranks else None
    if kind == "permission":
        floors = {item["name"]: item["min_role"] for item in surface.get("permissions", ())}
        floor = floors.get(name)
        return (ranks[floor], True) if floor in ranks else None
    return None


def _requirement_narrows(
    was: object, now: object, baseline: dict[str, Any], current: dict[str, Any]
) -> bool:
    if was == now:
        return True
    old, new = _floor(was, baseline), _floor(now, current)
    if old is None or new is None:
        return False
    (old_rank, old_grant), new_rank = old, new[0]
    # A permission moved to another permission, or to a role, admits people who were not
    # admitted before: a role admits its whole rung, a different permission other holders.
    if old_grant:
        return False
    return new_rank >= old_rank


def _policy_narrows(
    was: Any, now: Any, baseline: dict[str, Any], current: dict[str, Any]
) -> bool:
    if was == now or now is None:
        return True  # no policy refuses every caller
    if was is None:
        return False
    if now.get("public"):
        return bool(was.get("public")) and not (
            now.get("allows_public_writes") and not was.get("allows_public_writes")
        )
    if was.get("public"):
        return True
    if was.get("authenticated") and not now.get("authenticated"):
        return False
    return all(
        _requirement_narrows(was.get(tier), now.get(tier), baseline, current)
        for tier in ("read", "write")
    )


def _module_changes(baseline: dict[str, Any], current: dict[str, Any]) -> list[dict[str, Any]]:
    """A module's own policy and access, compared on their own.

    The endpoint entries test one method per route, so a route serving GET and POST can have
    its read tier lowered with no endpoint entry moving; and a module that starts taking
    per-module roles lets an assignment lift a caller over a floor (ADR 0121) without any
    rung's answer changing in this view.
    """
    before = {module["name"]: module for module in baseline.get("modules", ())}
    after = {module["name"]: module for module in current.get("modules", ())}
    entries: list[dict[str, Any]] = []
    for name in sorted(before.keys() & after.keys()):
        was, now = before[name], after[name]
        if was.get("policy") != now.get("policy"):
            entries.append(
                _entry(
                    "module",
                    f"module {name}: policy {was.get('policy')!r} -> {now.get('policy')!r}",
                    not _policy_narrows(was.get("policy"), now.get("policy"), baseline, current),
                    module=name,
                )
            )
        if was.get("access") != now.get("access"):
            assignable = bool((now.get("access") or {}).get("assignable"))
            entries.append(
                _entry(
                    "module",
                    f"module {name}: access {was.get('access')!r} -> {now.get('access')!r}",
                    assignable and not bool((was.get("access") or {}).get("assignable")),
                    module=name,
                )
            )
    return entries


def _floors_fell(baseline: dict[str, Any], current: dict[str, Any]) -> bool:
    """Whether a permission declared on both sides now has a lower floor (or one unknown)."""
    before = {item["name"]: item["min_role"] for item in baseline.get("permissions", ())}
    after = {item["name"]: item["min_role"] for item in current.get("permissions", ())}
    old_ranks = {role["name"]: role["rank"] for role in baseline.get("roles", ())}
    new_ranks = {role["name"]: role["rank"] for role in current.get("roles", ())}
    for name in before.keys() & after.keys():
        old, new = old_ranks.get(before[name]), new_ranks.get(after[name])
        if old is None or new is None or new < old:
            return True
    return False


def authority_changes(
    baseline: dict[str, Any],
    current: dict[str, Any],
    graph: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Every authority difference, each labelled with whether it widens who can reach what.

    *graph* (the access graph *current* was reduced from) supplies the labels a person reads
    a change by: each endpoint's declared operation and each permission's label. The
    baseline has neither, so an endpoint that is gone carries no operation.
    """
    operations, permission_labels = _labels(graph)
    entries: list[dict[str, Any]] = []
    before, after = _endpoints(baseline), _endpoints(current)
    for key in sorted(before.keys() & after.keys()):
        module, now = after[key]
        changed = _endpoint_change(
            key, module, before[key][1], now, operations.get(key), permission_labels
        )
        if changed is not None:
            entries.append(changed)
    for key in sorted(after.keys() - before.keys()):
        module, now = after[key]
        reaches = [rung for rung, answer in now.get("by_role", {}).items() if _reach(answer)]
        entries.append(
            _entry(
                "endpoint",
                f"{key[1]} {key[0]}: NEW endpoint, requirement {now['requirement']!r} - "
                "nothing has reviewed what it requires",
                bool(reaches),
                module=module,
                methods=key[1],
                path=key[0],
                operation=operations.get(key),
                gains=reaches,
                anonymous=any(answer == "public" for answer in now.get("by_role", {}).values()),
                permissions=_permissions_involved(_named_permissions(now), permission_labels),
            )
        )
    for key in sorted(before.keys() - after.keys()):
        module, was = before[key]
        entries.append(
            _entry(
                "endpoint",
                f"{key[1]} {key[0]}: gone from the surface",
                False,
                module=module,
                methods=key[1],
                path=key[0],
                loses=[rung for rung, answer in was.get("by_role", {}).items() if _reach(answer)],
            )
        )
    entries.extend(_module_changes(baseline, current))
    # The ladder itself, last: a changed rank silently re-scores every floor above it, so it
    # is a widening however it moved.
    if baseline.get("roles") != current.get("roles"):
        entries.append(
            _entry(
                "roles",
                f"the role ladder changed: {baseline.get('roles')} -> {current.get('roles')}",
                True,
            )
        )
    if baseline.get("permissions") != current.get("permissions"):
        entries.append(
            _entry(
                "permissions",
                "the declared permissions or their floors changed",
                _floors_fell(baseline, current),
            )
        )
    # Anything the entries above do not name is still a change to who can reach what, or to
    # the record of it. Passing it as "no difference" is the one answer this check must never
    # give, so it is reported whole, and as a widening.
    if not entries and baseline != current:
        entries.append(
            _entry(
                "surface",
                "the authorization surface changed in a way this check does not itemise; "
                "read the diff of authz-surface.json line by line",
                True,
            )
        )
    return entries
