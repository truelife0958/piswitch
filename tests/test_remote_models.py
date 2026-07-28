import io
import json
from urllib.error import HTTPError, URLError

import pytest

import core


class Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        pass

    def read(self):
        return json.dumps(self.payload).encode()


def test_fetch_remote_models_sends_key_and_deduplicates(monkeypatch):
    seen = {}

    def opener(request, timeout):
        seen["url"] = request.full_url
        seen["authorization"] = request.get_header("Authorization")
        seen["user_agent"] = request.get_header("User-agent")
        seen["timeout"] = timeout
        return Response({"data": [
            {"id": "m1", "name": "Model One"},
            {"id": "m1"},
            {"id": "m2"},
        ]})

    models = core.fetch_remote_models("https://gateway.example/v1", "sk-test", timeout=7, opener=opener)
    assert models == [{"id": "m1", "name": "Model One"}, {"id": "m2", "name": "m2"}]
    assert seen == {
        "url": "https://gateway.example/v1/models",
        "authorization": "Bearer sk-test",
        "user_agent": "piswitch/1.0",
        "timeout": 7,
    }


def test_fetch_remote_models_resolves_environment_key(monkeypatch):
    monkeypatch.setenv("TEST_GATEWAY_KEY", "resolved-key")

    def opener(request, timeout):
        assert request.get_header("Authorization") == "Bearer resolved-key"
        return Response({"models": ["m1"]})

    assert core.fetch_remote_models("https://gateway.example", "$TEST_GATEWAY_KEY", opener=opener) == [
        {"id": "m1", "name": "m1"}
    ]


def test_fetch_remote_models_reports_auth_and_connection_errors():
    def unauthorized(_request, timeout):
        raise HTTPError("https://example/models", 401, "Unauthorized", {}, io.BytesIO())

    with pytest.raises(ValueError, match="authentication failed"):
        core.fetch_remote_models("https://example.com", "bad", opener=unauthorized)

    def offline(_request, timeout):
        raise URLError("offline")

    with pytest.raises(ValueError, match="cannot connect"):
        core.fetch_remote_models("https://example.com", "", opener=offline)


def test_fetch_remote_models_rejects_missing_environment_key():
    with pytest.raises(ValueError, match="is not set"):
        core.fetch_remote_models("https://example.com", "$MISSING_KEY", opener=lambda *_args, **_kwargs: None)


def test_resolve_api_key_respects_explicit_empty_environment():
    with pytest.raises(ValueError, match="is not set"):
        core.resolve_api_key_value("$TEST_GATEWAY_KEY", environ={})
