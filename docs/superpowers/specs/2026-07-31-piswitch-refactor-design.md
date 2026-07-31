# piswitch 结构重构设计

日期：2026-07-31
状态：已确认，待实施

## 背景

`piswitch.py` 已长到 960 行（`App` 类占 899 行、48 个方法），超出项目编码标准的 800 行上限；`layout.py:build` 220 行、`dialogs.py:show_remote_models` 143 行远超 50 行的函数上限。

性能已实测，**不是问题**，不在本次范围内：

```
import modules          42.2 ms
App() + first paint    153.2 ms   (13 个供应商)
refresh_providers       2.44 ms/call
_render_provider_rows   0.12 ms/call
filter 3 keystrokes     0.35 ms/call
```

但 profile 暴露了一个结构问题：20 次 `refresh_providers` 触发 160 次 `read_json`——每次刷新把同一批 JSON 重读 8 遍。这按异味处理，不按性能处理。

## 目标

1. 每个文件回到 200–400 行区间，无文件超过 800 行
2. 无函数超过 50 行
3. 现在被困在 Tk 窗口里的纯推导逻辑变得可无头单测
4. 消除一次刷新内的重复文件读取
5. 消除跨模块的私有方法调用

**非目标**：性能优化、行为变更、新功能。本次重构全程行为不变。

## 一、纯逻辑下沉到 `core/uistate.py`

`refresh_providers` 内的 `_insert` 闭包及其两个循环是纯推导——auth 标签、内置合并、★ 默认标记、自定义覆盖内置的优先级——却因为写在 `App` 方法里而只能通过构造真实窗口来测试。

提成纯函数：

```python
def provider_rows(custom, auth, store, *, default_provider,
                  health, hidden, show_hidden) -> list[dict]:
    """返回 [{"provider": str, "builtin": bool, "values": tuple}, ...]"""
```

`auth_label` 的推导（`已登录`/`已过期`/`OAuth`/`API Key`/`无`，以及 `内置·` 前缀）单独提成 `auth_label(provider, auth, custom, *, builtin) -> str`：五个分支加一条前缀规则，值得独立测试。

**效果**：`refresh_providers` 71 → 约 25 行；约 50 行推导逻辑获得单测覆盖。

## 二、`core.load_snapshot()` 消除重复读

`refresh_providers` 读 custom/auth/store/settings 之后调用 `_load_provider`，后者把同样三个文件再读一遍。

新增：

```python
def load_snapshot() -> Snapshot:   # custom / auth / store / settings 各读一次
```

向下传递而非各自重读。一次刷新 8 次读 → 1 次。

**这是清异味不是提性能**——省下的 2.4ms 用户感知不到。

## 三、`ui/` 五个 mixin

`App(FormGuardMixin, ProviderListMixin, ModelOpsMixin, NetworkMixin, ProviderCrudMixin, tk.Tk)`

选择 mixin 而非协作对象：与现有架构一致，`dialogs.py` 的调用点不必改写，diff 可控。代价是边界靠约定而非强制——各 mixin 仍通过 `self` 共享状态，这一点在评审时需要留意。

| 模块 | 方法 | 预估行数 |
|---|---|---|
| `ui/form_guard.py` | `_capture_form_state` `_on_form_changed` `_mark_form_clean` `_confirm_form_transition` `_restore_provider_selection` `_on_close` `request_refresh` `_toggle_key_visibility` | ~70 |
| `ui/provider_list.py` | `_render_provider_rows` `refresh_providers` `_on_provider_selected` `_load_provider` `_apply_action_states` `_refresh_key_status` `toggle_show_hidden` `_on_provider_filter_changed` | ~165 |
| `ui/model_ops.py` | `_refresh_models` `_on_model_filter_changed` `_on_model_double_click` `edit_model` `_open_model_editor` `set_default` `add_models` `delete_model` `clear_models` `_refresh_provider_models` `_selected_model_id` | ~235 |
| `ui/network.py` | `_set_network_busy` `_run_network` `_poll_network_results` `_fetch_action_from_form` `test_connection` `check_all_providers` `_show_health_results` `fetch_models` `_show_remote_models` | ~155 |
| `ui/provider_crud.py` | `_reset_new_provider_form` `new_provider` `new_from_template` `apply_template_values` `save_provider` `delete_provider` `logout_provider` `toggle_hide_builtin` `export_config` `import_config` `open_backup_restore` | ~175 |
| `piswitch.py` | `App` 组装、`__init__`、`_build_ui`、`main()` | ~140 |

## 四、超长函数拆分

| 函数 | 现状 | 拆法 |
|---|---|---|
| `layout.py:build` | 220 | `_build_provider_pane` / `_build_form` / `_build_model_pane` / `_build_menus` |
| `dialogs.py:show_remote_models` | 143 | 抽出选择状态管理与行渲染 |
| `piswitch.py:__init__` | 71 | 变量声明与事件绑定分成两个私有方法 |
| `piswitch.py:refresh_providers` | 71 | 由第一节的下沉自然降到 ~25 |
| `piswitch.py:_load_provider` | 60 | 由第二节的快照自然降到 ~45，仍需再拆表单回填一段 |

## 五、跨模块私有调用收口

`dialogs.py` 目前调用 `app._confirm_form_transition()` 与 `app._refresh_provider_models()`——跨文件访问私有方法。改为公开名（`confirm_form_transition` / `refresh_provider_models`），调用点同步更新。

## 六、安全网

行为不变是硬约束。每一步提交前必须全绿：

```bash
python3 -m pytest -q                    # 237 passed
python3 smoke_gui.py                    # 0 failure(s)
python3 audit_layout.py                 # 0 个问题
python3 -m py_compile piswitch.py dialogs.py layout.py ui/*.py core/*.py
```

第一节下沉的纯函数需补单测，写进 `tests/test_helpers.py`——现有 `uistate` 的测试（`text_matches_query`、`hidden_builtins`）都在那里，不另开文件。覆盖：自定义覆盖同名内置、内置隐藏、★ 默认标记、四种 auth 标签、health 列沿用。

`bench_startup.py` 在重构期间保留作回归哨兵，确认耗时无退化后删除。

## 七、提交拆分

| # | 内容 | 可独立回滚 |
|---|---|---|
| ① | `core.provider_rows` 下沉 + `load_snapshot` + 新单测 | 是 |
| ② | `ui/` 五个 mixin 拆分 | 是 |
| ③ | 超长函数拆分（layout / dialogs / `__init__`） | 是 |
| ④ | 私有调用收口 + 删除 `bench_startup.py` | 是 |

每次提交都独立通过第六节的全部检查。
