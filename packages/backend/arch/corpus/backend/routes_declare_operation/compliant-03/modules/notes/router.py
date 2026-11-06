from control_plane.operations import (
    NOTES_CREATE,
    NOTES_DELETE,
    NOTES_GET,
    NOTES_LIST,
    NOTES_UPDATE,
)
from terp.core import build_crud_router

router = build_crud_router(
    NoteService(),
    read_schema=NoteRead,
    create_schema=NoteCreate,
    update_schema=NoteUpdate,
    list_operation=NOTES_LIST,
    create_operation=NOTES_CREATE,
    get_operation=NOTES_GET,
    update_operation=NOTES_UPDATE,
    delete_operation=NOTES_DELETE,
)
