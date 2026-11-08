# GhostGraph — Modernization Runner (Stage 1)

**Current scope:** legacy Python repo -> LLM code edit -> new repo -> optional regression tests.

**Deliberately NOT implemented yet:** SpacetimeDB schema, mathematical state `z`, persistent agent handoff, distributed coordination, multi-agent continuity, or controlled ablation. The future `ContextPort` interface is present, but the default `NullContext` does nothing. This is a working **scaffold**, not the completed GhostGraph research system.

## Architecture

```text
Existing legacy Python project (input, read-only)
           |
           v
     Modernization Runner  <---- ContextPort.read() [currently NullContext]
           |
           +--> NVIDIA Nemotron / compatible LLM API
           |      returns revised Python source files
           v
  Isolated modernized project (output)
           |
           +--> optional pytest or other test command
           +--> ghostgraph_run.json
           |
           +--> ContextPort.write() [currently no-op]
```

**Ownership:** Git/source files stay outside SpacetimeDB. Only future context state and events will go through `ContextPort`.

## Install (Ubuntu / Linux)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
```

## 1. Smoke test without any API key

```bash
ghostgraph --provider mock \
  --input examples/legacy_orders \
  --output outputs/offline-test \
  --run-tests
```

The mock adapter merely inserts a harmless comment into one source file to test the pipeline. It does **not** perform any actual modernization. You should see generated output and passing regression tests.

## 2. Real AI modernization using NVIDIA Nemotron

Get an API key from https://build.nvidia.com/nvidia/nemotron-3-ultra-550b-a55b . Set the key via shell (do not commit it):

```bash
export NVIDIA_API_KEY='your_key_here'
ghostgraph --provider nvidia \
  --model nvidia/nemotron-3-ultra-550b-a55b \
  --input examples/legacy_orders \
  --output outputs/nemotron-run-1 \
  --goal 'Refactor for maintainability while preserving public behavior and tests' \
  --run-tests --steps 2
```

For your own 300–500-line Python legacy project, replace `--input` with its directory and choose a new `--output` directory each run. The runner copies the input project and changes only existing application `.py` files in the output. The model sees code and test definitions but cannot submit rewritten test files through the edit interface.

`--steps 2` lets the model receive the previous test output and make a second revision if the tests fail. Do not expect this lightweight runner to match Codex's repository-wide tool-use abilities.

Only run `--run-tests` on trusted repositories: it executes their code locally. For untrusted input, use a container sandbox.

## Model choice and fallback

Default: `nvidia/nemotron-3-ultra-550b-a55b` via `https://integrate.api.nvidia.com/v1`. This is NVIDIA's large Nemotron 3 reasoning/coding model, not a claim that it wins every benchmark. Actual access, latency, and quality depend on your account and endpoint availability. If API stalls, you can switch models or use another OpenAI-compatible service:

```bash
export GHOSTGRAPH_BASE_URL='https://your-provider.example/v1'
export GHOSTGRAPH_API_KEY='provider-key'
ghostgraph --provider nvidia --model 'provider/model-id' --input ... --output ...
```

The `nvidia` provider flag simply uses the OpenAI-compatible chat-completions adapter in this starter.

## Frozen context adapter contract (for Stage 2)

See `ghostgraph/context.py`:

- `read(ContextRequest) -> ContextSnapshot`: invoked **before** every LLM revision. Can supply compact machine-derived instructions, abstract state, and a state/version reference.
- `write(ContextEvent)`: receives `step_started` and `step_completed` events with changed files and test outcomes.

The exact mathematical meaning and SpacetimeDB representation of `z` are **intentionally undecided**. Implement the interface later, without changing the runner:

```bash
ghostgraph --context-adapter yourmodule:make_adapter --input ... --output ...
```

The placeholder `ghostgraph/spacetime_adapter_template.py` is purposely unimplemented. The baseline `--context-adapter none` can later be compared against the real database adapter using the same input snapshots, tests, prompts and model.

## Output and later experiments

Every run writes `ghostgraph_run.json` in the output, containing step summaries, modified paths, test results, and run ID. Input is never overwritten. Each repeated trial must use a distinct output directory.

**Not yet guaranteed:** deterministic LLM code or exact token-level continuation. Those claims require controlled experiments and a more sophisticated future state model.

## Contributing / GitHub

```bash
python -m pytest -q
git init
git add .
git commit -m 'Bootstrap GhostGraph modernization runner and context adapter'
# create a repository on GitHub, then set remote and push
```

Never commit `.env`, API keys, or generated outputs.
