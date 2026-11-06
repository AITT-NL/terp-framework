"""Violation: attribute-qualified text() with .format() — qualification must not evade."""

import sqlalchemy


def find_all(session, table_name):
    return session.execute(sqlalchemy.text("SELECT * FROM {}".format(table_name)))
