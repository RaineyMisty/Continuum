# Database extension contract (schema version 1)

Implement `read(ContextRequest) -> ContextSnapshot` and `write(ContextEvent) -> None`, then expose a zero-argument factory through `--context-adapter package.module:create_port`. `none` selects `NullContext`. The bundled SpacetimeDB template deliberately raises `NotImplementedError`; no schema or mathematical state is implied.

## Read

The request includes project content identity, run ID, next step, goal, current files, checkpoint ID, public history, explicit handoff and optional `requested_state_ref`. The adapter may derive or retrieve whatever state your algorithm needs.

Return:

- `instructions`: compact supplemental task guidance.
- `model_state`: JSON-serializable abstract state/projection. No database-specific type may cross this boundary.
- `state_ref`: actual version/snapshot reference read. If a requested frozen version cannot be honored, fail explicitly rather than silently using live state.

Read should not advance authoritative state: a crash can retry it. The returned snapshot and exact prompt are saved before inference. A resumed in-flight request reuses them instead of reading newer memory.

## Write

Events include `event_id`, `schema_version`, project/run/step, kind and payload:

- `baseline_completed`: verification results on unchanged input.
- `step_started`: upcoming step and snapshot reference.
- `step_completed`: summary, edit paths, validation/error feedback, explicit handoff and code hashes.

Events are persisted in the same local checkpoint as the execution state. Delivery is **at least once**. `write` MUST atomically deduplicate `event_id` before mutating database state. If delivery fails, execution stops with a recoverable error; it does not silently proceed with missing memory. New runs/forks have distinct run IDs. Project ID derives from the input content manifest, not just directory name.

Step completion carries public `plan`, `completed`, `decisions`, and `next_actions`, not hidden chain-of-thought. An adapter can maintain skills, constraints, causal links or compressed state based on these records, without changing the worker.

## Experiment isolation

`fork --memory-ref frozen-v1` requests the same initial database version for repeat trials. The future adapter must define branch initialization and write isolation. It must not let branch A update the memory subsequently read by branch B unless that interaction is deliberately part of the experiment.

The runner does not implement a database clone, SpacetimeDB transactions, mathematical update U, or state z. These are the research module to build later. Never interpret successful plumbing tests with fake memory as evidence that a particular memory algorithm preserves agent intent.
