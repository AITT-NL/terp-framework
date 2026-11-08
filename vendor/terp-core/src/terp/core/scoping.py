"""The row-scope predicate registry — capabilities plug row visibility into reads.

Soft-delete is the kernel's own built-in row scope; a capability (e.g. tenancy)
adds its predicate here so :class:`~terp.core.BaseService` composes it into **every**
read query, without the kernel importing the capability. Predicates are applied
centrally and **cannot be dropped by a service**: a module narrows its reads through
:meth:`~terp.core.BaseService.business_filters` (which only *adds* conditions), never
by overriding ``base_query`` (the ``terp.arch`` ``base_query_not_overridden`` rule
forbids it). This is the structural fix for the "a ``super()``-less ``base_query``
override silently drops soft-delete / tenant scoping" footgun (ADR 0017).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Iterator
from typing import Any

from sqlalchemy import Column, Select, Table, event, literal_column, or_
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import Mapper
from sqlalchemy.sql.dml import UpdateBase
from sqlalchemy.sql.elements import ClauseElement, ColumnClause, TextClause
from sqlalchemy.sql.expression import FunctionElement, TableClause
from sqlalchemy.sql.selectable import (
    CTE,
    AliasedReturnsRows,
    CompoundSelect,
    Exists,
    FromGrouping,
    Join,
    ScalarSelect,
    SelectBase,
    Subquery,
    TextualSelect,
    Values,
)
from sqlmodel import Session, SQLModel, select
from sqlmodel.main import default_registry
from sqlmodel.sql.expression import SelectOfScalar

from terp.core.base_models import OwnedMixin, SoftDeleteMixin
from terp.core.errors import ConflictError

# A predicate narrows a read query for the models it owns (row visibility). It
# receives the model and the query and returns the query with its WHERE clause
# added — or the query unchanged for a model it does not apply to (it must guard on
# the relevant mixin and be idempotent, since it runs on every read of every model).
ScopePredicate = Callable[[type[SQLModel], SelectOfScalar], SelectOfScalar]

_scope_predicates: list[ScopePredicate] = []


def register_scope_predicate(predicate: ScopePredicate) -> None:
    """Register a row-visibility predicate applied to every ``BaseService`` read.

    The seam a capability uses to plug a row predicate (e.g. the tenant filter) into
    the kernel without the kernel importing it. Registration is idempotent.
    ``BaseService.base_query`` composes every registered predicate on top of the
    built-in soft-delete scope, so a service cannot drop it.
    """
    if predicate not in _scope_predicates:
        _scope_predicates.append(predicate)


def registered_scope_predicates() -> tuple[ScopePredicate, ...]:
    """Every registered row-scope predicate, in registration order."""
    return tuple(_scope_predicates)


def apply_row_scope(model: type[SQLModel], query: SelectOfScalar) -> SelectOfScalar:
    """Compose the framework's non-droppable row scope onto *query* for *model*.

    The single definition of "row scope": the built-in soft-delete predicate (when
    *model* is a :class:`~terp.core.SoftDeleteMixin`) plus every capability-registered
    row predicate (e.g. the tenant filter). :meth:`~terp.core.BaseService.base_query`
    composes it, **and** the request session applies its criteria to ORM query
    entities, aliases and relationship loads — so reaching a scope-trait model
    through another model cannot silently drop soft-delete / tenant scope (the
    runtime backstop for ADR 0017; the ``reads_use_base_query`` rule is the
    build-time early warning). It is **idempotent** — composing it twice yields the
    same filtered set — so the double application (``base_query`` + session) is safe,
    and it is a no-op for a model with no scope trait.
    """
    if issubclass(model, SoftDeleteMixin):
        query = query.where(model.deleted_at.is_(None))  # type: ignore[attr-defined]
    for predicate in _scope_predicates:
        query = predicate(model, query)
    return query


def _owner_read_scope_predicate(
    model: type[SQLModel], query: SelectOfScalar
) -> SelectOfScalar:
    """Filter an :class:`~terp.core.OwnedMixin` model's reads to the request actor.

    The read half of the ownership trait, which the trait itself deliberately is not:
    ``OwnedMixin`` gates *writes*, because a post-load boolean cannot paginate a list,
    and its docstring has always pointed here for visibility. Installing it was left as
    an exercise, and an exercise left undone reads exactly like a control that is
    present — which is how a surface comes to be described as owner-scoped while every
    caller who clears its role sees every row.

    An **unowned** row (``owner_id is None`` — created by a job, a migration, a seed,
    anything with no bound actor) stays visible to everyone, matching the write gate,
    which does not restrict a row with no owner to protect. An **actor-less read** (out
    of request, a worker, a CLI) is not narrowed either: there is no "self" to scope to,
    and narrowing to nothing would make background work silently see an empty database
    rather than fail. Both are widening defaults, which is why this is opt-in rather
    than automatic — see :func:`register_owner_read_scope`.
    """
    # Imported at call time, not at module scope: `terp.core.audit` reaches this
    # module through the session guard, so a top-level import here closes a cycle
    # that only shows up as a half-initialised module at first import.
    from terp.core.audit import audit_actor_ctx  # noqa: PLC0415 - cycle, see above

    if not issubclass(model, OwnedMixin):
        return query
    actor = audit_actor_ctx.get()
    if actor is None:
        return query
    return query.where(
        or_(model.owner_id.is_(None), model.owner_id == actor)  # type: ignore[attr-defined]
    )


def register_owner_read_scope() -> None:
    """Install the owner read filter for every :class:`~terp.core.OwnedMixin` model.

    One composition-root line, idempotent, and **opt-in on purpose**: it narrows what an
    already-authorized caller can see, so turning it on is a decision about a product
    rather than a default a framework can take. A deployment whose administrators are
    expected to see each other's rows would find its screens quietly emptied by an
    automatic version of this.

    Composed with the trait's built-in write gate it gives the property ``OwnedMixin``
    describes in full — only the owner sees **or** changes the row — and it is the whole
    of the "register a row-scope predicate keyed on ``owner_id``" that docstring asks
    for, so an app no longer has to write the predicate to get it right.
    """
    register_scope_predicate(_owner_read_scope_predicate)


#: Shared with the database's own refusal of a missing target, word for word: a reference
#: the writer may not see fails exactly as one that does not exist, so the answer says
#: nothing about rows outside the writer's scope.
_REFERENCE_REFUSAL = "This write conflicts with a unique or referential constraint."


def refuse_out_of_scope_references(session: Session, entity: object, *, created: bool) -> None:
    """Refuse a write whose reference points at a row its writer cannot read (ADR 0178).

    The row scope filters what a read returns, and until this nothing held a write to it.
    A reference is a pointer, and a write could aim one at a row its author could never
    have read: another tenant's, or one already soft-deleted. A foreign key checks that
    the row exists, never that it is in scope, so a link from one tenant's row to
    another tenant's row passed both.

    It runs for every row a flush writes, after the flush's SQL and before its commit (the
    session hook below), so it sees what the write actually carries: a reference filled in
    from a relationship, a target inserted earlier in the same unit, and every row the
    flush writes, however the flush was reached (a ``_save``, an autoflush, a sibling's
    commit). Each single-column foreign key is looked up under the target model's row scope:
    every reference on an insert, and on an update only the ones it changed, so an
    untouched pointer to a row that has since been soft-deleted does not block an unrelated
    edit. A target outside the scope fails exactly as a missing one does
    (:class:`~terp.core.ConflictError`, the 409 the foreign key itself raises), and the
    real reason travels in ``log_context`` only. A target model with no scope trait is
    left to the database: the scope would add nothing the foreign key does not check.
    """
    state = sa_inspect(entity, raiseerr=False)
    if state is None:
        return  # a non-mapped stand-in carries no reference
    table = state.mapper.local_table
    for constraint in getattr(table, "foreign_key_constraints", ()):
        if len(constraint.elements) != 1:
            continue
        element = constraint.elements[0]
        key = state.mapper.get_property_by_column(element.parent).key
        # History before value: an unchanged reference is never loaded, let alone looked up.
        if not (created or state.attrs[key].history.has_changes()):
            continue
        value = getattr(entity, key)
        if value is None:
            continue
        target = _mapped_class(state.mapper.registry.mappers, element.column.table)
        if target is None:
            continue
        target_column = getattr(target, target.__mapper__.get_property_by_column(element.column).key)
        query = select(target_column)
        scoped = apply_row_scope(target, query)
        if scoped is query:
            continue
        # Inside the flush, on its transaction: a target this unit inserted is there to be found,
        # and no autoflush can start while the flush is running.
        found = session.scalars(scoped.where(target_column == value).limit(1)).first()
        if found is None:
            raise ConflictError(
                _REFERENCE_REFUSAL,
                log_context={
                    "reason": "reference_out_of_scope",
                    "reference": f"{table.name}.{element.parent.name}",
                    "target": element.target_fullname,
                },
            )


def _check_flushed_references(session: Session, _flush_context: object) -> None:
    """Hold every row a flush wrote to the reference rule (ADR 0178).

    ``after_flush`` still shows the flush's new and dirty rows and their attribute history,
    and raising here fails the flush and its transaction, as the database's own refusal of a
    missing target would.
    """
    for entity in tuple(session.new):
        refuse_out_of_scope_references(session, entity, created=True)
    for entity in tuple(session.dirty):
        refuse_out_of_scope_references(session, entity, created=False)


# On the session class every Terp session is, so its subclasses (the request session) are held
# too; a listener on a class reaches every instance of it and of its subclasses.
event.listen(Session, "after_flush", _check_flushed_references)

_mapped_classes: dict[Table, type[SQLModel]] = {}


def _mapped_class(mappers: object, table: Table) -> type[SQLModel] | None:
    """The model class mapped to *table*: the base of an inheritance tree that shares it."""
    cached = _mapped_classes.get(table)
    if cached is not None:
        return cached
    candidates = [mapper for mapper in mappers if mapper.local_table is table]  # type: ignore[attr-defined]
    if not candidates:
        return None
    base = next((mapper for mapper in candidates if mapper.inherits is None), candidates[0])
    _mapped_classes[table] = base.class_
    return base.class_


def _reset_scope_predicates() -> None:
    """Clear all registered predicates (a test seam; capabilities re-register on import).

    **Private, and reachable only through** :mod:`terp.core._internal.registry_resets`
    (ADR 0137). Emptying this list is not a neutral act: it removes the tenant filter
    and every other registered row predicate for the whole process, in one call, with
    no exception and nothing in the log — reads simply start returning rows they used
    to hide. That is the shape of thing the ``no_internal_imports`` rule exists to keep
    out of module code, which is why the public spelling now lives behind it, exactly
    as ``allow_session_writes`` does for the write guard.
    """
    _scope_predicates.clear()


# --------------------------------------------------------------------------- #
# Which SELECTs read a row-scoped table through Core (ADR 0204 decision 6)
# --------------------------------------------------------------------------- #
# The request session's ORM execution hook scopes a read by attaching this module's row
# scope to each mapped entity the statement reaches. A SELECT that names a scoped table
# only through Core offers no entity to attach it to, so the hook asks for those SELECTs
# here and refuses the read before it runs (UnscopedReadError in the session guard).

# Every mapped table, by Table and by (schema, name): static facts about the schema, so the
# lookup is rebuilt only when a mapper is constructed. Whether a table carries row scope is
# NOT cached here: a predicate can depend on the context (the owner scope needs an actor),
# so that is asked of the table at the moment a read reaches it through Core.
_mapped: dict[str, Any] = {}


@event.listens_for(Mapper, "after_mapper_constructed")
def _forget_mapped_tables(mapper: Mapper[Any], class_: type) -> None:
    _mapped.clear()


def _mapped_tables() -> tuple[dict[Any, list[type]], dict[str, list[type]]]:
    """Each mapped table's models, by the Table itself and by its name, case folded."""
    if not _mapped:
        by_table: dict[Any, list[type]] = {}
        by_name: dict[str, list[type]] = {}
        for mapper in default_registry.mappers:
            for table in mapper.tables:
                by_table.setdefault(table, []).append(mapper.class_)
                by_name.setdefault(table.name.casefold(), []).append(mapper.class_)
        _mapped.update(by_table=by_table, by_name=by_name)
    return _mapped["by_table"], _mapped["by_name"]


def _models_of(table: Any) -> list[type]:
    """The models mapped onto *table*, or onto any table of its name.

    Matched by name alone, case folded and in any schema: a ``table("NAME")``, a copy of the
    Table in another ``MetaData`` or under its schema's own name reaches the same rows, and a
    database folds an unquoted name. Matching a same-named table in another schema too errs
    toward a refusal, never toward an unscoped read.
    """
    by_table, by_name = _mapped_tables()
    if table in by_table:
        return by_table[table]
    return by_name.get(str(getattr(table, "name", "")).casefold(), [])


def _row_scoped(models: list[type]) -> list[type]:
    """The ones of *models* that carry row scope in the current context."""
    return [model for model in models if apply_row_scope(model, select(model)).whereclause is not None]


def _orm_named_tables(select_: Any) -> set[Any]:
    """The tables *select_* names through a mapped entity, not looking into nested selects."""
    named: set[Any] = set()
    pending = list(select_.get_children())
    while pending:
        element = pending.pop()
        if isinstance(element, (SelectBase, Subquery, ScalarSelect, Exists, CTE)):
            continue
        entity = getattr(element, "_annotations", {}).get("parententity")
        if entity is not None:
            # An ORM alias names its own selectable, which the hook scopes through its adapter.
            named.update([entity.selectable] if entity.is_aliased_class else entity.mapper.tables)
        pending.extend(element.get_children())
    return named


#: Literal SQL the session can read: a bare name, a dotted one, a number or ``*`` (what
#: ``func.count()`` and ``exists()`` write). Anything longer can hold a SELECT of its own.
_PLAIN_LITERAL = re.compile(r"[\w.]+|\*")


def _option_sql(option: Any) -> Iterator[Any]:
    """The SQL a loader option writes into a read: its criteria, and an expression it loads."""
    criteria = getattr(option, "where_criteria", None)  # with_loader_criteria
    if isinstance(criteria, ClauseElement):
        yield criteria
    for load in getattr(option, "context", ()):  # a relationship's .and_(), with_expression()
        yield from getattr(load, "_extra_criteria", ())


def _elements(statement: Any, place: str | None = None) -> Iterator[tuple[Any, str | None]]:
    """Every element *statement* writes into its SQL, with where it stands.

    SQLAlchemy's own walk (``get_children``) leaves out a statement's prefixes, suffixes and
    hints, the rows of a ``VALUES`` list and the SQL its loader options carry, though each is
    written into the SQL; they are walked here too, a hint (plain text) as a literal column.
    An element reached through a ``VALUES`` row or a loader option comes with that place, and
    every other one with *place*, so that a refusal can say where it stands.
    """
    pending = [(statement, place)]
    while pending:
        element, at = pending.pop()
        yield element, at
        pending.extend((child, at) for child in element.get_children())
        texts = [*getattr(element, "_prefixes", ()), *getattr(element, "_suffixes", ())]
        pending.extend((part, at) for part, _dialect in texts)
        hints = [*getattr(element, "_hints", {}).values()]
        hints.extend(hint for _dialect, hint in getattr(element, "_statement_hints", ()))
        pending.extend((literal_column(hint), at) for hint in hints)
        if isinstance(element, Values):
            rows = (value for data in element._data for row in data for value in row)
            pending.extend((value, at or "a VALUES list") for value in rows if isinstance(value, ClauseElement))
        for option in getattr(element, "_with_options", ()):
            pending.extend((sql, at or "a loader option") for sql in _option_sql(option))


def _mapping_sql(mapper: Any) -> list[tuple[Any, str]]:
    """The SQL *mapper* writes into every load of its model beyond its columns, and where.

    A column property that is more than a column, a count of a model's children say, is a
    query of its own in every SELECT that loads the model, though the statement never shows it.
    """
    return [
        (prop.expression, f"the column property {mapper.class_.__name__}.{prop.key}")
        for prop in mapper.column_attrs
        if not all(isinstance(column, Column) for column in prop.columns)
    ]


def _entities_in(statement: Any) -> Iterator[Any]:
    """Each mapper or ORM alias *statement* names, wherever it writes SQL.

    The request session attaches the row scope to each of them (the session guard's
    execution hook), so an entity named only in a loader option, a ``VALUES`` row or a
    column property is scoped as one in the statement's own clauses is.
    """
    for element, _place in _elements(statement):
        inspected = sa_inspect(getattr(element, "entity_namespace", None), raiseerr=False)
        if getattr(inspected, "is_aliased_class", False) or getattr(inspected, "is_mapper", False):
            yield inspected


def _writes(statement: Any) -> bool:
    """Whether *statement* holds an ``INSERT``, ``UPDATE`` or ``DELETE`` anywhere (a CTE's)."""
    return any(isinstance(element, UpdateBase) for element, _place in _elements(statement))


def _from_leaves(from_: Any) -> Iterator[Any]:
    """The FROM elements *from_* reads, through every join and parenthesised group of joins."""
    pending = [from_]
    while pending:
        element = pending.pop()
        if isinstance(element, Join):
            pending.extend((element.left, element.right))
        elif isinstance(element, FromGrouping):
            pending.append(element.element)
        else:
            yield element


def _literal_sql(element: Any) -> bool:
    """Whether *element* is SQL written as text that is more than a name.

    A ``text().columns()`` select is judged by its text, which the walk reaches beneath it.
    """
    if isinstance(element, TextClause):
        return not _PLAIN_LITERAL.fullmatch(element.text)
    return isinstance(element, ColumnClause) and element.is_literal and not _PLAIN_LITERAL.fullmatch(element.name)


def _at(item: str, place: str | None) -> str:
    return item if place is None else f"{item}, in {place}"


def _unscoped_from(leaf: Any, named: set[Any], place: str | None) -> list[str]:
    """What *leaf*, one FROM element of a SELECT, reads that no row scope reaches.

    *named* holds the tables a mapped entity of that SELECT names, and *place* where the
    SELECT stands outside the statement's own clauses, for the refusal to say.
    """
    if "parententity" in getattr(leaf, "_annotations", {}):
        return []  # an ORM entity's own FROM (a joined eager load's alias, say)
    base = leaf
    while isinstance(base, AliasedReturnsRows):
        base = base.element
    if isinstance(base, Select | CompoundSelect | Values | FunctionElement):
        # A nested SELECT is judged on its own, and the rows of a VALUES list and the
        # arguments of a function are walked with the rest of the statement.
        return []
    if isinstance(base, TextualSelect | TextClause):
        return [_at("literal SQL", place)]
    if not isinstance(base, TableClause):
        return [_at(f"a FROM element it does not know ({type(leaf).__name__})", place)]
    if leaf in named:
        return []
    return [_at(f"{model.__name__} through Core", place) for model in _row_scoped(_models_of(base))]


def _core_only_reads(statement: Any, mappers: Iterable[Any] = ()) -> list[str]:
    """What *statement* reads that the row scope cannot reach, each by what it is.

    Only the shapes the session can scope pass; anything else is refused, so a shape nobody
    listed fails closed rather than open. Judged per SELECT, nested ones included: a
    row-scoped table in a SELECT's FROM list must be named by a mapped entity **in that same
    SELECT**, which is what the loader criteria attach to. A mapped entity elsewhere in the
    statement does not scope it: a parent's relationship to a child reaches the child's
    mapper without covering a Core join to the child's table. A FROM element is:

    * an ORM entity's own FROM (a joined eager load's alias, say): scoped;
    * a subquery or CTE of a SELECT or a compound of them: judged as its own SELECTs;
    * a table, or any alias or sample of one, through every join and parenthesised group:
      scoped only when an ORM entity or alias of that same SELECT names it, and matched to its
      models by name alone, case folded and in any schema;
    * a ``VALUES`` list, or a function's rows: walked with the rest of the statement;
    * anything else, and literal SQL anywhere in the statement (``text()``, a ``text()``
      subquery, a literal column, a prefix, suffix or hint that is more than a name):
      refused, since the session can neither read nor scope it.

    The same holds wherever the read writes SQL: in a loader option, a ``VALUES`` row, and
    each column property of *mappers* (the mappers the read reaches), whose SQL every load of
    its model carries. The session attaches the criteria to an entity named in any of them.
    """
    found: set[str] = set()
    sources: list[tuple[Any, str | None]] = [(statement, None)]
    for mapper in mappers:
        sources.extend(_mapping_sql(mapper))
    for source, place in sources:
        for element, at in _elements(source, place):
            if _literal_sql(element):
                found.add(_at("literal SQL", at))
                continue
            if not isinstance(element, Select):
                continue
            named: set[Any] | None = None
            for from_ in element.get_final_froms():
                for leaf in _from_leaves(from_):
                    named = _orm_named_tables(element) if named is None else named
                    found.update(_unscoped_from(leaf, named, at))
    return sorted(found)


__all__ = [
    "ScopePredicate",
    "apply_row_scope",
    "refuse_out_of_scope_references",
    "register_owner_read_scope",
    "register_scope_predicate",
    "registered_scope_predicates",
]
