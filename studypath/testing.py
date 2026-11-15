"""A fake LLM for tests: it returns prepared answers and records every call."""

from __future__ import annotations

from .llm import LLMResponse


class ScriptedLLM:
    """Returns the given answers in order. An answer can be a string (the model's
    text), an LLMResponse, or an exception instance to raise."""

    def __init__(self, *answers):
        self._answers = list(answers)
        self.calls: list[dict] = []

    def complete(self, messages, *, system=None, tools=None, json_schema=None) -> LLMResponse:
        self.calls.append({"messages": messages, "system": system, "tools": tools, "json_schema": json_schema})
        if not self._answers:
            raise AssertionError("ScriptedLLM was called more times than it has answers")
        answer = self._answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        if isinstance(answer, LLMResponse):
            return answer
        return LLMResponse(text=answer)
