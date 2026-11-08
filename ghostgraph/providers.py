"""LLM transport, isolated from recovery and database logic."""
from __future__ import annotations
import json
import os
from typing import Protocol
from .workspace import is_test


class LLM(Protocol):
    def generate(self, prompt: str, files: dict[str, str]) -> str: ...


class NvidiaLLM:
    def __init__(self, model: str, timeout: float = 120, base_url: str | None = None,
                 temperature: float = 0.2, max_tokens: int = 16000):
        from openai import OpenAI
        key = os.getenv('GHOSTGRAPH_API_KEY') or os.getenv('NVIDIA_API_KEY')
        if not key:
            raise RuntimeError('Set NVIDIA_API_KEY or GHOSTGRAPH_API_KEY')
        self.model, self.temperature, self.max_tokens = model, temperature, max_tokens
        self.client = OpenAI(base_url=base_url or 'https://integrate.api.nvidia.com/v1',
                             api_key=key, timeout=timeout, max_retries=1)

    def generate(self, prompt: str, files: dict[str, str]) -> str:
        result = self.client.chat.completions.create(
            model=self.model, temperature=self.temperature, max_tokens=self.max_tokens,
            messages=[{'role': 'system', 'content': 'You are a Python refactoring agent. Return one JSON object.'},
                      {'role': 'user', 'content': prompt}])
        if result.choices[0].finish_reason == 'length':
            raise RuntimeError('Response truncated; increase token budget or reduce project size')
        message = result.choices[0].message.content
        if not message:
            raise RuntimeError('Model returned no content')
        return message


class MockLLM:
    """Deterministic two-round smoke test, NOT an AI modernization benchmark."""
    def generate(self, prompt: str, files: dict[str, str]) -> str:
        path = next(p for p in sorted(files) if p.endswith('.py') and not is_test(p))
        marker = '# GhostGraph offline checkpoint demo\n'
        done = files[path].startswith(marker)
        return json.dumps({'summary': 'Offline checkpoint demo only',
                           'status': 'done' if done else 'continue',
                           'handoff': {'plan': ['Exercise pause/resume', 'Verify completion'],
                                       'completed': ['Demo marker saved'],
                                       'decisions': ['No semantic refactor in mock mode'],
                                       'next_actions': [] if done else ['Verify saved marker and finish']},
                           'files': [] if done else [{'path': path, 'content': marker + files[path]}]})
