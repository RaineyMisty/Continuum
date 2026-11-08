"""Project snapshots and constrained edits; input projects must be trusted."""
from __future__ import annotations
import ast
import hashlib
import os
from pathlib import Path, PurePosixPath
import shutil

SKIP = {'.git', '.venv', 'venv', '__pycache__', '.pytest_cache', 'node_modules',
        '.env', '.tox', '.artifacts', 'runs', 'outputs', 'dist', 'build'}


def copy_project(source: Path, target: Path) -> None:
    for base, dirs, files in os.walk(source, followlinks=False):
        dirs[:] = [d for d in dirs if d not in SKIP]
        for name in dirs + [f for f in files if f not in SKIP and not f.endswith('.pyc')]:
            path = Path(base) / name
            if path.is_symlink():
                raise ValueError(f'Symlinks are not supported: {path}')
    shutil.copytree(source, target, ignore=shutil.ignore_patterns(*SKIP, '*.pyc'))


def prepare(input_dir: Path, output_dir: Path) -> None:
    src, dst = input_dir.resolve(), output_dir.resolve()
    if not src.is_dir():
        raise ValueError(f'Input directory does not exist: {src}')
    if src == dst or src in dst.parents or dst in src.parents:
        raise ValueError('Input and run directories must be separate and not nested')
    if dst.exists():
        raise ValueError(f'Output already exists: {dst}')
    copy_project(src, dst)


def is_test(path: str) -> bool:
    p = PurePosixPath(path.replace('\\', '/'))
    return (any(x.lower() in {'test', 'tests', 'testing'} for x in p.parts[:-1])
            or p.name.lower().startswith('test_') or p.name.lower().endswith('_test.py')
            or p.name.lower() == 'conftest.py')


def source_files(root: Path, max_files: int = 100, max_chars: int = 180_000) -> dict[str, str]:
    result = {}
    for path in sorted(root.rglob('*')):
        rel = path.relative_to(root)
        if any(x in SKIP for x in rel.parts) or path.suffix not in {'.py', '.toml', '.md', '.txt', '.ini', '.cfg'}:
            continue
        if not path.is_file():
            continue
        try:
            result[rel.as_posix()] = path.read_text(encoding='utf-8')
        except UnicodeError:
            continue
    if not any(p.endswith('.py') for p in result):
        raise ValueError('No Python source found')
    if len(result) > max_files or sum(map(len, result.values())) > max_chars:
        raise ValueError('Project exceeds context budget (100 text files / 180000 characters)')
    return result


def hashes(root: Path) -> dict[str, str]:
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob('*')) if p.is_file()}


def apply_changes(root: Path, edits: list[dict]) -> list[str]:
    if not isinstance(edits, list):
        raise ValueError('files must be an array')
    validated, seen = [], set()
    for edit in edits:
        if not isinstance(edit, dict) or not isinstance(edit.get('path'), str) or not isinstance(edit.get('content'), str):
            raise ValueError('Each edit must contain path and content strings')
        rel = edit['path']
        p = PurePosixPath(rel)
        if '\\' in rel or ':' in rel or p.is_absolute() or '..' in p.parts or p.suffix != '.py':
            raise ValueError(f'Invalid Python path: {rel}')
        if is_test(rel):
            raise ValueError(f'Tests are immutable: {rel}')
        target = (root / rel).resolve()
        if not target.is_relative_to(root.resolve()) or not target.is_file():
            raise ValueError(f'Only existing application files may be edited: {rel}')
        key = str(target).casefold()
        if key in seen:
            raise ValueError(f'Duplicate path: {rel}')
        seen.add(key)
        try:
            ast.parse(edit['content'], filename=rel)
        except SyntaxError as exc:
            raise ValueError(f'Invalid Python in {rel}: {exc}') from exc
        validated.append((rel, target, edit['content']))
    # The engine applies these only to a disposable candidate, never a checkpoint.
    for _, target, content in validated:
        target.write_text(content, encoding='utf-8')
    return [rel for rel, _, _ in validated]
