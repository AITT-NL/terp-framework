"""Refresh-family revocation survives a successor inserted behind a row-lock wait.

The real READ COMMITTED schedule requires PostgreSQL. ``terp_pg_url`` creates a
scratch database and uses the repository's ordinary skip/required-lane contract.
"""

from __future__ import annotations

import threading
import time
from queue import Queue

import pytest
from sqlalchemy import text
from sqlmodel import Session, SQLModel, create_engine, select

from terp.capabilities.auth import RefreshRotation, refresh_token_digest
from terp.capabilities.identity import RefreshToken, RefreshTokenService, User


@pytest.mark.parametrize("issued_epoch", [None, 0], ids=["legacy-family", "bound-family"])
def test_cookie_logout_refuses_a_successor_inserted_while_revocation_waits(
    terp_pg_url: str, monkeypatch: pytest.MonkeyPatch, issued_epoch: int | None
) -> None:
    engine = create_engine(
        terp_pg_url,
        isolation_level="READ COMMITTED",
        connect_args={"options": "-c lock_timeout=10000 -c statement_timeout=15000"},
    )
    SQLModel.metadata.create_all(engine, tables=[User.__table__, RefreshToken.__table__])
    refresh = RefreshTokenService()
    with Session(engine) as session:
        user = User(email="concurrent-session@example.test")
        session.add(user)
        session.commit()
        user_id = user.id
        ancestor = refresh.issue(session, user_id, token_version=issued_epoch)
        first_rotation = refresh.rotate(session, ancestor)
        assert first_rotation is not None
        successor = first_rotation.token
        unrelated_family = refresh.issue(session, user_id, token_version=0)

    rotation_holds_row = threading.Event()
    allow_rotation_to_finish = threading.Event()
    logout_has_connection = threading.Event()
    errors: Queue[BaseException] = Queue()
    rotations: Queue[RefreshRotation | None] = Queue()
    logout_pid: Queue[int] = Queue()
    original_mint = refresh._mint

    def pause_before_successor_insert(*args, **kwargs):
        # rotate() already holds its presented successor's FOR UPDATE lock.
        # It has validated the family, but has not inserted the next token yet.
        rotation_holds_row.set()
        assert allow_rotation_to_finish.wait(10), "revocation never reached the held row"
        return original_mint(*args, **kwargs)

    monkeypatch.setattr(refresh, "_mint", pause_before_successor_insert)

    def rotate() -> None:
        try:
            with Session(engine) as session:
                rotations.put(refresh.rotate(session, successor))
        except BaseException as exc:
            errors.put(exc)

    def logout() -> None:
        try:
            with Session(engine) as session:
                logout_pid.put(session.scalar(text("SELECT pg_backend_pid()")))
                logout_has_connection.set()
                refresh.revoke_presented(session, ancestor)
        except BaseException as exc:
            errors.put(exc)

    rotating = threading.Thread(target=rotate, daemon=True)
    logging_out = threading.Thread(target=logout, daemon=True)
    try:
        rotating.start()
        assert rotation_holds_row.wait(10), "rotation never acquired its row lock"
        logging_out.start()
        assert logout_has_connection.wait(10), "logout never opened its connection"
        pid = logout_pid.get_nowait()

        # A client-side event before execute is insufficient: the SELECT's server
        # snapshot must actually precede the late INSERT. Observe the real lock
        # wait before allowing the rotation to commit on its other connection.
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as observer:
            deadline = time.monotonic() + 10
            while True:
                wait_type = observer.execute(
                    text("SELECT wait_event_type FROM pg_stat_activity WHERE pid = :pid"),
                    {"pid": pid},
                ).scalar_one()
                if wait_type == "Lock":
                    break
                assert time.monotonic() < deadline, "logout never blocked on the rotating row"
                assert errors.empty(), "a concurrent operation failed before the lock wait"
                allow_rotation_to_finish.wait(0.01)
        allow_rotation_to_finish.set()
        rotating.join(10)
        logging_out.join(10)
        assert not rotating.is_alive() and not logging_out.is_alive(), "refresh race did not finish"
        if not errors.empty():
            raise errors.get_nowait()
        late_rotation = rotations.get_nowait()
        assert late_rotation is not None
        monkeypatch.setattr(refresh, "_mint", original_mint)

        with Session(engine) as session:
            late_row = session.exec(
                select(RefreshToken).where(
                    RefreshToken.token_hash == refresh_token_digest(late_rotation.token)
                )
            ).one()
            # The SELECT that waited held an older snapshot and really missed C.
            assert late_row.revoked_at is None
            assert session.get(User, user_id).token_version == 0
            assert refresh.rotate(session, late_rotation.token) is None
            session.refresh(late_row)
            assert late_row.revoked_at is not None
            assert refresh.rotate(session, unrelated_family) is not None
    finally:
        allow_rotation_to_finish.set()
        rotating.join(10)
        if logging_out.ident is not None:
            logging_out.join(10)
        engine.dispose()
