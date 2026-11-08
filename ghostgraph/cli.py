"""Commands for execution, recovery and controlled continuation experiments."""
from __future__ import annotations
import argparse
import difflib
import importlib
import json
import os
from pathlib import Path
import sys

from .context import NullContext
from .engine import RunConfig, create_run, export_run, fork_run, run, save
from .providers import MockLLM, NvidiaLLM
from .storage import Store
from .validation import validate
from .workspace import hashes


def get_context_adapter(spec: str):
    if spec == 'none':
        return NullContext()
    module, factory = spec.split(':', 1)
    port = getattr(importlib.import_module(module), factory)()
    if not callable(getattr(port, 'read', None)) or not callable(getattr(port, 'write', None)):
        raise TypeError('Context adapter must implement read and write')
    return port


def describe(store: Store) -> dict:
    state = store.load()
    return {k: state.get(k) for k in ('run_id', 'checkpoint_id', 'phase', 'paused', 'step',
                                     'baseline', 'handoff', 'error', 'forked_from')} | {
        'project': str(store.project(state)), 'history': state['history']}


def execute(store: Store, stop_after: int | None) -> dict:
    cfg = store.load()['config']
    port = get_context_adapter(cfg['context_adapter'])
    llm = MockLLM() if cfg['provider'] == 'mock' else NvidiaLLM(
        cfg['model'], base_url=cfg['base_url'], temperature=cfg['temperature'], max_tokens=cfg['max_tokens'])
    return run(store, llm, port, stop_after)


def compare(left: Store, right: Store) -> dict:
    a, b = left.load(), right.load()
    ah, bh = hashes(left.project(a)), hashes(right.project(b))
    paths = sorted(set(ah) | set(bh))
    similarities = {}
    for p in paths:
        if p.endswith('.py') and p in ah and p in bh:
            x = (left.project(a) / p).read_text(encoding='utf-8')
            y = (right.project(b) / p).read_text(encoding='utf-8')
            similarities[p] = round(difflib.SequenceMatcher(None, x, y, autojunk=False).ratio(), 4)
    settings = ('goal', 'model', 'provider', 'base_url', 'temperature', 'max_tokens', 'max_steps', 'commands', 'timeout')
    parent = a.get('forked_from')
    return {'same_fork_checkpoint': bool(parent) and parent == b.get('forked_from'),
            'same_input': a['input_hashes'] == b['input_hashes'],
            'same_settings_except_memory': all(a['config'][k] == b['config'][k] for k in settings),
            'left': {'phase': a['phase'], 'steps': a['step'], 'handoff': a['handoff'],
                     'verification': a['history'][-1] if a['history'] else a['baseline']},
            'right': {'phase': b['phase'], 'steps': b['step'], 'handoff': b['handoff'],
                      'verification': b['history'][-1] if b['history'] else b['baseline']},
            'different_files': [p for p in paths if ah.get(p) != bh.get(p)],
            'text_similarity_only': similarities,
            'note': 'Text similarity is not semantic equivalence or evidence of identical internal reasoning.'}


def main() -> None:
    parser = argparse.ArgumentParser(description='Continuum / GhostGraph resumable modernization lab')
    sub = parser.add_subparsers(dest='command', required=True)
    start = sub.add_parser('start', help='Snapshot input, verify baseline and start a new run')
    start.add_argument('--input', type=Path, required=True)
    start.add_argument('--run-dir', type=Path, required=True)
    start.add_argument('--goal', default=RunConfig.goal)
    start.add_argument('--provider', choices=['mock', 'nvidia'], default='nvidia')
    start.add_argument('--model', default=os.getenv('GHOSTGRAPH_MODEL', RunConfig.model))
    start.add_argument('--base-url', default=os.getenv('GHOSTGRAPH_BASE_URL', RunConfig.base_url))
    start.add_argument('--max-steps', type=int, default=8)
    start.add_argument('--stop-after', type=int)
    start.add_argument('--checks-file', type=Path, help='JSON array of argv arrays; {python} uses current interpreter')
    start.add_argument('--timeout', type=float, default=90)
    start.add_argument('--temperature', type=float, default=0.2)
    start.add_argument('--max-tokens', type=int, default=16000)
    start.add_argument('--context-adapter', default='none')
    start.add_argument('--memory-ref', help='Optional frozen database snapshot/version for experiments')
    for name in ('resume', 'pause', 'status', 'export', 'fork', 'verify'):
        cmd = sub.add_parser(name)
        cmd.add_argument('--run-dir', type=Path, required=True)
        if name == 'resume':
            cmd.add_argument('--stop-after', type=int)
            cmd.add_argument('--extra-steps', type=int, default=0)
        if name in {'export', 'fork'}:
            cmd.add_argument('--output', type=Path, required=True)
        if name == 'fork':
            cmd.add_argument('--context-adapter', default='none')
            cmd.add_argument('--memory-ref')
    comparison = sub.add_parser('compare')
    comparison.add_argument('--left', type=Path, required=True)
    comparison.add_argument('--right', type=Path, required=True)
    args = parser.parse_args()
    code = 0
    try:
        if args.command == 'compare':
            result = compare(Store(args.left), Store(args.right))
        else:
            store = Store(args.run_dir)
            if args.command == 'start':
                commands = json.loads(args.checks_file.read_text(encoding='utf-8-sig')) if args.checks_file else [['{python}', '-m', 'pytest', '-q']]
                store = create_run(RunConfig(args.input, args.run_dir, args.goal, args.model,
                    args.max_steps, commands, args.timeout, args.provider, args.context_adapter,
                    args.base_url, args.temperature, args.max_tokens, args.memory_ref))
                state = execute(store, args.stop_after)
                result = describe(store)
                code = 1 if state['phase'] in {'exhausted', 'baseline_failed'} else 0
            elif args.command == 'resume':
                if args.extra_steps < 0:
                    raise ValueError('extra-steps must not be negative')
                with store.lock():
                    state = store.load()
                    if args.extra_steps:
                        state['config']['max_steps'] += args.extra_steps
                        if state['phase'] == 'exhausted':
                            state['phase'] = 'generate'
                        save(store, state)
                    (store.root / 'PAUSE').unlink(missing_ok=True)
                state = execute(store, args.stop_after)
                result = describe(store)
                code = 1 if state['phase'] in {'exhausted', 'baseline_failed'} else 0
            elif args.command == 'pause':
                store.load()
                (store.root / 'PAUSE').touch()
                result = {'pause_requested': True, 'note': 'Stops at next durable boundary; Ctrl+C interrupts an active call.'}
            elif args.command == 'status':
                result = describe(store)
            elif args.command == 'export':
                export_run(store, args.output)
                result = {'output': str(args.output.resolve()), 'verified': True}
            elif args.command == 'fork':
                result = describe(fork_run(store, args.output, args.context_adapter, args.memory_ref))
            elif args.command == 'verify':
                with store.lock():
                    state = store.load()
                    if hashes(store.project(state)) != state['file_hashes']:
                        raise ValueError('Checkpoint was modified')
                    result = validate(store.project(state), state['config']['commands'], state['config']['timeout'], store.root / 'work')
                    code = 0 if result['passed'] else 1
        print(json.dumps(result, indent=2, ensure_ascii=False))
    except KeyboardInterrupt:
        print('Paused. Resume with the same --run-dir.', file=sys.stderr)
        code = 130
    except Exception as exc:
        print(f'GhostGraph error: {exc}', file=sys.stderr)
        code = 2
    raise SystemExit(code)
