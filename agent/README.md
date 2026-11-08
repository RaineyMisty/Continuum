# Agent — AI 执行模块

负责模型调用、多轮改写、固定验证、暂停、恢复、分叉与导出。

- `engine.py`：检查点状态机。
- `providers.py`：真实模型与离线 mock。
- `workspace.py`、`validation.py`：安全路径校验、文件修改和验证副本。
- `storage.py`：本地执行检查点；这是恢复基础设施，不是数据库研究算法。
- `cli.py`、`__main__.py`：`continuum` / `python -m agent` 入口。
- `tests/`：执行、故障恢复和数据库接口集成测试。

仅依赖 `memory.context` 中的数据库协议，不依赖 demo 的业务实现。通过输入路径读取任意支持的 Python 项目。

在仓库根目录运行 `python -m pytest -q`。具体命令见根 README。

## State machine

```text
baseline --fail--> baseline_failed
   |
  pass
   v
generate: read optional database memory, persist exact prompt
   v
request: call model OR reuse already saved response
   v
apply: validate the entire proposal, apply in private copy
   | invalid JSON/edit -> feedback history -> next round
   v
verify: persist candidate code AND explicit handoff before running tests
   |
   +-- tests pass AND model says done -> completed
   +-- otherwise -> generate, or exhausted if round budget reached
```

The latest unsuccessful candidate is intentionally retained: the next worker sees the partially edited code and its failures. Input remains separate. A failing baseline stops before the first model call, so environment problems cannot be mistaken for model regressions.

Every commit creates a new directory containing code and state, then replaces HEAD with `os.replace`. Checkpoint readers follow HEAD only. A killed copy/commit leaves an unreferenced directory, never a partially selected revision. Checkpoints are not garbage-collected automatically. This design targets small experiments and prioritizes auditability over space efficiency.

Run-level OS locking prevents concurrent writers and releases automatically when a process dies. Validation uses disposable copies and fixed commands, so its writes cannot contaminate a checkpoint. Arbitrary project code is trusted, not sandboxed; hard-killing the runner can leave a verification subprocess running until it exits, but that subprocess works on its disposable copy.

## Recovery boundaries

| Interruption | Recovery |
| --- | --- |
| Baseline validation | Re-run baseline on saved input |
| Database read | Retry read; no request was committed |
| LLM request before full response is saved | Re-send exact committed prompt |
| Full response saved, HEAD not advanced | Reuse response by request ID |
| Candidate copy/edit or HEAD switch | Follow prior HEAD and replay cached response |
| Verification | Re-run fixed commands on persisted candidate |
| Database event acknowledged but local ack not saved | Replay identical event ID |

No promise of exactly-once remote inference or recovery of unreturned token streams. The backend may bill a request even if its response was lost. `Ctrl+C` records a pause when possible; SIGKILL leaves the last durable phase. Process-crash consistency is distinct from power-loss durability.

## Continuity experiment

Recovery state is a local execution requirement, not the experimental memory algorithm. Both branches receive the same explicit public handoff and history. Only the treatment branch receives `ContextSnapshot.instructions/model_state`. The exact prompt and snapshot are retained in the request checkpoint; `state_ref` records actual database provenance.

Fork only at the `generate` boundary after a completed round and delivered events. Forks have new run IDs and record their common parent checkpoint. They retain matching source, model, goal and validation settings. Start the common parent with NullContext; a parent previously influenced by memory is not a clean no-memory baseline. Pin database state with `memory_ref` and enforce per-run isolation in the future adapter.

The current optimizer edits existing application modules only. This intentionally keeps test/config/dependency contracts fixed, and bounds the task to refactoring rather than arbitrary repository redevelopment. Full-file proposals support multiple modules per step. More advanced tool use, file creation/deletion, dependency changes and long-context retrieval can be added later without replacing the recovery or database contracts.
