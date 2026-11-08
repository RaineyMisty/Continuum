# Stage 1: Frozen boundaries

## Purpose

Produce a real new version of a legacy Python program using an LLM. Preserve a stable hook for a future SpacetimeDB context/skill/world-model provider, without deciding the algorithm yet.

## Module A — Legacy project (input)

- Input: an existing Python codebase, preferably with regression tests.
- The project is **not** a simulated API: the source files are real and are used as LLM input.
- The input stays unchanged. A modernized copy is written to a different directory.
- Tests are read-only contract examples. A successful test run alone does not prove better maintainability.

## Module B — AI modernization runner

- Inputs: legacy source snapshot, goal, optional `ContextSnapshot`, optional previous test feedback.
- Model: OpenAI-compatible API (NVIDIA Nemotron Ultra by default); mock adapter for offline wiring tests only.
- Output: list of **entire revised file contents**, restricted to existing Python application files.
- Verification: optionally execute project's test command on the output tree.
- Emits `ContextEvent` at step start and step completion. It does not assume anything about SpacetimeDB's schema.
- Stage 1 is deliberately a bounded edit loop, not an autonomous coding agent or full tool-use framework.

## Module C — Context / Skill port (UNIMPLEMENTED)

The future database may manage whatever abstract state and algorithm are found useful.
The Stage-1 runner needs only:

```text
ContextPort.read(ContextRequest) -> ContextSnapshot
ContextPort.write(ContextEvent) -> None
```

`ContextSnapshot` has these fields:

- `instructions` — what the LLM-facing adapter wants included in the current prompt
- `model_state` — optional small JSON-compatible projection of the abstract state
- `state_ref` — a reference/version ID of the authoritative DB state

`ContextEvent` includes project/run/step, an event kind, and a payload.

**The mathematical state z, update algorithm U, and database schema are explicitly outside this stage.** An adapter can project the state for the LLM while keeping the authoritative state inside SpacetimeDB. The runner never sees database tables.

## Future experiments (not implemented)

- With/without DB: same input source, starting commit, task, model, temperature, tools and tests; only context adapter differs.
- Crash: same frozen checkpoint, two independent workers, a reproducible interruption point.
- Multiple continuations: repeated independent output directories; compare semantic behavior and key decisions rather than exact code bytes.

Do not claim these experiments pass until they are built and run.
