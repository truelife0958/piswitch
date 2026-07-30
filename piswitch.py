#!/usr/bin/env python3
"""Small GUI for managing custom pi model providers."""
from __future__ import annotations

import concurrent.futures
import os
import queue
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, simpledialog, ttk

import core
import dialogs
import layout
from core import mutation_timestamp


ICON_PATH = Path(__file__).resolve().parent / "assets" / "piswitch.png"
OAUTH_LABELS = {"logged_in": "(OAuth，已登录)", "expired": "(OAuth，已过期)"}
# Batch health checks run concurrently but stay modest: these are third-party gateways,
# and a burst of parallel requests is a good way to get rate-limited.
HEALTH_CHECK_WORKERS = 6
HEALTH_CHECK_TIMEOUT = 10



class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("piswitch")
        self.geometry("920x600")
        self.minsize(760, 500)
        self._window_icon = None
        if ICON_PATH.exists():
            try:
                self._window_icon = tk.PhotoImage(file=ICON_PATH)
                self.iconphoto(True, self._window_icon)
            except tk.TclError:
                pass

        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        # clam ships TButton with width=-11, i.e. "at least 11 characters wide", so every
        # button rendered 115px regardless of its label — five of them overflowed the
        # action row and packed 拉取模型 off-screen entirely. Sizing to the actual text
        # takes the row from 575px to ~419px, which fits with room to spare.
        style.configure("TButton", width=0, padding=(9, 4))

        self.current_provider: str | None = None
        # Facts about the current selection that action-button state derives from.
        self._current_is_builtin = False
        self._current_has_oauth = False
        self._current_is_hidden = False
        self.provider_var = tk.StringVar()
        self.name_var = tk.StringVar()
        self.base_url_var = tk.StringVar(value="https://")
        self.api_var = tk.StringVar(value=core.API_TYPES[0])
        self.api_key_var = tk.StringVar()
        self.key_status_var = tk.StringVar()
        self.show_key_var = tk.BooleanVar(value=False)
        self.status_var = tk.StringVar(value="就绪")
        self.show_hidden = tk.BooleanVar(value=False)  # show builtin providers the user hid
        self._network_results: queue.Queue = queue.Queue()
        self._network_busy = False
        # provider id -> last health-check cell text; survives refresh_providers redraws.
        self._health: dict[str, str] = {}

        self._build_ui()
        self.bind("<Control-n>", lambda _event: self.new_provider())
        self.bind("<Control-s>", lambda _event: self.save_provider())
        # Re-evaluate the $ENV_VAR indicator as the field is typed into.
        self.api_key_var.trace_add("write", lambda *_a: self._refresh_key_status())
        self.after(100, self._poll_network_results)
        self.refresh_providers()

    def _build_ui(self) -> None:
        layout.build(self)

    def _toggle_key_visibility(self) -> None:
        self.api_key_entry.configure(show="" if self.show_key_var.get() else "*")

    def _apply_action_states(self) -> None:
        """Push the derived enable/disable state onto every action button.

        Sole writer of action-button state: selection changes and network transitions both
        route through here, so they cannot leave contradictory states behind.
        """
        states = core.action_states(
            busy=self._network_busy,
            selected=bool(self.current_provider),
            builtin=self._current_is_builtin,
            has_oauth=self._current_has_oauth,
        )
        for key, button in self._action_buttons.items():
            button.configure(state="normal" if states[key] else "disabled")
        self.hide_builtin_button.configure(
            text="恢复显示" if self._current_is_hidden else "从列表移除"
        )
        # Batch check depends only on the network being idle, not on any selection.
        self.check_all_button.configure(state="disabled" if self._network_busy else "normal")

    def refresh_providers(self, select: str | None = None) -> None:
        custom = core.load_custom()
        auth = core.load_auth()
        store = core.load_models_store()
        custom_providers = custom["providers"]
        default_provider = core.load_settings().get("defaultProvider")
        self.provider_tree.delete(*self.provider_tree.get_children())

        def _insert(provider: str, config: dict, model_count: int) -> None:
            kind = core.auth_kind(provider, auth, custom)
            builtin = core.is_builtin_provider(provider, store)
            if kind == "oauth":
                state = core.auth_login_state(provider, auth)
                auth_label = "已登录" if state == "logged_in" else ("已过期" if state == "expired" else "OAuth")
            elif kind == "api_key":
                auth_label = "API Key"
            else:
                auth_label = "无"
            if builtin:
                auth_label = f"内置·{auth_label}" if auth_label != "无" else "内置"
            # ★ marks pi's current default provider; cheaper than an extra column.
            label = config.get("name") or provider
            if provider == default_provider:
                label = f"★ {label}"
            self.provider_tree.insert(
                "",
                "end",
                iid=provider,
                values=(provider, label, model_count, auth_label, self._health.get(provider, "")),
            )

        custom_count = 0
        for provider, config in sorted(custom_providers.items()):
            if not isinstance(config, dict):
                continue
            models = config.get("models", [])
            model_count = len(models) if isinstance(models, list) else 0
            _insert(provider, config, model_count)
            custom_count += 1

        # Then builtin providers not overridden by a custom entry of the same id.
        hidden = set() if self.show_hidden.get() else core.load_hidden_builtins()
        for provider, info in sorted(store.items()):
            if provider in custom_providers or not isinstance(info, dict):
                continue
            if provider in hidden:
                continue
            models = info.get("models", [])
            model_count = len(models) if isinstance(models, list) else 0
            _insert(provider, info, model_count)
        target = select or self.current_provider
        if target and self.provider_tree.exists(target):
            self.provider_tree.selection_set(target)
            self.provider_tree.focus(target)
            self.provider_tree.see(target)
            self._load_provider(target)
        elif not self.provider_tree.get_children():
            self.new_provider()
        else:
            first = self.provider_tree.get_children()[0]
            self.provider_tree.selection_set(first)
            self._load_provider(first)
        # The list holds builtins too, so report both counts rather than only the custom ones.
        builtin_count = len(self.provider_tree.get_children()) - custom_count
        self.status_var.set(f"已加载 {custom_count} 个自定义供应商，{builtin_count} 个内置")

    def _on_provider_selected(self, _event=None) -> None:
        selection = self.provider_tree.selection()
        if selection:
            self._load_provider(selection[0])

    def _load_provider(self, provider: str) -> None:
        custom = core.load_custom()
        auth = core.load_auth()
        store = core.load_models_store()
        config = custom["providers"].get(provider)
        builtin = core.is_builtin_provider(provider, store)
        if not isinstance(config, dict):
            # not custom — fall back to the builtin store entry (read-only)
            if not builtin:
                return
            config = store.get(provider, {})

        auth_entry = auth.get(provider)
        kind = core.auth_kind(provider, auth, custom)
        self.current_provider = provider
        self._current_is_builtin = builtin
        # Logout / delete-credentials needs an actual OAuth entry to clear.
        self._current_has_oauth = (
            kind == "oauth" and isinstance(auth_entry, dict) and bool(auth_entry)
        )
        self._current_is_hidden = builtin and provider in core.load_hidden_builtins()

        self.provider_var.set(provider)
        self.name_var.set(config.get("name") or provider)
        self.base_url_var.set(config.get("baseUrl", ""))
        self.api_var.set(config.get("api", core.API_TYPES[0]))
        if kind == "oauth":
            # OAuth access tokens are extension-managed; show read-only status instead.
            self.api_key_var.set(OAUTH_LABELS.get(core.auth_login_state(provider, auth), "(OAuth)"))
        elif kind == "api_key":
            auth_key = auth_entry.get("key") if isinstance(auth_entry, dict) else ""
            self.api_key_var.set(auth_key or config.get("apiKey", ""))
        else:
            self.api_key_var.set(config.get("apiKey", ""))

        # Builtin providers are read-only: lock the form and label the store's own values.
        if builtin:
            self.name_var.set(config.get("name") or f"{provider} (内置)")
            self.base_url_var.set(config.get("baseUrl") or "(内置)")
        self.provider_entry.configure(state="disabled" if builtin else "normal")
        self.api_key_entry.configure(
            state="normal" if not builtin and kind != "oauth" else "disabled"
        )
        self._apply_action_states()
        self._refresh_models(config)

    def _refresh_models(self, config: dict) -> None:
        self.model_tree.delete(*self.model_tree.get_children())
        models = config.get("models", [])
        if not isinstance(models, list):
            return
        settings = core.load_settings()
        default_provider = settings.get("defaultProvider")
        default_model = settings.get("defaultModel")
        for index, model in enumerate(models):
            if not isinstance(model, dict) or not model.get("id"):
                continue
            is_default = self.current_provider == default_provider and model["id"] == default_model
            self.model_tree.insert(
                "",
                "end",
                iid=str(index),
                values=(
                    "★" if is_default else "",
                    model["id"],
                    model.get("name", model["id"]),
                    core.format_context_window(model.get("contextWindow")),
                    "是" if model.get("reasoning") else "否",
                ),
            )

    def _refresh_key_status(self) -> None:
        """Show whether a `$ENV_VAR` key would actually resolve, without waiting for a request."""
        state, variable = core.api_key_status(self.api_key_var.get())
        self.key_status_var.set({
            "env_set": f"✓ 环境变量 ${variable} 已设置",
            "env_missing": f"✗ 环境变量 ${variable} 未设置——请求时会失败",
            "invalid": "✗ $ 后缺少变量名",
        }.get(state, ""))

    def _on_model_double_click(self, event) -> str | None:
        if not self.model_tree.identify_row(event.y):
            return None
        # The 默认 column doubles as the set-default hit area; elsewhere edits metadata.
        if self.model_tree.identify_column(event.x) == "#1":
            self.set_default()
        else:
            self.edit_model()
        return "break"

    def edit_model(self) -> None:
        """Edit a model's metadata — the numbers pi uses for context limits and cost."""
        provider = self.current_provider
        selection = self.model_tree.selection() or (
            (self.model_tree.focus(),) if self.model_tree.focus() else ()
        )
        if not provider or not selection:
            messagebox.showinfo("编辑模型", "请先选中一个模型")
            return
        if core.is_builtin_provider(provider, core.load_models_store()):
            messagebox.showinfo("编辑模型", f"{provider} 是内置供应商，不可修改")
            return
        model_id = self.model_tree.set(selection[0], "id")
        models = core.load_custom()["providers"].get(provider, {}).get("models", [])
        model = next(
            (m for m in models if isinstance(m, dict) and m.get("id") == model_id), None
        )
        if model is None:
            messagebox.showerror("编辑模型", f"模型 {model_id} 已不存在")
            return
        self._open_model_editor(provider, model)

    def _open_model_editor(self, provider: str, model: dict) -> None:
        dialogs.open_model_editor(self, provider, model)

    def set_default(self) -> None:
        """Point pi at the selected model. This is what the tool is named after."""
        provider = self.current_provider
        if not provider:
            messagebox.showinfo("设为默认", "请先选中一个供应商")
            return
        selection = self.model_tree.selection() or ((self.model_tree.focus(),)
                                                    if self.model_tree.focus() else ())
        if not selection:
            messagebox.showinfo("设为默认", "请先选中一个模型")
            return
        if len(selection) > 1:
            messagebox.showinfo("设为默认", "请只选中一个模型")
            return
        model_id = self.model_tree.set(selection[0], "id")
        if core.is_default_model(provider, model_id):
            self.status_var.set(f"{provider}/{model_id} 已经是 pi 默认模型")
            return
        try:
            core.set_default_model(provider, model_id, ts=mutation_timestamp())
        except (OSError, ValueError) as exc:
            messagebox.showerror("设为默认失败", str(exc))
            return
        self.refresh_providers(select=provider)
        self.status_var.set(f"pi 默认模型 → {provider}/{model_id}")

    def new_provider(self) -> None:
        self.current_provider = None
        self._current_is_builtin = False
        self._current_has_oauth = False
        self._current_is_hidden = False
        selection = self.provider_tree.selection()
        if selection:
            self.provider_tree.selection_remove(*selection)
        self.provider_entry.configure(state="normal")
        # Re-enable the key field: it is left disabled by an OAuth or builtin selection.
        self.api_key_entry.configure(state="normal")
        self.provider_var.set("")
        self.name_var.set("")
        self.base_url_var.set("https://")
        self.api_var.set(core.API_TYPES[0])
        self.api_key_var.set("")
        self.model_tree.delete(*self.model_tree.get_children())
        self._apply_action_states()  # new-provider mode: save/test on, per-provider actions off
        self.provider_entry.focus_set()
        self.status_var.set("填写供应商信息后保存")

    def new_from_template(self) -> None:
        dialogs.choose_template(self)

    def apply_template_values(self, values: dict) -> None:
        """Seed the form from a template, as a brand-new unsaved provider."""
        self.new_provider()
        self.provider_var.set(values["provider"])
        self.name_var.set(values["name"])
        self.base_url_var.set(values["baseUrl"])
        self.api_var.set(values["api"])
        self.api_key_var.set(values["apiKey"])
        self._apply_action_states()
        self.status_var.set(f"已套用模板 {values['name']}——确认 Base URL 与 Key 后保存")

    def save_provider(self) -> None:
        provider = self.provider_var.get().strip()
        if core.is_builtin_provider(provider, core.load_models_store()):
            messagebox.showerror("保存失败", f"{provider} 是内置供应商，不能覆盖或保存。")
            return
        if not self.current_provider and provider in core.load_custom()["providers"]:
            messagebox.showerror("保存失败", f"Provider ID {provider} 已存在，请从左侧选择后编辑")
            return
        original_provider = self.current_provider
        try:
            core.save_custom_provider(
                provider,
                self.name_var.get(),
                self.base_url_var.get(),
                self.api_var.get(),
                self.api_key_var.get(),
                ts=mutation_timestamp(),
                original_provider=original_provider,
            )
        except (OSError, ValueError) as exc:
            messagebox.showerror("保存失败", str(exc))
            return
        self.current_provider = provider
        self.refresh_providers(select=provider)
        self.status_var.set(f"已保存供应商 {provider}")

    def _set_network_busy(self, busy: bool) -> None:
        self._network_busy = busy
        self._apply_action_states()

    def _run_network(self, status: str, action, on_success) -> None:
        if self._network_busy:
            return
        self._set_network_busy(True)
        self.status_var.set(status)

        def worker() -> None:
            try:
                result = action()
            except Exception as exc:  # noqa: BLE001 - converted to a GUI error on the main thread
                self._network_results.put((None, exc))
            else:
                self._network_results.put((lambda: on_success(result), None))

        threading.Thread(target=worker, daemon=True).start()

    def _poll_network_results(self) -> None:
        try:
            while True:
                callback, error = self._network_results.get_nowait()
                self._set_network_busy(False)
                if error is not None:
                    self.status_var.set("连接失败")
                    messagebox.showerror("连接失败", str(error))
                elif callback is not None:
                    callback()
        except queue.Empty:
            pass
        self.after(100, self._poll_network_results)

    def _fetch_action_from_form(self):
        base_url = self.base_url_var.get()
        api_key = self.api_key_var.get()
        return lambda: core.fetch_remote_models(base_url, api_key, timeout=20)

    def _selected_model_id(self) -> str:
        selection = self.model_tree.selection() or (
            (self.model_tree.focus(),) if self.model_tree.focus() else ()
        )
        if selection:
            return self.model_tree.set(selection[0], "id")
        rows = self.model_tree.get_children()
        return self.model_tree.set(rows[0], "id") if rows else ""

    def test_connection(self) -> None:
        """List models, then send one real 1-token completion.

        A proxy that answers /v1/models can still reject real completions — that gap is
        why backfill_proxy_compat exists, and listing alone never revealed it.
        """
        base_url = self.base_url_var.get()
        api_key = self.api_key_var.get()
        api = self.api_var.get()
        preferred = self._selected_model_id()

        def action():
            models = core.fetch_remote_models(base_url, api_key, timeout=20)
            if not core.supports_chat_probe(api):
                return (models, None, f"{api} 不支持对话探测，仅验证了模型接口。")
            probe_model = preferred or (models[0]["id"] if models else "")
            if not probe_model:
                return (models, None, "接口未返回模型，无法进行对话探测。")
            try:
                core.probe_chat(base_url, api, probe_model, api_key, timeout=20)
            except ValueError as exc:
                return (models, False, f"对话失败（{probe_model}）：{exc}")
            return (models, True, f"对话正常（{probe_model}）。")

        def success(result) -> None:
            models, chat_ok, note = result
            if chat_ok is False:
                self.status_var.set("模型接口可用，但对话失败")
                messagebox.showwarning(
                    "对话测试失败",
                    f"模型接口可用，共 {len(models)} 个模型。\n\n{note}",
                )
                return
            self.status_var.set(f"连接成功，发现 {len(models)} 个模型")
            messagebox.showinfo("连接成功", f"共发现 {len(models)} 个模型。\n{note}")

        self._run_network("正在测试模型接口与对话…", action, success)

    def check_all_providers(self) -> None:
        """Health-check every listed provider using the free /v1/models endpoint.

        Deliberately shallow: a real completion costs tokens, so that stays on
        测试连接 for one provider at a time. Results are display-only — nothing is written.
        """
        custom = core.load_custom()
        auth = core.load_auth()
        store = core.load_models_store()
        custom_providers = custom["providers"]
        targets = [
            (provider, cfg) for provider, cfg in sorted(custom_providers.items())
            if isinstance(cfg, dict)
        ]
        hidden = set() if self.show_hidden.get() else core.load_hidden_builtins()
        for provider, info in sorted(store.items()):
            if provider in custom_providers or not isinstance(info, dict):
                continue
            if provider in hidden:
                continue
            targets.append((provider, info))
        if not targets:
            messagebox.showinfo("检查全部", "没有可检查的供应商。")
            return

        def action():
            with concurrent.futures.ThreadPoolExecutor(max_workers=HEALTH_CHECK_WORKERS) as pool:
                return list(pool.map(
                    lambda item: core.probe_provider(
                        item[0], item[1], auth, timeout=HEALTH_CHECK_TIMEOUT,
                    ),
                    targets,
                ))

        self._run_network(f"正在检查 {len(targets)} 个供应商…", action, self._show_health_results)

    def _show_health_results(self, results: list[dict]) -> None:
        ok_count = 0
        for result in results:
            provider = result.get("provider")
            if result.get("ok"):
                ok_count += 1
                cell = f"✓ {result.get('latency_ms', 0)}ms"
            else:
                cell = "✗ 失败"
            self._health[provider] = cell
            if self.provider_tree.exists(provider):
                self.provider_tree.set(provider, "health", cell)
        failed = [r for r in results if not r.get("ok")]
        self.status_var.set(f"检查完成：{ok_count} 通过，{len(failed)} 失败")
        if failed:
            lines = "\n".join(f"{r['provider']}：{r['detail']}" for r in failed[:12])
            if len(failed) > 12:
                lines += f"\n… 共 {len(failed)} 个失败"
            messagebox.showwarning("部分供应商不可用", lines)

    def fetch_models(self) -> None:
        if not self.current_provider:
            messagebox.showinfo("拉取模型", "请先保存供应商")
            return
        provider = self.current_provider
        self._run_network(
            "正在拉取模型列表…",
            self._fetch_action_from_form(),
            lambda models: self._show_remote_models(models, provider),
        )

    def _show_remote_models(self, models: list[dict], provider: str) -> None:
        dialogs.show_remote_models(self, models, provider)

    def delete_provider(self) -> None:
        provider = self.current_provider
        if not provider:
            return
        if core.is_builtin_provider(provider, core.load_models_store()):
            messagebox.showinfo("无法删除", f"{provider} 是内置供应商，不能删除。\n可用左侧“从列表移除”把它从本列表中隐藏，或用“退出登录”移除其凭据。")
            return
        prompt = f"删除 {provider} 及其模型和 API key？"
        if core.is_default_provider(provider):
            prompt = (
                f"{provider} 是 pi 当前默认供应商。\n\n"
                "删除后默认模型将不可用，建议先在 pi 中切换默认模型。\n\n"
                "仍然删除？"
            )
        if not messagebox.askyesno("删除供应商", prompt):
            return
        try:
            core.delete_custom_provider(provider, ts=mutation_timestamp())
        except OSError as exc:
            messagebox.showerror("删除失败", str(exc))
            return
        self.current_provider = None
        self.refresh_providers()
        self.status_var.set(f"已删除供应商 {provider}")

    def logout_provider(self) -> None:
        provider = self.current_provider
        if not provider:
            return
        auth = core.load_auth()
        entry = auth.get(provider)
        if not isinstance(entry, dict) or not entry:
            messagebox.showinfo("退出登录", f"{provider} 当前没有存储的凭据")
            return
        kind = core.auth_kind(provider, auth, core.load_custom())
        noun = "OAuth 凭据" if kind == "oauth" else "API Key"
        prompt = f"删除 {provider} 的{noun}?\n\n这将仅清除凭据,保留该供应商的模型配置。"
        if kind == "oauth":
            prompt += (
                "\n之后需重新走 pi /login 流程来重新登录(由该供应商的扩展负责)。"
            )
        if not messagebox.askyesno("退出登录", prompt):
            return
        try:
            removed = core.delete_provider_credentials(provider, ts=mutation_timestamp())
        except OSError as exc:
            messagebox.showerror("退出登录失败", str(exc))
            return
        if not removed:
            messagebox.showinfo("退出登录", "未发生变化")
            return
        self.refresh_providers(select=provider)
        self.status_var.set(f"已退出登录 {provider}")


    def toggle_hide_builtin(self) -> None:
        """Hide or unhide a builtin provider from the piswitch list (models-store is left untouched)."""
        provider = self.current_provider
        if not provider:
            return
        store = core.load_models_store()
        if not core.is_builtin_provider(provider, store):
            messagebox.showinfo("不适用", f"{provider} 不是内置供应商。")
            return
        hidden = core.load_hidden_builtins()
        if provider in hidden:
            core.unhide_builtin(provider)
            self.refresh_providers(select=provider)
            self.status_var.set(f"已恢复显示 {provider}")
        else:
            core.hide_builtin(provider)
            self.refresh_providers()
            self.status_var.set(f"已从列表移除 {provider}（勾选顶部“显示隐藏”可重新显示）")

    def add_models(self) -> None:
        provider = self.current_provider
        if not provider:
            messagebox.showinfo("增加模型", "请先保存供应商")
            return
        if core.is_builtin_provider(provider, core.load_models_store()):
            messagebox.showinfo("增加模型", f"{provider} 是内置供应商，不可修改")
            return
        model_ids = simpledialog.askstring("增加模型", "Model ID（多个用逗号分隔）：", parent=self)
        if model_ids is None:
            return
        try:
            # A hand-typed id may already be described in models-store.json.
            store = core.load_models_store()
            metadata = {}
            for model_id in core.parse_model_ids(model_ids):
                inferred = core.builtin_model_metadata(model_id, store)
                if inferred:
                    metadata[model_id] = inferred
            core.add_provider_models(
                provider, model_ids, ts=mutation_timestamp(), metadata=metadata
            )
        except (OSError, ValueError) as exc:
            messagebox.showerror("增加失败", str(exc))
            return
        self.refresh_providers(select=provider)
        self.status_var.set(f"已更新 {provider} 的模型")

    def delete_model(self) -> None:
        provider = self.current_provider
        selection = self.model_tree.selection()
        if not provider or not selection:
            messagebox.showinfo("删除模型", "请先选中一个模型")
            return
        if core.is_builtin_provider(provider, core.load_models_store()):
            messagebox.showinfo("删除模型", f"{provider} 是内置供应商，不可修改")
            return
        # Column-name access, not positional: the tree gained 默认/上下文 columns and a
        # positional read here would silently return the wrong field.
        model_ids = [self.model_tree.set(iid, "id") for iid in selection]
        count = len(model_ids)
        # Warn if any selected model is currently the pi default.
        default_hits = [mid for mid in model_ids if core.is_default_model(provider, mid)]
        if count == 1:
            prompt = f"从 {provider} 删除模型 {model_ids[0]}？"
        else:
            prompt = f"从 {provider} 删除 {count} 个模型？\n" + "\n".join(model_ids[:10])
            if len(model_ids) > 10:
                prompt += f"\n… 共 {count} 个"
        if default_hits:
            prompt += (
                f"\n\n其中 {len(default_hits)} 个是 pi 当前默认模型。"
                "\n删除后默认模型将不可用，建议先在 pi 中切换默认模型。\n\n"
                "仍然删除？"
            )
        if not messagebox.askyesno("删除模型", prompt):
            return
        try:
            if count == 1:
                core.delete_provider_model(provider, model_ids[0], ts=mutation_timestamp())
            else:
                core.delete_provider_models(provider, model_ids, ts=mutation_timestamp())
        except OSError as exc:
            messagebox.showerror("删除失败", str(exc))
            return
        self.refresh_providers(select=provider)
        self.status_var.set(f"已删除 {count} 个模型")

    def clear_models(self) -> None:
        provider = self.current_provider
        if not provider:
            messagebox.showinfo("清空模型", "请先选中一个供应商")
            return
        if core.is_builtin_provider(provider, core.load_models_store()):
            messagebox.showinfo("清空模型", f"{provider} 是内置供应商，不可清空")
            return
        current = core.load_custom().get("providers", {}).get(provider, {}).get("models", [])
        n = len(current) if isinstance(current, list) else 0
        if n == 0:
            self.status_var.set(f"{provider} 已无模型")
            return
        prompt = f"清空 {provider} 的全部 {n} 个模型？"
        # The pi default model may live under this provider.
        default_id = None
        settings = core.load_settings() or {}
        if settings.get("defaultProvider") == provider:
            default_id = settings.get("defaultModel")
        if default_id:
            prompt += (
                f"\n\n{default_id} 是 pi 当前默认模型。"
                "\n清空后默认模型将不可用，建议先在 pi 中切换默认模型。\n\n仍然清空？"
            )
        else:
            prompt += "\n\n此操作不可撤销。仍然清空？"
        if not messagebox.askyesno("清空模型", prompt):
            return
        try:
            removed = core.clear_provider_models(provider, ts=mutation_timestamp())
        except OSError as exc:
            messagebox.showerror("清空失败", str(exc))
            return
        self.refresh_providers(select=provider)
        self.status_var.set(f"已清空 {removed} 个模型")

    def export_config(self) -> None:
        dialogs.export_config(self)

    def import_config(self) -> None:
        dialogs.import_config(self)

    def open_backup_restore(self) -> None:
        dialogs.open_backup_restore(self)


def main() -> None:
    result = core.dispatch(sys.argv[1:])
    if result is not None:
        raise SystemExit(result)
    try:
        app = App()
    except tk.TclError as exc:
        if os.environ.get("PISWITCH_DEBUG"):
            raise
        print(f"[piswitch] 无法启动 GUI: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    except (OSError, ValueError) as exc:
        # A malformed models.json / auth.json otherwise dies with a bare traceback —
        # precisely when the user needs to be told where the backups live.
        if os.environ.get("PISWITCH_DEBUG"):
            raise
        message = (
            f"读取 pi 配置失败：{exc}\n\n"
            f"请修复上述文件，或从备份目录手动恢复：\n{core.switch_backups_dir()}"
        )
        print(f"[piswitch] {message}", file=sys.stderr)
        try:
            messagebox.showerror("piswitch 无法启动", message)
        except tk.TclError:
            pass
        raise SystemExit(1) from exc
    app.mainloop()


if __name__ == "__main__":
    main()
