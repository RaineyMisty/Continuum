"""Loopback-only console for the real checkpoint runner. No extra dependencies."""
from __future__ import annotations
import argparse
import difflib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
import time
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import threading
from urllib.parse import urlsplit
import uuid
import webbrowser

from .assets import ensure_monaco
from agent.cli import compare
from agent.engine import RunConfig, create_run, export_run, fork_run
from agent.storage import Store, atomic_json
from agent.workspace import source_files


class Console:
    def __init__(self, repo: Path):
        self.repo = repo.resolve()
        self.runs = self.repo / '.artifacts/runs'
        self.logs = self.repo / '.artifacts/console'
        self.runs.mkdir(parents=True, exist_ok=True)
        self.logs.mkdir(parents=True, exist_ok=True)
        self.workers: dict[str, subprocess.Popen] = {}
        self.mutex = threading.RLock()
        self.token = secrets.token_urlsafe(32)
        config = self.repo / 'frontend/demo.json'
        self.config = json.loads(config.read_text(encoding='utf-8')) if config.exists() else {}

    def store(self, name):
        if not isinstance(name, str) or not re.fullmatch(r'ui-[a-f0-9]{12}', name):
            raise ValueError('Invalid console run ID')
        store = Store(self.runs / name)
        if not (store.root / 'HEAD.json').exists():
            raise ValueError('Run not found')
        return store

    def active(self, name):
        return name in self.workers and self.workers[name].poll() is None

    def launch(self, name, stop_after=False, extra_steps=0):
        if self.active(name):
            raise ValueError('Worker is already running')
        checkpoint = self.store(name).load()['checkpoint_id']
        args = [sys.executable, '-m', 'agent', 'resume', '--run-dir', str(self.store(name).root)]
        if stop_after:
            args += ['--stop-after', '1']
        if extra_steps:
            args += ['--extra-steps', str(extra_steps)]
        with (self.logs / (name + '.log')).open('ab') as log:
            self.workers[name] = subprocess.Popen(args, cwd=self.repo, stdout=log, stderr=log,
                env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONUNBUFFERED='1'),
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        path = self.logs / (name + '.workers.json')
        workers = json.loads(path.read_text()) if path.exists() else []
        workers.append({'pid': self.workers[name].pid, 'started': time.time(), 'checkpoint': checkpoint})
        path.write_text(json.dumps(workers), encoding='utf-8')
        threading.Thread(target=self.finish, args=(name, self.workers[name]), daemon=True).start()

    def export_completed(self, name):
        store = self.store(name)
        state = store.load()
        output = self.repo / 'ghostgraph/output'
        output.mkdir(parents=True, exist_ok=True)
        dest = output / name
        if not dest.exists():
            export_run(store, dest)
        atomic_json(output / 'latest.json', {'run': name, 'provider': state['config']['provider']})
        return dest

    def finish(self, name, process):
        process.wait()
        with self.mutex:
            state = self.store(name).load()
            if process.returncode == 0 and state['phase'] == 'completed':
                try:
                    self.export_completed(name)
                except Exception as exc:
                    atomic_json(self.logs / (name + '.export-error.json'), {'message': str(exc)})

    def stop(self, name):
        if not self.active(name):
            raise ValueError('No running worker to interrupt')
        proc = self.workers[name]
        if os.name == 'nt':
            subprocess.run(['taskkill', '/PID', str(proc.pid), '/T', '/F'], capture_output=True)
        if proc.poll() is None:
            proc.kill()
        proc.wait(timeout=10)

    def close(self):
        for name in list(self.workers):
            if self.active(name):
                self.stop(name)

    def view(self, name, detail=False):
        store = self.store(name)
        state = store.load()
        worker = self.workers.get(name)
        result = {k: state.get(k) for k in ('phase', 'step', 'paused', 'error', 'handoff', 'baseline', 'history', 'forked_from', 'checkpoint_id')}
        worker_file = self.logs / (name + '.workers.json')
        result['workers'] = json.loads(worker_file.read_text()) if worker_file.exists() else []
        result.update(id=name, running=self.active(name), pid=worker.pid if worker else None,
                      exit_code=worker.poll() if worker else None,
                      provider=state['config']['provider'], model=state['config']['model'],
                      adapter=state['config']['context_adapter'], goal=state['config']['goal'],
                      max_steps=state['config']['max_steps'])
        if detail:
            before = source_files(store.root / 'input')
            if state['phase'] == 'completed' and not self.active(name):
                after = source_files(self.export_completed(name))
            else:
                after = source_files(store.project(state))
            result['files'] = [{'path': p, 'before': before.get(p, ''), 'after': after.get(p, ''),
                'diff': ''.join(difflib.unified_diff(before.get(p, '').splitlines(True), after.get(p, '').splitlines(True),
                                                    fromfile='original/' + p, tofile='current/' + p))}
                for p in sorted(before.keys() | after.keys()) if p.endswith('.py')]
            log = self.logs / (name + '.log')
            if log.exists():
                with log.open('rb') as handle:
                    handle.seek(max(0, log.stat().st_size - 16000))
                    result['log'] = handle.read().decode('utf-8', errors='replace')
            else:
                result['log'] = ''
        return result

    def action(self, data):
        with self.mutex:
            action = data.get('action')
            if action == 'start':
                provider = data.get('provider', 'mock')
                if provider not in {'mock', 'nvidia'}:
                    raise ValueError('Unknown provider')
                if provider == 'nvidia' and not (os.getenv('NVIDIA_API_KEY') or os.getenv('GHOSTGRAPH_API_KEY')):
                    raise ValueError('请先在启动服务的终端设置 NVIDIA_API_KEY 或 GHOSTGRAPH_API_KEY，再重新启动控制台。')
                name = 'ui-' + uuid.uuid4().hex[:12]
                src = Path(data.get('input') or 'ghostgraph/input')
                src = src if src.is_absolute() else self.repo / src
                default_demo = src.resolve() == (self.repo / 'ghostgraph/input').resolve()
                commands = json.loads((src / 'checks.json').read_text()) if default_demo else [['{python}', '-m', 'pytest', '-q']]
                steps = int(data.get('max_steps', 8))
                if not 1 <= steps <= 30:
                    raise ValueError('轮数需在 1–30 之间')
                cfg = RunConfig(src, self.runs / name, goal=data.get('goal') or RunConfig.goal,
                                provider=provider, model=data.get('model') or os.getenv('GHOSTGRAPH_MODEL', RunConfig.model),
                                base_url=os.getenv('GHOSTGRAPH_BASE_URL', RunConfig.base_url),
                                commands=commands, max_steps=steps, context_adapter=data.get('adapter') or 'none')
                create_run(cfg)
                self.launch(name, data.get('stop_after', True))
                return {'id': name}
            name = data.get('id')
            store = self.store(name)
            if action == 'pause':
                if not self.active(name):
                    raise ValueError('Worker is not running')
                (store.root / 'PAUSE').touch()
            elif action == 'kill':
                self.stop(name)
            elif action == 'resume':
                self.launch(name, data.get('stop_after', False), 4 if store.load()['phase'] == 'exhausted' else 0)
            elif action == 'fork':
                if self.active(name):
                    raise ValueError('请先暂停，再从固定检查点分叉')
                target = 'ui-' + uuid.uuid4().hex[:12]
                fork_run(store, self.runs / target, data.get('adapter') or 'none', data.get('memory_ref') or None)
                return {'id': target}
            elif action == 'compare':
                other = self.store(data.get('other'))
                if self.active(name) or self.active(data.get('other')):
                    raise ValueError('请在两个 worker 都停止后比较')
                return compare(store, other)
            elif action == 'export':
                if self.active(name):
                    raise ValueError('请等待 worker 完成')
                dest = self.export_completed(name)
                return {'output': str(dest)}
            else:
                raise ValueError('Unknown action')
            return {'id': name}


def make_server(repo: Path, port=8765):
    console = Console(repo)
    assets = Path(__file__).parent

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def send(self, status, body, mime='application/json; charset=utf-8'):
            if not isinstance(body, bytes):
                body = json.dumps(body, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header('Content-Type', mime)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy', "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-eval'; worker-src 'self' blob:; font-src 'self' data:; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(body)

        def authorized(self, api=False):
            if self.headers.get('Host') != f'127.0.0.1:{self.server.server_port}':
                self.send(403, {'error': 'Use the printed loopback URL'})
                return False
            if api and not secrets.compare_digest(self.headers.get('X-Console-Token', ''), console.token):
                self.send(403, {'error': 'Invalid console session'})
                return False
            return True

        def do_GET(self):
            path = urlsplit(self.path).path
            if not self.authorized(path.startswith('/api/')):
                return
            try:
                if path == '/api/demo':
                    src = Path(console.config.get('input', 'ghostgraph/input'))
                    src = src if src.is_absolute() else console.repo / src
                    files = source_files(src)
                    after = {}
                    latest = console.repo / 'ghostgraph/output/latest.json'
                    if latest.exists():
                        name = json.loads(latest.read_text())['run']
                        console.store(name)  # Validate the locally managed run ID.
                        after = source_files(console.repo / 'ghostgraph/output' / name)
                    self.send(200, {'config': console.config, 'has_output': latest.exists(), 'files': [
                        {'path': p, 'before': files.get(p, ''), 'after': after.get(p, '')}
                        for p in sorted(files.keys() | after.keys()) if p.endswith('.py')]})
                elif path.startswith('/vendor/monaco/'):
                    target = (assets / path.lstrip('/')).resolve()
                    if not target.is_relative_to((assets / 'vendor/monaco').resolve()) or not target.is_file():
                        self.send(404, {'error': 'Asset not found'})
                    else:
                        self.send(200, target.read_bytes(), mimetypes.guess_type(target)[0] or 'application/octet-stream')
                elif path == '/api/runs':
                    with console.mutex:
                        runs = [console.view(p.name) for p in sorted(console.runs.glob('ui-*'), reverse=True)
                                if (p / 'HEAD.json').exists()]
                    self.send(200, {'runs': runs, 'has_key': bool(os.getenv('NVIDIA_API_KEY') or os.getenv('GHOSTGRAPH_API_KEY'))})
                elif path.startswith('/api/run/'):
                    with console.mutex:
                        self.send(200, console.view(path.rsplit('/', 1)[1], True))
                elif path in {'/', '/app.js', '/style.css'}:
                    filename = 'index.html' if path == '/' else path[1:]
                    content = (assets / filename).read_bytes().replace(b'__CONSOLE_TOKEN__', console.token.encode())
                    mime = {'/': 'text/html', '/app.js': 'text/javascript', '/style.css': 'text/css'}[path]
                    self.send(200, content, mime + '; charset=utf-8')
                else:
                    self.send(404, {'error': 'Not found'})
            except (ValueError, OSError) as exc:
                self.send(400, {'error': str(exc)})

        def do_POST(self):
            if not self.authorized(True):
                return
            if self.path != '/api/action':
                self.send(404, {'error': 'Not found'})
                return
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= 16384:
                    raise ValueError('Invalid request size')
                data = json.loads(self.rfile.read(size))
                if not isinstance(data, dict):
                    raise ValueError('Expected an object')
                self.send(200, console.action(data))
            except Exception as exc:
                self.send(400, {'error': str(exc)})

    class LocalServer(ThreadingHTTPServer):
        allow_reuse_address = False

    server = LocalServer(('127.0.0.1', port), Handler)
    server.console = console
    return server


def main():
    parser = argparse.ArgumentParser(description='Local Continuum demo console')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--repo', type=Path, default=Path.cwd())
    parser.add_argument('--open', action='store_true')
    args = parser.parse_args()
    ensure_monaco()
    server = make_server(args.repo, args.port)
    url = f'http://127.0.0.1:{server.server_port}'
    print(f'Continuum console: {url}', flush=True)
    if args.open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.console.close()
        server.server_close()
