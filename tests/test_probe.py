"""Tests for the real-completion probe (③) and batch provider health check (⑤)."""
import io
import json
from urllib.error import HTTPError, URLError

import pytest

import core


class Response:
    def __init__(self, payload, status=200):
        self.payload = payload
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        pass

    def read(self):
        return json.dumps(self.payload).encode()


def capture(payload=None):
    """An opener that records the request it was given and returns `payload`."""
    seen = {}

    def opener(request, timeout):
        seen["url"] = request.full_url
        seen["method"] = request.get_method()
        seen["headers"] = {k.lower(): v for k, v in request.header_items()}
        seen["body"] = json.loads(request.data.decode()) if request.data else None
        seen["timeout"] = timeout
        return Response(payload if payload is not None else {"choices": [{"message": {"content": "hi"}}]})

    return opener, seen


# --- ③ endpoint shapes -----------------------------------------------------

def test_probe_chat_openai_completions_shape():
    opener, seen = capture()
    core.probe_chat("https://gw/v1", "openai-completions", "gpt-4o", "sk-x", opener=opener)
    assert seen["url"] == "https://gw/v1/chat/completions"
    assert seen["method"] == "POST"
    assert seen["headers"]["authorization"] == "Bearer sk-x"
    assert seen["body"]["model"] == "gpt-4o"
    assert seen["body"]["messages"][0]["role"] == "user"
    assert seen["body"]["max_tokens"] == 1
    assert seen["body"]["stream"] is False


def test_probe_chat_normalizes_base_url_variants():
    """baseUrl may be stored with or without /v1, same as fetch_models_url tolerates."""
    for base in ("https://gw", "https://gw/", "https://gw/v1", "https://gw/v1/"):
        opener, seen = capture()
        core.probe_chat(base, "openai-completions", "m", "k", opener=opener)
        assert seen["url"] == "https://gw/v1/chat/completions", base


def test_probe_chat_openai_responses_shape():
    opener, seen = capture({"output": []})
    core.probe_chat("https://gw/v1", "openai-responses", "gpt-5", "sk-x", opener=opener)
    assert seen["url"] == "https://gw/v1/responses"
    assert seen["body"]["model"] == "gpt-5"
    assert "input" in seen["body"]


def test_probe_chat_anthropic_uses_x_api_key_not_bearer():
    """Anthropic authenticates with x-api-key + anthropic-version, never Bearer."""
    opener, seen = capture({"content": [{"text": "hi"}]})
    core.probe_chat("https://ant/v1", "anthropic-messages", "claude-x", "sk-ant", opener=opener)
    assert seen["url"] == "https://ant/v1/messages"
    assert seen["headers"]["x-api-key"] == "sk-ant"
    assert "authorization" not in seen["headers"]
    assert seen["headers"]["anthropic-version"]
    assert seen["body"]["max_tokens"] == 1


def test_probe_chat_google_uses_generate_content_and_header_key():
    """The key goes in a header, not the query string, so it cannot leak via logs."""
    opener, seen = capture({"candidates": []})
    core.probe_chat(
        "https://generativelanguage.googleapis.com",
        "google-generative-ai", "gemini-3-pro", "AIza-x", opener=opener,
    )
    assert seen["url"].endswith("/v1beta/models/gemini-3-pro:generateContent")
    assert seen["headers"]["x-goog-api-key"] == "AIza-x"
    assert "key=" not in seen["url"]
    assert seen["body"]["contents"][0]["parts"][0]["text"]


def test_probe_chat_rejects_unsupported_api_type():
    """bedrock/vertex/azure need credentials piswitch's form does not collect."""
    assert core.supports_chat_probe("openai-completions") is True
    assert core.supports_chat_probe("bedrock-converse-stream") is False
    with pytest.raises(ValueError, match="不支持|not support"):
        core.probe_chat("https://x", "bedrock-converse-stream", "m", "k",
                        opener=lambda *a, **k: None)


def test_probe_chat_requires_a_model_id():
    with pytest.raises(ValueError, match="model"):
        core.probe_chat("https://gw/v1", "openai-completions", "", "k",
                        opener=lambda *a, **k: None)


# --- ③ error reporting -----------------------------------------------------

def test_probe_chat_surfaces_the_error_body_on_400():
    """The 400 body is the whole diagnostic — it names the rejected parameter.
    This is exactly the compat/prompt_cache_key failure mode the probe exists for."""
    body = json.dumps({"error": {"message": "Unsupported parameter: prompt_cache_key"}}).encode()

    def failing(_request, timeout):
        raise HTTPError("https://gw/v1/chat/completions", 400, "Bad Request", {},
                        io.BytesIO(body))

    with pytest.raises(ValueError) as exc:
        core.probe_chat("https://gw/v1", "openai-completions", "m", "k", opener=failing)
    assert "400" in str(exc.value)
    assert "prompt_cache_key" in str(exc.value)


def test_probe_chat_maps_auth_failures():
    def unauthorized(_request, timeout):
        raise HTTPError("https://gw", 401, "Unauthorized", {}, io.BytesIO(b""))

    with pytest.raises(ValueError, match="authentication failed"):
        core.probe_chat("https://gw/v1", "openai-completions", "m", "k", opener=unauthorized)


def test_probe_chat_maps_connection_failures():
    def offline(_request, timeout):
        raise URLError("offline")

    with pytest.raises(ValueError, match="cannot connect"):
        core.probe_chat("https://gw/v1", "openai-completions", "m", "k", opener=offline)


def test_probe_chat_resolves_env_var_keys():
    opener, seen = capture()
    core.probe_chat("https://gw/v1", "openai-completions", "m", "$PROBE_KEY",
                    opener=opener, environ={"PROBE_KEY": "resolved"})
    assert seen["headers"]["authorization"] == "Bearer resolved"


def test_probe_chat_reports_missing_env_var_without_a_request():
    called = []

    def opener(*_a, **_k):
        called.append(1)
        raise AssertionError("should not have sent a request")

    with pytest.raises(ValueError, match="is not set"):
        core.probe_chat("https://gw/v1", "openai-completions", "m", "$NOPE",
                        opener=opener, environ={})
    assert not called


