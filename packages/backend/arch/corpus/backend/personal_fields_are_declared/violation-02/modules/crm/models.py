from terp.core import BaseTable, Personal


class Customer(BaseTable, table=True):
    email: str = Personal(max_length=320, unique=True)
