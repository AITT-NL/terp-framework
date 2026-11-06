from terp.core import BaseSchema, Personal


class CustomerCreate(BaseSchema):
    email: str = Personal()
