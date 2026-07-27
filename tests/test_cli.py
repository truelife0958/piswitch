import json
import core


def _cap():
    buf = []
    return buf, (lambda *a: buf.append(" ".join(str(x) for x in a)))


def _settings():
    return json.loads((core.agent_dir() / "settings.json").read_text(encoding="utf-8"))


def test_dispatch_no_args_signals_gui():
    assert core.dispatch([]) is None


def test_cli_list_marks_active():
    core.add_preset({"name": "NV", "kind": "builtin", "provider": "nvidia", "model": "z-ai/glm-5.2"})
    buf, out = _cap()
    rc = core.cli_list(out=out)
    assert rc == 0
    assert any(line.startswith("*") and "nvidia/z-ai/glm-5.2" in line for line in buf)


def test_cli_use_switches_by_name():
    core.add_preset({"name": "DeepSeek", "kind": "builtin", "provider": "deepseek", "model": "deepseek-chat"})
    rc = core.cli_use("DeepSeek", "20260727-130000", out=lambda *a: None)
    assert rc == 0
    assert _settings()["defaultProvider"] == "deepseek"


def test_cli_use_not_found_returns_nonzero():
    assert core.cli_use("nope", "20260727-130001", out=lambda *a: None) != 0


def test_cli_model_unique_match_switches():
    rc = core.cli_model("deepseek-chat", "20260727-130002", out=lambda *a: None)
    assert rc == 0
    assert _settings()["defaultModel"] == "deepseek-chat"


def test_cli_model_ambiguous_returns_nonzero():
    # "z-ai" 命中 glm-5.2 与 glm-4 两个 → 歧义
    assert core.cli_model("z-ai", "20260727-130003", out=lambda *a: None) != 0


def test_dispatch_routes_help_and_list():
    assert core.dispatch(["--help"]) == 0
    core.add_preset({"name": "X", "kind": "builtin", "provider": "nvidia", "model": "z-ai/glm-4"})
    assert core.dispatch(["ls"]) == 0
