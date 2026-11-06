from terp.core import BaseTable, Personal, SoftDeleteMixin


class Customer(BaseTable, SoftDeleteMixin, table=True):
    email: str = Personal(max_length=320, unique=True)
