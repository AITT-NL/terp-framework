"""Typed realtime channel declarations + the process registry.

A channel is the realtime analogue of ``EventDefinition``: app code names it
once and binds its wire payload to Pydantic models. The transport never accepts
an untyped dict. ``mode='sse'`` is server-push only; ``mode='websocket'`` may
add an inbound model + handler for bidirectional messages.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from threading import RLock
from typing import Literal

from pydantic import BaseModel
from sqlmodel import Session

from terp.core import (
    AuthorizationRequirement,
    Permission,
    Principal,
    Role,
    Roles,
    as_role,
)

_CHANNEL_RE = re.compile(r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$")

InboundHandler = Callable[[Session, Principal, BaseModel], None]
AudienceResolver = Callable[[Session, Principal], str]


def principal_audience(_session: Session, principal: Principal) -> str:
    """Default audience: only connections minted for this principal."""
    return str(principal.id)


def global_audience(_session: Session, _principal: Principal) -> str:
    """Explicit opt-in audience for a channel intentionally shared by all subscribers."""
    return "global"


RealtimeAuthzRef = AuthorizationRequirement | Permission | Role | Roles


def _requirement(value: RealtimeAuthzRef) -> AuthorizationRequirement:
    if isinstance(value, AuthorizationRequirement):
        return value
    if isinstance(value, Permission):
        return AuthorizationRequirement.from_permission(value)
    return AuthorizationRequirement.from_role(as_role(value))


@dataclass(frozen=True, init=False)
class RealtimeChannel:
    """One typed, authorized realtime stream.

    ``requirement`` is the read authority for minting a ticket. Role floors and
    permissions use the same normalized objects as ``Policy``; a permission is
    denied fail-closed unless the realtime capability is configured with a
    permission enforcer. ``inbound_model`` / ``on_message`` are both required
    or both absent, and only WebSocket channels may declare them.
    """

    name: str
    outbound_model: type[BaseModel]
    mode: Literal["sse", "websocket"] = "sse"
    requirement: AuthorizationRequirement
    inbound_requirement: AuthorizationRequirement
    inbound_model: type[BaseModel] | None = None
    on_message: InboundHandler | None = None
    audience: AudienceResolver

    def __init__(
        self,
        name: str,
        outbound_model: type[BaseModel],
        *,
        mode: Literal["sse", "websocket"] = "sse",
        requirement: RealtimeAuthzRef = Roles.VIEWER,
        inbound_requirement: RealtimeAuthzRef = Roles.EDITOR,
        inbound_model: type[BaseModel] | None = None,
        on_message: InboundHandler | None = None,
        audience: AudienceResolver = principal_audience,
    ) -> None:
        if _CHANNEL_RE.fullmatch(name) is None:
            raise ValueError(
                "RealtimeChannel.name must be a lowercase dotted/dashed token, "
                f"got {name!r}"
            )
        if not isinstance(outbound_model, type) or not issubclass(
            outbound_model, BaseModel
        ):
            raise TypeError("RealtimeChannel.outbound_model must be a Pydantic model")
        if mode not in {"sse", "websocket"}:
            raise ValueError("RealtimeChannel.mode must be 'sse' or 'websocket'")
        has_model = inbound_model is not None
        has_handler = on_message is not None
        if has_model != has_handler:
            raise ValueError(
                "RealtimeChannel.inbound_model and on_message must be declared together"
            )
        if has_model and mode != "websocket":
            raise ValueError("only WebSocket channels can receive inbound messages")
        if has_model and (
            not isinstance(inbound_model, type)
            or not issubclass(inbound_model, BaseModel)
        ):
            raise TypeError("RealtimeChannel.inbound_model must be a Pydantic model")
        if not callable(audience):
            raise TypeError("RealtimeChannel.audience must be callable")
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "outbound_model", outbound_model)
        object.__setattr__(self, "mode", mode)
        object.__setattr__(self, "requirement", _requirement(requirement))
        object.__setattr__(
            self, "inbound_requirement", _requirement(inbound_requirement)
        )
        object.__setattr__(self, "inbound_model", inbound_model)
        object.__setattr__(self, "on_message", on_message)
        object.__setattr__(self, "audience", audience)


_lock = RLock()
_channels: dict[str, RealtimeChannel] = {}


def register_channel(channel: RealtimeChannel) -> RealtimeChannel:
    """Register *channel* exactly once (idempotent for the same declaration)."""
    with _lock:
        existing = _channels.get(channel.name)
        if existing is not None and existing != channel:
            raise ValueError(f"duplicate realtime channel declaration: {channel.name!r}")
        _channels[channel.name] = channel
    return channel


def get_channel(name: str) -> RealtimeChannel | None:
    """The declared channel named *name*, or ``None`` (never a dynamic topic)."""
    with _lock:
        return _channels.get(name)


def registered_channels() -> tuple[RealtimeChannel, ...]:
    """All declarations, sorted for deterministic introspection/tests."""
    with _lock:
        return tuple(_channels[name] for name in sorted(_channels))


def clear_channels() -> None:
    """Drop the registry (test-isolation seam; declarations are import-time)."""
    with _lock:
        _channels.clear()


__all__ = [
    "AudienceResolver",
    "InboundHandler",
    "RealtimeAuthzRef",
    "RealtimeChannel",
    "clear_channels",
    "get_channel",
    "global_audience",
    "principal_audience",
    "register_channel",
    "registered_channels",
]
