"""Read-only input, isolated output, validated model file writes."""
from __future__ import annotations

import os
from pathlib import Path
import shutil

SKIP = {".git", ".venv", "venv", "__pycache__", ".pytest_cache", "node_modules", ".env", ".tox"}


def prepare(input_dir: Path, output_dir: Path) -> None:
    src = input_dir.resolve()
    dst = output_dir.resolve()
    if not src.is_dir():
        raise ValueError(f"Input directory does not exist: {src}")
    if dst == src or src in dst.parents or dst in src.parents:
        raise ValueError("Input and output directories must be separate and not nested")
    if dst.exists():
        raise ValueError(f"Output already exists: {dst}; use another directory")
    for root, dirs, files in os.walk(src, followlinks=False):
        for name in dirs + files:
            if (Path(root) / name).is_symlink():
                raise ValueError("Input symlinks not supported; remove them before running")
        dirs[:] = [d for d in dirs if d not in SKIP]
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns(*SKIP))


def source_files(root: Path, max_files: int = 25, max_chars: int = 120_000) -> dict[str, str]:
    files: dict[str, str] = {}
    allowed = {".py", ".toml", ".md", ".txt"}
    count = 0
    size = 0
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in allowed or any(p in SKIP for p in path.parts):
            continue
        rel = path.relative_to(root).as_posix()
        if path.name == "README.md":
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except (UnicodeError, OSError):
            continue
        count += 1
        size += len(content)
        if count > max_files or size > max_chars:
            raise ValueError("Project too large for starter's one-shot context; reduce to <=25 text files and <=120k characters")
        files[rel] = content
    if not any(p.endswith(".py") for p in files):
        raise ValueError("No Python source found")
    return files


def apply_changes(root: Path, edits: list[dict]) -> list[str]:
    if not isinstance(edits, list) or not edits:
        raise ValueError("Model must return at least one changed Python file")
    changed: list[str] = []
    seen = set()
    for edit in edits:
        if not isinstance(edit, dict) or not isinstance(edit.get("path"), str) or not isinstance(edit.get("content"), str):
            raise ValueError("Invalid edit: expected {path:string, content:string}")
        rel = edit["path"]
        p = Path(rel)
        if p.is_absolute() or ".." in p.parts or p.suffix != ".py" or len(p.parts) < 1:
            raise ValueError(f"Invalid target path: {rel}")
        if p.parts[0] in {"tests", "test"} or p.name.startswith("test_") or p.name == "conftest.py":
            raise ValueError(f"Tests are immutable: {rel}")
        target = (root / p).resolve()
        if not target.is_relative_to(root.resolve()) or not target.is_file() or target.is_symlink():
            raise ValueError(f"Edit must target an existing regular Python file: {rel}")
        if rel in seen:
            raise ValueError(f"Duplicate edited path: {rel}")
        seen.add(rel)
        target.write_text(edit["content"], encoding="utf-8")
        changed.append(rel)
    return changed
