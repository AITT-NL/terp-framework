class UserCreate(BaseSchema):
    password: str = Field(max_length=128)
class UserRead(BaseSchema):
    id: uuid.UUID
    token_version: int
