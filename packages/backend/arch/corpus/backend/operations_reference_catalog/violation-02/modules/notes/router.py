from terp.core import build_crud_router

router = build_crud_router(
    NoteService(),
    read_schema=NoteRead,
    create_schema=NoteCreate,
    update_schema=NoteUpdate,
    list_operation="notes.list",
)
