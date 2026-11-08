"""Checkpointed state machine: baseline -> request -> apply -> verify -> repeat."""
from __future__ import annotations
from dataclasses import asdict, dataclass, field
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import uuid

from memory.context import ContextEvent, ContextPort, ContextRequest
from .providers import LLM
from .storage import Store, atomic_json
from .validation import validate
from .workspace import apply_changes, hashes, prepare, source_files

TERMINAL = {'completed', 'baseline_failed', 'exhausted'}


@dataclass
class RunConfig:
    input_dir: Path
    output_dir: Path
    goal: str = 'Improve modularity and readability while preserving public behavior'
    model: str = 'nvidia/nemotron-3-ultra-550b-a55b'
    max_steps: int = 8
    commands: list[list[str]] = field(default_factory=lambda: [['{python}', '-m', 'pytest', '-q']])
    timeout: float = 90
    provider: str = 'nvidia'
    context_adapter: str = 'none'
    base_url: str = 'https://integrate.api.nvidia.com/v1'
    temperature: float = 0.2
    max_tokens: int = 16000
    memory_ref: str | None = None


def create_run(cfg: RunConfig) -> Store:
    if cfg.max_steps < 1 or cfg.timeout <= 0:
        raise ValueError('max_steps and timeout must be positive')
    if not cfg.commands or any(not c or any(not isinstance(x, str) for x in c) for c in cfg.commands):
        raise ValueError('Verification requires nonempty argv arrays')
    root, src = cfg.output_dir.resolve(), cfg.input_dir.resolve()
    if root == src or root in src.parents or src in root.parents:
        raise ValueError('Input and run directories must be separate and not nested')
    # Validate before allocating the run directory.
    source_files(src)
    root.mkdir(parents=True, exist_ok=False)
    store = Store(root)
    try:
        prepare(src, root / 'input')
        manifest = hashes(root / 'input')
        config = asdict(cfg)
        config.update(input_dir=str(src), output_dir=str(root))
        state = {'schema_version': 1, 'run_id': str(uuid.uuid4()),
                 'project_id': hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest(),
                 'config': config, 'phase': 'baseline', 'step': 0, 'history': [],
                 'handoff': {}, 'baseline': None, 'outbox': [], 'error': None,
                 'file_hashes': manifest, 'input_hashes': manifest}
        store.commit(state, root / 'input')
    except BaseException:
        # Keep incomplete initialization for diagnosis; never silently overwrite it.
        raise
    return store


def parse_model_json(message: str) -> dict:
    text = message.strip()
    if text.startswith('```') and text.endswith('```'):
        text = '\n'.join(text.splitlines()[1:-1])
    data = json.loads(text)
    if not isinstance(data, dict) or not isinstance(data.get('files'), list):
        raise ValueError('Expected an object with files array')
    if data.get('status') not in {'continue', 'done'} or not isinstance(data.get('summary'), str):
        raise ValueError('Expected summary string and status continue/done')
    handoff = data.get('handoff')
    if not isinstance(handoff, dict):
        raise ValueError('Expected explicit handoff object')
    for key in ('plan', 'completed', 'decisions', 'next_actions'):
        if not isinstance(handoff.get(key), list) or any(not isinstance(x, str) for x in handoff[key]):
            raise ValueError(f'handoff.{key} must be a string array')
    return data


def make_prompt(state: dict, files: dict, memory: dict) -> str:
    schema = {'summary': 'short change description', 'status': 'continue or done',
              'handoff': {'plan': ['overall plan'], 'completed': ['completed work'],
                          'decisions': ['public design decisions and constraints'],
                          'next_actions': ['concrete next steps for a new worker']},
              'files': [{'path': 'existing/module.py', 'content': 'entire replacement source'}]}
    return '\n\n'.join([
        'Refactor this Python project autonomously in small coherent steps. Preserve public behavior. '
        'Only edit existing application .py files. Tests and configuration are immutable. '
        'No new dependencies. Return ONLY JSON matching the schema. '
        'You may change multiple files. Set done only when the entire goal is achieved; '
        'passing tests alone is not completion. Empty files is allowed when finished. '
        'Provide a concise explicit work handoff, not private internal reasoning. '
        'Recover from previous validation or response errors.',
        'RESPONSE SCHEMA: ' + json.dumps(schema),
        'GOAL: ' + state['config']['goal'],
        'ROUND: ' + str(state['step'] + 1),
        'PUBLIC HANDOFF: ' + json.dumps(state['handoff'], ensure_ascii=False),
        'HISTORY AND VERIFICATION: ' + json.dumps(state['history'], ensure_ascii=False),
        'OPTIONAL DATABASE MEMORY: ' + json.dumps(memory, ensure_ascii=False),
        'PROJECT FILES: ' + json.dumps(files, ensure_ascii=False)])


def queue_event(state: dict, kind: str, payload: dict) -> None:
    event_step = state['step'] + 1 if kind == 'step_started' else state['step']
    state['outbox'].append(asdict(ContextEvent(
        state['project_id'], state['run_id'], event_step, kind, payload, str(uuid.uuid4()))))


def save(store: Store, state: dict, project: Path | None = None) -> dict:
    return store.commit(state, project or store.project(state))


def finish_step(store: Store, state: dict, entry: dict) -> dict:
    state['step'] += 1
    entry['step'] = state['step']
    state['history'].append(entry)
    state['phase'] = 'completed' if entry.get('tests_passed') and entry.get('status') == 'done' else 'generate'
    if state['phase'] != 'completed' and state['step'] >= state['config']['max_steps']:
        state['phase'] = 'exhausted'
    queue_event(state, 'step_completed', dict(entry, handoff=state['handoff'], file_hashes=state['file_hashes']))
    state.pop('request', None)
    state.pop('proposal', None)
    return save(store, state)


def run(store: Store, llm: LLM, context: ContextPort, stop_after: int | None = None) -> dict:
    if stop_after is not None and stop_after < 1:
        raise ValueError('stop_after must be positive')
    with store.lock():
        state = store.load()
        if hashes(store.project(state)) != state['file_hashes']:
            raise ValueError('Checkpoint code changed on disk; do not edit immutable checkpoints')
        initial_step = state['step']
        state['error'] = None
        try:
            while True:
                # Durable outbox: write is retryable; adapters deduplicate event_id.
                if state['outbox']:
                    context.write(ContextEvent(**state['outbox'][0]))
                    state['outbox'] = state['outbox'][1:]
                    state = save(store, state)
                    continue
                if state['phase'] in TERMINAL:
                    return state
                pause = store.root / 'PAUSE'
                if pause.exists() or (stop_after is not None and state['step'] - initial_step >= stop_after):
                    pause.unlink(missing_ok=True)
                    state['paused'] = True
                    return save(store, state)
                state['paused'] = False
                phase = state['phase']
                if phase == 'baseline':
                    result = validate(store.project(state), state['config']['commands'],
                                      state['config']['timeout'], store.root / 'work')
                    state['baseline'] = result
                    state['phase'] = 'generate' if result['passed'] else 'baseline_failed'
                    queue_event(state, 'baseline_completed', result)
                    state = save(store, state)
                elif phase == 'generate':
                    files = source_files(store.project(state))
                    snapshot = context.read(ContextRequest(
                        state['project_id'], state['run_id'], state['step'] + 1,
                        state['config']['goal'], files, state['checkpoint_id'],
                        state['history'], state['handoff'], requested_state_ref=state['config'].get('memory_ref')))
                    memory = asdict(snapshot)
                    state['request'] = {'id': uuid.uuid4().hex, 'memory': memory,
                                        'prompt': make_prompt(state, files, memory)}
                    state['phase'] = 'request'
                    queue_event(state, 'step_started', {'step': state['step'] + 1, 'state_ref': snapshot.state_ref})
                    state = save(store, state)
                elif phase == 'request':
                    responses = store.root / 'responses'
                    responses.mkdir(exist_ok=True)
                    path = responses / (state['request']['id'] + '.json')
                    if not path.exists():
                        response = llm.generate(state['request']['prompt'], source_files(store.project(state)))
                        atomic_json(path, {'text': response})
                    state['phase'] = 'apply'
                    state = save(store, state)
                elif phase == 'apply':
                    path = store.root / 'responses' / (state['request']['id'] + '.json')
                    response = json.loads(path.read_text(encoding='utf-8'))['text']
                    work = store.root / 'work'
                    work.mkdir(exist_ok=True)
                    try:
                        proposal = parse_model_json(response)
                        with tempfile.TemporaryDirectory(dir=work) as tmp:
                            candidate = Path(tmp) / 'project'
                            shutil.copytree(store.project(state), candidate)
                            changed = apply_changes(candidate, proposal['files'])
                            state['proposal'] = dict(proposal, changed_files=changed)
                            state['handoff'] = proposal['handoff']
                            state['file_hashes'] = hashes(candidate)
                            state['phase'] = 'verify'
                            state = save(store, state, candidate)
                    except (ValueError, SyntaxError) as exc:
                        state = finish_step(store, state, {'error': str(exc), 'tests_passed': False,
                                                          'request_id': state['request']['id'],
                                                          'changed_files': [], 'status': 'continue'})
                elif phase == 'verify':
                    result = validate(store.project(state), state['config']['commands'],
                                      state['config']['timeout'], store.root / 'work')
                    proposal = state['proposal']
                    state = finish_step(store, state, {
                        'summary': proposal['summary'], 'status': proposal['status'],
                        'changed_files': proposal['changed_files'], 'tests_passed': result['passed'],
                        'verification': result, 'request_id': state['request']['id']})
                else:
                    raise ValueError(f'Unknown phase: {phase}')
        except BaseException as exc:
            # HEAD is the authoritative checkpoint; never persist half-mutated local state.
            state = store.load()
            state['error'] = {'type': type(exc).__name__, 'message': str(exc)}
            state['paused'] = isinstance(exc, KeyboardInterrupt)
            save(store, state)
            raise


def fork_run(source: Store, target: Path, adapter: str = 'none', memory_ref: str | None = None) -> Store:
    with source.lock():
        state = source.load()
        if state['phase'] != 'generate' or state['outbox']:
            raise ValueError('Fork a paused run between rounds (use --stop-after 1)')
        if hashes(source.project(state)) != state['file_hashes']:
            raise ValueError('Checkpoint was modified')
        target = target.resolve()
        if target == source.root or source.root in target.parents or target in source.root.parents:
            raise ValueError('Fork directory must be separate from source run')
        target.mkdir(parents=True, exist_ok=False)
        shutil.copytree(source.root / 'input', target / 'input')
        old_checkpoint = state['checkpoint_id']
        project = source.project(state)
        state['forked_from'] = {'run_id': state['run_id'], 'checkpoint_id': old_checkpoint}
        state['run_id'] = str(uuid.uuid4())
        state['config'] = dict(state['config'], context_adapter=adapter, output_dir=str(target), memory_ref=memory_ref)
        state['error'] = None
        state['paused'] = True
        dest = Store(target)
        dest.commit(state, project)
        return dest


def export_run(store: Store, output: Path) -> dict:
    with store.lock():
        state = store.load()
        if state['phase'] != 'completed':
            raise ValueError('Only a completed, verified run can be exported')
        if hashes(store.project(state)) != state['file_hashes']:
            raise ValueError('Checkpoint was modified')
        output = output.resolve()
        if output == store.root or store.root in output.parents or output in store.root.parents:
            raise ValueError('Export outside the run directory')
        shutil.copytree(store.project(state), output)
        atomic_json(output / 'ghostgraph_run.json', state)
        return state
