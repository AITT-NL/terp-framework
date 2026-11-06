from sqlmodel import Field, SQLModel


class Note(SQLModel, table=True):
    title: str = Field(max_length=200)
