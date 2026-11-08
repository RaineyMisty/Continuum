"""Versioned research-memory port. Local recovery never depends on this port."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class ContextRequest:
    project_id: str
    run_id: str
    step: int
    goal: str
    files: dict[str, str]
    checkpoint_id: str = ''
    history: list[dict] = field(default_factory=list)
    handoff: dict = field(default_factory=dict)
    schema_version: int = 1
    requested_state_ref: str | None = None


@dataclass(frozen=True)
class ContextSnapshot:
    instructions: str = ''
    model_state: dict[str, Any] = field(default_factory=dict)
    state_ref: str | None = None


@dataclass(frozen=True)
class ContextEvent:
    project_id: str
    run_id: str
    step: int
    kind: str
    payload: dict[str, Any]
    event_id: str = ''
    schema_version: int = 1


class ContextPort(Protocol):
    def read(self, request: ContextRequest) -> ContextSnapshot: ...
    def write(self, event: ContextEvent) -> None:
        """At-least-once delivery: implementations MUST deduplicate by event_id."""
        ...


class NullContext:
    def read(self, request: ContextRequest) -> ContextSnapshot:
        return ContextSnapshot()

    def write(self, event: ContextEvent) -> None:
        pass
