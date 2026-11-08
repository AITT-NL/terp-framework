"""A hard delete a reference refuses is the uniform 409, and its logged detail withholds personal data.

``BaseService._remove`` maps a referential refusal to a ``ConflictError`` and keeps the
database's own detail in ``log_context`` with the row's personal values withheld (ADR 0190).
A refused flush expires the rows in it while the session waits for its rollback, so reading
those values must not load them: a load there raises, and the 409 became a 500 whose log
carried the database's unredacted detail.

The reference is on the address, so PostgreSQL's detail names it (``Key (email)=(...) is still
referenced``) and the withholding has something to withhold; SQLite's names no value at all.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
import sqlalchemy as sa
from sqlmodel import Session, SQLModel, create_engine

from terp.core import ConflictError
from terp.core._internal.session_guard import WriteGuardedSession

import terp.capabilities.audit.models  # noqa: F401 - the audit table the delete writes to
from terp.capabilities.auth import hash_password
from terp.capabilities.identity import User
from terp.capabilities.users import UsersService


@pytest.fixture
def engine(terp_db_url: str) -> Iterator[Any]:
    engine = create_engine(terp_db_url)
    if engine.dialect.name == "sqlite":
        sa.event.listen(engine, "connect", lambda connection, _: connection.execute("PRAGMA foreign_keys=ON"))
    SQLModel.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE example_reference (id INTEGER PRIMARY KEY, user_email VARCHAR(320) "
            "REFERENCES identity_user (email) ON DELETE RESTRICT)"
        )
    yield engine
    engine.dispose()


def _referenced_user(engine: Any, email: str) -> Any:
    with Session(engine) as session:
        user = User(email=email, hashed_password=hash_password("a long and unremarkable passphrase"), role=10)
        session.add(user)
        session.commit()
        user_id = user.id
    with engine.begin() as connection:
        connection.execute(sa.text("INSERT INTO example_reference (id, user_email) VALUES (1, :email)"), {"email": email})
    return user_id


def test_a_hard_delete_a_reference_refuses_is_the_uniform_409(engine: Any) -> None:
    user_id = _referenced_user(engine, "kept@example.test")
    with WriteGuardedSession(engine) as session, pytest.raises(ConflictError) as refused:
        UsersService().delete(session, user_id)
    assert refused.value.status_code == 409
    if engine.dialect.name == "postgresql":
        assert "kept@example.test" in str(refused.value.__cause__), "control: the database's own detail names it"
    assert "kept@example.test" not in str(refused.value.log_context), "the detail withholds the address"
    with Session(engine) as session:
        assert session.get(User, user_id) is not None, "the refused delete changed nothing"


def test_the_session_is_usable_again_after_the_refusal(engine: Any) -> None:
    user_id = _referenced_user(engine, "again@example.test")
    with WriteGuardedSession(engine) as session:
        with pytest.raises(ConflictError):
            UsersService().delete(session, user_id)
        assert UsersService().get(session, user_id).email == "again@example.test"
