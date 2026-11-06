from sqlmodel import SQLModel
from terp.core import BaseSchema


class AppSchema(BaseSchema):
    pass


class ContactCard(AppSchema):
    last_name: str = ""


class Applicant(SQLModel):
    national_id: str = ""
