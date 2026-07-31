# piswitch 结构重构实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 960 行的 `piswitch.py` 拆成职责清晰的模块，让被困在 Tk 窗口里的纯推导逻辑变得可无头单测，行为完全不变。

**Architecture:** 两步走。先把 `refresh_providers` 里的行构造逻辑下沉到 `core/uistate.py` 成为纯函数，并引入一次性配置快照消除重复文件读取；再把剩余的 GUI 方法按职责拆成五个 mixin 放进 `ui/`，`App` 只负责组装。

**Tech Stack:** Python 3、tkinter/ttk、pytest。无新增第三方依赖。

## Global Constraints

- **行为不变是硬约束。** 本计划不改变任何用户可见行为，不加功能，不做性能优化。
- 每个任务结束前必须全绿：`python3 -m pytest -q`（当前 237 passed）、`python3 smoke_gui.py`（0 failure(s)）、`python3 audit_layout.py`（0 个问题）。
- 无文件超过 800 行，目标区间 200–400 行。无函数超过 50 行。
- 中文注释与用户可见文案保持原样，不做翻译或改写。
- 新增纯函数的单测写进 `tests/test_helpers.py`，与既有 `uistate` 测试同处。
- 提交信息用 conventional commits，正文说明「为什么」而非「改了什么」。

---

## File Structure

| 文件 | 职责 | 状态 |
|---|---|---|
| `core/uistate.py` | GUI 需要的纯推导，可无头测试 | 修改（+`auth_label`、+`provider_rows`） |
| `core/store.py` | 配置读写 | 修改（+`load_snapshot`） |
| `core/__init__.py` | 门面导出 | 修改 |
| `ui/__init__.py` | 空包标记 | 新建 |
| `ui/form_guard.py` | 表单脏状态与转场确认 | 新建 |
| `ui/provider_list.py` | 供应商列表渲染、筛选、选择、载入 | 新建 |
| `ui/model_ops.py` | 模型增删改与设默认 | 新建 |
| `ui/network.py` | 后台探测、批量健康检查、拉取模型 | 新建 |
| `ui/provider_crud.py` | 供应商新建、模板、保存、删除、登出 | 新建 |
| `piswitch.py` | `App` 组装 + `main()` | 大幅缩减 |
| `layout.py` | 控件构建 | 拆成四个子构建器 |
| `dialogs.py` | 模态对话框 | 拆长函数 + 改用公开 API |
| `tests/test_helpers.py` | 纯函数单测 | 新增用例 |

### 对 spec 的两处偏离

1. spec 写的 `provider_rows(..., hidden, show_hidden)` 简化为只收 `hidden`——调用方在 `show_hidden` 为真时传 `set()` 即可，少一个布尔参数。
2. 现有 `_provider_records` 记录里的 `"builtin"` 键**从未被读取**（`_render_provider_rows` 只用 `values` 和 `provider`）。而状态栏的 `custom_count` 不能由 `builtin` 推导——自定义条目可覆盖同名内置，那时 `builtin=True` 却应计入自定义。因此记录里的死键 `builtin` 换成真正需要的 `custom`。

### 任务与 spec 提交的对应

spec 规划四次提交，本计划拆成七个任务、六次提交——把 spec 提交 ① 内部再分成三步，每步都能独立验证和回滚：

| spec 提交 | 任务 | 提交点 |
|---|---|---|
| ① core 下沉 + 快照 | Task 1、Task 2 | Task 2 Step 7 |
| ① （续） | Task 3 | Task 3 Step 7 |
| ② ui/ 拆分 | Task 4 | Task 4 Step 6 |
| ③ 长函数 | Task 5 | Task 5 Step 4 |
| ③ （续） | Task 6 | Task 6 Step 7 |
| ④ 私有调用收口 | Task 7 | Task 7 Step 5 |

---

## Task 1: `core.auth_label` 纯函数

**Files:**
- Modify: `core/uistate.py`
- Modify: `core/__init__.py`
- Test: `tests/test_helpers.py`

**Interfaces:**
- Consumes: `core.auth_kind(provider, auth, custom) -> str`、`core.auth_login_state(provider, auth) -> str`（均已存在于 `core/auth.py`）
- Produces: `auth_label(provider, auth, custom, *, builtin) -> str`

- [ ] **Step 1: 写失败的测试**

追加到 `tests/test_helpers.py` 末尾：

```python
def test_auth_label_covers_every_auth_kind():
    custom = {"providers": {"p": {"api": "openai-completions"}}}
    key_auth = {"p": {"type": "api_key", "key": "sk-x"}}
    assert core.auth_label("p", key_auth, custom, builtin=False) == "API Key"
    assert core.auth_label("p", {}, custom, builtin=False) == "无"


def test_auth_label_reports_oauth_login_state():
    custom = {"providers": {"p": {}}}
    live = {"p": {"type": "oauth", "access": "t", "expires": 9_999_999_999_999}}
    dead = {"p": {"type": "oauth", "access": "t", "expires": 1}}
    assert core.auth_label("p", live, custom, builtin=False) == "已登录"
    assert core.auth_label("p", dead, custom, builtin=False) == "已过期"


def test_auth_label_prefixes_builtin_and_collapses_empty():
    custom = {"providers": {}}
    key_auth = {"p": {"type": "api_key", "key": "sk-x"}}
    assert core.auth_label("p", key_auth, custom, builtin=True) == "内置·API Key"
    # 无凭据的内置只显示「内置」，不显示「内置·无」
    assert core.auth_label("p", {}, custom, builtin=True) == "内置"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python3 -m pytest -q tests/test_helpers.py -k auth_label`
Expected: FAIL，`AttributeError: module 'core' has no attribute 'auth_label'`

- [ ] **Step 3: 实现**

在 `core/uistate.py` 顶部加入 import 并追加函数：

```python
from .auth import auth_kind, auth_login_state
```

> 已核对：`core/auth.py` 只引入 `.backups` / `.paths` / `.store`，不引入 `uistate`，无循环导入。

```python
from .auth import auth_kind, auth_login_state


def auth_label(provider: str, auth: dict, custom: dict, *, builtin: bool) -> str:
    """列表「验证」列的文案。内置供应商加前缀，但无凭据时只显示「内置」。"""
    kind = auth_kind(provider, auth, custom)
    if kind == "oauth":
        state = auth_login_state(provider, auth)
        label = "已登录" if state == "logged_in" else ("已过期" if state == "expired" else "OAuth")
    elif kind == "api_key":
        label = "API Key"
    else:
        label = "无"
    if builtin:
        label = f"内置·{label}" if label != "无" else "内置"
    return label
```

在 `core/__init__.py` 的 `from .uistate import (...)` 块加入 `auth_label`，并在 `__all__` 加入 `"auth_label"`。

- [ ] **Step 4: 跑测试确认通过**

Run: `python3 -m pytest -q tests/test_helpers.py -k auth_label`
Expected: 3 passed

- [ ] **Step 5: 全量验证**

Run: `python3 -m pytest -q`
Expected: 240 passed

> 本任务不单独提交。`auth_label` 只有被 Task 2 的 `provider_rows` 调用后才有意义，两者合并为 spec 提交 ① 的一部分，在 Task 2 Step 7 一起提交。

---

## Task 2: `core.provider_rows` 纯函数并接入

**Files:**
- Modify: `core/uistate.py`
- Modify: `core/__init__.py`
- Modify: `piswitch.py:231-301`（`refresh_providers`）
- Test: `tests/test_helpers.py`

**Interfaces:**
- Consumes: Task 1 的 `auth_label`
- Produces: `provider_rows(custom, auth, store, *, default_provider, health, hidden) -> list[dict]`，
  每个元素形如 `{"provider": str, "custom": bool, "values": tuple[str, str, int, str, str]}`，
  `values` 顺序为 `(provider, label, model_count, auth_label, health_text)`

- [ ] **Step 1: 写失败的测试**

追加到 `tests/test_helpers.py`：

```python
def _rows_by_id(rows):
    return {r["provider"]: r for r in rows}


def test_provider_rows_merges_custom_over_builtin_of_same_id():
    custom = {"providers": {"dup": {"name": "我的", "models": [1, 2]}}}
    store = {"dup": {"name": "内置的", "models": [1]}, "only": {"models": []}}
    rows = core.provider_rows(custom, {}, store, default_provider=None,
                              health={}, hidden=set())
    by_id = _rows_by_id(rows)
    # 同名自定义覆盖内置，列表里只出现一次，用自定义的名字和模型数
    assert len(rows) == 2
    assert by_id["dup"]["values"][1] == "我的"
    assert by_id["dup"]["values"][2] == 2
    # 覆盖内置的自定义条目仍计入自定义
    assert by_id["dup"]["custom"] is True
    assert by_id["only"]["custom"] is False


def test_provider_rows_hides_listed_builtins_only():
    custom = {"providers": {"mine": {"models": []}}}
    store = {"gone": {"models": []}, "kept": {"models": []}}
    rows = core.provider_rows(custom, {}, store, default_provider=None,
                              health={}, hidden={"gone", "mine"})
    # hidden 只对内置生效，自定义供应商不受影响
    assert set(_rows_by_id(rows)) == {"mine", "kept"}


def test_provider_rows_stars_the_default_and_keeps_health():
    custom = {"providers": {"a": {"name": "A", "models": []},
                            "b": {"name": "B", "models": []}}}
    rows = core.provider_rows(custom, {}, {}, default_provider="b",
                              health={"a": "✓ 120ms"}, hidden=set())
    by_id = _rows_by_id(rows)
    assert by_id["b"]["values"][1] == "★ B"
    assert by_id["a"]["values"][1] == "A"
    assert by_id["a"]["values"][4] == "✓ 120ms"
    assert by_id["b"]["values"][4] == ""


def test_provider_rows_tolerates_malformed_entries():
    custom = {"providers": {"ok": {"models": []}, "bad": "not a dict"}}
    store = {"okstore": {"models": []}, "badstore": ["nope"]}
    rows = core.provider_rows(custom, {}, store, default_provider=None,
                              health={}, hidden=set())
    assert set(_rows_by_id(rows)) == {"ok", "okstore"}


def test_provider_rows_counts_non_list_models_as_zero():
    custom = {"providers": {"x": {"models": "oops"}}}
    rows = core.provider_rows(custom, {}, {}, default_provider=None,
                              health={}, hidden=set())
    assert rows[0]["values"][2] == 0
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python3 -m pytest -q tests/test_helpers.py -k provider_rows`
Expected: FAIL，`AttributeError: module 'core' has no attribute 'provider_rows'`

- [ ] **Step 3: 实现纯函数**

追加到 `core/uistate.py`：

```python
from .store import is_builtin_provider


def provider_rows(custom: dict, auth: dict, store: dict, *,
                  default_provider: str | None,
                  health: dict, hidden: set) -> list[dict]:
    """供应商列表的行数据。自定义条目覆盖同名内置；hidden 只作用于内置。

    `custom` 标记这一行来自自定义配置——它不等于 `not builtin`，因为自定义
    条目可以覆盖同名内置，那种行既是内置 id 又该计入自定义。
    """
    custom_providers = custom.get("providers", {})
    if not isinstance(custom_providers, dict):
        custom_providers = {}
    rows: list[dict] = []

    def _row(provider: str, config: dict, *, is_custom: bool) -> dict:
        builtin = is_builtin_provider(provider, store)
        models = config.get("models", [])
        model_count = len(models) if isinstance(models, list) else 0
        # ★ 标记 pi 当前默认供应商，比多加一列便宜
        label = config.get("name") or provider
        if provider == default_provider:
            label = f"★ {label}"
        return {
            "provider": provider,
            "custom": is_custom,
            "values": (
                provider, label, model_count,
                auth_label(provider, auth, custom, builtin=builtin),
                health.get(provider, ""),
            ),
        }

    for provider, config in sorted(custom_providers.items()):
        if not isinstance(config, dict):
            continue
        rows.append(_row(provider, config, is_custom=True))

    # 再补上没有被同名自定义条目覆盖的内置供应商
    for provider, info in sorted(store.items()):
        if provider in custom_providers or not isinstance(info, dict):
            continue
        if provider in hidden:
            continue
        rows.append(_row(provider, info, is_custom=False))
    return rows
```

在 `core/__init__.py` 导入并加进 `__all__`。

- [ ] **Step 4: 跑测试确认通过**

Run: `python3 -m pytest -q tests/test_helpers.py -k provider_rows`
Expected: 5 passed

- [ ] **Step 5: 接入 `refresh_providers`**

把 `piswitch.py:231-301` 整个方法替换为：

```python
    def refresh_providers(
        self, select: str | None = None, *, load_selection: bool = True
    ) -> None:
        store = core.load_models_store()
        hidden = set() if self.show_hidden.get() else core.load_hidden_builtins()
        records = core.provider_rows(
            core.load_custom(), core.load_auth(), store,
            default_provider=core.load_settings().get("defaultProvider"),
            health=self._health, hidden=hidden,
        )
        self._provider_records = records
        target = select or self.current_provider
        self._render_provider_rows(select=target)
        if target and self.provider_tree.exists(target):
            if load_selection:
                self._load_provider(target)
        elif load_selection and not self.provider_tree.get_children():
            if not self.provider_filter_var.get().strip():
                self._reset_new_provider_form()
        elif load_selection:
            first = self.provider_tree.get_children()[0]
            self.provider_tree.selection_set(first)
            self.provider_tree.focus(first)
            self._load_provider(first)
        # 列表里也有内置，所以两个数都报，而不是只报自定义的
        custom_count = sum(1 for record in records if record["custom"])
        self.status_var.set(
            f"已加载 {custom_count} 个自定义供应商，{len(records) - custom_count} 个内置"
        )
```

- [ ] **Step 6: 全量验证**

Run: `python3 -m pytest -q && python3 smoke_gui.py && python3 audit_layout.py`
Expected: 245 passed；smoke `0 failure(s)`；audit `0 个问题`

`refresh_providers` 应从 71 行降到约 27 行，用 `python3 -c "import ast;t=ast.parse(open('piswitch.py').read());print([n.end_lineno-n.lineno+1 for n in ast.walk(t) if getattr(n,'name','')=='refresh_providers'])"` 核对。

- [ ] **Step 7: 提交**

```bash
git add core/uistate.py core/__init__.py piswitch.py tests/test_helpers.py
git commit -m "refactor(core): 供应商行构造下沉为纯函数"
```

---

## Task 3: `core.load_snapshot` 消除单次刷新内的重复读

**Files:**
- Modify: `core/store.py`
- Modify: `core/__init__.py`
- Modify: `piswitch.py`（`refresh_providers`、`_load_provider`、`_refresh_models`）
- Test: `tests/test_helpers.py`

**Interfaces:**
- Produces: `load_snapshot() -> Snapshot`，`Snapshot` 是 `dataclasses.dataclass(frozen=True)`，字段 `custom: dict`、`auth: dict`、`store: dict`、`settings: dict`、`hidden: set`

- [ ] **Step 1: 写失败的测试**

```python
def test_load_snapshot_reads_each_config_once(monkeypatch):
    calls: list[str] = []
    original = core.store.read_json

    def counting(path, default):
        calls.append(str(path))
        return original(path, default)

    monkeypatch.setattr(core.store, "read_json", counting)
    snap = core.load_snapshot()
    # 四个配置文件各读一次，不多不少
    assert len(calls) == len(set(calls)) == 4
    assert isinstance(snap.custom.get("providers"), dict)
    assert isinstance(snap.hidden, set)
```

> `tests/conftest.py:32` 的 `pi_env` 是 `autouse=True`，测试无需声明该参数即可获得隔离的临时配置目录。
> `load_hidden_builtins` 直接用 `path.read_text` 而不走 `read_json`，所以它不计入这四次。

- [ ] **Step 2: 跑测试确认失败**

Run: `python3 -m pytest -q tests/test_helpers.py -k load_snapshot`
Expected: FAIL，`AttributeError: module 'core' has no attribute 'load_snapshot'`

- [ ] **Step 3: 实现**

在 `core/store.py` 顶部加 `from dataclasses import dataclass`，并追加：

```python
@dataclass(frozen=True)
class Snapshot:
    """一次刷新用到的全部配置，各文件只读一次。

    这里存在的理由是可读性而非速度：原先 refresh_providers 与它调用的
    _load_provider / _refresh_models 各自重读同一批文件，一次刷新读了八遍。
    """
    custom: dict
    auth: dict
    store: dict
    settings: dict
    hidden: set


def load_snapshot() -> Snapshot:
    return Snapshot(
        custom=load_custom(),
        auth=load_auth(),
        store=load_models_store(),
        settings=load_settings(),
        hidden=load_hidden_builtins(),
    )
```

在 `core/__init__.py` 导出 `load_snapshot` 与 `Snapshot`。

- [ ] **Step 4: 跑测试确认通过**

Run: `python3 -m pytest -q tests/test_helpers.py -k load_snapshot`
Expected: 1 passed

- [ ] **Step 5: 接入三个调用点**

`refresh_providers` 开头改为取一次快照并向下传：

```python
        snap = core.load_snapshot()
        hidden = set() if self.show_hidden.get() else snap.hidden
        records = core.provider_rows(
            snap.custom, snap.auth, snap.store,
            default_provider=snap.settings.get("defaultProvider"),
            health=self._health, hidden=hidden,
        )
```

后面两处 `self._load_provider(...)` 改为 `self._load_provider(target, snap=snap)` / `self._load_provider(first, snap=snap)`。

`_load_provider` 签名与前四行改为：

```python
    def _load_provider(self, provider: str, *, snap: core.Snapshot | None = None) -> None:
        snap = snap or core.load_snapshot()
        custom, auth, store = snap.custom, snap.auth, snap.store
```

并把方法体内的 `core.load_hidden_builtins()` 换成 `snap.hidden`，`self._refresh_models(config)` 换成 `self._refresh_models(config, settings=snap.settings)`。

`_refresh_models` 签名改为 `def _refresh_models(self, config: dict, *, settings: dict | None = None) -> None:`，体内 `settings = settings or core.load_settings()`。

> 保留默认参数，让 `dialogs.py` 等外部调用点无需同步修改。

- [ ] **Step 6: 验证重复读确实消失**

Run: `python3 bench_startup.py`
Expected: cProfile 里 `read_json` 的 `ncalls` 从 160 降到 80 上下（20 次刷新 × 4 个文件），且各项耗时不高于改动前

- [ ] **Step 7: 全量验证并提交**

```bash
python3 -m pytest -q && python3 smoke_gui.py && python3 audit_layout.py
git add core/store.py core/__init__.py piswitch.py tests/test_helpers.py
git commit -m "refactor(core): 一次刷新只读一遍配置"
```

---

## Task 4: `ui/` 五个 mixin

**Files:**
- Create: `ui/__init__.py`、`ui/form_guard.py`、`ui/provider_list.py`、`ui/model_ops.py`、`ui/network.py`、`ui/provider_crud.py`
- Modify: `piswitch.py`

**Interfaces:**
- Produces: `FormGuardMixin`、`ProviderListMixin`、`ModelOpsMixin`、`NetworkMixin`、`ProviderCrudMixin`，
  均为不继承任何基类的纯 mixin，方法体逐字搬运，不改签名、不改行为

方法归属（49 个方法，无重复无遗漏）：

| Mixin | 方法 |
|---|---|
| `FormGuardMixin` | `_toggle_key_visibility` `_capture_form_state` `_on_form_changed` `_mark_form_clean` `_confirm_form_transition` `_restore_provider_selection` `_on_close` `request_refresh` |
| `ProviderListMixin` | `_render_provider_rows` `refresh_providers` `_on_provider_selected` `_load_provider` `_apply_action_states` `_refresh_key_status` `toggle_show_hidden` `_on_provider_filter_changed` |
| `ModelOpsMixin` | `_refresh_models` `_on_model_filter_changed` `_on_model_double_click` `edit_model` `_open_model_editor` `set_default` `add_models` `delete_model` `clear_models` `_refresh_provider_models` `_selected_model_id` |
| `NetworkMixin` | `_set_network_busy` `_run_network` `_poll_network_results` `_fetch_action_from_form` `test_connection` `check_all_providers` `_show_health_results` `fetch_models` `_show_remote_models` |
| `ProviderCrudMixin` | `_reset_new_provider_form` `new_provider` `new_from_template` `apply_template_values` `save_provider` `delete_provider` `logout_provider` `toggle_hide_builtin` `export_config` `import_config` `open_backup_restore` |
| `piswitch.py` 保留 | `__init__` `_build_ui` |

- [ ] **Step 1: 建包**

```bash
mkdir -p ui
printf '"""GUI 行为按职责拆分的 mixin，由 piswitch.App 组装。"""\n' > ui/__init__.py
```

- [ ] **Step 2: 逐个搬运**

每个 mixin 文件的骨架（以 `form_guard` 为例，其余同理）：

```python
"""表单脏状态跟踪与转场确认。"""
from __future__ import annotations

from tkinter import messagebox


class FormGuardMixin:
    """依赖 App 提供的：表单五个 StringVar、provider_tree、current_provider、
    _current_is_builtin、_tracking_form、save_provider、refresh_providers。"""
```

**逐字搬运方法体，一个字符都不改。** 每搬完一个 mixin 就跑一次 `python3 -m pytest -q`，不要五个搬完再一起跑——出错时无法定位。

- [ ] **Step 3: 改 `App` 声明**

```python
from ui.form_guard import FormGuardMixin
from ui.model_ops import ModelOpsMixin
from ui.network import NetworkMixin
from ui.provider_crud import ProviderCrudMixin
from ui.provider_list import ProviderListMixin


class App(
    FormGuardMixin, ProviderListMixin, ModelOpsMixin,
    NetworkMixin, ProviderCrudMixin, tk.Tk,
):
```

> MRO 注意：`tk.Tk` 必须排在最后。mixin 之间无同名方法，因此顺序不影响行为，但 `tk.Tk` 前置会让 mixin 的方法被基类遮蔽。

- [ ] **Step 4: 确认无遗漏**

```bash
python3 -c "
import ast
names = set()
for p in ['piswitch.py'] + __import__('glob').glob('ui/*.py'):
    t = ast.parse(open(p).read())
    for c in t.body:
        if isinstance(c, ast.ClassDef):
            for m in c.body:
                if isinstance(m, ast.FunctionDef):
                    assert m.name not in names, f'重复定义: {m.name}'
                    names.add(m.name)
print(f'{len(names)} 个方法，无重复')
"
```
Expected: `49 个方法，无重复`

- [ ] **Step 5: 确认行数达标**

Run: `wc -l piswitch.py ui/*.py`
Expected: 每个文件都低于 400 行

- [ ] **Step 6: 全量验证并提交**

```bash
python3 -m pytest -q && python3 smoke_gui.py && python3 audit_layout.py
python3 -m py_compile piswitch.py dialogs.py layout.py audit_layout.py smoke_gui.py ui/*.py core/*.py
git add ui piswitch.py
git commit -m "refactor(ui): App 按职责拆成五个 mixin"
```

---

## Task 5: 拆 `layout.build`

**Files:**
- Modify: `layout.py`

**Interfaces:**
- Produces: `_build_toolbar(app) -> ttk.Frame`、`_build_provider_pane(app, parent) -> None`、`_build_form(app, parent) -> None`、`_build_model_pane(app, parent) -> None`；四者均只被 `build` 调用，不对外暴露

现有 `build`（`layout.py:14-233`）的自然分段：

| 行 | 内容 | 去处 |
|---|---|---|
| 15–46 | toolbar、检查全部/刷新/从模板/新增按钮、`more_menu` | `_build_toolbar` |
| 47–55 | 状态栏与 Panedwindow | 留在 `build` |
| 56–101 | 左窗格：筛选框、`provider_tree`、滚动条 | `_build_provider_pane` |
| 102–167 | 表单字段、`api_combo`、Key 输入、操作按钮与菜单 | `_build_form` |
| 168–233 | 模型头部、筛选、`model_tree`、双击绑定 | `_build_model_pane` |

- [ ] **Step 1: 拆分**

按上表切分，**方法体逐字搬运**。注意两条既有注释里记录的顺序约束必须保留：
- 状态栏必须在扩展窗格之前 pack（否则 Tk 会把剩余高度全给窗格，状态栏完全不映射）
- 滚动条必须在树之前 pack（否则树吃掉全部像素，滚动条永不映射）

`build` 收敛为约 25 行的装配函数。

- [ ] **Step 2: 验证布局未退化**

Run: `python3 audit_layout.py`
Expected: `0 个问题`（这个工具正是为了守住这类改动而写的）

- [ ] **Step 3: 确认函数长度**

```bash
python3 -c "
import ast
t = ast.parse(open('layout.py').read())
for n in ast.walk(t):
    if isinstance(n, ast.FunctionDef):
        print(f'{n.end_lineno - n.lineno + 1:4d}  {n.name}')
"
```
Expected: 每个函数都低于 50 行

- [ ] **Step 4: 全量验证并提交**

```bash
python3 -m pytest -q && python3 smoke_gui.py && python3 audit_layout.py
git add layout.py
git commit -m "refactor(layout): build 拆成四个子构建器"
```

---

## Task 6: 拆 `show_remote_models`、`_load_provider` 与 `App.__init__`

**Files:**
- Modify: `dialogs.py`（`show_remote_models`，143 行）
- Modify: `ui/provider_list.py`（`_load_provider`，快照接入后约 45 行）
- Modify: `piswitch.py`（`__init__`，71 行）

**Interfaces:**
- Produces: `dialogs._RemoteSelection`（封装勾选状态与 shift 锚点）；`ProviderListMixin._fill_provider_form(config, *, provider, kind, auth, builtin) -> None`；`App._declare_vars() -> None`、`App._bind_events() -> None`

- [ ] **Step 1: 抽出远程模型选择状态**

`show_remote_models` 内的七个闭包共享 `last_clicked` 锚点与勾选集合。提成一个小类，闭包按下表逐字搬为方法：

| 原闭包 | 新方法 |
|---|---|
| `update_selection_text` | `_RemoteSelection.update_count` |
| `set_checked` | `_RemoteSelection.set_checked` |
| `toggle_item` | `_RemoteSelection.toggle` |
| `on_tree_click` | `_RemoteSelection.on_click` |
| `on_tree_space` | `_RemoteSelection.on_space` |
| `select_all` | `_RemoteSelection.select_all` |
| `clear_selection` | `_RemoteSelection.clear` |

```python
class _RemoteSelection:
    """勾选状态与 Shift 框选锚点。抽出来是因为七个闭包共享它，
    平铺在对话框函数里读不出谁在改什么。

    真相是 `selected` 这个 id 集合，树里第 0 列的 ☑/☐ 只是它的显示。
    两者必须一起改，否则会出现勾了却导不进来的行。"""

    def __init__(self, tree, selection_text, total: int):
        self.tree = tree
        self.selection_text = selection_text   # 原 selection_text StringVar
        self.total = total
        self.selected: set[str] = set()        # 原 selected 集合
        self.anchor: str | None = None         # 原 last_clicked["iid"]

    def checked_ids(self) -> list[str]:
        return [
            self.tree.item(item, "values")[1]
            for item in self.tree.get_children()
            if item in self.selected
        ]
```

`show_remote_models` 只负责建控件并接线：`sel = _RemoteSelection(tree, selection_text, len(models))`，按钮 command 与事件绑定改指 `sel.` 的方法。`import_selected` 里那段列表推导直接换成 `sel.checked_ids()`。

> 树的列名是 `("selected", "id", "name")`，勾选列写值用 `values[0] = "☑" if checked else "☐"`——搬运时别改成别的列标识。

> 搬运时保留原有的 Shift 框选语义：整段统一进入或退出勾选，以本次点击产生的状态为准。`tests/test_gui_app.py` 里有对应用例，改完必须仍通过。

- [ ] **Step 2: 验证对话框仍可用**

Run: `python3 smoke_gui.py && python3 -m pytest -q tests/test_remote_models.py tests/test_gui_app.py`
Expected: smoke 输出含 `remote dialog buttons: ['全选', '取消', '导入所选', '清空']` 与 `ok: _show_remote_models()`；测试全过

- [ ] **Step 3: 拆 `_load_provider` 的表单回填段**

Task 3 之后 `_load_provider` 仍约 45 行，其中「抑制 trace → 回填五个字段 → 恢复 trace」是独立的一段。提成方法：

```python
    def _fill_provider_form(self, config: dict, *, provider: str,
                            kind: str, auth: dict, builtin: bool) -> None:
        """程序化回填表单。全程压住 _tracking_form，否则这些赋值会被
        _on_form_changed 当成用户编辑，一选中供应商就显示「未保存」。"""
        self._tracking_form = False
        try:
            self.provider_var.set(provider)
            self.name_var.set(config.get("name") or provider)
            self.base_url_var.set(config.get("baseUrl", ""))
            self.api_var.set(config.get("api", core.API_TYPES[0]))
            if kind == "oauth":
                # OAuth access tokens are extension-managed; show read-only status instead.
                self.api_key_var.set(
                    OAUTH_LABELS.get(core.auth_login_state(provider, auth), "(OAuth)")
                )
            elif kind == "api_key":
                auth_entry = auth.get(provider)
                auth_key = auth_entry.get("key") if isinstance(auth_entry, dict) else ""
                self.api_key_var.set(auth_key or config.get("apiKey", ""))
            else:
                self.api_key_var.set(config.get("apiKey", ""))

            # Builtin providers are read-only: label missing store-owned values clearly.
            if builtin:
                self.name_var.set(config.get("name") or f"{provider} (内置)")
                self.base_url_var.set(config.get("baseUrl") or "(内置)")
            self.show_key_var.set(False)
            self._toggle_key_visibility()
        finally:
            self._tracking_form = True
```

`_load_provider` 对应段落替换为一次调用，随后的控件 state 设置与 `_apply_action_states` / `_refresh_models` / `_mark_form_clean` 保持原位原序。

- [ ] **Step 4: 拆 `App.__init__`**

```python
    def _declare_vars(self) -> None:
        """所有 Tk 变量与内部状态字段。只声明，不绑定、不读盘。"""
        self.current_provider: str | None = None
        self._current_is_builtin = False
        self._current_has_oauth = False
        self._current_is_hidden = False
        self.provider_var = tk.StringVar()
        self.name_var = tk.StringVar()
        self.base_url_var = tk.StringVar()
        self.api_var = tk.StringVar()
        self.api_key_var = tk.StringVar()
        self.key_status_var = tk.StringVar()
        self.show_key_var = tk.BooleanVar(value=False)
        self.status_var = tk.StringVar(value="就绪")
        self.form_status_var = tk.StringVar()
        self.show_hidden = tk.BooleanVar(value=False)  # show builtin providers the user hid
        self.provider_filter_var = tk.StringVar()
        self.provider_count_var = tk.StringVar()
        self.model_filter_var = tk.StringVar()
        self.model_count_var = tk.StringVar()
        self._network_results: queue.Queue = queue.Queue()
        self._network_busy = False
        # provider id -> last health-check cell text; survives refresh_providers redraws.
        self._health: dict[str, str] = {}
        self._provider_records: list[dict] = []
        self._current_config: dict = {}
        self._tracking_form = False
        self._form_snapshot: tuple[str, ...] = ()
        self._form_dirty = False

    def _bind_events(self) -> None:
        """快捷键、trace 回调、关窗协议。必须在 _build_ui 之后调用。"""
        self.bind("<Control-n>", lambda _event: self.new_provider())
        self.bind("<Control-s>", lambda _event: self.save_provider())
        self.bind("<Control-f>", lambda _event: self.provider_filter_entry.focus_set())
        for variable in (
            self.provider_var, self.name_var, self.base_url_var,
            self.api_var, self.api_key_var,
        ):
            variable.trace_add("write", self._on_form_changed)
        # Re-evaluate the $ENV_VAR indicator and the two list filters while typing.
        self.api_key_var.trace_add("write", lambda *_a: self._refresh_key_status())
        self.provider_filter_var.trace_add("write", self._on_provider_filter_changed)
        self.model_filter_var.trace_add("write", self._on_model_filter_changed)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._tracking_form = True
```

`__init__` 收敛为：窗口标题/尺寸/样式 → `self._declare_vars()` → `self._build_ui()` → `self._bind_events()` → `self.after(100, self._poll_network_results)` → `self.refresh_providers()`。

> 顺序约束不可动：`_bind_events` 依赖 `_build_ui` 建出的 `provider_filter_entry`；`self._tracking_form = True` 必须留在 `_bind_events` 末尾——提前置位会让建表单期间的程序化赋值被当成用户修改，窗口一开就显示「未保存」。

- [ ] **Step 5: 验证脏状态守卫未被破坏**

Run: `python3 -m pytest -q tests/test_gui_app.py && python3 smoke_gui.py`
Expected: 全部通过；smoke 首屏 `status` 不含「未保存」

- [ ] **Step 6: 确认函数长度**

```bash
python3 -c "
import ast, glob
for p in ['piswitch.py', 'dialogs.py'] + glob.glob('ui/*.py'):
    t = ast.parse(open(p).read())
    for n in ast.walk(t):
        if isinstance(n, ast.FunctionDef) and n.end_lineno - n.lineno + 1 >= 50:
            print(f'{n.end_lineno - n.lineno + 1:4d}  {p}:{n.name}')
"
```
Expected: 无输出

- [ ] **Step 7: 全量验证并提交**

```bash
python3 -m pytest -q && python3 smoke_gui.py && python3 audit_layout.py
git add dialogs.py piswitch.py ui/provider_list.py
git commit -m "refactor: 拆分 show_remote_models、_load_provider 与 App.__init__"
```

---

## Task 7: 跨模块私有调用收口

**Files:**
- Modify: `ui/form_guard.py`、`ui/model_ops.py`、`dialogs.py`
- Delete: `bench_startup.py`

**Interfaces:**
- Produces: `confirm_form_transition()`（原 `_confirm_form_transition`）、`refresh_provider_models(provider)`（原 `_refresh_provider_models`）

- [ ] **Step 1: 改名**

```bash
grep -rn "_confirm_form_transition\|_refresh_provider_models" --include=*.py .
```

把两个方法定义与全部调用点改成公开名。当前调用点：`dialogs.py:197`（恢复备份）、`dialogs.py:151` 与 `dialogs.py:265`（导入模型 / 编辑元数据）、`ui/provider_list.py` 内的选择转场、`ui/form_guard.py` 内的 `_on_close` 与 `request_refresh`。

- [ ] **Step 2: 确认没有残留的跨模块私有调用**

```bash
grep -rn "app\._" --include=*.py dialogs.py layout.py
```
Expected: 无输出。若有残留，一并评估是否该公开。

- [ ] **Step 3: 确认性能无退化后删除哨兵**

Run: `python3 bench_startup.py`
Expected: `App() + first paint` 不高于 160 ms，`refresh_providers` 不高于 2.6 ms/call

```bash
git rm bench_startup.py
```

- [ ] **Step 4: 更新 README 验证命令**

`README.md` 的 py_compile 行需加入 `ui/*.py`：

```bash
python3 -m py_compile piswitch.py dialogs.py layout.py audit_layout.py smoke_gui.py ui/*.py core/*.py
```

- [ ] **Step 5: 终局验证并提交**

```bash
python3 -m pytest -q && python3 smoke_gui.py && python3 audit_layout.py
python3 -m py_compile piswitch.py dialogs.py layout.py audit_layout.py smoke_gui.py ui/*.py core/*.py
bash -n bin/piswitch install.sh
wc -l piswitch.py layout.py dialogs.py ui/*.py core/*.py
git add -A
git commit -m "refactor: 跨模块调用改用公开 API"
```

Expected: 全绿；所有文件低于 400 行。

---

## 完成标准

| 项 | 目标 |
|---|---|
| `python3 -m pytest -q` | ≥ 245 passed（新增约 9 个纯函数用例） |
| `python3 smoke_gui.py` | `0 failure(s)` |
| `python3 audit_layout.py` | `0 个问题` |
| 最大文件行数 | < 400 |
| 最长函数行数 | < 50 |
| 一次 `refresh_providers` 的 `read_json` 次数 | 8 → 4 |
| 用户可见行为 | 无任何变化 |
