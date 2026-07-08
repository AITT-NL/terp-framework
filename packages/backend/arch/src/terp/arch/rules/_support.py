"""Shared machinery for the ``terp.arch`` rule modules.

The :class:`ArchViolation` value type, the scan constants, the small AST/path
helpers, and the ``# arch-allow-*`` escape-hatch marker machinery — everything the
individual rule modules in this package build on. Rule functions live in the
themed sibling modules (``imports`` / ``authz`` / ``http`` / ``persistence`` /
``events`` / ``traits`` / ``budget``); this module holds no rules itself.
"""

from __future__ import annotations

import ast
import pathlib
import re
from collections.abc import Iterable
from dataclasses import dataclass

from terp.arch._ast import base_name, iter_python_files

_HTTP_METHODS = frozenset({"get", "post", "put", "patch", "delete"})
_SESSION_CONSTRUCTORS = frozenset({"Session", "create_engine", "sessionmaker"})
_POLICY_AUTHZ_KEYWORDS = frozenset({"read", "write", "read_role", "write_role"})

# The body-mutating HTTP verbs: a route on one of these is a write surface, so its
# module ``Policy`` must require a write tier above the read floor (VIEWER).
_MUTATING_HTTP_METHODS = frozenset({"post", "put", "patch", "delete"})

# Raw session-write verbs and the conventional session variable names a module
# would call them on. ``mutations_emit_audit`` flags ``session.commit()`` and
# friends so every persistence goes through the audited ``BaseService`` chokepoint.
# The verb set covers the ORM unit-of-work writers *and* the bulk/flush helpers; a
# write smuggled through ``execute`` / ``exec`` with a DML statement is detected
# separately (see ``_SESSION_EXECUTORS`` / ``_DML_CHAIN_ROOTS``).
_SESSION_MUTATORS = frozenset(
    {
        "add",
        "add_all",
        "delete",
        "merge",
        "commit",
        "flush",
        "bulk_save_objects",
        "bulk_insert_mappings",
        "bulk_update_mappings",
    }
)
_SESSION_VAR_NAMES = frozenset({"session", "db", "sess", "db_session"})

# The annotations that make a parameter a session handle, so a write on it is
# flagged regardless of the variable's *name* (``def f(s: SessionDep): s.add(...)``
# no longer evades the rule just by renaming the variable).
_SESSION_TYPES = frozenset({"Session", "SessionDep"})

# ``session.execute(...)`` / ``session.exec(...)`` are reads when handed a
# ``select(...)`` but writes when handed a DML statement; flag only the latter.
_SESSION_EXECUTORS = frozenset({"execute", "exec"})
_DML_CHAIN_ROOTS = frozenset({"insert", "update", "delete", "text"})

# Framework-managed row-scope columns: a module must never filter, set, or compare
# these by hand. ``BaseService.base_query`` applies the soft-delete predicate and
# the tenancy scoped service applies the tenant predicate, centrally.
_MANAGED_SCOPE_COLUMNS = frozenset({"deleted_at", "tenant_id"})

# Framework-managed actor-stamp columns: a module must never set these by hand.
# ``BaseService._save`` fills them from the request actor (ADR 0012) — a hand-set
# value would forge or clobber provenance.
_MANAGED_ACTOR_COLUMNS = frozenset({"created_by_id", "modified_by_id"})

# Framework-managed ownership column: a module must never filter, set, or compare
# this by hand. ``BaseService`` stamps ``owner_id`` from the request actor on create
# and authorizes every update/delete of an owned row centrally (ADR 0029) — a
# hand-rolled ``entity.owner_id == principal.id`` check is the easy-to-get-wrong
# pattern the object-authz seam replaces (and it is distinct from the actor columns,
# so it carries its own rule).
_MANAGED_OWNERSHIP_COLUMNS = frozenset({"owner_id"})

# Framework-managed columns a client ``*Create`` / ``*Update`` input schema must
# never declare: the primary key, the audit timestamps, the optimistic-concurrency
# ``version``, plus the scope/actor/owner columns the framework fills centrally.
# Because ``BaseService.create`` / ``update`` copy a schema's fields onto the model,
# exposing any of these would re-open an over-posting (mass-assignment) hole — the
# runtime ``BaseService`` strips the same set, the two halves of one control.
_MANAGED_INPUT_COLUMNS = (
    frozenset({"id", "created_at", "updated_at", "version"})
    | _MANAGED_SCOPE_COLUMNS
    | _MANAGED_ACTOR_COLUMNS
    | _MANAGED_OWNERSHIP_COLUMNS
    | frozenset({"token_version"})
)

# A read / response DTO must never carry a credential-shaped field -- serializing one
# leaks a secret out of the API boundary. Matched as an underscore-delimited word so a
# benign name (``sort_key`` / ``version``) is never caught, while every common spelling
# is: ``password`` / ``passwd`` / ``pwd`` / ``passphrase`` / ``hashed_password`` /
# ``*_password``, anything with a ``secret`` component (``secret`` / ``secret_key`` /
# ``client_secret`` / ``mfa_secret``), an ``api_key`` / ``private_key``, a ``salt``, or a
# ``credential`` / ``credentials``. A bearer ``token`` is matched only as a *trailing*
# word (``token`` / ``access_token`` / ``refresh_token``) so the benign metadata
# ``token_type`` (e.g. "bearer") / ``token_version`` (the revocation epoch) is not caught.
# ``version`` / ``token_version`` are integer counters, not secrets, and are excluded.
_SENSITIVE_FIELD_RE = re.compile(
    r"(?:^|_)(?:password|passwd|pwd|passphrase|secret|salt|api_key|apikey"
    r"|private_key|privatekey|credentials?)(?:$|_)"
    r"|(?:^|_)token$"
)
_SENSITIVE_FIELD_EXCLUSIONS = frozenset({"token_version", "version"})


def _is_sensitive_field_name(name: str) -> bool:
    """True for a credential-shaped field name a response DTO must not expose."""
    lowered = name.lower()
    return lowered not in _SENSITIVE_FIELD_EXCLUSIONS and bool(
        _SENSITIVE_FIELD_RE.search(lowered)
    )


# Escape-hatch opt-out markers: ``# arch-allow-<rule>: <justification>``. A marker
# suppresses exactly the rule it names, on the line it annotates, and only when a
# non-empty justification follows the colon (an unjustified opt-out fails closed).
# The bare-token form is used to *count* markers for the budget ratchet (design §8).
_ALLOW_TOKEN_RE = re.compile(r"arch-allow-[a-z0-9]+(?:-[a-z0-9]+)*")
_ALLOW_MARKER_RE = re.compile(
    r"#\s*(?P<token>arch-allow-[a-z0-9]+(?:-[a-z0-9]+)*)\s*(?::\s*(?P<why>\S[^\n]*)?)?"
)


@dataclass(frozen=True)
class ArchViolation:
    """A single architecture-rule breach, with a precise, fixable message."""

    rule: str
    path: str
    line: int
    message: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: [{self.rule}] {self.message}"


# --------------------------------------------------------------------------- #
# internal helpers
# --------------------------------------------------------------------------- #
def _rel(path: pathlib.Path, app_root: pathlib.Path) -> str:
    """Path relative to the app package's parent (keeps the ``app/`` prefix)."""
    try:
        return str(path.relative_to(app_root.parent))
    except ValueError:
        return str(path)


def _module_under(path: pathlib.Path, package: str) -> str | None:
    """Return the ``modules/<name>`` a file belongs to, or ``None``."""
    parts = path.parts
    if "modules" in parts:
        index = parts.index("modules")
        if index + 1 < len(parts):
            return parts[index + 1]
    return None


def _module_parts(path: pathlib.Path, app_root: pathlib.Path) -> list[str]:
    """The dotted-module parts of *path*, rooted at the package dir (keeps the prefix).

    ``app/modules/notes/service.py`` → ``["app", "modules", "notes", "service"]``;
    an ``__init__.py`` resolves to its package (the trailing name is dropped).
    """
    try:
        rel = path.relative_to(app_root.parent)
    except ValueError:
        rel = path
    parts = list(rel.with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return parts


def _resolve_relative_import(
    importing_parts: list[str], level: int, module: str | None
) -> str:
    """Resolve a relative ``from ... import`` to its absolute dotted module.

    *importing_parts* is the importing file's dotted parts (including its own
    module name). ``level`` 1 is the current package, 2 its parent, etc. — so a
    ``from ..tasks.service import X`` in ``app.modules.notes.service`` resolves to
    ``app.modules.tasks.service``, which the cross-module rule can then inspect.
    """
    base = importing_parts[: -level] if level <= len(importing_parts) else []
    if module:
        base = [*base, *module.split(".")]
    return ".".join(base)


# Sequence containers whose element carries the input-cap obligation: a
# ``list[str]`` / ``tuple[str, ...]`` field is as unbounded as a bare ``str``, so a
# ``max_length`` (which bounds the collection's size) is still required. ``dict`` is
# intentionally excluded -- ``max_length`` is not the right bound for a mapping.
_STR_CONTAINER_TYPES = frozenset(
    {"list", "set", "frozenset", "tuple", "Sequence", "MutableSequence", "Iterable", "Collection"}
)


def _is_str_annotation(annotation: ast.expr | None) -> bool:
    """True for the input-cap-relevant string forms.

    Matches ``str``, ``str | None``, and a sequence container of those
    (``list[str]``, ``tuple[str, ...]``, ``Sequence[str] | None``) -- every shape
    where a client supplies unbounded text a ``max_length`` should cap. A ``dict``
    is deliberately not matched (``max_length`` is the wrong bound for a mapping).
    """
    if isinstance(annotation, ast.Name):
        return annotation.id == "str"
    if isinstance(annotation, ast.BinOp) and isinstance(annotation.op, ast.BitOr):
        return _is_str_annotation(annotation.left) or _is_str_annotation(annotation.right)
    if isinstance(annotation, ast.Subscript) and base_name(annotation.value) in _STR_CONTAINER_TYPES:
        slice_ = annotation.slice
        elements = slice_.elts if isinstance(slice_, ast.Tuple) else [slice_]
        return any(_is_str_annotation(element) for element in elements)
    return False


def _has_max_length(value: ast.expr | None) -> bool:
    """True when *value* is a ``Field(..., max_length=...)`` call."""
    if not isinstance(value, ast.Call) or base_name(value.func) != "Field":
        return False
    return any(keyword.arg == "max_length" for keyword in value.keywords)


def _is_table_model_class(node: ast.ClassDef) -> bool:
    """True when *node* declares an ORM table (``class X(..., table=True)``).

    The single source of truth for "is this a persisted model" across the rules:
    ``table_models_use_base_table`` (every table extends ``BaseTable``) and
    ``response_model_not_table_model`` (a table model must not be serialized out).
    """
    return any(
        keyword.arg == "table"
        and isinstance(keyword.value, ast.Constant)
        and keyword.value.value is True
        for keyword in node.keywords
    )


def _service_model(node: ast.ClassDef) -> str | None:
    """Return the model name a service binds via ``model = <Name>``."""
    for stmt in node.body:
        if isinstance(stmt, ast.Assign):
            for target in stmt.targets:
                if (
                    isinstance(target, ast.Name)
                    and target.id == "model"
                    and isinstance(stmt.value, ast.Name)
                ):
                    return stmt.value.id
    return None


def _annotated_session_params_for_function(node: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    """Session-typed parameter names for one function scope only."""
    names: set[str] = set()
    params = (
        *node.args.posonlyargs,
        *node.args.args,
        *node.args.kwonlyargs,
    )
    for param in params:
        if param.annotation is not None and base_name(param.annotation) in _SESSION_TYPES:
            names.add(param.arg)
    return names


def _has_http_route_decorator(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """True when *node* carries an HTTP route decorator (``@router.get`` / ``.post`` / ...)."""
    for decorator in node.decorator_list:
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        if isinstance(target, ast.Attribute) and target.attr in _HTTP_METHODS:
            return True
    return False


def _annotation_type_name(annotation: ast.expr | None) -> str | None:
    """The principal class name of a parameter annotation, unwrapping the ordinary
    wrappers so a request-body DTO is recognized in every common form.

    ``LoginRequest`` / ``schemas.LoginRequest`` -> ``"LoginRequest"``;
    ``Annotated[LoginRequest, Body()]`` -> ``"LoginRequest"``; ``LoginRequest |
    None`` / ``Optional[LoginRequest]`` -> ``"LoginRequest"``. A non-DTO annotation
    (``SessionDep``, ``int``) yields a name with no matching ``ClassDef``, which the
    caller harmlessly ignores.
    """
    if annotation is None:
        return None
    if isinstance(annotation, ast.Subscript):
        head = base_name(annotation.value)
        if head in {"Annotated", "Optional"}:
            inner = annotation.slice
            first = inner.elts[0] if isinstance(inner, ast.Tuple) and inner.elts else inner
            return _annotation_type_name(first)
        return head
    if isinstance(annotation, ast.BinOp) and isinstance(annotation.op, ast.BitOr):
        return _annotation_type_name(annotation.left) or _annotation_type_name(annotation.right)
    return base_name(annotation)


def _request_body_model_names(trees: Iterable[ast.AST]) -> set[str]:
    """Names of classes used as an HTTP request body anywhere in the app.

    A class is a request body when it annotates a route handler's parameter
    (``def provision(payload: UserProvision)``, including the ``Annotated[...]`` /
    ``T | None`` / qualified ``module.T`` forms) or is passed to
    ``build_crud_router(create_schema=/update_schema=...)``. Non-body params
    (``session: SessionDep``, ``count: int``) resolve to names with no matching
    ``ClassDef`` and are harmlessly ignored by the caller -- so the set lets the
    input rules treat off-convention input DTOs (``LoginRequest``) as inputs, not
    only the ``*Create`` / ``*Update`` ones.
    """
    names: set[str] = set()
    for tree in trees:
        for node in ast.walk(tree):
            if isinstance(
                node, ast.FunctionDef | ast.AsyncFunctionDef
            ) and _has_http_route_decorator(node):
                params = (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs)
                names.update(
                    name
                    for param in params
                    if (name := _annotation_type_name(param.annotation)) is not None
                )
            elif isinstance(node, ast.Call) and base_name(node.func) == "build_crud_router":
                names.update(
                    keyword.value.id
                    for keyword in node.keywords
                    if keyword.arg in {"create_schema", "update_schema"}
                    and isinstance(keyword.value, ast.Name)
                )
    return names


def _response_model_names(trees: Iterable[ast.AST]) -> set[str]:
    """Names of classes serialized out of the boundary via ``response_model=``.

    Covers decorator routes (``@router.get(..., response_model=NoteRead)``),
    imperative ``add_api_route(..., response_model=...)``, and the
    ``build_crud_router(read_schema=...)`` factory. ``Page[NoteRead]`` resolves to
    ``NoteRead`` (``base_name`` unwraps the subscript), so a paginated read DTO is
    recognized. Lets the sensitive-field rule treat *any* outbound DTO as a response,
    even one named off-convention or an input DTO mistakenly reused as a response.
    """
    names: set[str] = set()
    for tree in trees:
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            is_crud_factory = base_name(node.func) == "build_crud_router"
            for keyword in node.keywords:
                if keyword.arg == "response_model" or (is_crud_factory and keyword.arg == "read_schema"):
                    if (name := base_name(keyword.value)) is not None:
                        names.add(name)
    return names


def _is_text_dml(expr: ast.Call) -> bool:
    """True for ``text('INSERT ...')`` / ``text('UPDATE ...')`` / etc."""
    if base_name(expr.func) != "text" or not expr.args:
        return False
    first = expr.args[0]
    if not isinstance(first, ast.Constant) or not isinstance(first.value, str):
        # Dynamic SQL through text(...) is not statically knowable; fail closed.
        return True
    leading = first.value.lstrip().split(None, 1)[0].lower() if first.value.strip() else ""
    return leading in {"insert", "update", "delete", "merge", "replace", "create", "drop", "alter", "truncate"}


def _is_dml_expression(expr: ast.expr) -> bool:
    """Return whether *expr* is a statically recognizable SQL DML statement."""
    current = expr
    while isinstance(current, ast.Call):
        if not isinstance(current.func, ast.Attribute):
            name = base_name(current.func)
            if name == "text":
                return _is_text_dml(current)
            return name in _DML_CHAIN_ROOTS
        current = current.func.value
    return False


def _rule_token(rule: str) -> str:
    """The opt-out marker that suppresses *rule* (``no_x`` → ``arch-allow-no-x``)."""
    return "arch-allow-" + rule.replace("_", "-")


@dataclass(frozen=True)
class _AllowMarker:
    """An ``# arch-allow-*`` comment found on a single source line."""

    token: str
    justified: bool


def _scan_allow_markers(root: pathlib.Path) -> dict[str, dict[int, _AllowMarker]]:
    """Map each app file (rel path) → {line: marker} for every ``arch-allow-*`` comment."""
    markers: dict[str, dict[int, _AllowMarker]] = {}
    for path in iter_python_files(root):
        per_line: dict[int, _AllowMarker] = {}
        for lineno, text in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            match = _ALLOW_MARKER_RE.search(text)
            if match:
                per_line[lineno] = _AllowMarker(match.group("token"), bool(match.group("why")))
        if per_line:
            markers[_rel(path, root)] = per_line
    return markers


def _apply_suppressions(
    violations: list[ArchViolation], markers: dict[str, dict[int, _AllowMarker]]
) -> list[ArchViolation]:
    """Drop violations suppressed by a justified ``arch-allow-<rule>`` on their line.

    A marker that names the violated rule but carries no justification does **not**
    suppress (fail-closed); it is reported as ``escape_hatch_requires_justification``
    so the only fix is to add a reason — never to silently opt out.
    """
    result: list[ArchViolation] = []
    for violation in violations:
        marker = markers.get(violation.path, {}).get(violation.line)
        if marker is None or marker.token != _rule_token(violation.rule):
            result.append(violation)
            continue
        if marker.justified:
            continue  # explicit, justified, budgeted opt-out
        result.append(
            ArchViolation(
                "escape_hatch_requires_justification",
                violation.path,
                violation.line,
                f"{marker.token!r} suppresses {violation.rule!r} but gives no reason; "
                "add ': <justification>' — an unjustified opt-out does not apply",
            )
        )
    return result
