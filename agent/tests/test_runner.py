import json
from pathlib import Path
import subprocess
import sys
import time

import pytest

from agent.cli import compare
from memory.context import NullContext, ContextSnapshot
from agent.engine import RunConfig, create_run, export_run, fork_run, run
from agent.providers import MockLLM
from agent.storage import Store
from agent.validation import validate
from agent.workspace import apply_changes, hashes


@pytest.fixture
def project(tmp_path):
    src = tmp_path / 'legacy'
    src.mkdir()
    (src / 'app.py').write_text('def answer():\n    x = 40\n    x += 2\n    return x\n', encoding='utf-8')
    (src / 'test_contract.py').write_text('from app import answer\ndef test_answer():\n    assert answer() == 42\n', encoding='utf-8')
    return src


def new_run(project, tmp_path, **kwargs):
    return create_run(RunConfig(project, tmp_path / 'run', provider='mock', **kwargs))


def response(code=None, status='done'):
    return json.dumps({'summary': 'Simplify answer', 'status': status,
                       'handoff': {'plan': ['Simplify arithmetic'], 'completed': ['Simplified answer'],
                                   'decisions': ['Keep answer API'], 'next_actions': []},
                       'files': [] if code is None else [{'path': 'app.py', 'content': code}]})


class Scripted:
    def __init__(self, *responses):
        self.responses = iter(responses)
        self.prompts = []

    def generate(self, prompt, files):
        self.prompts.append(prompt)
        item = next(self.responses)
        if isinstance(item, BaseException):
            raise item
        return item


def test_real_edits_fail_repair_and_export(project, tmp_path):
    before = hashes(project)
    store = new_run(project, tmp_path)
    model = Scripted(response('def answer():\n    return 0\n'), response('def answer():\n    return 42\n'))
    state = run(store, model, NullContext())
    assert state['phase'] == 'completed'
    assert state['baseline']['passed']
    assert [x['tests_passed'] for x in state['history']] == [False, True]
    assert 'assert 0 == 42' in model.prompts[1]
    assert hashes(project) == before
    export_run(store, tmp_path / 'modernized')
    assert 'return 42' in (tmp_path / 'modernized/app.py').read_text()
    assert (tmp_path / 'modernized/ghostgraph_run.json').exists()


def test_pause_new_worker_and_forks(project, tmp_path):
    store = new_run(project, tmp_path)
    state = run(store, MockLLM(), NullContext(), stop_after=1)
    assert state['phase'] == 'generate' and state['paused'] and state['step'] == 1
    a = fork_run(store, tmp_path / 'a')
    b = fork_run(store, tmp_path / 'b', 'future_db:create_port')
    assert hashes(a.project(a.load())) == hashes(b.project(b.load()))
    run(Store(a.root), MockLLM(), NullContext())
    run(Store(b.root), MockLLM(), NullContext())
    result = compare(a, b)
    assert result['same_fork_checkpoint'] and result['same_settings_except_memory']
    assert not result['different_files']
    assert store.load()['step'] == 1


def test_baseline_failure_never_calls_model(project, tmp_path):
    (project / 'app.py').write_text('def answer():\n    return 0\n')
    store = new_run(project, tmp_path)
    model = Scripted()
    assert run(store, model, NullContext())['phase'] == 'baseline_failed'
    assert not model.prompts


def test_passing_tests_is_not_completion(project, tmp_path):
    store = new_run(project, tmp_path, max_steps=1)
    state = run(store, MockLLM(), NullContext())
    assert state['history'][0]['tests_passed'] and state['phase'] == 'exhausted'
    with pytest.raises(ValueError):
        export_run(store, tmp_path / 'bad_export')


@pytest.mark.parametrize('path', ['tests/helpers.py', 'pkg/tests/helpers.py', 'pkg/testing/util.py',
                                  'foo_test.py', 'test_ok.py', 'conftest.py', '../escape.py'])
def test_protected_edits_are_atomic(tmp_path, path):
    (tmp_path / 'app.py').write_text('x=1')
    if '..' not in path:
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('x=1')
    with pytest.raises(ValueError):
        apply_changes(tmp_path, [{'path': 'app.py', 'content': 'x=2'}, {'path': path, 'content': 'x=2'}])
    assert (tmp_path / 'app.py').read_text() == 'x=1'


def test_bad_json_and_invalid_python_feed_back(project, tmp_path):
    store = new_run(project, tmp_path)
    model = Scripted('invalid JSON', response('def broken('), response('def answer():\n    return 42\n'))
    state = run(store, model, NullContext())
    assert state['phase'] == 'completed' and state['step'] == 3
    assert 'Invalid Python' in model.prompts[-1]
    assert state['history'][0]['changed_files'] == []


def test_interrupt_and_api_error_preserve_request(project, tmp_path):
    store = new_run(project, tmp_path)
    with pytest.raises(KeyboardInterrupt):
        run(store, Scripted(KeyboardInterrupt()), NullContext())
    state = store.load()
    assert state['phase'] == 'request' and state['paused']
    original = state['request']['prompt']
    with pytest.raises(RuntimeError):
        run(store, Scripted(RuntimeError('offline')), NullContext())
    assert store.load()['request']['prompt'] == original
    assert run(store, Scripted(response()), NullContext())['phase'] == 'completed'


def test_saved_response_reused_after_commit_failure(project, tmp_path, monkeypatch):
    store = new_run(project, tmp_path)
    original = store.commit
    failed = False

    def crash(state, project):
        nonlocal failed
        if state['phase'] == 'apply' and not failed:
            failed = True
            raise OSError('simulated crash before HEAD replacement')
        return original(state, project)

    monkeypatch.setattr(store, 'commit', crash)
    with pytest.raises(OSError):
        run(store, Scripted(response()), NullContext())
    assert store.load()['phase'] == 'request'
    assert run(store, Scripted(), NullContext())['phase'] == 'completed'


def test_adapter_outbox_retry_and_memory(project, tmp_path):
    store = new_run(project, tmp_path)

    class Memory:
        def __init__(self):
            self.events, self.failed, self.requests = [], False, []

        def read(self, request):
            self.requests.append(request)
            return ContextSnapshot('Maintain public answer API', {'decision': 'constant'}, 'v1')

        def write(self, event):
            self.events.append(event)
            if not self.failed:
                self.failed = True
                raise RuntimeError('database temporarily offline')

    port = Memory()
    with pytest.raises(RuntimeError):
        run(store, Scripted(), port)
    model = Scripted(response())
    assert run(store, model, port)['phase'] == 'completed'
    assert port.events[0].event_id == port.events[1].event_id
    assert 'Maintain public answer API' in model.prompts[0]
    assert port.requests[0].files['app.py']
    assert not store.load()['outbox']


def test_verification_is_disposable_and_timeout(project, tmp_path):
    original = hashes(project)
    result = validate(project, [['{python}', '-c', "open('app.py','w').write('bad')"]], 5, tmp_path / 'work')
    assert result['passed'] and hashes(project) == original
    result = validate(project, [['{python}', '-c', 'import time; time.sleep(30)']], .1, tmp_path / 'work')
    assert not result['passed'] and result['commands'][0]['timed_out']


def test_os_lock_released_after_forced_process_kill(project, tmp_path):
    store = new_run(project, tmp_path)
    ready = tmp_path / 'ready'
    script = '''
import sys, time
from pathlib import Path
from agent.engine import run
from agent.storage import Store
from memory.context import NullContext
class Blocking:
    def generate(self, prompt, files):
        Path(sys.argv[2]).write_text('ready')
        time.sleep(120)
run(Store(Path(sys.argv[1])), Blocking(), NullContext())
'''
    proc = subprocess.Popen([sys.executable, '-c', script, str(store.root), str(ready)])
    try:
        deadline = time.monotonic() + 20
        while not ready.exists() and time.monotonic() < deadline and proc.poll() is None:
            time.sleep(.05)
        assert ready.exists(), 'worker did not reach model call'
        with pytest.raises(RuntimeError, match='Another worker'):
            with store.lock():
                pass
        proc.kill()
        proc.wait(timeout=5)
        assert store.load()['phase'] == 'request'
        assert run(store, Scripted(response()), NullContext())['phase'] == 'completed'
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()


def test_cli_exit_codes_and_extra_steps(project, tmp_path):
    root = tmp_path / 'cli-run'
    proc = subprocess.run([sys.executable, '-m', 'agent', 'start', '--input', str(project),
                           '--run-dir', str(root), '--provider', 'mock', '--max-steps', '1'], capture_output=True, text=True)
    assert proc.returncode == 1, proc.stderr
    proc = subprocess.run([sys.executable, '-m', 'agent', 'resume', '--run-dir', str(root),
                           '--extra-steps', '1'], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)['phase'] == 'completed'


def test_pause_request_and_modified_checkpoint(project, tmp_path):
    store = new_run(project, tmp_path)
    (store.root / 'PAUSE').touch()
    assert run(store, Scripted(), NullContext())['paused']
    state = store.load()
    (store.project(state) / 'app.py').write_text('tampered=True')
    with pytest.raises(ValueError, match='changed on disk'):
        run(store, MockLLM(), NullContext())


def test_atomic_head_failure_keeps_previous_code(project, tmp_path, monkeypatch):
    import agent.storage as storage
    store = new_run(project, tmp_path)
    original = storage.atomic_json
    failed = False

    def interrupt_head(path, value):
        nonlocal failed
        if path.name == 'HEAD.json' and not failed:
            pending = json.loads((store.root / 'checkpoints' / value['checkpoint_id'] / 'state.json').read_text())
            if pending['phase'] == 'verify':
                failed = True
                raise OSError('crash before candidate HEAD switch')
        return original(path, value)

    monkeypatch.setattr(storage, 'atomic_json', interrupt_head)
    with pytest.raises(OSError):
        run(store, Scripted(response('def answer():\n    return 42\n')), NullContext())
    state = store.load()
    assert state['phase'] == 'apply'
    assert hashes(store.project(state)) == state['input_hashes']
    assert run(store, Scripted(), NullContext())['phase'] == 'completed'


def test_memory_reference_is_forwarded(project, tmp_path):
    store = new_run(project, tmp_path, memory_ref='frozen-v7')

    class Frozen(NullContext):
        def read(self, request):
            assert request.requested_state_ref == 'frozen-v7'
            return ContextSnapshot(state_ref='frozen-v7')

    assert run(store, Scripted(response()), Frozen())['phase'] == 'completed'


def test_atomic_json_retries_windows_reader_lock(tmp_path, monkeypatch):
    import os
    import agent.storage as storage
    if os.name != 'nt':
        pytest.skip('Windows sharing violation behavior')
    original = storage.os.replace
    calls = []
    def temporarily_locked(source, target):
        calls.append(target)
        if len(calls) < 3:
            error = PermissionError('reader holds HEAD briefly')
            error.winerror = 32
            raise error
        return original(source, target)
    monkeypatch.setattr(storage.os, 'replace', temporarily_locked)
    path = tmp_path / 'HEAD.json'
    storage.atomic_json(path, {'checkpoint_id': 'new'})
    assert json.loads(path.read_text()) == {'checkpoint_id': 'new'}
    assert len(calls) == 3