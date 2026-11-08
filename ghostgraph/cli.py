"""Command line entrypoint for runnable GitHub-ready scaffold."""
from __future__ import annotations

import argparse
import importlib
import json
import os
from pathlib import Path

from .context import NullContext
from .engine import RunConfig, run_modernization
from .providers import MockLLM, NvidiaLLM


def get_context_adapter(spec: str):
    if spec == "none":
        return NullContext()
    if ":" not in spec:
        raise ValueError("--context-adapter must be 'none' or 'python.module:factory'")
    module_name, factory_name = spec.split(":", 1)
    obj = getattr(importlib.import_module(module_name), factory_name)()
    if not callable(getattr(obj, "read", None)) or not callable(getattr(obj, "write", None)):
        raise TypeError("Context adapter must implement read(ContextRequest), write(ContextEvent)")
    return obj


def main() -> None:
    parser = argparse.ArgumentParser(description="GhostGraph: modernize an existing Python project")
    parser.add_argument("--input", type=Path, required=True, help="Legacy Python project directory")
    parser.add_argument("--output", type=Path, required=True, help="New output directory (must not exist)")
    parser.add_argument("--goal", default="Refactor legacy Python code to be modular and readable without changing behavior")
    parser.add_argument("--provider", choices=["nvidia", "mock"], default="nvidia")
    parser.add_argument("--model", default=os.getenv("GHOSTGRAPH_MODEL", "nvidia/nemotron-3-ultra-550b-a55b"))
    parser.add_argument("--steps", type=int, default=1, help="Maximum LLM edit rounds")
    parser.add_argument("--run-tests", action="store_true", help="Execute project code via its test command (trusted repos only)")
    parser.add_argument("--test-command", default="python -m pytest -q")
    parser.add_argument("--context-adapter", default="none", help="none or importable python.module:factory")
    args = parser.parse_args()
    if not 1 <= args.steps <= 5:
        parser.error("--steps must be between 1 and 5")
    if not args.input.is_dir():
        parser.error(f"Input directory not found: {args.input}")
    try:
        llm = MockLLM() if args.provider == "mock" else NvidiaLLM(args.model)
        context = get_context_adapter(args.context_adapter)
        report = run_modernization(RunConfig(args.input, args.output, args.goal, args.model,
                             args.steps, args.run_tests, args.test_command), llm, context)
    except (ValueError, RuntimeError, TypeError, OSError) as exc:
        parser.exit(2, f"GhostGraph error: {exc}\n")
    print(json.dumps({"run_id": report["run_id"], "output_dir": report["output_dir"],
                      "steps": [{"changed_files": x["changed_files"], "tests_passed": x["tests_passed"]}
                                for x in report["steps"]]}, indent=2))


if __name__ == "__main__":
    main()
