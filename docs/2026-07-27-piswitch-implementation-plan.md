# piswitch (cc-switch 式 pi 供应商切换器) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把散落的 pi 模型切换工具（pi-model CLI + 被清空的 piswitch GUI）整合成 `~/piswitch/` 里的单一应用：cc-switch 式的供应商预设卡片、一键切换、托盘常驻、写入前备份，并含吸收自 pi-model 的 CLI。

**Architecture:** 分两层——纯逻辑核心 `core.py`（不 import tkinter，路径经环境变量可覆盖，可 headless 单测）+ 外壳 `piswitch.py`（CLI dispatch + tkinter GUI，仅做参数分发与控件装配，全部调用 core）。GUI 以还原的 `.bak`（1176 行）为起点改造：把"当前默认模型"面板换成预设卡片主页 + 预设编辑弹窗，其余（托盘/主题/高级页）复用。

**Tech Stack:** Python 3 + tkinter 8.6（已装）、PIL、pystray（xorg 后端，缺失自动降级悬浮窗）；测试用 pytest 9.1.1；无第三方运行期依赖。

## Global Constraints

- 写 `~/.pi/agent/*.json` 一律用 `core.write_json_atomic`（临时文件 + `os.replace`，保留权限），禁止直接 `open(...,'w')`。
- 切换/写 `settings.json` **只改** `defaultProvider` / `defaultModel` / `defaultThinkingLevel`，**保留其余所有键**（`packages`、`lastChangelogVersion` 等）。
- `core.py` **不得** import `tkinter` 或调用 `messagebox`；错误以异常/返回值表达，由外壳层展示。
- 路径解析走环境变量：`PI_AGENT_DIR`（默认 `~/.pi/agent`）、`PISWITCH_DATA_DIR`（默认 `~/.local/share/piswitch`）。测试通过设置这两个环境变量指向 tmp 目录。
- 运行数据（`presets.json`/`notes.json`/`backups/`）位于 `PISWITCH_DATA_DIR`，不进 git（`.gitignore` 已含 `/backups/`）。
- API key 支持 `$ENV_VAR` 引用写法，写入时**原样保留**、不展开。
- 提交信息用 conventional commits（`feat:`/`test:`/`chore:`/`docs:`/`refactor:`）。
- 破坏性操作（删 `~/ebak/pi-gui`、删 `~/.local/bin/pi-model`）只在最后一个任务、且前置校验通过后执行。

**测试约定：** 所有 core 测试放 `tests/`，靠 `tests/conftest.py` 的 autouse fixture 把 `PI_AGENT_DIR`/`PISWITCH_DATA_DIR` 指向 `tmp_path` 并预置样例 JSON。跑：`cd ~/piswitch && python3 -m pytest -q`。

---

## Task 1: 仓库脚手架 + core 路径解析 + 原子 JSON 读写

**Files:**
- Create: `~/piswitch/core.py`
- Create: `~/piswitch/tests/conftest.py`
- Create: `~/piswitch/tests/test_io.py`
- Exists: `~/piswitch/.gitignore`（首次提交已建，含 `__pycache__/`、`*.pyc`、`/backups/`）

**Interfaces:**
- Produces:
  - `agent_dir() -> Path`, `data_dir() -> Path`
  - `settings_path()`, `models_store_path()`, `models_path()`, `auth_path()`, `presets_path()`, `switch_backups_dir()` → 均 `-> Path`
  - `read_json(path: Path, default)` → 文件不存在返回 `default`；损坏抛 `ValueError`
  - `write_json_atomic(path: Path, data) -> None`

- [ ] **Step 1: 写 conftest（测试环境 fixture）**

```python
# tests/conftest.py
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
```

- [ ] **Step 2: 写失败测试 `tests/test_io.py`**

```python
import json
from pathlib import Path
import pytest
import core


def test_paths_follow_env(pi_env):
    assert core.agent_dir() == pi_env["agent"]
    assert core.data_dir() == pi_env["data"]
    assert core.settings_path() == pi_env["agent"] / "settings.json"
    assert core.presets_path() == pi_env["data"] / "presets.json"
    assert core.switch_backups_dir() == pi_env["data"] / "backups"


def test_read_json_missing_returns_default():
    assert core.read_json(core.data_dir() / "nope.json", {"x": 1}) == {"x": 1}


def test_read_json_corrupt_raises(pi_env):
    bad = pi_env["agent"] / "settings.json"
    bad.write_text("{ not json", encoding="utf-8")
    with pytest.raises(ValueError):
        core.read_json(bad, {})


def test_write_json_atomic_roundtrip_and_mkdir(pi_env):
    target = pi_env["data"] / "sub" / "out.json"
    core.write_json_atomic(target, {"a": [1, 2], "中文": "值"})
    assert json.loads(target.read_text(encoding="utf-8")) == {"a": [1, 2], "中文": "值"}


def test_write_json_atomic_preserves_mode(pi_env):
    target = pi_env["agent"] / "settings.json"
    target.chmod(0o600)
    core.write_json_atomic(target, {"k": "v"})
    assert (target.stat().st_mode & 0o777) == 0o600
```

- [ ] **Step 3: 跑测试确认失败**

Run: `cd ~/piswitch && python3 -m pytest tests/test_io.py -q`
Expected: FAIL（`ModuleNotFoundError: No module named 'core'`）

- [ ] **Step 4: 实现 `core.py` 的路径 + IO 部分**

```python
# core.py — 纯逻辑，不 import tkinter
from __future__ import annotations
import json, os, shutil, tempfile
from pathlib import Path
from typing import Any


def agent_dir() -> Path:
    return Path(os.environ.get("PI_AGENT_DIR", str(Path.home() / ".pi" / "agent")))


def data_dir() -> Path:
    return Path(os.environ.get("PISWITCH_DATA_DIR", str(Path.home() / ".local" / "share" / "piswitch")))


def settings_path() -> Path:      return agent_dir() / "settings.json"
def models_store_path() -> Path:  return agent_dir() / "models-store.json"
def models_path() -> Path:        return agent_dir() / "models.json"
def auth_path() -> Path:          return agent_dir() / "auth.json"
def presets_path() -> Path:       return data_dir() / "presets.json"
def switch_backups_dir() -> Path: return data_dir() / "backups"


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default
    except json.JSONDecodeError as e:
        raise ValueError(f"{path}: {e}") from e


def write_json_atomic(path: Path, data: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        if path.exists():
            shutil.copymode(path, tmp)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
```

- [ ] **Step 5: 跑测试确认通过**

Run: `cd ~/piswitch && python3 -m pytest tests/test_io.py -q`
Expected: PASS（5 passed）

- [ ] **Step 6: 提交**

```bash
cd ~/piswitch && git add -A && git commit -m "feat(core): env-overridable paths and atomic JSON io"
```

---

## Task 2: 配置加载器 + 供应商/模型枚举 + has_key + reasoning

**Files:**
- Modify: `~/piswitch/core.py`（追加）
- Create: `~/piswitch/tests/test_catalog.py`

**Interfaces:**
- Consumes: `read_json`, `settings_path/models_store_path/models_path/auth_path`
- Produces:
  - `load_settings() -> dict`、`load_models_store() -> dict`、`load_custom() -> dict`（保证含 `"providers"` 键）、`load_auth() -> dict`
  - `provider_model_map(store: dict, custom: dict) -> dict[str, list[dict]]`，元素 `{"id","name","source"}`，`source` ∈ `{"builtin","custom"}`，按 `(source, id)` 排序
  - `resolve_has_key(provider: str, auth: dict, custom: dict) -> bool`
  - `model_supports_reasoning(store: dict, custom: dict, provider: str, model_id: str|None) -> bool`

- [ ] **Step 1: 写失败测试 `tests/test_catalog.py`**

```python
import core


def test_loaders_read_samples():
    assert core.load_settings()["defaultProvider"] == "nvidia"
    assert "nvidia" in core.load_models_store()
    assert "newapi" in core.load_custom()["providers"]
    assert core.load_auth()["deepseek"]["key"] == "sk-abc"


def test_load_custom_ensures_providers_key(pi_env):
    (pi_env["agent"] / "models.json").write_text("{}", encoding="utf-8")
    assert core.load_custom() == {"providers": {}}


def test_provider_model_map_merges_builtin_and_custom():
    m = core.provider_model_map(core.load_models_store(), core.load_custom())
    assert {x["id"] for x in m["nvidia"]} == {"z-ai/glm-5.2", "z-ai/glm-4"}
    assert m["nvidia"][0]["source"] == "builtin"
    assert m["newapi"][0] == {"id": "gpt-4o", "name": "gpt-4o", "source": "custom"}


def test_resolve_has_key():
    auth, custom = core.load_auth(), core.load_custom()
    assert core.resolve_has_key("deepseek", auth, custom) is True   # 在 auth.json
    assert core.resolve_has_key("newapi", auth, custom) is True     # custom.apiKey 非空
    assert core.resolve_has_key("nvidia", auth, custom) is False


def test_model_supports_reasoning():
    store, custom = core.load_models_store(), core.load_custom()
    assert core.model_supports_reasoning(store, custom, "nvidia", "z-ai/glm-5.2") is True
    assert core.model_supports_reasoning(store, custom, "nvidia", "z-ai/glm-4") is False
    assert core.model_supports_reasoning(store, custom, "nvidia", None) is False
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd ~/piswitch && python3 -m pytest tests/test_catalog.py -q`
Expected: FAIL（`AttributeError: module 'core' has no attribute 'load_settings'`）

- [ ] **Step 3: 实现（追加到 core.py）**

```python
def load_settings() -> dict:
    return read_json(settings_path(), {}) or {}


def load_models_store() -> dict:
    return read_json(models_store_path(), {}) or {}


def load_custom() -> dict:
    data = read_json(models_path(), {}) or {}
    if "providers" not in data:
        data["providers"] = {}
    return data


def load_auth() -> dict:
    return read_json(auth_path(), {}) or {}


def provider_model_map(store: dict, custom: dict) -> dict:
    result: dict[str, list[dict]] = {}
    for prov, info in store.items():
        if not isinstance(info, dict):
            continue
        for m in info.get("models", []) or []:
            if isinstance(m, dict):
                result.setdefault(prov, []).append(
                    {"id": m.get("id"), "name": m.get("name") or m.get("id"), "source": "builtin"})
    for prov, cfg in custom.get("providers", {}).items():
        if not isinstance(cfg, dict):
            continue
        for m in cfg.get("models", []) or []:
            if isinstance(m, dict):
                result.setdefault(prov, []).append(
                    {"id": m.get("id"), "name": m.get("name") or m.get("id"), "source": "custom"})
    for prov in result:
        result[prov].sort(key=lambda x: (x["source"], x["id"] or ""))
    return result


def resolve_has_key(provider: str, auth: dict, custom: dict) -> bool:
    if provider in auth and auth[provider].get("key"):
        return True
    ak = custom.get("providers", {}).get(provider, {}).get("apiKey")
    return isinstance(ak, str) and bool(ak.strip())


def model_supports_reasoning(store: dict, custom: dict, provider: str, model_id) -> bool:
    if not provider or not model_id:
        return False
    for m in store.get(provider, {}).get("models", []) or []:
        if m.get("id") == model_id:
            return bool(m.get("reasoning"))
    for m in custom.get("providers", {}).get(provider, {}).get("models", []) or []:
        if m.get("id") == model_id:
            return bool(m.get("reasoning"))
    return False
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd ~/piswitch && python3 -m pytest tests/test_catalog.py -q`
Expected: PASS（5 passed）

- [ ] **Step 5: 提交**

```bash
cd ~/piswitch && git add -A && git commit -m "feat(core): config loaders, provider/model map, has_key, reasoning"
```

---

## Task 3: 纯辅助函数（供 GUI/CLI 复用，全部可单测）

**Files:**
- Modify: `~/piswitch/core.py`（追加）
- Create: `~/piswitch/tests/test_helpers.py`

**Interfaces:**
- Produces:
  - `parse_model_ids(text: str) -> list[str]`（逗号分隔、去空白、去重保序）
  - `build_custom_provider_cfg(preset: dict) -> dict`（生成 `models.json` 的 provider 条目；模型带默认字段）
  - `fetch_models_url(base: str) -> str`（把 baseUrl 规整成 `.../v1/models`）
  - `format_preset_row(preset: dict, settings: dict) -> str`（CLI 列表/卡片副标题用的一行文本）

- [ ] **Step 1: 写失败测试 `tests/test_helpers.py`**

```python
import core


def test_parse_model_ids_dedupe_and_strip():
    assert core.parse_model_ids(" a, b ,a,, c") == ["a", "b", "c"]
    assert core.parse_model_ids("") == []


def test_build_custom_provider_cfg():
    preset = {"name": "NewAPI·GPT-4o", "provider": "newapi", "model": "gpt-4o",
              "baseUrl": "https://gw/v1", "api": "openai-completions", "apiKey": "$K"}
    cfg = core.build_custom_provider_cfg(preset)
    assert cfg["name"] == "NewAPI·GPT-4o"
    assert cfg["baseUrl"] == "https://gw/v1"
    assert cfg["api"] == "openai-completions"
    assert cfg["apiKey"] == "$K"
    ids = [m["id"] for m in cfg["models"]]
    assert "gpt-4o" in ids
    assert cfg["models"][0]["contextWindow"] == 128000  # 默认字段存在


def test_fetch_models_url_normalization():
    assert core.fetch_models_url("https://gw") == "https://gw/v1/models"
    assert core.fetch_models_url("https://gw/") == "https://gw/v1/models"
    assert core.fetch_models_url("https://gw/v1") == "https://gw/v1/models"
    assert core.fetch_models_url("https://gw/v1/models") == "https://gw/v1/models"


def test_format_preset_row_marks_active():
    settings = {"defaultProvider": "newapi", "defaultModel": "gpt-4o"}
    active = {"name": "NewAPI·GPT-4o", "provider": "newapi", "model": "gpt-4o", "kind": "custom"}
    other = {"name": "DS", "provider": "deepseek", "model": "deepseek-chat", "kind": "builtin"}
    assert core.format_preset_row(active, settings).startswith("*")
    assert core.format_preset_row(other, settings).startswith(" ")
    assert "newapi/gpt-4o" in core.format_preset_row(active, settings)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd ~/piswitch && python3 -m pytest tests/test_helpers.py -q`
Expected: FAIL（`AttributeError: ... 'parse_model_ids'`）

- [ ] **Step 3: 实现（追加到 core.py）**

```python
DEFAULT_INPUT_TYPES = ["text", "image"]


def parse_model_ids(text: str) -> list[str]:
    out: list[str] = []
    for part in (text or "").split(","):
        s = part.strip()
        if s and s not in out:
            out.append(s)
    return out


def build_custom_provider_cfg(preset: dict) -> dict:
    ids = parse_model_ids(preset.get("model", "")) or ([preset["model"]] if preset.get("model") else [])
    models = [{
        "id": i, "name": i, "reasoning": bool(preset.get("reasoning", False)),
        "input": list(DEFAULT_INPUT_TYPES),
        "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
        "contextWindow": 128000, "maxTokens": 16384,
    } for i in ids]
    return {
        "name": preset.get("name") or preset["provider"],
        "baseUrl": preset.get("baseUrl", ""),
        "api": preset.get("api", "openai-completions"),
        "apiKey": preset.get("apiKey", ""),
        "models": models,
    }


def fetch_models_url(base: str) -> str:
    b = (base or "").rstrip("/")
    if b.endswith("/models"):
        return b
    if b.endswith("/v1"):
        return b + "/models"
    return b + "/v1/models"


def format_preset_row(preset: dict, settings: dict) -> str:
    mark = "*" if is_active(preset, settings) else " "
    return f"{mark} {preset.get('name','?')}  [{preset.get('provider')}/{preset.get('model')}]  {preset.get('kind','')}"
```

> 注：`format_preset_row` 依赖 `is_active`（Task 5 定义）。本任务测试只断言以 `*`/空格开头与含 `provider/model`，Task 5 完成后此依赖闭合；若单跑本任务，先在 core 末尾加占位 `def is_active(preset, settings): return preset.get("provider")==settings.get("defaultProvider") and preset.get("model")==settings.get("defaultModel")`，Task 5 会把它正式实现（同签名，覆盖即可）。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd ~/piswitch && python3 -m pytest tests/test_helpers.py -q`
Expected: PASS（4 passed）

- [ ] **Step 5: 提交**

```bash
cd ~/piswitch && git add -A && git commit -m "feat(core): pure helpers (parse ids, custom cfg, models url, preset row)"
```

---

## Task 4: 预设 CRUD

**Files:**
- Modify: `~/piswitch/core.py`（追加）
- Create: `~/piswitch/tests/test_presets.py`

**Interfaces:**
- Consumes: `read_json`, `write_json_atomic`, `presets_path`
- Produces:
  - `new_preset_id() -> str`（`uuid4().hex`）
  - `load_presets() -> list[dict]`（读 `presets.json` 的 `"presets"`，缺省 `[]`）
  - `save_presets(presets: list[dict]) -> None`（写 `{"presets": presets}`）
  - `add_preset(preset: dict) -> dict`（无 `id` 则赋 `new_preset_id()`，追加保存，返回入库对象）
  - `update_preset(preset_id: str, changes: dict) -> dict|None`（按 id merge changes 保存，返回更新后对象或 None）
  - `delete_preset(preset_id: str) -> bool`（按 id 删除保存，返回是否删到）

- [ ] **Step 1: 写失败测试 `tests/test_presets.py`**

```python
import core


def test_load_presets_default_empty():
    assert core.load_presets() == []


def test_add_assigns_id_and_persists():
    p = core.add_preset({"name": "A", "kind": "builtin", "provider": "deepseek", "model": "deepseek-chat"})
    assert p["id"]
    reloaded = core.load_presets()
    assert len(reloaded) == 1 and reloaded[0]["name"] == "A"


def test_update_merges_changes():
    p = core.add_preset({"name": "A", "kind": "builtin", "provider": "deepseek", "model": "deepseek-chat"})
    upd = core.update_preset(p["id"], {"name": "A2", "thinking": "high"})
    assert upd["name"] == "A2" and upd["thinking"] == "high"
    assert core.load_presets()[0]["name"] == "A2"


def test_update_missing_returns_none():
    assert core.update_preset("nope", {"name": "x"}) is None


def test_delete():
    p = core.add_preset({"name": "A", "kind": "builtin", "provider": "deepseek", "model": "deepseek-chat"})
    assert core.delete_preset(p["id"]) is True
    assert core.load_presets() == []
    assert core.delete_preset(p["id"]) is False


def test_ids_unique():
    assert core.new_preset_id() != core.new_preset_id()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd ~/piswitch && python3 -m pytest tests/test_presets.py -q`
Expected: FAIL（`AttributeError: ... 'load_presets'`）

- [ ] **Step 3: 实现（追加到 core.py，文件顶部 import 增加 `import uuid`）**

```python
def new_preset_id() -> str:
    return uuid.uuid4().hex


def load_presets() -> list:
    data = read_json(presets_path(), {}) or {}
    presets = data.get("presets", [])
    return presets if isinstance(presets, list) else []


def save_presets(presets: list) -> None:
    write_json_atomic(presets_path(), {"presets": presets})


def add_preset(preset: dict) -> dict:
    preset = dict(preset)
    preset.setdefault("id", new_preset_id())
    presets = load_presets()
    presets.append(preset)
    save_presets(presets)
    return preset


def update_preset(preset_id: str, changes: dict):
    presets = load_presets()
    updated = None
    for p in presets:
        if p.get("id") == preset_id:
            p.update(changes)
            updated = p
            break
    if updated is not None:
        save_presets(presets)
    return updated


def delete_preset(preset_id: str) -> bool:
    presets = load_presets()
    kept = [p for p in presets if p.get("id") != preset_id]
    if len(kept) == len(presets):
        return False
    save_presets(kept)
    return True
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd ~/piswitch && python3 -m pytest tests/test_presets.py -q`
Expected: PASS（6 passed）

- [ ] **Step 5: 提交**

```bash
cd ~/piswitch && git add -A && git commit -m "feat(core): preset CRUD backed by presets.json"
```

---

## Task 5: 切换引擎 + 当前生效判定 + 从当前配置导入

**Files:**
- Modify: `~/piswitch/core.py`（追加；正式实现 `is_active`）
- Create: `~/piswitch/tests/test_switch.py`

**Interfaces:**
- Consumes: `load_settings/load_custom/load_auth`, `write_json_atomic`, `build_custom_provider_cfg`, `settings_path/models_path/auth_path/switch_backups_dir`
- Produces:
  - `light_backup(ts: str) -> Path`（把存在的 `settings.json/models.json/auth.json` 拷进 `switch_backups_dir()/f"switch-{ts}"`，返回该目录）
  - `apply_settings(provider: str, model: str, thinking: str|None=None) -> dict`（读全量 settings，只改三键，原子写，返回新 settings）
  - `merge_custom_provider(preset: dict) -> None`（把 `build_custom_provider_cfg(preset)` 写进 `models.json` 的 `providers[preset["provider"]]`）
  - `merge_auth_key(provider: str, api_key: str) -> None`（写 `auth.json[provider] = {"type":"apikey","key":api_key}`）
  - `switch_to(preset: dict, ts: str) -> dict`（light_backup → custom 则 merge provider/key → apply_settings；返回新 settings）
  - `is_active(preset, settings) -> bool`、`active_preset_id(presets, settings) -> str|None`
  - `preset_from_current(settings: dict, custom: dict) -> dict`

- [ ] **Step 1: 写失败测试 `tests/test_switch.py`**

```python
import json
import core


def _settings():
    return json.loads((core.agent_dir() / "settings.json").read_text(encoding="utf-8"))


def test_apply_settings_preserves_unrelated_keys():
    core.apply_settings("deepseek", "deepseek-chat", "high")
    s = _settings()
    assert s["defaultProvider"] == "deepseek"
    assert s["defaultModel"] == "deepseek-chat"
    assert s["defaultThinkingLevel"] == "high"
    assert s["packages"] == ["npm:a", "npm:b"]          # 未被清掉
    assert s["lastChangelogVersion"] == "0.80.10"       # 未被清掉


def test_apply_settings_thinking_optional():
    core.apply_settings("nvidia", "z-ai/glm-4")          # 不传 thinking
    assert _settings()["defaultThinkingLevel"] == "medium"  # 保留原值


def test_light_backup_copies_three_files():
    d = core.light_backup("20260727-120000")
    assert (d / "settings.json").exists()
    assert (d / "models.json").exists()
    assert (d / "auth.json").exists()


def test_switch_to_builtin():
    preset = {"id": "1", "name": "DS", "kind": "builtin", "provider": "deepseek", "model": "deepseek-chat"}
    core.switch_to(preset, "20260727-120001")
    assert _settings()["defaultProvider"] == "deepseek"


def test_switch_to_custom_merges_models_and_auth():
    preset = {"id": "2", "name": "GW", "kind": "custom", "provider": "gw", "model": "m1, m2",
              "baseUrl": "https://gw/v1", "api": "openai-completions", "apiKey": "$GW"}
    core.switch_to(preset, "20260727-120002")
    models = json.loads((core.agent_dir() / "models.json").read_text(encoding="utf-8"))
    auth = json.loads((core.agent_dir() / "auth.json").read_text(encoding="utf-8"))
    assert set(m["id"] for m in models["providers"]["gw"]["models"]) == {"m1", "m2"}
    assert auth["gw"] == {"type": "apikey", "key": "$GW"}
    assert _settings()["defaultProvider"] == "gw"


def test_active_detection():
    presets = [
        {"id": "1", "provider": "nvidia", "model": "z-ai/glm-5.2"},
        {"id": "2", "provider": "deepseek", "model": "deepseek-chat"},
    ]
    assert core.active_preset_id(presets, core.load_settings()) == "1"  # 样例默认 nvidia/glm-5.2
    assert core.is_active(presets[1], core.load_settings()) is False


def test_preset_from_current():
    p = core.preset_from_current(core.load_settings(), core.load_custom())
    assert p["provider"] == "nvidia" and p["model"] == "z-ai/glm-5.2" and p["kind"] == "builtin"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd ~/piswitch && python3 -m pytest tests/test_switch.py -q`
Expected: FAIL（`AttributeError: ... 'apply_settings'`）

- [ ] **Step 3: 实现（追加到 core.py；若 Task 3 加了占位 `is_active`，用下方正式版覆盖）**

```python
def light_backup(ts: str) -> Path:
    dest = switch_backups_dir() / f"switch-{ts}"
    dest.mkdir(parents=True, exist_ok=True)
    for p in (settings_path(), models_path(), auth_path()):
        if p.exists():
            shutil.copy2(p, dest / p.name)
    return dest


def apply_settings(provider: str, model: str, thinking=None) -> dict:
    settings = load_settings()
    settings["defaultProvider"] = provider
    if model:
        settings["defaultModel"] = model
    if thinking:
        settings["defaultThinkingLevel"] = thinking
    write_json_atomic(settings_path(), settings)
    return settings


def merge_custom_provider(preset: dict) -> None:
    custom = load_custom()
    custom.setdefault("providers", {})[preset["provider"]] = build_custom_provider_cfg(preset)
    write_json_atomic(models_path(), custom)


def merge_auth_key(provider: str, api_key: str) -> None:
    auth = load_auth()
    auth[provider] = {"type": "apikey", "key": api_key}
    write_json_atomic(auth_path(), auth)


def switch_to(preset: dict, ts: str) -> dict:
    light_backup(ts)
    if preset.get("kind") == "custom":
        merge_custom_provider(preset)
        if preset.get("apiKey"):
            merge_auth_key(preset["provider"], preset["apiKey"])
    return apply_settings(preset.get("provider"), preset.get("model"), preset.get("thinking"))


def is_active(preset: dict, settings: dict) -> bool:
    return (preset.get("provider") == settings.get("defaultProvider")
            and preset.get("model") == settings.get("defaultModel"))


def active_preset_id(presets: list, settings: dict):
    for p in presets:
        if is_active(p, settings):
            return p.get("id")
    return None


def preset_from_current(settings: dict, custom: dict) -> dict:
    prov = settings.get("defaultProvider")
    model = settings.get("defaultModel")
    cfg = custom.get("providers", {}).get(prov)
    preset = {
        "id": new_preset_id(),
        "name": f"{prov}/{model}",
        "kind": "custom" if cfg else "builtin",
        "provider": prov, "model": model,
        "thinking": settings.get("defaultThinkingLevel"),
    }
    if cfg:
        preset.update({"baseUrl": cfg.get("baseUrl", ""), "api": cfg.get("api", "openai-completions"),
                       "apiKey": cfg.get("apiKey", "")})
    return preset
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd ~/piswitch && python3 -m pytest tests/test_switch.py -q`
Expected: PASS（7 passed）

- [ ] **Step 5: 全量回归**

Run: `cd ~/piswitch && python3 -m pytest -q`
Expected: PASS（全部通过）

- [ ] **Step 6: 提交**

```bash
cd ~/piswitch && git add -A && git commit -m "feat(core): switch engine, active detection, import-from-current"
```

---

## Task 6: CLI dispatch（吸收 pi-model）

**Files:**
- Modify: `~/piswitch/core.py`（追加 CLI 函数）
- Create: `~/piswitch/tests/test_cli.py`

**Interfaces:**
- Consumes: 全部 core 逻辑
- Produces:
  - `cli_list(out=print) -> int`
  - `cli_use(name: str, ts: str, out=print) -> int`（名称精确优先，否则子串唯一匹配；命中即 `switch_to`）
  - `cli_model(query: str, ts: str, out=print) -> int`（catalog 子串匹配 `provider/model`，唯一则 `apply_settings`）
  - `dispatch(args: list[str], ts: str|None=None) -> int|None`（无参数返回 `None` 表示"启动 GUI"；否则返回退出码）

- [ ] **Step 1: 写失败测试 `tests/test_cli.py`**

```python
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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd ~/piswitch && python3 -m pytest tests/test_cli.py -q`
Expected: FAIL（`AttributeError: ... 'dispatch'`）

- [ ] **Step 3: 实现（追加到 core.py；顶部 import 增加 `from datetime import datetime`）**

```python
USAGE = (
    "piswitch — pi 供应商切换器\n"
    "  piswitch                启动 GUI\n"
    "  piswitch list | ls      列出预设(*=当前)\n"
    "  piswitch use <名称>     按预设名切换\n"
    "  piswitch model <query>  按 provider/model 子串直接切换(兼容 pi-model)\n"
    "  piswitch --help         本帮助\n"
)


def _default_ts() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def cli_list(out=print) -> int:
    settings = load_settings()
    presets = load_presets()
    if not presets:
        out("(无预设) 用 GUI 新增，或 `piswitch model <query>` 直接切换。")
        return 0
    for p in presets:
        out(format_preset_row(p, settings))
    return 0


def _find_preset(name: str):
    presets = load_presets()
    exact = [p for p in presets if p.get("name") == name]
    if exact:
        return exact[0]
    subs = [p for p in presets if name.lower() in (p.get("name", "").lower())]
    return subs[0] if len(subs) == 1 else (None if not subs else False)  # False=歧义


def cli_use(name: str, ts: str, out=print) -> int:
    hit = _find_preset(name)
    if hit is None:
        out(f"piswitch: 没有匹配预设 “{name}”")
        return 1
    if hit is False:
        out(f"piswitch: “{name}” 匹配到多个预设，请写更精确的名称")
        return 1
    core_switch = switch_to(hit, ts)
    out(f"✓ 已切换到预设 {hit.get('name')} → {core_switch.get('defaultProvider')}/{core_switch.get('defaultModel')}")
    return 0


def cli_model(query: str, ts: str, out=print) -> int:
    store, custom = load_models_store(), load_custom()
    pm = provider_model_map(store, custom)
    matches = []
    q = query.lower()
    for prov, models in pm.items():
        for m in models:
            key = f"{prov}/{m['id']}"
            if q in key.lower():
                matches.append((prov, m["id"]))
    if not matches:
        out(f"piswitch: 无模型匹配 “{query}”")
        return 1
    if len(matches) > 1:
        out(f"piswitch: “{query}” 匹配到 {len(matches)} 个，请写更精确：")
        for prov, mid in matches[:20]:
            out(f"  {prov}/{mid}")
        return 1
    prov, mid = matches[0]
    light_backup(ts)
    apply_settings(prov, mid)
    out(f"✓ pi 默认模型 → {prov}/{mid}")
    return 0


def dispatch(args, ts=None):
    if not args:
        return None  # 启动 GUI
    ts = ts or _default_ts()
    cmd = args[0]
    if cmd in ("-h", "--help", "help"):
        print(USAGE)
        return 0
    if cmd in ("list", "ls", "-l", "--list"):
        return cli_list()
    if cmd == "use":
        if len(args) < 2:
            print("用法: piswitch use <名称>")
            return 1
        return cli_use(" ".join(args[1:]), ts)
    if cmd == "model":
        if len(args) < 2:
            print("用法: piswitch model <query>")
            return 1
        return cli_model(" ".join(args[1:]), ts)
    print(f"piswitch: 未知命令 “{cmd}”\n\n{USAGE}")
    return 2
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd ~/piswitch && python3 -m pytest tests/test_cli.py -q`
Expected: PASS（7 passed）

- [ ] **Step 5: 全量回归 + 提交**

```bash
cd ~/piswitch && python3 -m pytest -q && git add -A && git commit -m "feat(core): CLI dispatch (list/use/model/help) absorbing pi-model"
```

---

## Task 7: GUI 外壳 A —— 还原 .bak、接 core、预设卡片主页 + 编辑弹窗 + 切换

**Files:**
- Create: `~/piswitch/piswitch.py`（以 `.bak` 为起点改造）
- Source: `~/.local/share/piswitch/piswitch.py.bak.1784368548`（1176 行原始 GUI，只读参考）

> 本任务与 Task 8 是 GUI，tkinter 界面不做单元测试；验证＝`py_compile` + headless import + 人工冒烟清单。逻辑已在 core 全测，GUI 只做控件装配。

**Interfaces:**
- Consumes: 全部 `core.*`
- Produces: `piswitch.py` 内 `class App(tk.Tk)`（含 `refresh_presets()`、`open_preset_editor(preset=None)`、`switch_selected()`）与 `main()`

- [ ] **Step 1: 以 .bak 为基底创建 piswitch.py**

```bash
cp ~/.local/share/piswitch/piswitch.py.bak.1784368548 ~/piswitch/piswitch.py
```

- [ ] **Step 2: 删除 piswitch.py 里已迁入 core 的模块级纯函数，改为从 core import**

删除 piswitch.py 中这些现由 core 提供的定义：`load_json`、`save_json`、`load_settings`、`load_models_store`、`load_custom_models`、`load_auth`、`all_provider_model_map`、`resolve_has_key`、`load_notes`/`save_notes`/`note_key`（notes 相关保留在 GUI 本地即可，不迁）、路径常量 `AGENT_DIR/SETTINGS_PATH/MODELS_STORE_PATH/MODELS_PATH/AUTH_PATH/DATA_DIR/NOTES_PATH/BACKUPS_DIR`。
在文件顶部（`import tkinter` 之后）加：

```python
import core
```

并把 GUI 内对上述函数/常量的调用改为 `core.*`（例如 `save_json(SETTINGS_PATH, x)` → `core.write_json_atomic(core.settings_path(), x)`；`all_provider_model_map(a,b)` → `core.provider_model_map(a,b)`；`load_custom_models()` → `core.load_custom()`）。GUI 内需要弹窗报错处，改成 `try: core.xxx() except Exception as e: messagebox.showerror(...)`。

> notes/tags 与 `NOTES_PATH/BACKUPS_DIR` 这类 GUI 本地路径，改为 `core.data_dir() / "notes.json"` 与 `core.switch_backups_dir()`，保证与 core 同源。

- [ ] **Step 3: 用预设卡片主页替换旧「当前默认模型」左面板**

把 `_build_left` 改造为构建**预设卡片区**（保留右侧 NewAPI 快速面板可挪到编辑弹窗）：

```python
def _build_left(self, parent):
    frame = ttk.Frame(parent)
    bar = ttk.Frame(frame); bar.pack(fill="x", padx=6, pady=6)
    for text, cmd in (("新增预设", lambda: self.open_preset_editor()),
                      ("编辑", self.edit_selected_preset),
                      ("删除", self.delete_selected_preset),
                      ("从当前配置导入", self.import_current_as_preset),
                      ("导入JSON", self.import_presets_json),
                      ("导出JSON", self.export_presets_json)):
        ttk.Button(bar, text=text, command=cmd).pack(side="left", padx=2)
    self.preset_list = ttk.Treeview(frame, columns=("name", "target", "kind", "key"),
                                    show="headings", selectmode="browse")
    for c, t, w in (("name", "预设", 220), ("target", "provider/model", 240),
                    ("kind", "类型", 70), ("key", "Key", 50)):
        self.preset_list.heading(c, text=t); self.preset_list.column(c, width=w, anchor="w")
    self.preset_list.pack(fill="both", expand=True, padx=6, pady=6)
    self.preset_list.bind("<Double-1>", lambda _e: self.switch_selected())
    ttk.Button(frame, text="切为当前生效", command=self.switch_selected).pack(fill="x", padx=6, pady=6)
    return frame
```

- [ ] **Step 4: 实现预设主页方法（新增到 App）**

```python
def refresh_presets(self):
    self.presets = core.load_presets()
    settings = core.load_settings()
    active = core.active_preset_id(self.presets, settings)
    auth, custom = core.load_auth(), core.load_custom()
    self.preset_list.delete(*self.preset_list.get_children())
    for p in self.presets:
        mark = "✓ " if p.get("id") == active else ""
        haskey = "✓" if core.resolve_has_key(p.get("provider", ""), auth, custom) else "—"
        self.preset_list.insert("", "end", iid=p["id"],
            values=(mark + p.get("name", "?"), f"{p.get('provider')}/{p.get('model')}",
                    p.get("kind", ""), haskey))

def _selected_preset(self):
    sel = self.preset_list.selection()
    if not sel:
        messagebox.showinfo("提示", "先选中一个预设"); return None
    return next((p for p in self.presets if p["id"] == sel[0]), None)

def switch_selected(self):
    p = self._selected_preset()
    if not p: return
    from datetime import datetime
    try:
        s = core.switch_to(p, datetime.now().strftime("%Y%m%d-%H%M%S"))
    except Exception as e:
        messagebox.showerror("切换失败", str(e)); return
    self._set_status(f"已切换: {s.get('defaultProvider')}/{s.get('defaultModel')}")
    self.refresh_presets()

def switch_selected and delete/import methods:  # 见下方 Step 5/6
```

- [ ] **Step 5: 实现预设编辑弹窗 `open_preset_editor`**

```python
def open_preset_editor(self, preset=None):
    win = tk.Toplevel(self); win.title("编辑预设" if preset else "新增预设"); win.geometry("560x460")
    v = {k: tk.StringVar(value=(preset or {}).get(k, d)) for k, d in
         (("name", ""), ("provider", ""), ("kind", "builtin"), ("model", ""),
          ("baseUrl", "https://"), ("api", "openai-completions"),
          ("apiKey", ""), ("thinking", ""))}
    rows = [("名称", "name"), ("provider", "provider"), ("kind(builtin/custom)", "kind"),
            ("model(逗号分隔可多)", "model"), ("baseUrl(custom)", "baseUrl"),
            ("api类型(custom)", "api"), ("apiKey(custom,可$ENV)", "apiKey"),
            ("thinking(可空)", "thinking")]
    for i, (label, key) in enumerate(rows):
        ttk.Label(win, text=label).grid(row=i, column=0, sticky="w", padx=8, pady=4)
        ttk.Entry(win, textvariable=v[key], width=52).grid(row=i, column=1, padx=8, pady=4)

    def save():
        data = {k: var.get().strip() for k, var in v.items()}
        if not data["name"] or not data["provider"] or not data["model"]:
            messagebox.showerror("必填", "name / provider / model 必填", parent=win); return
        if preset:
            core.update_preset(preset["id"], data)
        else:
            core.add_preset(data)
        win.destroy(); self.refresh_presets()
    ttk.Button(win, text="保存", command=save).grid(row=len(rows), column=0, columnspan=2, pady=10)

def edit_selected_preset(self):
    p = self._selected_preset()
    if p: self.open_preset_editor(p)

def delete_selected_preset(self):
    p = self._selected_preset()
    if p and messagebox.askyesno("确认", f"删除预设 {p.get('name')}?"):
        core.delete_preset(p["id"]); self.refresh_presets()
```

- [ ] **Step 6: 实现导入/导出**

```python
def import_current_as_preset(self):
    p = core.preset_from_current(core.load_settings(), core.load_custom())
    core.add_preset(p); self.refresh_presets()
    self._set_status(f"已从当前配置导入预设: {p['name']}")

def export_presets_json(self):
    from tkinter import filedialog
    path = filedialog.asksaveasfilename(defaultextension=".json", initialfile="piswitch-presets.json")
    if path:
        core.write_json_atomic(__import__("pathlib").Path(path), {"presets": core.load_presets()})
        self._set_status(f"已导出到 {path}")

def import_presets_json(self):
    from tkinter import filedialog
    path = filedialog.askopenfilename(filetypes=[("JSON", "*.json")])
    if not path: return
    data = core.read_json(__import__("pathlib").Path(path), {})
    for p in data.get("presets", []):
        p.pop("id", None); core.add_preset(p)
    self.refresh_presets(); self._set_status("导入完成")
```

- [ ] **Step 7: 在 `App.__init__` 末尾把旧 `refresh_all()` 调用替换/补充为 `self.refresh_presets()`；`main()` 顶部加 CLI 分支**

```python
def main() -> None:
    import sys
    rc = core.dispatch(sys.argv[1:])
    if rc is not None:
        sys.exit(rc)
    # 无参数 → GUI（保留原有致命错误兜底）
    debug = bool(os.environ.get("PISWITCH_DEBUG"))
    try:
        App().mainloop()
    except Exception as e:
        if debug: raise
        try: messagebox.showerror("piswitch 致命错误", str(e))
        except Exception: print(f"[piswitch] 致命错误: {e}", file=sys.stderr)
        sys.exit(1)
```

- [ ] **Step 8: 编译 + CLI 冒烟（headless，可无 X）**

Run:
```bash
cd ~/piswitch && python3 -m py_compile piswitch.py && echo COMPILE_OK
PI_AGENT_DIR=/tmp/pa PISWITCH_DATA_DIR=/tmp/pd bash -c '
  mkdir -p /tmp/pa /tmp/pd
  cp ~/.pi/agent/settings.json ~/.pi/agent/models-store.json ~/.pi/agent/models.json ~/.pi/agent/auth.json /tmp/pa/
  python3 ~/piswitch/piswitch.py --help
  python3 ~/piswitch/piswitch.py model deepseek 2>&1 | head -3
'
```
Expected: `COMPILE_OK`，`--help` 打印用法，`model` 命令给出切换或歧义提示（不弹窗、不需 X）。

- [ ] **Step 9: 提交**

```bash
cd ~/piswitch && git add -A && git commit -m "feat(gui): preset-card home, editor dialog, switch wiring on core"
```

---

## Task 8: GUI 外壳 B —— 高级页/托盘/主题接 core + headless import 冒烟

**Files:**
- Modify: `~/piswitch/piswitch.py`
- Create: `~/piswitch/tests/test_gui_import.py`

**Interfaces:**
- Consumes: `core.*`
- Produces: 可用的「高级」Notebook（auth / raw settings / builtin-override / notes / 全量备份恢复），托盘与主题沿用

- [ ] **Step 1: 把右栏 Notebook 收敛为「高级」区并全部接 core**

保留 `.bak` 的 `_build_auth_tab`/`_build_models_tab(raw)`/`_build_backup_tab`、`edit_builtin_override`、notes/tags、`backup_agent`/`restore_agent`，把其中所有 `save_json/load_*/路径常量` 改成 `core.*`（`backup_agent` 用 `core.agent_dir()`，全量备份仍拷整个 agent 目录、恢复时跳过 `sessions`）。`save_newapi`/`fetch_models` 改用 `core.write_json_atomic(core.models_path(), ...)` 与 `core.fetch_models_url(base)`。

- [ ] **Step 2: 写 headless import 冒烟测试**

```python
# tests/test_gui_import.py — 不创建窗口，只确认模块可导入且 core 契合
import importlib


def test_piswitch_module_imports():
    mod = importlib.import_module("piswitch")
    assert hasattr(mod, "App")
    assert hasattr(mod, "main")


def test_gui_uses_core_dispatch(monkeypatch):
    mod = importlib.import_module("piswitch")
    import core
    called = {}
    monkeypatch.setattr(core, "dispatch", lambda args, ts=None: called.setdefault("args", args) or 0)
    monkeypatch.setattr("sys.argv", ["piswitch", "ls"])
    with __import__("pytest").raises(SystemExit) as ei:
        mod.main()
    assert ei.value.code == 0 and called["args"] == ["ls"]
```

- [ ] **Step 3: 跑测试确认通过（import 阶段不需 X）**

Run: `cd ~/piswitch && python3 -m pytest tests/test_gui_import.py -q`
Expected: PASS（2 passed）。若报 `no display`，说明有代码在 import 期创建了 Tk——把它移进 `App.__init__`/`main()`。

- [ ] **Step 4: 全量回归**

Run: `cd ~/piswitch && python3 -m pytest -q`
Expected: PASS（全部）

- [ ] **Step 5: 人工冒烟清单（有 WSLg/X 时执行；无则记录为待人工验证）**

```bash
python3 ~/piswitch/piswitch.py   # 应出现窗口
```
逐项确认：① 主页列出预设、当前项有 ✓；② 新增/编辑/删除预设生效并落盘 `~/.local/share/piswitch/presets.json`；③ 选中→「切为当前生效」后 `~/.pi/agent/settings.json` 的 provider/model 变更且生成 `backups/switch-*`；④ 高级页能读到 auth/raw settings/备份列表；⑤ 关窗最小化到托盘/悬浮窗。

- [ ] **Step 6: 提交**

```bash
cd ~/piswitch && git add -A && git commit -m "feat(gui): advanced tabs + tray on core; headless import smoke"
```

---

## Task 9: 启动器 + 安装脚本 + README

**Files:**
- Create: `~/piswitch/bin/piswitch`
- Create: `~/piswitch/install.sh`
- Create: `~/piswitch/README.md`

**Interfaces:**
- Produces: 可执行 `bin/piswitch`；幂等 `install.sh`

- [ ] **Step 1: 写启动器 `bin/piswitch`**

```bash
#!/usr/bin/env bash
# piswitch 启动器：指定 pystray 后端，转交主程序
export PYSTRAY_BACKEND="${PYSTRAY_BACKEND:-xorg}"
DIR="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
exec python3 "$DIR/piswitch.py" "$@"
```

- [ ] **Step 2: 写 `install.sh`（幂等：软链 + .desktop）**

```bash
#!/usr/bin/env bash
set -euo pipefail
REPO="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
BIN="$HOME/.local/bin"; APPS="$HOME/.local/share/applications"; ICONS="$HOME/.local/share/icons"
mkdir -p "$BIN" "$APPS" "$ICONS"
chmod +x "$REPO/bin/piswitch"
ln -sfn "$REPO/bin/piswitch" "$BIN/piswitch"
cat > "$ICONS/piswitch.svg" <<'SVG'
<svg xmlns="http://www.w3.org/2000/svg" width="128" height="128"><rect x="8" y="8" width="112" height="112" rx="24" fill="#89b4fa"/><text x="64" y="86" font-size="72" text-anchor="middle" fill="#1e1e2e" font-family="sans-serif" font-weight="bold">π</text></svg>
SVG
cat > "$APPS/piswitch.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=piswitch
Comment=pi 供应商切换器
Exec=$BIN/piswitch
Icon=$ICONS/piswitch.svg
Terminal=false
Categories=Utility;Development;
Keywords=pi;model;switch;provider;
DESKTOP
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$APPS" || true
echo "installed: $BIN/piswitch -> $REPO/bin/piswitch"
```

- [ ] **Step 3: 写 README.md**

内容需含：项目简介（cc-switch 式 pi 切换器）；安装（`bash install.sh`）；GUI 用法（预设卡片/切换/高级页/托盘）；CLI 用法（`piswitch list|use|model|--help`）；`presets.json` 格式示例（builtin/custom 各一）；涉及文件（`~/.pi/agent/*.json` 与 `~/.local/share/piswitch/*`）；WSL 说明（GUI 需 WSLg/X，CLI 无需）；备份说明（每次切换轻量备份 + 菜单全量备份）。

- [ ] **Step 4: 赋可执行 + 冒烟**

Run:
```bash
cd ~/piswitch && chmod +x bin/piswitch install.sh
./bin/piswitch --help
```
Expected: 打印 CLI 用法。

- [ ] **Step 5: 提交**

```bash
cd ~/piswitch && git add -A && git commit -m "feat: launcher, idempotent install.sh, README"
```

---

## Task 10: 切换上线 + 破坏性清理（最后执行）

**Files:**
- Symlink: `~/.local/bin/piswitch` → `~/piswitch/bin/piswitch`
- Delete: `~/.local/bin/pi-model`、`~/.local/share/piswitch/piswitch.py`（空）、`~/.local/share/piswitch/__pycache__/`、`~/ebak/pi-gui`

**Interfaces:** 无（收尾）

- [ ] **Step 1: 备份现有旧启动器指向（回滚信息）并安装**

Run:
```bash
ls -l ~/.local/bin/piswitch ~/.local/bin/pi-model 2>&1   # 记录当前状态
cd ~/piswitch && ./install.sh
readlink -f ~/.local/bin/piswitch                        # 应指向 ~/piswitch/bin/piswitch
piswitch --help                                          # PATH 命令可用
```
Expected: `piswitch` 指向新仓库且 `--help` 正常。

- [ ] **Step 2: 保存 .bak 溯源到仓库（若尚未），再删除 ~/.local/share 下的空文件/缓存**

Run:
```bash
# .bak 已随首次提交保存? 若否，复制进仓库 docs 供溯源
test -f ~/piswitch/docs/piswitch.py.bak || cp ~/.local/share/piswitch/piswitch.py.bak.* ~/piswitch/docs/piswitch.py.bak
cd ~/piswitch && git add -A && git commit -m "chore: archive original piswitch .bak for provenance" || true
# 删空的旧主程序与缓存(运行数据 notes.json/backups 保留)
rm -f ~/.local/share/piswitch/piswitch.py
rm -rf ~/.local/share/piswitch/__pycache__
```
Expected: 无报错。

- [ ] **Step 3: 删除 pi-model（已被 CLI 吸收）**

Run:
```bash
rm -f ~/.local/bin/pi-model
command -v pi-model || echo "pi-model removed"
```
Expected: `pi-model removed`。

- [ ] **Step 4: 删除 ~/ebak/pi-gui（用户已确认放弃 6 个未推送提交）**

> ⚠️ 一次性不可逆。执行前二次确认目录就是目标、体积符合预期。

Run:
```bash
du -sh ~/ebak/pi-gui 2>/dev/null           # 预期 ~1.7G
rm -rf ~/ebak/pi-gui
test -d ~/ebak/pi-gui && echo "STILL EXISTS(异常)" || echo "pi-gui deleted"
```
Expected: `pi-gui deleted`。

- [ ] **Step 5: 最终验证**

Run:
```bash
cd ~/piswitch && python3 -m pytest -q            # 全绿
piswitch ls                                       # 列预设(或"无预设"提示)
piswitch model glm-5.2 && cat ~/.pi/agent/settings.json | python3 -c 'import json,sys;d=json.load(sys.stdin);print(d["defaultProvider"],d["defaultModel"],"packages_kept=",len(d.get("packages",[])))'
ls ~/.local/share/piswitch/backups/ | tail -1    # 有 switch-* 备份
```
Expected: 测试全绿；`piswitch` 命令可用；`settings.json` 被正确切换且 `packages` 仍在；已生成切换备份。

- [ ] **Step 6: 提交收尾**

```bash
cd ~/piswitch && git add -A && git commit -m "chore: cutover to piswitch, remove pi-model, drop pi-gui" || true
```

---

## Self-Review（作者自检结论）

**Spec 覆盖：** §3 数据模型→Task 3/4/5；§4 切换+备份→Task 5；§5 界面(主页/编辑/高级/托盘)→Task 7/8；§6 CLI→Task 6；§7 结构→Task 1/9；§8 删除/保留→Task 10；§9 环境→Global Constraints；§10 验证→各 Task 步骤 + Task 10 Step 5。全部有对应任务。

**保留键约束：** `apply_settings` 只改三键并整体回写，`test_apply_settings_preserves_unrelated_keys` 显式验证 `packages`/`lastChangelogVersion` 不丢。

**类型/命名一致性：** core 函数签名在 Interfaces 与实现中一致；`is_active` 在 Task 3 以占位引入、Task 5 正式实现（同签名）；GUI 调用点统一 `core.*`。

**破坏性操作：** 仅在 Task 10、且前置校验（新命令可用、测试全绿）后执行；`rm -rf ~/ebak/pi-gui` 附体积二次确认。
