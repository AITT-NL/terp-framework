"""Reading timestamp text without its UTC offset is an escape, named and counted (ADR 0206).

A ``BaseSchema`` refuses timestamp text that carries no UTC offset, and a declared filter
refuses a bound with none: such a value names no instant, and read as UTC it puts a writer in
another zone off by its offset. ``NaiveMeansUtc`` from ``terp.core`` is the framework's way
around both, for a sender known to send UTC without saying so, and this rule refuses each use
of it, so taking it is the rule's opt-out marker, which the app's escape-hatch budget counts.

An app's own validator that runs before a timestamp's type is the other way around (ADR 0207):
a ``before``, ``wrap`` or ``plain`` validator sees the text first, so it can read a wall time
in a zone of its choosing. A wall time in a named zone is ``LocalTimeIn``'s, which names the
instant, so the rule counts such a validator on a timestamp field as the escape too.
"""

from __future__ import annotations

import ast
import pathlib
from collections.abc import Iterator

from terp.arch._ast import base_name, iter_python_files, parse
from terp.arch.rules._support import ArchViolation, _rel
from terp.arch.rules.datetimes import _bound_names

_NAIVE_MEANS_UTC = "NaiveMeansUtc"

#: The boundary's own machinery; an app takes the escape from ``terp.core``.
_TIMESTAMPS_MODULE = "terp.core.timestamps"

#: The packages the framework scans that implement the boundary rather than use it: the one
#: that defines the boundary and its escape, and the one that defines this rule, which names
#: both as the data it matches.
_IMPLEMENTING_PACKAGES = frozenset({"terp.core", "terp.arch"})

_ESCAPE_MESSAGE = (
    "NaiveMeansUtc reads a timestamp with no UTC offset as UTC, so a sender in any other "
    "zone is stored off by its offset; take the timestamp with its offset (a plain datetime "
    "field or filter refuses one without it), or, for a sender known to send UTC without "
    "saying so, keep it with '# arch-allow-request-timestamps-carry-their-offset: <reason>' "
    "(budgeted by the app's escape-hatch-budget.json)"
)
_MACHINERY_MESSAGE = (
    "terp.core.timestamps is the timestamp boundary's own module, which nothing outside the "
    "framework reaches; take the escape as NaiveMeansUtc from terp.core, where this rule "
    "counts each use, and recognise a refusal by its error type, timestamp_offset_required"
)
_EARLY_VALIDATOR_MESSAGE = (
    "a before, wrap or plain validator on a timestamp field reads its text before the "
    "timestamp's type does, so it can read a time with no UTC offset in a zone of its "
    "choosing; for the wall time of a named zone, type the field "
    "Annotated[datetime, LocalTimeIn('Europe/Amsterdam')] from terp.core, which names the "
    "instant and refuses a time the clocks skip or repeat, use an after validator, or keep "
    "it with '# arch-allow-request-timestamps-carry-their-offset: <reason>' (budgeted by the "
    "app's escape-hatch-budget.json)"
)

#: The types a timestamp is read through: a value of any of them is timestamp text first.
_TIMESTAMP_TYPES = frozenset({"datetime", "AwareDatetime", "NaiveDatetime", "PastDatetime", "FutureDatetime"})

#: Pydantic's validators that see a value before its type does, as ``Annotated`` metadata.
_EARLY_VALIDATORS = frozenset({"BeforeValidator", "WrapValidator", "PlainValidator"})

#: A field validator's modes that run before, around or instead of the type.
_EARLY_MODES = frozenset({"before", "wrap", "plain"})

#: The calls that bind a type rather than a value: their second argument is that type.
_TYPE_FACTORIES = frozenset({"NewType", "TypeAliasType"})


def _strings_outside_literals(expr: ast.AST) -> Iterator[ast.Constant]:
    if isinstance(expr, ast.Subscript) and base_name(expr.value) == "Literal":
        return
    if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
        yield expr
        return
    for child in ast.iter_child_nodes(expr):
        yield from _strings_outside_literals(child)


def _quoted_nodes(expr: ast.AST) -> list[ast.AST]:
    """The nodes of every string in *expr* that reads as an expression, parsed, at its line.

    Pydantic evaluates a string as a type wherever it stands for one: a quoted annotation
    (``"NaiveMeansUtc | None"``), a forward reference in ``Optional["NaiveMeansUtc"]``, a field
    ``create_model`` is given. So a string that names the escape takes it as surely as a name
    does. Prose does not read as an expression, and a ``Literal`` value is text, not a type.
    """
    found: list[ast.AST] = []
    for quote in _strings_outside_literals(expr):
        try:
            parsed = ast.parse(quote.value, mode="eval")
        except SyntaxError:
            continue
        for node in ast.walk(parsed):
            if isinstance(node, ast.expr):
                ast.copy_location(node, quote)
            found.append(node)
    return found


def _assignment(node: ast.AST) -> tuple[list[str], ast.expr | None]:
    if isinstance(node, ast.Assign):
        return [name for target in node.targets for name in _bound_names(target)], node.value
    if isinstance(node, ast.AnnAssign) and node.value is not None:
        return _bound_names(node.target), node.value
    if isinstance(node, ast.TypeAlias) and isinstance(node.name, ast.Name):
        return [node.name.id], node.value
    return [], None


def _mentions(value: ast.expr, names: set[str]) -> bool:
    return any(
        (isinstance(inner, ast.Name) and inner.id in names)
        or (isinstance(inner, ast.Attribute) and inner.attr == _NAIVE_MEANS_UTC)
        for inner in [*ast.walk(value), *_quoted_nodes(value)]
    )


def _bodies(scope: ast.AST) -> Iterator[ast.AST]:
    """The nodes of *scope* that run in it: not inside a nested function or class."""
    for child in ast.iter_child_nodes(scope):
        if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda | ast.ClassDef):
            continue
        yield child
        yield from _bodies(child)


def _aliases_in(scope: ast.AST, visible: set[str]) -> set[str]:
    """The names *scope* binds to the escape, by import alias, assignment or type alias."""
    names = set(visible)
    for node in _bodies(scope):
        if isinstance(node, ast.ImportFrom):
            names.update(
                alias.asname for alias in node.names if alias.name == _NAIVE_MEANS_UTC and alias.asname
            )
    grown = True
    while grown:
        grown = False
        for node in _bodies(scope):
            targets, value = _assignment(node)
            if value is None or not _mentions(value, names):
                continue
            for target in targets:
                if target not in names:
                    names.add(target)
                    grown = True
    return names


def _nested_scopes(scope: ast.AST) -> Iterator[ast.AST]:
    """The functions, lambdas and classes nearest inside *scope*, not looking into them."""
    for child in ast.iter_child_nodes(scope):
        if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda | ast.ClassDef):
            yield child
        else:
            yield from _nested_scopes(child)


def _locals(scope: ast.AST) -> set[str]:
    """The names a function binds for itself: its parameters and what it assigns."""
    bound: set[str] = set()
    if isinstance(scope, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda):
        arguments = scope.args
        for argument in (*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs):
            bound.add(argument.arg)
        for extra in (arguments.vararg, arguments.kwarg):
            if extra is not None:
                bound.add(extra.arg)
    for node in _bodies(scope):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            bound.add(node.id)
    return bound


def _core_aliases(tree: ast.Module) -> set[str]:
    """Dotted local names that mean the terp.core package in this file."""
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname is not None and alias.name == "terp.core":
                    found.add(alias.asname)
                elif alias.asname is None and alias.name.split(".")[0] == "terp":
                    found.add("terp.core")
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module == "terp":
            found.update(alias.asname or alias.name for alias in node.names if alias.name == "core")
    return found


def _dotted(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        head = _dotted(node.value)
        return None if head is None else f"{head}.{node.attr}"
    return None


def _names_machinery(name: str) -> bool:
    return name == _TIMESTAMPS_MODULE or name.startswith(f"{_TIMESTAMPS_MODULE}.")


def _imports_machinery(node: ast.AST) -> bool:
    """True for an import of the boundary's own module, or its dotted name as a literal.

    A literal is how ``importlib`` and ``sys.modules`` are handed the module.
    """
    if isinstance(node, ast.ImportFrom) and node.level == 0:
        if _names_machinery(node.module or ""):
            return True
        return node.module == "terp.core" and any(alias.name == "timestamps" for alias in node.names)
    if isinstance(node, ast.Import):
        return any(_names_machinery(alias.name) for alias in node.names)
    return isinstance(node, ast.Constant) and isinstance(node.value, str) and _names_machinery(node.value)


def _reaches_machinery(node: ast.AST, core: set[str]) -> bool:
    """True for ``timestamps`` taken from a name that means ``terp.core`` where it is read.

    As an attribute, or through ``getattr`` with that literal name.
    """
    if isinstance(node, ast.Attribute) and node.attr == "timestamps":
        return _dotted(node.value) in core
    if isinstance(node, ast.Call) and base_name(node.func) == "getattr" and len(node.args) >= 2:
        name = node.args[1]
        return isinstance(name, ast.Constant) and name.value == "timestamps" and _dotted(node.args[0]) in core
    return False


def _escape_findings(tree: ast.Module) -> dict[int, str]:
    """Each line that takes the escape, or reaches for its machinery, with its message.

    It fails closed by name: any reference to ``NaiveMeansUtc`` is the escape, whatever the
    file imported it from or shadows it with, and so is every name the file binds to it, at
    each use, where that binding is the one in scope, and every string that names one. A class
    attribute bound to it counts at each use of that attribute's name, through the class, a
    subclass or an instance.
    """
    findings: dict[int, str] = {}
    module_aliases = _aliases_in(tree, {_NAIVE_MEANS_UTC})
    core = _core_aliases(tree)

    def escape(node: ast.AST) -> None:
        findings.setdefault(getattr(node, "lineno", 0), _ESCAPE_MESSAGE)

    def machinery(node: ast.AST) -> None:
        findings[getattr(node, "lineno", 0)] = _MACHINERY_MESSAGE

    attribute_aliases: set[str] = set()

    def judge(scope: ast.AST, visible: set[str], core_visible: set[str]) -> None:
        """Flag the scope's own uses of what it sees, then each scope nested in it."""
        for node in _bodies(scope):
            if (
                isinstance(node, ast.Name)
                and isinstance(node.ctx, ast.Load)
                and (node.id == _NAIVE_MEANS_UTC or node.id in visible)
            ):
                escape(node)
            elif _reaches_machinery(node, core_visible):
                machinery(node)
        for nested in _nested_scopes(scope):
            if isinstance(nested, ast.ClassDef):
                class_aliases = _aliases_in(nested, visible)
                attribute_aliases.update(class_aliases - visible)
                judge(nested, class_aliases, core_visible)
            else:
                own = _locals(nested)
                judge(
                    nested,
                    _aliases_in(nested, {name for name in visible if name not in own}),
                    {name for name in core_visible if name.split(".")[0] not in own},
                )

    judge(tree, module_aliases, core)

    quoted = _quoted_nodes(tree)
    for node in [*ast.walk(tree), *quoted]:
        if isinstance(node, ast.Attribute) and (
            node.attr == _NAIVE_MEANS_UTC or node.attr in attribute_aliases
        ):
            escape(node)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) and node.id == _NAIVE_MEANS_UTC:
            escape(node)
        elif (
            isinstance(node, ast.Call)
            and base_name(node.func) == "getattr"
            and len(node.args) >= 2
            and isinstance(node.args[1], ast.Constant)
            and node.args[1].value == _NAIVE_MEANS_UTC
        ):
            escape(node)
        elif _imports_machinery(node):
            machinery(node)
        elif isinstance(node, ast.ImportFrom) and any(
            alias.name == _NAIVE_MEANS_UTC and alias.asname not in (None, _NAIVE_MEANS_UTC)
            for alias in node.names
        ):
            escape(node)
    for node in quoted:
        if isinstance(node, ast.Name) and node.id in module_aliases:
            escape(node)
        elif _reaches_machinery(node, core):
            machinery(node)
    return findings


def _with_aliases(tree: ast.Module, originals: frozenset[str]) -> set[str]:
    """*originals* and every name this file imports one of them under."""
    names = set(originals)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            names.update(alias.asname for alias in node.names if alias.name in originals and alias.asname)
    return names


def _quoted_type_spells_a_timestamp(text: str, names: set[str]) -> bool:
    try:
        parsed = ast.parse(text, mode="eval")
    except SyntaxError:
        return False  # prose, not a type
    return _spells_a_timestamp(parsed.body, names)


def _spells_a_timestamp(expr: ast.AST, names: set[str]) -> bool:
    """Whether the type *expr* spells reads a timestamp anywhere in it.

    A name the file reads a timestamp through counts, and so does an attribute of that name on
    anything (``datetime.datetime``, ``pydantic.AwareDatetime``), but not the object it is taken
    from, so ``datetime.date`` is a day. An ``Annotated`` type is its first element, a
    ``Literal`` value is text, and a string is read as the type Pydantic reads it as.
    """
    if isinstance(expr, ast.Name):
        return expr.id in names
    if isinstance(expr, ast.Attribute):
        return expr.attr in _TIMESTAMP_TYPES
    if isinstance(expr, ast.Constant):
        return isinstance(expr.value, str) and _quoted_type_spells_a_timestamp(expr.value, names)
    if isinstance(expr, ast.Subscript) and base_name(expr.value) == "Literal":
        return False
    if isinstance(expr, ast.Subscript) and base_name(expr.value) == "Annotated":
        elements = expr.slice.elts if isinstance(expr.slice, ast.Tuple) else [expr.slice]
        return any(_spells_a_timestamp(first, names) for first in elements[:1])
    return any(_spells_a_timestamp(child, names) for child in ast.iter_child_nodes(expr))


def _bound_type(value: ast.expr | None) -> ast.expr | None:
    """The type a binding's *value* spells: itself, a ``NewType``'s or a ``TypeAliasType``'s
    second argument, or none for any other call, which makes a value rather than a type."""
    if not isinstance(value, ast.Call):
        return value
    if base_name(value.func) in _TYPE_FACTORIES and len(value.args) >= 2:
        return value.args[1]
    return None


def _timestamp_names(tree: ast.Module) -> set[str]:
    """The names this file reads a timestamp through.

    The timestamp types, the names it imports them under, and each name it binds to a type
    that reads one, such as ``Stamp = datetime | None`` or ``NewType("Stamp", datetime)``,
    followed until nothing new is bound. ``EPOCH = datetime(1970, 1, 1)`` binds a value.
    """
    names = _with_aliases(tree, _TIMESTAMP_TYPES)
    grown = True
    while grown:
        grown = False
        for node in ast.walk(tree):
            targets, value = _assignment(node)
            bound = _bound_type(value)
            if bound is None or not _spells_a_timestamp(bound, names):
                continue
            for target in targets:
                if target not in names:
                    names.add(target)
                    grown = True
    return names


def _bound_to_a_call(tree: ast.Module, callees: set[str]) -> set[str]:
    """The names this file binds to a call of one of *callees*, as ``v = BeforeValidator(f)``."""
    bound: set[str] = set()
    for node in ast.walk(tree):
        targets, value = _assignment(node)
        if isinstance(value, ast.Call) and base_name(value.func) in callees:
            bound.update(targets)
    return bound


def _timestamp_fields(
    cls: ast.ClassDef, classes: dict[str, list[ast.ClassDef]], names: set[str], seen: set[str]
) -> set[str]:
    """The fields *cls* declares as timestamps: its own, and those of each base this file defines."""
    fields = {
        item.target.id
        for item in cls.body
        if isinstance(item, ast.AnnAssign)
        and isinstance(item.target, ast.Name)
        and _spells_a_timestamp(item.annotation, names)
    }
    for base in cls.bases:
        name = base_name(base)
        if name in classes and name not in seen:
            seen.add(name)
            for parent in classes[name]:
                fields |= _timestamp_fields(parent, classes, names, seen)
    return fields


def _validates_early(decorator: ast.expr, field_validators: set[str], pydantic_v1: set[str]) -> bool:
    """Whether *decorator* declares a field validator that sees a value before its type does.

    ``field_validator``'s ``mode`` decides, ``after`` unless given; Pydantic 1's ``validator``
    runs first with ``pre=True``. A mode the file computes, or passes in a ``**`` mapping,
    cannot be read here, so it counts.
    """
    if not isinstance(decorator, ast.Call):
        return False
    keywords = {keyword.arg: keyword.value for keyword in decorator.keywords}
    name = base_name(decorator.func)
    if name in field_validators:
        flag, early = keywords.get("mode"), _EARLY_MODES
    elif name in pydantic_v1:
        flag, early = keywords.get("pre"), frozenset({True})
    else:
        return False
    if None in keywords:
        return True
    return flag is not None and not (isinstance(flag, ast.Constant) and flag.value not in early)


def _covers_a_timestamp(decorator: ast.Call, fields: set[str]) -> bool:
    """Whether a field validator applies to one of *fields*: by its name, by ``"*"``, or by a
    name the file computes, which cannot be read here and so counts."""
    return any(
        not (isinstance(arg, ast.Constant) and isinstance(arg.value, str))
        or arg.value == "*"
        or arg.value in fields
        for arg in decorator.args
    )


def _early_validator_findings(tree: ast.Module) -> dict[int, str]:
    """Each line that declares an app's own early validator on a timestamp (ADR 0207).

    A ``before``, ``wrap`` or ``plain`` validator sees a timestamp's text before its type does,
    and before the refusal ``BaseSchema`` puts in front of that type, so it can read a time with
    no offset in a zone of its own choosing. It counts where it is declared: as a
    ``BeforeValidator``, ``WrapValidator`` or ``PlainValidator`` in an ``Annotated`` type that
    reads a timestamp, or a name bound to one, wherever that type is spelled; and as a
    ``field_validator`` in one of those modes (or Pydantic 1's ``validator`` with ``pre=True``)
    on a field its class, or a base this file defines, declares as a timestamp. A validator of
    the whole model sees the body, not a field, and is left alone (ADR 0206, Open).
    """
    findings: dict[int, str] = {}
    names = _timestamp_names(tree)
    kinds = _with_aliases(tree, _EARLY_VALIDATORS)
    instances = _bound_to_a_call(tree, kinds)

    def early(node: ast.AST) -> None:
        findings.setdefault(getattr(node, "lineno", 0), _EARLY_VALIDATOR_MESSAGE)

    for node in [*ast.walk(tree), *_quoted_nodes(tree)]:
        if (
            isinstance(node, ast.Subscript)
            and base_name(node.value) == "Annotated"
            and isinstance(node.slice, ast.Tuple)
            and any(_spells_a_timestamp(first, names) for first in node.slice.elts[:1])
        ):
            for item in node.slice.elts[1:]:
                if (isinstance(item, ast.Call) and base_name(item.func) in kinds) or (
                    isinstance(item, ast.Name) and item.id in instances
                ):
                    early(item)

    field_validators = _with_aliases(tree, frozenset({"field_validator"}))
    pydantic_v1 = _with_aliases(tree, frozenset({"validator"}))
    classes: dict[str, list[ast.ClassDef]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            classes.setdefault(node.name, []).append(node)
    for cls in (cls for same_name in classes.values() for cls in same_name):
        fields = _timestamp_fields(cls, classes, names, {cls.name})
        for item in cls.body if fields else ():
            for decorator in getattr(item, "decorator_list", ()):
                if _validates_early(decorator, field_validators, pydantic_v1) and _covers_a_timestamp(
                    decorator, fields
                ):
                    early(decorator)
    return findings


def check_request_timestamps_carry_their_offset(
    app_root: str | pathlib.Path, *, package: str = "app"
) -> list[ArchViolation]:
    """Reading timestamp text without its UTC offset is an escape, named and counted.

    A ``BaseSchema`` refuses timestamp text that carries no UTC offset, and a declared filter
    refuses a bound with none (ADR 0206): such a value names no instant, and read as UTC it
    puts a writer in another zone off by its offset. ``NaiveMeansUtc`` is the framework's way
    around both, for a sender known to send UTC without saying so. Each use of it is refused
    here, so taking it is this rule's opt-out marker, which the app's escape-hatch budget
    counts. The rule fails closed by name: every reference to ``NaiveMeansUtc``, or to a name
    the file binds to it, and every string that names one, is the escape, and so is reaching
    for the boundary's own module. So is an app's own ``before``, ``wrap`` or ``plain``
    validator on a timestamp field (ADR 0207), which reads the text before the type does: a
    wall time in a named zone is ``LocalTimeIn``'s, which names the instant.
    """
    if package in _IMPLEMENTING_PACKAGES:
        return []  # the boundary's own implementation, and this rule's, is neither's user
    root = pathlib.Path(app_root)
    violations: list[ArchViolation] = []
    for path in iter_python_files(root):
        tree = parse(path)
        rel = _rel(path, root)
        findings = _escape_findings(tree)
        for line, message in _early_validator_findings(tree).items():
            findings.setdefault(line, message)
        violations.extend(
            ArchViolation("request_timestamps_carry_their_offset", rel, line, message)
            for line, message in sorted(findings.items())
        )
    return violations


__all__ = ["check_request_timestamps_carry_their_offset"]
