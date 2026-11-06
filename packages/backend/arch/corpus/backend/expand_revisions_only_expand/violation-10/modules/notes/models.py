from terp.core import BaseTable, SoftDeleteMixin


class Note(SoftDeleteMixin, BaseTable, table=True):
    __tablename__ = 'notes'
