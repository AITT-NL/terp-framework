class UserRead(BaseSchema):
    id: uuid.UUID
    hashed_password: str
