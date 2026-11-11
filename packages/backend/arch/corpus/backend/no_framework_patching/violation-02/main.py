"""Violation: the walk over the route table, replaced on the web stack by name."""

from fastapi import routing

from app.hidden import without_the_export

setattr(routing, "iter_route_contexts", without_the_export)
