"""``build_crud_router`` — the optional CRUD-router factory (Tier-C sugar, ADR 0023).

Generates the five canonical, secure routes — ``list`` (paginated), ``create``
(201), ``get``, ``update`` (OCC), ``delete`` (204) — over a :class:`BaseService`
and its DTOs, and returns a **native** ``APIRouter``. It is Tier-C *opinionated
sugar* (ADR 0006): every route it builds is exactly what the hand-written module
writes — each returns the ``*Read`` DTO (never the table model), the list paginates,
and writes route through the audited ``BaseService`` chokepoint — so the repeated
CRUD boilerplate (see ``notes`` / ``projects``) collapses to one call, while a
module that needs anything bespoke still writes its routes by hand. Native FastAPI
is always allowed; this is a convenience, never the only path.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Sequence

from fastapi import APIRouter
from sqlmodel import SQLModel

from terp.core.base_models import BaseTable, BaseUpdateSchema
from terp.core.base_service import BaseService
from terp.core.db import SessionDep
from terp.core.operations import OperationDefinition
from terp.core.pagination import Page, PaginationDep
from terp.core.routing import operation

# The read DTO's suffix, stripped to recover the entity's own name: ``ProjectRead``
# describes a project, and the route is named for the project, not for the DTO.
_READ_SUFFIX = "Read"


def _snake(name: str) -> str:
    """``SyncRun`` -> ``sync_run``; the naming shape hand-written routers use."""
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def _plural(noun: str) -> str:
    """A regular English plural for *noun*, for the collection route's name.

    Deliberately small: the three regular rules, and nothing that pretends to know
    an irregular noun. A ``person`` collection is named ``persons`` here, which is
    slightly wrong and entirely harmless — the name is a *fallback* identity for a
    route that has not declared its own operation, and declaring one supersedes it.
    Getting ``companies`` and ``addresses`` right is what earns the rules their keep.
    """
    if noun.endswith(("s", "x", "z", "ch", "sh")):
        return noun + "es"
    if len(noun) > 1 and noun.endswith("y") and noun[-2] not in "aeiou":
        return noun[:-1] + "ies"
    return noun + "s"


def _entity_name(read_schema: type) -> str:
    """The entity these routes are about, from the read DTO's class name.

    Leading underscores are dropped first. A module-private DTO is a normal thing
    to hand this factory — the repository's own tests declare ``_WidgetRead`` — and
    the underscore is Python's visibility convention, not part of the entity's
    name: without stripping it the collection route came out as ``list___widgets``.
    """
    name = read_schema.__name__.lstrip("_")
    if name.endswith(_READ_SUFFIX) and len(name) > len(_READ_SUFFIX):
        name = name[: -len(_READ_SUFFIX)]
    return _snake(name) or "item"


def build_crud_router[
    ModelT: BaseTable,
    CreateT: SQLModel,
    UpdateT: BaseUpdateSchema,
    ReadT: SQLModel,
](
    service: BaseService[ModelT, CreateT, UpdateT],
    *,
    read_schema: type[ReadT],
    create_schema: type[CreateT],
    update_schema: type[UpdateT],
    tags: Sequence[str] | None = None,
    list_operation: OperationDefinition | None = None,
    create_operation: OperationDefinition | None = None,
    get_operation: OperationDefinition | None = None,
    update_operation: OperationDefinition | None = None,
    delete_operation: OperationDefinition | None = None,
) -> APIRouter:
    """Build the five canonical CRUD routes over *service* and its DTOs.

    *read_schema* / *create_schema* / *update_schema* are the module's ``*Read`` /
    ``*Create`` / ``*Update`` DTOs. The returned ``APIRouter`` is mounted by
    ``create_app`` like any hand-written module router (behind its policy guard);
    the responses are the read DTO, so the runtime response-model guard (ADR 0020)
    is satisfied by construction.

    The five ``*_operation`` parameters declare what each route does (ADR 0102 §7):
    a factory-built module is otherwise undeclarable — every one of them derives the
    same five labels from the same five route names — which would make ``strict``
    coverage unreachable for exactly the modules this framework tells consumers to
    build with sugar. Each defaults to ``None`` (no declaration, matching a
    hand-written route that carries no ``@operation``), so an existing caller is
    unaffected; passing one is exactly like decorating the equivalent hand-written
    handler with ``@operation(...)``, applied here because the factory builds the
    handler rather than letting the caller decorate it.
    """
    router = APIRouter(tags=list(tags or ()))
    page_model = Page[read_schema]
    # Name the routes after the entity rather than after the closures below. Left
    # to FastAPI they would all be called `*_item`, so every factory-built module
    # was indistinguishable in the access graph AND in the exported OpenAPI, where
    # `generate_unique_id` builds each operationId from the route name.
    entity = _entity_name(read_schema)
    collection = _plural(entity)

    def list_items(session, pagination):
        rows, total = service.list(session, skip=pagination.skip, limit=pagination.limit)
        return page_model.of(
            [read_schema.model_validate(row) for row in rows], total, pagination
        )

    def create_item(payload, session):
        return read_schema.model_validate(service.create(session, payload))

    def get_item(item_id, session):
        return read_schema.model_validate(service.get(session, item_id))

    def update_item(item_id, payload, session):
        return read_schema.model_validate(service.update(session, item_id, payload))

    def delete_item(item_id, session):
        service.delete(session, item_id)

    # FastAPI derives the request body, the path id, and the dependencies from each
    # endpoint's annotations at runtime, so bind the concrete per-call types here:
    # the real DTO classes, the uuid id, and SessionDep / PaginationDep (Annotated
    # → Depends). They cannot be written as ``def`` annotations because the schema
    # types are runtime arguments, not module-level names.
    list_items.__annotations__ = {
        "session": SessionDep,
        "pagination": PaginationDep,
        "return": page_model,
    }
    create_item.__annotations__ = {
        "payload": create_schema,
        "session": SessionDep,
        "return": read_schema,
    }
    get_item.__annotations__ = {
        "item_id": uuid.UUID,
        "session": SessionDep,
        "return": read_schema,
    }
    update_item.__annotations__ = {
        "item_id": uuid.UUID,
        "payload": update_schema,
        "session": SessionDep,
        "return": read_schema,
    }
    delete_item.__annotations__ = {
        "item_id": uuid.UUID,
        "session": SessionDep,
    }

    # Declare each route's operation before registering it. `operation(...)` returns
    # its argument unchanged (it stamps an attribute), so applying it here is exactly
    # what `@operation(...)` does above a hand-written handler.
    if list_operation is not None:
        operation(list_operation)(list_items)
    if create_operation is not None:
        operation(create_operation)(create_item)
    if get_operation is not None:
        operation(get_operation)(get_item)
    if update_operation is not None:
        operation(update_operation)(update_item)
    if delete_operation is not None:
        operation(delete_operation)(delete_item)

    router.add_api_route(
        "/",
        list_items,
        methods=["GET"],
        response_model=page_model,
        name=f"list_{collection}",
    )
    router.add_api_route(
        "/",
        create_item,
        methods=["POST"],
        response_model=read_schema,
        status_code=201,
        name=f"create_{entity}",
    )
    router.add_api_route(
        "/{item_id}",
        get_item,
        methods=["GET"],
        response_model=read_schema,
        name=f"get_{entity}",
    )
    router.add_api_route(
        "/{item_id}",
        update_item,
        methods=["PATCH"],
        response_model=read_schema,
        name=f"update_{entity}",
    )
    router.add_api_route(
        "/{item_id}",
        delete_item,
        methods=["DELETE"],
        status_code=204,
        name=f"delete_{entity}",
    )
    return router


__all__ = ["build_crud_router"]
