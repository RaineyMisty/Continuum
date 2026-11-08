"""Stable extension point for a future SpacetimeDB-backed mathematical state.

The execution engine never imports SpacetimeDB directly. Implement the protocol
and supply module:factory via --context-adapter when the DB design is ready.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class ContextRequest:
    project_id: str
    run_id: str
    step: int
    goal: str
    files: list[str]


@dataclass(frozen=True)
class ContextSnapshot:
    """Application-facing projection of future state z; no z model is prescribed."""
    instructions: str = ""
    model_state: dict[str, Any] = field(default_factory=dict)
    state_ref: str | None = None


@dataclass(frozen=True)
class ContextEvent:
    project_id: str
    run_id: str
    step: int
    kind: str
    payload: dict[str, Any]


class ContextPort(Protocol):
    def read(self, request: ContextRequest) -> ContextSnapshot: ...
    def write(self, event: ContextEvent) -> None: ...


class NullContext:
    """Baseline for later with/without SpacetimeDB comparisons."""
    def read(self, request: ContextRequest) -> ContextSnapshot:
        return ContextSnapshot()

    def write(self, event: ContextEvent) -> None:
        pass
