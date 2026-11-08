"""Real model API adapter plus an offline pipeline smoke-test adapter."""
from __future__ import annotations

import json
import os
from typing import Protocol


class LLM(Protocol):
    def generate(self, prompt: str, files: dict[str, str]) -> str: ...


class NvidiaLLM:
    def __init__(self, model: str, timeout: float = 120.0):
        from openai import OpenAI
        key = os.getenv("GHOSTGRAPH_API_KEY") or os.getenv("NVIDIA_API_KEY")
        if not key:
            raise RuntimeError("Missing NVIDIA_API_KEY or GHOSTGRAPH_API_KEY; see .env.example")
        self.model = model
        self.client = OpenAI(
            base_url=os.getenv("GHOSTGRAPH_BASE_URL", "https://integrate.api.nvidia.com/v1"),
            api_key=key,
            timeout=timeout,
            max_retries=1,
        )

    def generate(self, prompt: str, files: dict[str, str]) -> str:
        # Ultra supports this thinking toggle according to NVIDIA's model page.
        result = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": "You are a careful Python modernization engineer. Reply with a single JSON object only."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            max_tokens=16000,
            stream=False,
            extra_body={"chat_template_kwargs": {"enable_thinking": False}},
        )
        message = result.choices[0].message.content
        if not message:
            raise RuntimeError("LLM returned no final content; try a smaller project or higher token budget")
        return message


class MockLLM:
    """Offline wiring check ONLY. It does not perform real code modernization."""
    def generate(self, prompt: str, files: dict[str, str]) -> str:
        editable = next(((k, v) for k, v in sorted(files.items())
                         if k.endswith(".py") and not k.startswith("tests/")
                         and "/tests/" not in k and not k.split("/")[-1].startswith("test_")), None)
        if not editable:
            raise RuntimeError("No eligible Python file in input")
        path, code = editable
        if not code.startswith("# GhostGraph mock pipeline"):
            code = "# GhostGraph mock pipeline (not an actual refactor)\n" + code
        return json.dumps({"summary": "Offline pipeline smoke test; no AI modernization performed", "files": [{"path": path, "content": code}]})
