"""A posted notice is mailed by the worker, through the mail capability's one relay."""

from __future__ import annotations

from sqlmodel import Session, select

from terp.core import Roles

from terp.capabilities.mail import MAIL_SEND
from terp.capabilities.outbox import STATUS_PENDING, OutboxMessage

from app.modules.notices.models import Notice

_NOTICE = {
    "title": "The car park is closed on Friday",
    "body": "Resurfacing starts at seven.\nPlease park on the street.",
    "recipient": "someone@reference.test",
}


def _pending(engine) -> list[OutboxMessage]:
    with Session(engine) as session:
        return list(
            session.exec(select(OutboxMessage).where(OutboxMessage.status == STATUS_PENDING))
        )


def test_posting_a_notice_mails_its_recipient_through_the_worker(
    client_as, mailbox, drain, db_engine
) -> None:
    created = client_as(Roles.EDITOR).post("/api/v1/notices/", json=_NOTICE)
    assert created.status_code == 201, created.text

    # The request only enqueued the mail, in the notice's own transaction: nothing has
    # been sent, and the job is a pending row beside the notice.
    assert mailbox.sent == []
    assert [row.name for row in _pending(db_engine)] == [MAIL_SEND.name]

    result = drain()
    assert result.dispatched == 1
    assert _pending(db_engine) == []
    [message] = mailbox.sent
    assert message["To"] == _NOTICE["recipient"]
    assert message["Subject"] == _NOTICE["title"]
    assert message["From"] == "Terp Reference <noreply@reference.example>"
    assert message.get_content().strip() == _NOTICE["body"]


def test_a_notice_that_could_not_be_mailed_is_refused_before_it_is_written(
    client_as, db_engine
) -> None:
    editor = client_as(Roles.EDITOR)
    two_lines = editor.post(
        "/api/v1/notices/", json={**_NOTICE, "title": "Closed\nBcc: everyone@reference.test"}
    )
    no_address = editor.post("/api/v1/notices/", json={**_NOTICE, "recipient": "the front desk"})

    assert two_lines.status_code == 422
    assert no_address.status_code == 422
    with Session(db_engine) as session:
        assert session.exec(select(Notice)).all() == []
    assert _pending(db_engine) == []


def test_a_viewer_reads_notices_and_cannot_post_one(client_as) -> None:
    editor, viewer = client_as(Roles.EDITOR), client_as(Roles.VIEWER)
    notice = editor.post("/api/v1/notices/", json=_NOTICE).json()

    listed = viewer.get("/api/v1/notices/")
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()["items"]] == [notice["id"]]
    assert viewer.get(f"/api/v1/notices/{notice['id']}").json()["title"] == _NOTICE["title"]
    assert viewer.post("/api/v1/notices/", json=_NOTICE).status_code == 403


def test_nothing_is_readable_without_signing_in(client_as) -> None:
    assert client_as(None).get("/api/v1/notices/").status_code == 401
