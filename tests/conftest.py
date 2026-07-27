import json, os, sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # 让测试能 import core / piswitch

SAMPLE_SETTINGS = {
    "lastChangelogVersion": "0.80.10",
    "defaultProvider": "nvidia",
    "defaultModel": "z-ai/glm-5.2",
    "defaultThinkingLevel": "medium",
    "packages": ["npm:a", "npm:b"],
}
SAMPLE_STORE = {
    "nvidia": {"models": [
        {"id": "z-ai/glm-5.2", "name": "GLM 5.2", "reasoning": True},
        {"id": "z-ai/glm-4", "name": "GLM 4"},
    ]},
    "deepseek": {"models": [
        {"id": "deepseek-chat", "name": "DeepSeek Chat"},
        {"id": "deepseek-v4-flash", "name": "Flash", "reasoning": True},
    ]},
}
SAMPLE_CUSTOM = {"providers": {"newapi": {
    "name": "NewAPI", "baseUrl": "https://gw/v1", "api": "openai-completions",
    "apiKey": "$NEWAPI_API_KEY", "models": [{"id": "gpt-4o", "name": "gpt-4o"}],
}}}
SAMPLE_AUTH = {"deepseek": {"type": "apikey", "key": "sk-abc"}}


@pytest.fixture(autouse=True)
def pi_env(tmp_path, monkeypatch):
    agent = tmp_path / "agent"
    data = tmp_path / "data"
    agent.mkdir(parents=True)
    data.mkdir(parents=True)
    monkeypatch.setenv("PI_AGENT_DIR", str(agent))
    monkeypatch.setenv("PISWITCH_DATA_DIR", str(data))
    (agent / "settings.json").write_text(json.dumps(SAMPLE_SETTINGS), encoding="utf-8")
    (agent / "models-store.json").write_text(json.dumps(SAMPLE_STORE), encoding="utf-8")
    (agent / "models.json").write_text(json.dumps(SAMPLE_CUSTOM), encoding="utf-8")
    (agent / "auth.json").write_text(json.dumps(SAMPLE_AUTH), encoding="utf-8")
    yield {"agent": agent, "data": data}
