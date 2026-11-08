"""Immutable code/state checkpoints and an atomically replaced HEAD pointer."""
from __future__ import annotations
from contextlib import contextmanager
import json
import os
from pathlib import Path
import shutil
import uuid


def atomic_json(path: Path, value: dict) -> None:
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    with temp.open('w', encoding='utf-8') as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)


class Store:
    def __init__(self, root: Path):
        self.root = root.resolve()

    @contextmanager
    def lock(self):
        """OS-held lock is released on process death; no stale PID lock."""
        with (self.root / 'run.lock').open('a+b') as handle:
            if os.fstat(handle.fileno()).st_size == 0:
                handle.write(b'0')
                handle.flush()
            handle.seek(0)
            try:
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise RuntimeError('Another worker owns this run') from exc
            try:
                yield
            finally:
                handle.seek(0)
                if os.name == 'nt':
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(handle, fcntl.LOCK_UN)

    def load(self) -> dict:
        head = json.loads((self.root / 'HEAD.json').read_text(encoding='utf-8'))
        return json.loads((self.root / 'checkpoints' / head['checkpoint_id'] / 'state.json').read_text(encoding='utf-8'))

    def project(self, state: dict) -> Path:
        return self.root / 'checkpoints' / state['checkpoint_id'] / 'project'

    def commit(self, state: dict, project: Path) -> dict:
        identifier = uuid.uuid4().hex
        dest = self.root / 'checkpoints' / identifier
        dest.mkdir(parents=True)
        shutil.copytree(project, dest / 'project')
        updated = dict(state, checkpoint_id=identifier)
        atomic_json(dest / 'state.json', updated)
        # Orphans from interrupted commits are never selected by HEAD.
        atomic_json(self.root / 'HEAD.json', {'checkpoint_id': identifier})
        return updated
