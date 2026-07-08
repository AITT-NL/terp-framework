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

import uuid
from collections.abc import Sequence

from fastapi import APIRouter
from sqlmodel import SQLModel

from terp.core.base_models import BaseTable, BaseUpdateSchema
from terp.core.base_service import BaseService
from terp.core.db import SessionDep
from terp.core.pagination import Page, PaginationDep


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
) -> APIRouter:
    """Build the five canonical CRUD routes over *service* and its DTOs.

    *read_schema* / *create_schema* / *update_schema* are the module's ``*Read`` /
    ``*Create`` / ``*Update`` DTOs. The returned ``APIRouter`` is mounted by
    ``create_app`` like any hand-written module router (behind its policy guard);
    the responses are the read DTO, so the runtime response-model guard (ADR 0020)
    is satisfied by construction.
    """
    router = APIRouter(tags=list(tags or ()))
    page_model = Page[read_schema]

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

    router.add_api_route("/", list_items, methods=["GET"], response_model=page_model)
    router.add_api_route(
        "/", create_item, methods=["POST"], response_model=read_schema, status_code=201
    )
    router.add_api_route(
        "/{item_id}", get_item, methods=["GET"], response_model=read_schema
    )
    router.add_api_route(
        "/{item_id}", update_item, methods=["PATCH"], response_model=read_schema
    )
    router.add_api_route("/{item_id}", delete_item, methods=["DELETE"], status_code=204)
    return router


__all__ = ["build_crud_router"]
