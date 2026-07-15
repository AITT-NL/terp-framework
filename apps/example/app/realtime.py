"""Example typed realtime channels (global SSE + principal-scoped WebSocket)."""

from __future__ import annotations

from pydantic import BaseModel, Field
from sqlmodel import Session

from terp.capabilities.realtime import (
    RealtimeChannel,
    global_audience,
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


def _handle_command(
    _session: Session, _principal: Principal, _message: BaseModel
) -> None:
    # Reference seam only: a real module delegates to its service. The handler
    # receives a validated RealtimeCommand + the authenticated principal.
    return None


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
