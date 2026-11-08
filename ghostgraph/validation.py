"""Run fixed verification commands in disposable copies, never checkpoints."""
from __future__ import annotations
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time


def validate(project: Path, commands: list[list[str]], timeout: float, work: Path) -> dict:
    work.mkdir(exist_ok=True)
    results = []
    with tempfile.TemporaryDirectory(dir=work) as folder:
        cwd = Path(folder) / 'project'
        shutil.copytree(project, cwd)
        for command in commands:
            argv = [sys.executable if x == '{python}' else x for x in command]
            started = time.monotonic()
            with tempfile.TemporaryFile() as log:
                timed_out = False
                try:
                    proc = subprocess.Popen(argv, cwd=cwd, stdout=log, stderr=log,
                                            start_new_session=os.name != 'nt')
                    try:
                        code = proc.wait(timeout=timeout)
                    except subprocess.TimeoutExpired:
                        timed_out = True
                        kill_tree(proc)
                        code = proc.wait()
                    except BaseException:
                        kill_tree(proc)
                        proc.wait()
                        raise
                    log.seek(0, 2)
                    length = log.tell()
                    log.seek(max(0, length - 16000))
                    output = log.read().decode('utf-8', errors='replace')
                except OSError as exc:
                    code, output = -1, str(exc)
            results.append({'command': command, 'returncode': code, 'timed_out': timed_out,
                            'output': output, 'seconds': round(time.monotonic() - started, 3)})
    return {'passed': bool(results) and all(x['returncode'] == 0 and not x['timed_out'] for x in results),
            'commands': results}


def kill_tree(proc: subprocess.Popen) -> None:
    if os.name == 'nt':
        subprocess.run(['taskkill', '/PID', str(proc.pid), '/T', '/F'], capture_output=True)
        if proc.poll() is None:
            proc.kill()
    else:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
