"""How a file spells a timestamp type, and an app's own validator that reads one first.

``request_timestamps_carry_their_offset`` reads a type where Pydantic does: in an annotation, a
quoted one, a type alias, ``NewType`` or ``TypeAliasType`` (ADR 0206). This module holds that
reading, and the half of the rule that counts an app's own ``before``, ``wrap`` or ``plain``
validator on a timestamp field (ADR 0207). Each walk keeps its own list of what is left to
read rather than recursing, so a file the parser takes cannot exhaust the rule's stack.
"""

from __future__ import annotations

import ast
import dataclasses
from collections.abc import Iterator, Mapping

from terp.arch._ast import base_name
from terp.arch.rules.datetimes import _bound_names, _dotted

_EARLY_VALIDATOR_MESSAGE = (
    "a before, wrap or plain validator on a timestamp field reads its text before the "
    "timestamp's type does, so it can read a time with no UTC offset in a zone of its "
    "choosing; for the wall time of a place, type the field "
    "Annotated[datetime, LocalTimeIn('Europe/Amsterdam')] from terp.core, which names the "
    "instant and refuses a time the clocks skip or repeat, use an after validator, or keep "
    "it with '# arch-allow-request-timestamps-carry-their-offset: <reason>' (budgeted by the "
    "app's escape-hatch-budget.json)"
)

#: The types a timestamp is read through: a value of any of them is timestamp text first.
#: ``Instant`` refuses text without an offset, but a validator in front of it reads the text
#: before it does (ADR 0208).
_TIMESTAMP_TYPES = frozenset(
    {"datetime", "AwareDatetime", "NaiveDatetime", "PastDatetime", "FutureDatetime", "Instant"}
)

#: Pydantic's validators that see a value before its type does, as ``Annotated`` metadata.
_EARLY_VALIDATORS = frozenset({"BeforeValidator", "WrapValidator", "PlainValidator"})

#: A field validator's modes that run before, around or instead of the type.
_EARLY_MODES = frozenset({"before", "wrap", "plain"})

#: The calls that bind a type rather than a value: their second argument is that type.
_TYPE_FACTORIES = frozenset({"NewType", "TypeAliasType"})

#: What a string holds that is no expression: prose or a null byte, which the parser refuses,
#: or nesting deeper than it builds. Pydantic reads none of them as a type, so neither does
#: the rule.
_NO_EXPRESSION = (SyntaxError, RecursionError, MemoryError)


def _strings_outside_literals(expr: ast.AST) -> Iterator[ast.Constant]:
    pending = [expr]
    while pending:
        node = pending.pop()
        if isinstance(node, ast.Subscript) and base_name(node.value) == "Literal":
            continue
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            yield node
            continue
        pending.extend(ast.iter_child_nodes(node))


def _parsed(text: str) -> list[ast.Expression]:
    """*text* as the expression Pydantic would evaluate it as, or nothing for one that is none."""
    try:
        return [ast.parse(text, mode="eval")]
    except _NO_EXPRESSION:
        return []


def _quoted_nodes(expr: ast.AST) -> list[ast.AST]:
    """The nodes of every string in *expr* that reads as an expression, parsed, at its line.

    Pydantic evaluates a string as a type wherever it stands for one: a quoted annotation
    (``"NaiveMeansUtc | None"``), a forward reference in ``Optional["NaiveMeansUtc"]``, a field
    ``create_model`` is given. So a string that names the escape takes it as surely as a name
    does. Prose does not read as an expression, and a ``Literal`` value is text, not a type.
    """
    found: list[ast.AST] = []
    for quote in _strings_outside_literals(expr):
        for parsed in _parsed(quote.value):
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


def _aliases(tree: ast.Module, originals: frozenset[str]) -> frozenset[str]:
    """*originals* and every name this file binds to one: by an import, or by assigning it, or
    an attribute of that name on a module (``Early = pydantic.BeforeValidator``)."""
    names = set(originals)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            names.update(alias.asname for alias in node.names if alias.name in originals and alias.asname)
    grown = True
    while grown:
        grown = False
        for node in ast.walk(tree):
            targets, value = _assignment(node)
            if (isinstance(value, ast.Name) and value.id in names) or (
                isinstance(value, ast.Attribute) and value.attr in originals
            ):
                fresh = set(targets) - names
                names |= fresh
                grown = grown or bool(fresh)
    return frozenset(names)


@dataclasses.dataclass(frozen=True)
class _Spelling:
    """The names a file reads its types through: its timestamps, ``Annotated`` and ``Literal``."""

    timestamps: frozenset[str]
    annotated: frozenset[str]
    literals: frozenset[str]


def _elements(subscript: ast.Subscript) -> list[ast.expr]:
    return list(subscript.slice.elts) if isinstance(subscript.slice, ast.Tuple) else [subscript.slice]


def _spells_a_timestamp(expr: ast.AST, spelling: _Spelling) -> bool:
    """Whether the type *expr* spells reads a timestamp anywhere in it.

    A name the file reads a timestamp through counts, and so does an attribute of that name on
    anything (``datetime.datetime``, ``pydantic.AwareDatetime``), but not the object it is taken
    from, so ``datetime.date`` is a day. An ``Annotated`` type is its first element, a
    ``Literal`` value is text, and a string is read as the type Pydantic reads it as.
    """
    pending: list[ast.AST] = [expr]
    while pending:
        node = pending.pop()
        if isinstance(node, ast.Name):
            if node.id in spelling.timestamps:
                return True
        elif isinstance(node, ast.Attribute):
            if node.attr in _TIMESTAMP_TYPES:
                return True
        elif isinstance(node, ast.Constant):
            if isinstance(node.value, str):
                pending.extend(parsed.body for parsed in _parsed(node.value))
        elif isinstance(node, ast.Subscript) and base_name(node.value) in spelling.literals:
            continue
        elif isinstance(node, ast.Subscript) and base_name(node.value) in spelling.annotated:
            pending.extend(_elements(node)[:1])
        else:
            pending.extend(ast.iter_child_nodes(node))
    return False


def _bound_type(value: ast.expr | None) -> ast.expr | None:
    """The type a binding's *value* spells: itself, a ``NewType``'s or a ``TypeAliasType``'s
    second argument, or none for any other call, which makes a value rather than a type."""
    if not isinstance(value, ast.Call):
        return value
    if base_name(value.func) in _TYPE_FACTORIES and len(value.args) >= 2:
        return value.args[1]
    return None


def _spelling(tree: ast.Module) -> _Spelling:
    """How this file spells its types.

    The timestamp types, ``Annotated`` and ``Literal`` under each name the file imports or
    assigns them to, and each name it binds to a type that reads a timestamp, such as
    ``Stamp = datetime | None`` or ``NewType("Stamp", datetime)``, followed until nothing new
    is bound. ``EPOCH = datetime(1970, 1, 1)`` binds a value, not a type.
    """
    spelling = _Spelling(
        _aliases(tree, _TIMESTAMP_TYPES),
        _aliases(tree, frozenset({"Annotated"})),
        _aliases(tree, frozenset({"Literal"})),
    )
    grown = True
    while grown:
        grown = False
        for node in ast.walk(tree):
            targets, value = _assignment(node)
            bound = _bound_type(value)
            fresh = set(targets) - spelling.timestamps
            if fresh and bound is not None and _spells_a_timestamp(bound, spelling):
                spelling = dataclasses.replace(spelling, timestamps=spelling.timestamps | fresh)
                grown = True
    return spelling


@dataclasses.dataclass(frozen=True)
class Imported:
    """What one file takes from the app's other modules: their early validators, and the types
    that carry one (ADR 0207).

    *instances* and *carriers* are the names this file binds to them by an import. *modules*
    maps each name this file binds by an import to the absolute module it may be, so a module
    attribute (``types.LocalStamp``) is read as the qualified name it reaches, and the
    qualified sets say which of those are a validator and which a carrier.
    """

    instances: frozenset[str] = frozenset()
    carriers: frozenset[str] = frozenset()
    modules: Mapping[str, str] = dataclasses.field(default_factory=dict)
    qualified_instances: frozenset[str] = frozenset()
    qualified_carriers: frozenset[str] = frozenset()

    def _qualified(self, node: ast.AST) -> str | None:
        dotted = _dotted(node) if isinstance(node, ast.Attribute) else None
        head, _, rest = (dotted or "").partition(".")
        module = self.modules.get(head)
        return None if module is None or not rest else f"{module}.{rest}"

    def is_instance(self, node: ast.AST) -> bool:
        return self._qualified(node) in self.qualified_instances

    def is_carrier(self, node: ast.AST) -> bool:
        return (isinstance(node, ast.Name) and node.id in self.carriers) or (
            self._qualified(node) in self.qualified_carriers
        )


def _early_in(
    node: ast.AST, spelling: _Spelling, kinds: frozenset[str], instances: set[str], imported: Imported
) -> list[ast.expr]:
    """The early validators *node* attaches to a timestamp, when it is an ``Annotated`` type."""
    if not (isinstance(node, ast.Subscript) and base_name(node.value) in spelling.annotated):
        return []
    elements = _elements(node)
    if not elements or not _spells_a_timestamp(elements[0], spelling):
        return []
    return [
        item
        for item in elements[1:]
        if (isinstance(item, ast.Call) and base_name(item.func) in kinds)
        or (isinstance(item, ast.Name) and item.id in instances)
        or imported.is_instance(item)
    ]


def _bound_to_a_call(tree: ast.Module, callees: frozenset[str]) -> set[str]:
    """The names this file binds to a call of one of *callees*, as ``v = BeforeValidator(f)``."""
    bound: set[str] = set()
    for node in ast.walk(tree):
        targets, value = _assignment(node)
        if isinstance(value, ast.Call) and base_name(value.func) in callees:
            bound.update(targets)
    return bound


def _early_types(
    tree: ast.Module, spelling: _Spelling, kinds: frozenset[str], instances: set[str], imported: Imported
) -> set[str]:
    """The names this file binds to a type that carries an early validator on a timestamp: one
    it spells, or one of the app's other modules declares and this file imports."""
    bound: set[str] = set()
    grown = True
    while grown:
        grown = False
        for node in ast.walk(tree):
            targets, value = _assignment(node)
            spelled = _bound_type(value)
            if spelled is None or set(targets) <= bound:
                continue
            if any(
                _early_in(inner, spelling, kinds, instances, imported)
                or (isinstance(inner, ast.Name) and inner.id in bound)
                or imported.is_carrier(inner)
                for inner in [*ast.walk(spelled), *_quoted_nodes(spelled)]
            ):
                bound.update(targets)
                grown = True
    return bound


def early_names(tree: ast.Module, imported: Imported) -> tuple[set[str], set[str]]:
    """The names this file binds to an early validator, and to a type that carries one, its
    imports included: what another module of the app takes when it imports them."""
    spelling = _spelling(tree)
    kinds = _aliases(tree, _EARLY_VALIDATORS)
    instances = _bound_to_a_call(tree, kinds) | imported.instances
    carriers = _early_types(tree, spelling, kinds, instances, imported) | imported.carriers
    return instances, carriers


def _lineage(cls: ast.ClassDef, classes: dict[str, list[ast.ClassDef]]) -> list[ast.ClassDef]:
    """*cls* and every base this file defines for it, at any depth, each once."""
    lineage: list[ast.ClassDef] = []
    pending = [cls]
    seen = {cls.name}
    while pending:
        current = pending.pop()
        lineage.append(current)
        for base in current.bases:
            name = base_name(base)
            if name in classes and name not in seen:
                seen.add(name)
                pending.extend(classes[name])
    return lineage


def _own_timestamp_fields(cls: ast.ClassDef, spelling: _Spelling) -> set[str]:
    return {
        item.target.id
        for item in cls.body
        if isinstance(item, ast.AnnAssign)
        and isinstance(item.target, ast.Name)
        and _spells_a_timestamp(item.annotation, spelling)
    }


def _calls_in_body(cls: ast.ClassDef, callees: frozenset[str]) -> Iterator[ast.Call]:
    """Each call of one of *callees* in *cls*'s own body: a decorator, or a call written out
    (``read = field_validator("at", mode="before")(classmethod(_read))``), but not one of a
    nested class, which is a class of its own."""
    pending: list[ast.AST] = list(cls.body)
    while pending:
        node = pending.pop()
        if isinstance(node, ast.ClassDef):
            continue
        if isinstance(node, ast.Call) and base_name(node.func) in callees:
            yield node
        pending.extend(ast.iter_child_nodes(node))


def _validates_early(call: ast.Call, field_validators: frozenset[str]) -> bool:
    """Whether *call*, a field validator, declares one that sees a value before its type does.

    ``field_validator``'s ``mode`` decides, ``after`` unless given. The class body yields no
    other call but Pydantic 1's ``validator``, which runs first with ``pre=True``. A mode the
    file computes, or passes in a ``**`` mapping, cannot be read here, so it counts.
    """
    keywords = {keyword.arg: keyword.value for keyword in call.keywords}
    if base_name(call.func) in field_validators:
        flag, early = keywords.get("mode"), _EARLY_MODES
    else:
        flag, early = keywords.get("pre"), frozenset({True})
    if None in keywords:
        return True
    return flag is not None and not (isinstance(flag, ast.Constant) and flag.value not in early)


def _covers_a_timestamp(call: ast.Call, fields: set[str]) -> bool:
    """Whether a field validator applies to one of *fields*: by its name, by ``"*"``, or by a
    name the file computes, which cannot be read here and so counts."""
    return any(
        not (isinstance(arg, ast.Constant) and isinstance(arg.value, str))
        or arg.value == "*"
        or arg.value in fields
        for arg in call.args
    )


def _early_validator_findings(tree: ast.Module, imported: Imported | None = None) -> dict[int, str]:
    """Each line that declares, or uses, an app's own early validator on a timestamp (ADR 0207).

    A ``before``, ``wrap`` or ``plain`` validator sees a timestamp's text before its type does,
    and before the refusal ``BaseSchema`` puts in front of that type, so it can read a time with
    no offset in a zone of its own choosing. It counts where it is declared: as a
    ``BeforeValidator``, ``WrapValidator`` or ``PlainValidator``, or a name bound to one, in an
    ``Annotated`` type that reads a timestamp, wherever that type is spelled, and at each use of
    a name bound to such a type, as each use of ``NaiveMeansUtc`` counts, in this file or in
    any module of the app that imports it (*imported*); and as a
    ``field_validator`` in one of those modes, or Pydantic 1's ``validator`` with ``pre=True``,
    written in the body of a class or of a base this file defines, on a field that class or one
    of those bases declares as a timestamp. A validator of the whole model sees the body, not a
    field, and is left alone (ADR 0206, Open).
    """
    findings: dict[int, str] = {}

    def early(node: ast.AST) -> None:
        findings.setdefault(getattr(node, "lineno", 0), _EARLY_VALIDATOR_MESSAGE)

    imported = imported or Imported()
    spelling = _spelling(tree)
    kinds = _aliases(tree, _EARLY_VALIDATORS)
    instances, carriers = early_names(tree, imported)
    for node in [*ast.walk(tree), *_quoted_nodes(tree)]:
        for item in _early_in(node, spelling, kinds, instances, imported):
            early(item)
        loaded = isinstance(node, ast.Name | ast.Attribute) and isinstance(node.ctx, ast.Load)
        if loaded and ((isinstance(node, ast.Name) and node.id in carriers) or imported.is_carrier(node)):
            early(node)

    field_validators = _aliases(tree, frozenset({"field_validator"}))
    pydantic_v1 = _aliases(tree, frozenset({"validator"}))
    classes: dict[str, list[ast.ClassDef]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            classes.setdefault(node.name, []).append(node)
    for cls in (cls for same_name in classes.values() for cls in same_name):
        lineage = _lineage(cls, classes)
        fields = {field for owner in lineage for field in _own_timestamp_fields(owner, spelling)}
        for owner in lineage if fields else ():
            for call in _calls_in_body(owner, field_validators | pydantic_v1):
                if _validates_early(call, field_validators) and _covers_a_timestamp(call, fields):
                    early(call)
    return findings

