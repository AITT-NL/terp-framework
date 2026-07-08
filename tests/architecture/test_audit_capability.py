"""Coverage for the terp-cap-audit durable sink's defensive edge paths.

The end-to-end API tests drive the sink with a request id present and an empty
payload; this exercises the complementary branches — a record with **no** request
id (e.g. a non-HTTP write) and a populated payload — so the capability holds 100%
line coverage.
"""

from __future__ import annotations

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from terp.core import AuditAction, AuditPolicy, AuditRecord

from terp.capabilities.audit import AuditEvent, persist_audit


def test_persist_audit_stores_a_record_without_a_request_id() -> None:
    import terp.capabilities.audit.models  # noqa: F401  (register the table)

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            persist_audit(
                session,
                AuditRecord(
                    action=AuditAction.CREATED,
                    target_type="Widget",
                    target_id="w1",
                    actor_id=None,
                    request_id=None,  # exercises the _clip(None) branch
                    payload={"note": "kept"},  # exercises the payload-dict branch
                ),
                AuditPolicy.default(),
            )
            session.commit()
            row = session.exec(select(AuditEvent)).one()
            assert row.action == "created"
            assert row.target_type == "Widget"
            assert row.request_id is None
            assert row.payload == {"note": "kept"}
    finally:
        engine.dispose()
