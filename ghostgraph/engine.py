"""Input -> LLM edit proposal -> isolated output -> optional tests.

A context adapter is called before and after each step, but no mathematical
state structure or SpacetimeDB implementation is assumed yet.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import shlex
import subprocess
import uuid

from .context import ContextPort, ContextRequest, ContextEvent
from .providers import LLM
from .workspace import prepare, source_files, apply_changes


@dataclass(frozen=True)
class RunConfig:
    input_dir: Path
    output_dir: Path
    goal: str
    model: str
    steps: int = 1
    run_tests: bool = False
    test_command: str = "python -m pytest -q"


def parse_model_json(message: str) -> dict:
    s = message.strip()
    if s.startswith("```"):
        lines = s.splitlines()
        if lines[-1].strip() == "```":
            s = "\n".join(lines[1:-1]).strip()
    try:
        data = json.loads(s)
    except json.JSONDecodeError:
        first, last = s.find("{"), s.rfind("}")
        if first < 0 or last < first:
            raise ValueError("Model did not return JSON")
        data = json.loads(s[first:last + 1])
    if not isinstance(data, dict) or not isinstance(data.get("files"), list):
        raise ValueError("Expected JSON object with 'files' array")
    return data


def make_prompt(goal: str, files: dict[str, str], instructions: str, state: dict,
                previous_result: str) -> str:
    content = [f"### {path}\n```\n{text}\n```" for path, text in files.items()]
    return "\n\n".join([
        "TASK: Modernize this real Python project while PRESERVING current behavior and API contracts.",
        f"GOAL: {goal}",
        "The tests are read-only and must continue to pass. Only modify existing application .py files; never alter tests.",
        "Return ONLY valid JSON: {\"summary\":\"...\",\"files\":[{\"path\":\"module.py\",\"content\":\"entire revised Python file\"}]}",
        "Return full replacement contents for each file you change, using exact existing relative paths.",
        "Do not wrap in markdown fences. Prefer a small, coherent change; fix errors reported by tests.",
        f"CONTEXT ADAPTER INSTRUCTIONS: {instructions or '(none)'}",
        "CONTEXT ADAPTER STATE (optional): " + json.dumps(state, ensure_ascii=False, default=str),
        f"PREVIOUS TEST RESULT: {previous_result or '(not run)'}",
        "PROJECT FILES:\n" + "\n\n".join(content),
    ])


def run_modernization(cfg: RunConfig, llm: LLM, context: ContextPort) -> dict:
    prepare(cfg.input_dir, cfg.output_dir)
    run_id = str(uuid.uuid4())
    project_id = cfg.input_dir.resolve().name
    out = cfg.output_dir.resolve()
    journal: list[dict] = []
    previous_result = ""
    for step in range(1, cfg.steps + 1):
        files = source_files(out)
        snapshot = context.read(ContextRequest(project_id, run_id, step, cfg.goal, list(files)))
        context.write(ContextEvent(project_id, run_id, step, "step_started", {"files": list(files), "state_ref": snapshot.state_ref}))
        prompt = make_prompt(cfg.goal, files, snapshot.instructions, snapshot.model_state, previous_result)
        response = llm.generate(prompt, files)
        proposed = parse_model_json(response)
        changed = apply_changes(out, proposed["files"])
        test_passed = None
        test_output = "Not executed (use --run-tests)"
        if cfg.run_tests:
            command = shlex.split(cfg.test_command)
            if not command:
                raise ValueError("test command is empty")
            try:
                result = subprocess.run(command, cwd=out, text=True, capture_output=True, timeout=90)
                test_passed = (result.returncode == 0)
                test_output = (result.stdout + "\n" + result.stderr)[-8000:]
            except subprocess.TimeoutExpired:
                test_passed = False
                test_output = "Test command exceeded 90 seconds"
            previous_result = test_output
        event = {"step": step, "summary": proposed.get("summary", ""), "changed_files": changed,
                 "tests_passed": test_passed, "test_output": test_output}
        journal.append(event)
        context.write(ContextEvent(project_id, run_id, step, "step_completed", event))
        if cfg.run_tests and test_passed:
            break
    report = {"run_id": run_id, "project_id": project_id, "model": cfg.model,
              "input_dir": str(cfg.input_dir.resolve()), "output_dir": str(out), "steps": journal}
    (out / "ghostgraph_run.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return report
