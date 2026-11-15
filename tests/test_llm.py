"""Tests for the Anthropic adapter. The SDK client is replaced by a stub, so no
request leaves the machine and no API key is needed."""

import os
from types import SimpleNamespace

import pytest

from studypath.config import load_env
from studypath.llm import FALLBACK_BETA, AnthropicClient, LLMError

anthropic = pytest.importorskip("anthropic")
httpx2 = pytest.importorskip("httpx2")

REQUEST = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")


def api_response(*blocks, stop_reason="end_turn"):
    return SimpleNamespace(
        content=list(blocks),
        stop_reason=stop_reason,
        model="claude-sonnet-5-5",
        usage=SimpleNamespace(input_tokens=120, output_tokens=40),
    )


def text(value):
    return SimpleNamespace(type="text", text=value)


class StubSDK:
    """Stands in for anthropic.Anthropic(): records the request, then returns or raises."""

    def __init__(self, outcome):
        self.outcome = outcome
        self.requests = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **request):
        self.requests.append(request)
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


def status_error(cls, status):
    return cls("boom", response=httpx2.Response(status, request=REQUEST), body=None)


def test_answer_is_mapped_to_llm_response():
    thinking = SimpleNamespace(type="thinking", thinking="")
    tool_use = SimpleNamespace(type="tool_use", id="toolu_1", name="search_courses", input={"query": "AI"})
    sdk = StubSDK(api_response(thinking, text("Let me look. "), tool_use, stop_reason="tool_use"))

    response = AnthropicClient(client=sdk).complete([{"role": "user", "content": "hi"}])

    assert response.text == "Let me look. "
    assert [(c.id, c.name, c.arguments) for c in response.tool_calls] == [("toolu_1", "search_courses", {"query": "AI"})]
    assert response.stop_reason == "tool_use"
    assert (response.input_tokens, response.output_tokens) == (120, 40)
    assert len(response.raw_content) == 3  # thinking block kept for the next turn


def test_request_carries_schema_system_prompt_and_fallback():
    sdk = StubSDK(api_response(text("{}")))
    schema = {"type": "object", "properties": {}, "required": [], "additionalProperties": False}

    AnthropicClient("claude-sonnet-5-5", client=sdk).complete(
        [{"role": "user", "content": "hi"}], system="Be brief.", json_schema=schema
    )

    request = sdk.requests[0]
    assert request["model"] == "claude-sonnet-5-5"
    assert request["system"] == "Be brief."
    assert request["output_config"] == {"effort": "low", "format": {"type": "json_schema", "schema": schema}}
    assert request["betas"] == [FALLBACK_BETA] and request["fallbacks"] == "default"
    assert "tools" not in request


def test_fallback_is_not_sent_for_models_without_it():
    sdk = StubSDK(api_response(text("ok")))

    AnthropicClient("claude-haiku-5-5", client=sdk).complete([{"role": "user", "content": "hi"}])

    assert "fallbacks" not in sdk.requests[0] and "betas" not in sdk.requests[0]


@pytest.mark.parametrize(
    "error, retryable, message",
    [
        (status_error(anthropic.AuthenticationError, 401), False, "API key was rejected"),
        (status_error(anthropic.NotFoundError, 404), False, "Unknown model"),
        (status_error(anthropic.BadRequestError, 400), False, "API error 400"),
        (status_error(anthropic.RateLimitError, 429), True, "Rate limit"),
        (status_error(anthropic.InternalServerError, 503), True, "API error 503"),
        (anthropic.APIConnectionError(request=REQUEST), True, "Could not reach"),
        (anthropic.APITimeoutError(request=REQUEST), True, "Could not reach"),
    ],
)
def test_sdk_errors_become_llm_errors(error, retryable, message):
    with pytest.raises(LLMError, match=message) as caught:
        AnthropicClient(client=StubSDK(error)).complete([{"role": "user", "content": "hi"}])

    assert caught.value.retryable is retryable


@pytest.mark.parametrize("stop_reason, message", [("refusal", "declined"), ("max_tokens", "cut off")])
def test_unusable_answers_are_errors(stop_reason, message):
    sdk = StubSDK(api_response(text("partial"), stop_reason=stop_reason))

    with pytest.raises(LLMError, match=message):
        AnthropicClient(client=sdk).complete([{"role": "user", "content": "hi"}])


def test_missing_credentials_give_a_clear_error(monkeypatch):
    for name in ("LLM_API_KEY", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    # Point the SDK at a closed local port: if it did try to send, it could not reach a real server.
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("ANTHROPIC_CONFIG_DIR", "/nonexistent")

    with pytest.raises(LLMError, match="Set LLM_API_KEY in .env"):
        AnthropicClient().complete([{"role": "user", "content": "hi"}])


def test_model_comes_from_env_and_key_is_never_shown(monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "claude-haiku-5-5")
    monkeypatch.setenv("LLM_API_KEY", "sk-test-secret-value")

    client = AnthropicClient()

    assert client.model == "claude-haiku-5-5"
    assert "secret" not in repr(client) and "secret" not in str(vars(client))


def test_load_env_reads_file_but_keeps_existing_variables(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "from-environment")
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text("# comment\nLLM_API_KEY='from-file'\nLLM_MODEL=from-file\nEMPTY=\nnot a pair\n")

    try:
        load_env(env_file)

        assert os.environ["LLM_API_KEY"] == "from-file"
        assert os.environ["LLM_MODEL"] == "from-environment"
        assert "EMPTY" not in os.environ
    finally:
        os.environ.pop("LLM_API_KEY", None)
