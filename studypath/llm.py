"""LLM access behind one small interface.

The rest of the application only knows `LLMClient.complete(...)`. The real
adapter talks to Claude through the Anthropic SDK; tests use a scripted fake
(see studypath/testing.py), so they need no API key and no network.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Protocol

from .config import DEFAULT_MODEL, MAX_OUTPUT_TOKENS

# If Claude's safety system declines a request, this lets the API retry it on
# another Claude model inside the same call instead of returning a refusal.
FALLBACK_BETA = "server-side-fallback-2026-07-01"
MODELS_WITH_FALLBACK = {
    "claude-sonnet-5-5", "claude-opus-5-5", "claude-opus-5",
    "claude-fable-5-1", "claude-fable-5-2",
}


class LLMError(Exception):
    """The model could not be reached or did not produce a usable answer."""

    def __init__(self, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class LLMResponse:
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    stop_reason: str = "end_turn"
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    # Provider-specific content blocks, kept so a later turn can send them back unchanged.
    raw_content: Any = None


class LLMClient(Protocol):
    def complete(
        self,
        messages: list[dict],
        *,
        system: str | None = None,
        tools: list[dict] | None = None,
        json_schema: dict | None = None,
    ) -> LLMResponse: ...


class AnthropicClient:
    """Adapter for the Anthropic Messages API."""

    def __init__(
        self,
        model: str | None = None,
        *,
        api_key: str | None = None,
        effort: str = "low",
        max_tokens: int = MAX_OUTPUT_TOKENS,
        client: Any = None,
    ):
        try:
            import anthropic
        except ImportError as e:
            raise LLMError("The 'anthropic' package is not installed. Run: pip install -r requirements.txt") from e
        self._sdk = anthropic
        self.model = model or os.environ.get("LLM_MODEL") or DEFAULT_MODEL
        self.effort = effort
        self.max_tokens = max_tokens
        if client is not None:  # injected in tests
            self._client = client
        else:
            key = api_key or os.environ.get("LLM_API_KEY")
            # Without LLM_API_KEY the SDK looks for its own credentials (ANTHROPIC_API_KEY, ...).
            try:
                self._client = anthropic.Anthropic(api_key=key) if key else anthropic.Anthropic()
            except anthropic.AnthropicError as e:
                raise LLMError(f"Model client is not configured ({e}). Set LLM_API_KEY in .env.") from e

    def __repr__(self) -> str:  # never show the key
        return f"AnthropicClient(model={self.model!r})"

    def complete(self, messages, *, system=None, tools=None, json_schema=None) -> LLMResponse:
        output_config: dict[str, Any] = {"effort": self.effort}
        if json_schema is not None:
            # Structured output: the API guarantees the answer is JSON matching the schema.
            output_config["format"] = {"type": "json_schema", "schema": json_schema}
        request: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "messages": messages,
            "output_config": output_config,
        }
        if system:
            request["system"] = system
        if tools:
            request["tools"] = tools
        if self.model in MODELS_WITH_FALLBACK:
            request["betas"] = [FALLBACK_BETA]
            request["fallbacks"] = "default"

        sdk = self._sdk
        try:
            response = self._client.beta.messages.create(**request)
        except sdk.AuthenticationError as e:
            raise LLMError("The API key was rejected. Check LLM_API_KEY in .env.") from e
        except sdk.PermissionDeniedError as e:
            raise LLMError(f"The API key may not use model {self.model!r}.") from e
        except sdk.NotFoundError as e:
            raise LLMError(f"Unknown model {self.model!r}. Check LLM_MODEL in .env.") from e
        except sdk.RateLimitError as e:
            raise LLMError("Rate limit reached. Try again later.", retryable=True) from e
        except sdk.APIStatusError as e:
            raise LLMError(f"API error {e.status_code}: {e.message}", retryable=e.status_code >= 500) from e
        except sdk.APIConnectionError as e:  # includes timeouts
            raise LLMError("Could not reach the model API (network error or timeout).", retryable=True) from e
        except (sdk.AnthropicError, TypeError) as e:
            # Raised before any request is sent, e.g. when no credentials are configured.
            raise LLMError(f"Model client is not configured ({e}). Set LLM_API_KEY in .env.") from e

        # Check why the model stopped before reading its answer.
        if response.stop_reason == "refusal":
            raise LLMError("The model declined to answer this request.")
        if response.stop_reason == "max_tokens":
            raise LLMError("The model answer was cut off at the token limit.")

        text_parts, tool_calls = [], []
        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(ToolCall(id=block.id, name=block.name, arguments=dict(block.input)))
        return LLMResponse(
            text="".join(text_parts),
            tool_calls=tool_calls,
            stop_reason=response.stop_reason,
            model=response.model,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            raw_content=response.content,
        )
