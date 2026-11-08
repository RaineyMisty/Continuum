"""Placeholder ONLY. No SpacetimeDB schema or mathematical algorithm selected yet.

When ready, implement read and write using SpacetimeDB's generated SDK:
    ghostgraph --context-adapter ghostgraph.spacetime_adapter_template:create_port ...
"""
from .context import ContextEvent, ContextRequest, ContextSnapshot


class SpacetimeContextPort:
    def read(self, request: ContextRequest) -> ContextSnapshot:
        raise NotImplementedError("Design z and SpacetimeDB world state in the next stage")

    def write(self, event: ContextEvent) -> None:
        raise NotImplementedError("Design z and SpacetimeDB world state in the next stage")


def create_port():
    return SpacetimeContextPort()
