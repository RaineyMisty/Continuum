import json
from pathlib import Path
import pytest

from ghostgraph.context import ContextRequest, NullContext
from ghostgraph.engine import RunConfig, run_modernization, parse_model_json
from ghostgraph.providers import MockLLM
from ghostgraph.workspace import apply_changes


def test_null_context_baseline():
    assert NullContext().read(ContextRequest("p", "r", 1, "g", [])).model_state == {}


def test_json_fence_accepted():
    assert parse_model_json('```json\n{"files": []}\n```')["files"] == []


def test_no_path_traversal(tmp_path):
    (tmp_path / "hello.py").write_text("x=1")
    with pytest.raises(ValueError):
        apply_changes(tmp_path, [{"path": "../outside.py", "content": "hi"}])


def test_no_edits_to_tests(tmp_path):
    (tmp_path / "test_ok.py").write_text("assert True")
    with pytest.raises(ValueError):
        apply_changes(tmp_path, [{"path": "test_ok.py", "content": "assert False"}])


def test_end_to_end_mock(tmp_path):
    inp = tmp_path / "legacy"
    inp.mkdir()
    (inp / "legacy.py").write_text("def answer():\n    return 42\n")
    output = tmp_path / "new"
    report = run_modernization(RunConfig(inp, output, "modernize", "mock"), MockLLM(), NullContext())
    assert (output / "legacy.py").read_text().startswith("# GhostGraph mock pipeline")
    assert (output / "ghostgraph_run.json").is_file()
    assert len(report["steps"]) == 1
    assert (inp / "legacy.py").read_text().startswith("def answer")
