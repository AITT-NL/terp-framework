class NotePatch(BaseSchema):
    title: str


router = build_crud_router(update_schema=NotePatch)
