"""Example typed realtime channels (global SSE + principal-scoped WebSocket)."""

from __future__ import annotations

from pydantic import BaseModel, Field
from sqlmodel import Session

from terp.capabilities.realtime import (
    RealtimeChannel,
    global_audience,
    publish,
    register_channel,
)
from terp.core import Principal


class SystemNotice(BaseModel):
    sequence: int = Field(ge=0)
    text: str = Field(min_length=1, max_length=500)


class PersonalUpdate(BaseModel):
    sequence: int = Field(ge=0)
    text: str = Field(min_length=1, max_length=500)


class RealtimeCommand(BaseModel):
    action: str = Field(pattern=r"^(refresh|acknowledge)$")


async def _handle_command(
    _session: Session, principal: Principal, message: BaseModel
) -> None:
    assert isinstance(message, RealtimeCommand)
    await publish(
        PERSONAL_UPDATES,
        PersonalUpdate(sequence=1, text=f"{message.action} accepted"),
        audience=str(principal.id),
    )


SYSTEM_NOTICES = register_channel(
    RealtimeChannel(
        "system.notices",
        SystemNotice,
        audience=global_audience,
    )
)

PERSONAL_UPDATES = register_channel(
    RealtimeChannel(
        "personal.updates",
        PersonalUpdate,
        mode="websocket",
        inbound_model=RealtimeCommand,
        on_message=_handle_command,
    )
)


def register_realtime_channels() -> None:
    """Idempotently restore the example declarations after reload/test reset."""
    register_channel(SYSTEM_NOTICES)
    register_channel(PERSONAL_UPDATES)


__all__ = [
    "PERSONAL_UPDATES",
    "SYSTEM_NOTICES",
    "PersonalUpdate",
    "RealtimeCommand",
    "SystemNotice",
    "register_realtime_channels",
]
