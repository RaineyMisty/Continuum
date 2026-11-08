"""Placeholder ONLY. No SpacetimeDB schema or mathematical algorithm selected yet.

When ready, implement read and write using SpacetimeDB's generated SDK:
    continuum start --context-adapter memory.spacetime_adapter_template:create_port ...

Implement the schema-v1 contract in memory/README.md, including event_id
deduplication and requested_state_ref support. This template deliberately fails
until a real database design is supplied; it never silently substitutes no memory.
"""
from .context import ContextEvent, ContextRequest, ContextSnapshot


class SpacetimeContextPort:
    def read(self, request: ContextRequest) -> ContextSnapshot:
        raise NotImplementedError("Design z and SpacetimeDB world state in the next stage")

    def write(self, event: ContextEvent) -> None:
        raise NotImplementedError("Design z and SpacetimeDB world state in the next stage")


def create_port():
    return SpacetimeContextPort()
