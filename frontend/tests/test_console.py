import json
from pathlib import Path
import threading
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from frontend.server import make_server


def test_http_console_real_worker_pause_resume_and_auth(tmp_path):
    project = tmp_path / 'ghostgraph/input'
    project.mkdir(parents=True)
    (project / 'app.py').write_text('def answer():\n    return 42\n')
    (project / 'test_app.py').write_text('from app import answer\ndef test_answer():\n    assert answer() == 42\n')
    (project / 'checks.json').write_text(json.dumps([['{python}', '-m', 'pytest', '-q']]))
    server = make_server(tmp_path, 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f'http://127.0.0.1:{server.server_port}'

    def api(path, body=None):
        req = Request(base + path, data=json.dumps(body).encode() if body else None,
                      headers={'X-Console-Token': server.console.token, 'Content-Type': 'application/json'})
        with urlopen(req, timeout=10) as response:
            return json.load(response)

    def wait(name):
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            state = api('/api/run/' + name)
            if not state['running']:
                return state
            time.sleep(.1)
        pytest.fail('worker did not stop')

    try:
        demo = api('/api/demo')
        assert all(f['after'] == '' for f in demo['files'])
        with urlopen(base) as response:
            assert b'__CONSOLE_TOKEN__' not in response.read()
        with pytest.raises(HTTPError) as error:
            urlopen(base + '/api/runs')
        assert error.value.code == 403
        with pytest.raises(HTTPError) as error:
            urlopen(Request(base, headers={'Host': 'attacker.example'}))
        assert error.value.code == 403
        try:
            name = api('/api/action', {'action': 'start', 'provider': 'mock', 'stop_after': True})['id']
        except HTTPError as exc:
            pytest.fail(exc.read().decode())
        state = wait(name)
        assert state['phase'] == 'generate' and state['paused']
        assert state['baseline']['passed'] and state['history'][0]['tests_passed']
        assert any(f['diff'] for f in state['files'])
        branch = api('/api/action', {'action': 'fork', 'id': name})['id']
        for identifier in (name, branch):
            api('/api/action', {'action': 'resume', 'id': identifier})
            assert wait(identifier)['phase'] == 'completed'
        comparison = api('/api/action', {'action': 'compare', 'id': name, 'other': branch})
        assert not comparison['different_files']
        exported = api('/api/action', {'action': 'export', 'id': name})['output']
        assert (Path(exported) / 'app.py').exists()
        assert Path(exported).parent == tmp_path / 'ghostgraph/output'
        assert (tmp_path / 'ghostgraph/output/latest.json').exists()
        assert (project / 'app.py').read_text() == 'def answer():\n    return 42\n'
        assert any(f['after'] != f['before'] for f in api('/api/demo')['files'])
        with pytest.raises(HTTPError):
            api('/api/action', {'action': 'resume', 'id': '../escape'})
    finally:
        server.console.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
