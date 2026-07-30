#!/usr/bin/env python3
"""Small GUI for managing custom pi model providers."""
from __future__ import annotations

import os
import queue
import sys
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import messagebox, simpledialog, ttk

import core


API_TYPES = (
    "openai-completions",
    "openai-responses",
    "anthropic-messages",
    "google-generative-ai",
    "mistral-conversations",
    "google-vertex",
    "azure-openai-responses",
    "openai-codex-responses",
    "bedrock-converse-stream",
)
ICON_PATH = Path(__file__).resolve().parent / "assets" / "piswitch.png"
OAUTH_LABELS = {"logged_in": "(OAuth，已登录)", "expired": "(OAuth，已过期)"}


def mutation_timestamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S-%f")


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

        self.current_provider: str | None = None
        # Facts about the current selection that action-button state derives from.
        self._current_is_builtin = False
        self._current_has_oauth = False
        self._current_is_hidden = False
        self.provider_var = tk.StringVar()
        self.name_var = tk.StringVar()
        self.base_url_var = tk.StringVar(value="https://")
        self.api_var = tk.StringVar(value=API_TYPES[0])
        self.api_key_var = tk.StringVar()
        self.key_status_var = tk.StringVar()
        self.show_key_var = tk.BooleanVar(value=False)
        self.status_var = tk.StringVar(value="就绪")
        self.show_hidden = tk.BooleanVar(value=False)  # show builtin providers the user hid
        self._network_results: queue.Queue = queue.Queue()
        self._network_busy = False

        self._build_ui()
        self.bind("<Control-n>", lambda _event: self.new_provider())
        self.bind("<Control-s>", lambda _event: self.save_provider())
        # Re-evaluate the $ENV_VAR indicator as the field is typed into.
        self.api_key_var.trace_add("write", lambda *_a: self._refresh_key_status())
        self.after(100, self._poll_network_results)
        self.refresh_providers()

    def _build_ui(self) -> None:
        toolbar = ttk.Frame(self, padding=(10, 8))
        toolbar.pack(fill="x")
        ttk.Label(toolbar, text="自定义模型供应商", font=("TkDefaultFont", 13, "bold")).pack(side="left")
        ttk.Button(toolbar, text="新增", command=self.new_provider).pack(side="right", padx=(6, 0))
        ttk.Checkbutton(toolbar, text="显示隐藏", variable=self.show_hidden, command=self.refresh_providers).pack(side="right", padx=(6, 0))
        ttk.Button(toolbar, text="刷新", command=self.refresh_providers).pack(side="right")
        ttk.Button(toolbar, text="恢复备份", command=self.open_backup_restore).pack(side="right", padx=6)

        pane = ttk.PanedWindow(self, orient="horizontal")
        pane.pack(fill="both", expand=True, padx=10, pady=(0, 8))

        left = ttk.Frame(pane, padding=(0, 4, 8, 4))
        right = ttk.Frame(pane, padding=(8, 4, 0, 4))
        pane.add(left, weight=2)
        pane.add(right, weight=3)

        self.provider_tree = ttk.Treeview(
            left,
            columns=("provider", "name", "models", "auth"),
            show="headings",
            selectmode="browse",
        )
        headings = (
            ("provider", "Provider ID", 120),
            ("name", "名称", 105),
            ("models", "模型", 42),
            ("auth", "验证", 66),
        )
        for column, title, width in headings:
            self.provider_tree.heading(column, text=title)
            self.provider_tree.column(column, width=width, minwidth=40, anchor="w")
        provider_scroll = ttk.Scrollbar(left, orient="vertical", command=self.provider_tree.yview)
        self.provider_tree.configure(yscrollcommand=provider_scroll.set)
        self.provider_tree.pack(side="left", fill="both", expand=True)
        provider_scroll.pack(side="right", fill="y")
        self.provider_tree.bind("<<TreeviewSelect>>", self._on_provider_selected)

        form = ttk.Frame(right)
        form.pack(fill="x")
        form.columnconfigure(1, weight=1)
        fields = (
            ("Provider ID", self.provider_var),
            ("显示名称", self.name_var),
            ("Base URL", self.base_url_var),
        )
        for row, (label, variable) in enumerate(fields):
            ttk.Label(form, text=label).grid(row=row, column=0, sticky="w", padx=(0, 10), pady=5)
            entry = ttk.Entry(form, textvariable=variable)
            entry.grid(row=row, column=1, columnspan=2, sticky="ew", pady=5)
            if row == 0:
                self.provider_entry = entry

        ttk.Label(form, text="API 类型").grid(row=3, column=0, sticky="w", padx=(0, 10), pady=5)
        ttk.Combobox(form, textvariable=self.api_var, values=API_TYPES, state="readonly").grid(
            row=3, column=1, columnspan=2, sticky="ew", pady=5
        )

        ttk.Label(form, text="API Key").grid(row=4, column=0, sticky="w", padx=(0, 10), pady=5)
        self.api_key_entry = ttk.Entry(form, textvariable=self.api_key_var, show="*")
        self.api_key_entry.grid(row=4, column=1, sticky="ew", pady=5)
        ttk.Checkbutton(
            form,
            text="显示",
            variable=self.show_key_var,
            command=self._toggle_key_visibility,
        ).grid(row=4, column=2, sticky="e", padx=(8, 0))
        self.key_status_label = ttk.Label(form, textvariable=self.key_status_var, anchor="w")
        self.key_status_label.grid(row=5, column=1, columnspan=2, sticky="w", pady=(0, 2))

        actions = ttk.Frame(right)
        actions.pack(fill="x", pady=(10, 14))
        self.save_provider_button = ttk.Button(actions, text="保存供应商", command=self.save_provider)
        self.save_provider_button.pack(side="left")
        self.test_connection_button = ttk.Button(actions, text="测试连接", command=self.test_connection)
        self.test_connection_button.pack(side="left", padx=(8, 0))
        self.delete_provider_button = ttk.Button(actions, text="删除供应商", command=self.delete_provider)
        self.delete_provider_button.pack(side="left", padx=8)
        self.logout_provider_button = ttk.Button(actions, text="退出登录", command=self.logout_provider)
        self.logout_provider_button.pack(side="left", padx=8)
        self.hide_builtin_button = ttk.Button(actions, text="从列表移除", command=self.toggle_hide_builtin)
        self.hide_builtin_button.pack(side="left", padx=8)
        self._action_buttons = {
            "save": self.save_provider_button,
            "test": self.test_connection_button,
            "delete_provider": self.delete_provider_button,
            "logout": self.logout_provider_button,
            "hide_builtin": self.hide_builtin_button,
        }

        model_header = ttk.Frame(right)
        model_header.pack(fill="x", pady=(2, 6))
        ttk.Label(model_header, text="模型", font=("TkDefaultFont", 11, "bold")).pack(side="left")
        self.set_default_button = ttk.Button(model_header, text="设为默认", command=self.set_default)
        self.set_default_button.pack(side="left", padx=(10, 0))
        self.clear_models_button = ttk.Button(model_header, text="清空", command=self.clear_models)
        self.clear_models_button.pack(side="right")
        self.delete_model_button = ttk.Button(model_header, text="删除模型", command=self.delete_model)
        self.delete_model_button.pack(side="right", padx=6)
        self.add_model_button = ttk.Button(model_header, text="增加模型", command=self.add_models)
        self.add_model_button.pack(side="right", padx=6)
        self.fetch_model_button = ttk.Button(model_header, text="拉取模型", command=self.fetch_models)
        self.fetch_model_button.pack(side="right")
        self._action_buttons.update({
            "add_model": self.add_model_button,
            "delete_model": self.delete_model_button,
            "clear_models": self.clear_models_button,
            "fetch_models": self.fetch_model_button,
            "set_default": self.set_default_button,
        })

        model_area = ttk.Frame(right)
        model_area.pack(fill="both", expand=True)
        self.model_tree = ttk.Treeview(
            model_area,
            columns=("default", "id", "name", "context", "reasoning"),
            show="headings",
            selectmode="extended",
        )
        for column, title, width in (
            ("default", "默认", 42),
            ("id", "Model ID", 196),
            ("name", "名称", 124),
            ("context", "上下文", 72),
            ("reasoning", "推理", 46),
        ):
            self.model_tree.heading(column, text=title)
            self.model_tree.column(column, width=width, minwidth=40, anchor="w")
        self.model_tree.column("default", anchor="center", stretch=False)
        model_scroll = ttk.Scrollbar(model_area, orient="vertical", command=self.model_tree.yview)
        self.model_tree.configure(yscrollcommand=model_scroll.set)
        self.model_tree.pack(side="left", fill="both", expand=True)
        model_scroll.pack(side="right", fill="y")
        # Double-click a model row to point pi at it.
        self.model_tree.bind("<Double-Button-1>", self._on_model_double_click)

        ttk.Label(self, textvariable=self.status_var, anchor="w", relief="sunken", padding=(8, 4)).pack(fill="x")

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
                values=(provider, label, model_count, auth_label),
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
        self.api_var.set(config.get("api", API_TYPES[0]))
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
        win = tk.Toplevel(self)
        win.title(f"编辑模型 {model['id']}")
        win.transient(self)
        body = ttk.Frame(win, padding=(12, 12, 12, 6))
        body.pack(fill="both", expand=True)
        body.columnconfigure(1, weight=1)

        cost = model.get("cost") if isinstance(model.get("cost"), dict) else {}

        def text_of(value) -> str:
            return "" if value in (None, "") else str(value)

        fields = (
            ("名称", "name", tk.StringVar(value=text_of(model.get("name") or model["id"]))),
            ("上下文窗口", "contextWindow", tk.StringVar(value=text_of(model.get("contextWindow")))),
            ("最大输出 tokens", "maxTokens", tk.StringVar(value=text_of(model.get("maxTokens")))),
            ("输入价格 /百万", "costInput", tk.StringVar(value=text_of(cost.get("input", 0)))),
            ("输出价格 /百万", "costOutput", tk.StringVar(value=text_of(cost.get("output", 0)))),
        )
        for index, (label, _key, variable) in enumerate(fields):
            ttk.Label(body, text=label).grid(row=index, column=0, sticky="w", padx=(0, 10), pady=4)
            ttk.Entry(body, textvariable=variable, width=26).grid(
                row=index, column=1, sticky="ew", pady=4
            )
        reasoning_var = tk.BooleanVar(value=bool(model.get("reasoning")))
        ttk.Checkbutton(body, text="支持推理 (reasoning)", variable=reasoning_var).grid(
            row=len(fields), column=1, sticky="w", pady=(6, 0)
        )
        ttk.Label(body, text="留空表示未知，不会写成 0。").grid(
            row=len(fields) + 1, column=0, columnspan=2, sticky="w", pady=(8, 0)
        )
        self._model_editor = win  # let tests reach the open dialog

        def save() -> None:
            raw = {key: variable.get() for _label, key, variable in fields}
            raw["reasoning"] = reasoning_var.get()
            try:
                changes = core.parse_model_edits(raw, existing=model)
                core.update_provider_model(
                    provider, model["id"], changes, ts=mutation_timestamp()
                )
            except (OSError, ValueError) as exc:
                messagebox.showerror("保存失败", str(exc), parent=win)
                return
            win.destroy()
            self.refresh_providers(select=provider)
            self.status_var.set(f"已更新模型 {model['id']}")

        buttons = ttk.Frame(win, padding=(12, 0, 12, 12))
        buttons.pack(fill="x")
        ttk.Button(buttons, text="取消", command=win.destroy).pack(side="right")
        ttk.Button(buttons, text="保存", command=save).pack(side="right", padx=8)

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
        self.api_var.set(API_TYPES[0])
        self.api_key_var.set("")
        self.model_tree.delete(*self.model_tree.get_children())
        self._apply_action_states()  # new-provider mode: save/test on, per-provider actions off
        self.provider_entry.focus_set()
        self.status_var.set("填写供应商信息后保存")

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
        if not models:
            self.status_var.set("连接成功，但接口没有返回模型")
            messagebox.showinfo("拉取模型", "接口返回了空模型列表。")
            return
        self.status_var.set(f"已拉取 {len(models)} 个模型")
        win = tk.Toplevel(self)
        win.title("选择要导入的模型")
        win.geometry("620x440")
        win.transient(self)

        selected: set[str] = set()
        selection_text = tk.StringVar(value=f"发现 {len(models)} 个模型，已选择 0 个")
        ttk.Label(win, textvariable=selection_text, padding=(10, 10, 10, 6)).pack(anchor="w")
        ttk.Label(win, text="提示：单击或空格切换单行勾选；Shift+单击框选一片。", padding=(10, 0, 10, 4)).pack(anchor="w")
        area = ttk.Frame(win, padding=(10, 0, 10, 8))
        area.pack(fill="both", expand=True)
        tree = ttk.Treeview(
            area,
            columns=("selected", "id", "name"),
            show="headings",
            selectmode="browse",
        )
        tree.heading("selected", text="选择")
        tree.heading("id", text="Model ID")
        tree.heading("name", text="名称")
        tree.column("selected", width=52, minwidth=52, stretch=False, anchor="center")
        tree.column("id", width=310, anchor="w")
        tree.column("name", width=205, anchor="w")
        scroll = ttk.Scrollbar(area, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)
        tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        for index, model in enumerate(models):
            tree.insert("", "end", iid=str(index), values=("☐", model["id"], model["name"]))

        def update_selection_text() -> None:
            selection_text.set(f"发现 {len(models)} 个模型，已选择 {len(selected)} 个")

        def set_checked(item: str, checked: bool) -> None:
            values = list(tree.item(item, "values"))
            values[0] = "☑" if checked else "☐"
            tree.item(item, values=values)
            if checked:
                selected.add(item)
            else:
                selected.discard(item)

        last_clicked = {"iid": None}  # anchor for shift-click range toggle

        def toggle_item(item: str) -> None:
            set_checked(item, item not in selected)
            tree.focus_set()
            tree.focus(item)
            tree.selection_set(item)
            update_selection_text()

        def on_tree_click(event) -> str | None:
            item = tree.identify_row(event.y)
            if not item or tree.identify_region(event.x, event.y) not in {"cell", "tree"}:
                return None
            # Shift+click = marquee toggle over the range from the anchor to this row,
            # unifying the whole span to whatever state this click produces.
            if event.state & 0x0001 and last_clicked["iid"] is not None:
                iids = tree.get_children()
                for row_iid, target in core.range_toggle_targets(
                    iids, last_clicked["iid"], item, lambda i: i in selected
                ):
                    set_checked(row_iid, target)
                last_clicked["iid"] = item
                tree.focus_set()
                tree.focus(item)
                tree.selection_set(item)
                update_selection_text()
                return "break"
            toggle_item(item)
            last_clicked["iid"] = item
            return "break"

        def on_tree_space(_event) -> str:
            item = tree.focus()
            if item:
                toggle_item(item)
            return "break"

        def select_all() -> None:
            for item in tree.get_children():
                set_checked(item, True)
            update_selection_text()

        def clear_selection() -> None:
            for item in tree.get_children():
                set_checked(item, False)
            tree.selection_remove(*tree.selection())
            update_selection_text()

        tree.bind("<Button-1>", on_tree_click)
        tree.bind("<space>", on_tree_space)

        def import_selected() -> None:
            selected_ids = [
                tree.item(item, "values")[1]
                for item in tree.get_children()
                if item in selected
            ]
            if not selected_ids:
                messagebox.showinfo("导入模型", "请至少选择一个模型。", parent=win)
                return
            if provider not in core.load_custom()["providers"]:
                messagebox.showerror("导入失败", f"供应商 {provider} 已不存在", parent=win)
                win.destroy()
                return
            try:
                # Prefer real metadata: whatever the gateway reported, overridden by
                # pi's own numbers when a builtin ships the same model id.
                store = core.load_models_store()
                wanted = set(selected_ids)
                metadata = {}
                for model in models:
                    model_id = model.get("id")
                    if model_id not in wanted:
                        continue
                    merged = dict(model.get("meta") or {})
                    merged.update(core.builtin_model_metadata(model_id, store))
                    if merged:
                        metadata[model_id] = merged
                core.add_provider_models(
                    provider, ",".join(selected_ids),
                    ts=mutation_timestamp(), metadata=metadata,
                )
            except (OSError, ValueError) as exc:
                messagebox.showerror("导入失败", str(exc), parent=win)
                return
            win.destroy()
            self.refresh_providers(select=provider)
            self.status_var.set(f"已导入 {len(selected_ids)} 个模型")

        buttons = ttk.Frame(win, padding=(10, 0, 10, 10))
        buttons.pack(fill="x")
        ttk.Button(buttons, text="全选", command=select_all).pack(side="left")
        ttk.Button(buttons, text="清空", command=clear_selection).pack(side="left", padx=6)
        ttk.Button(buttons, text="取消", command=win.destroy).pack(side="right")
        ttk.Button(buttons, text="导入所选", command=import_selected).pack(side="right", padx=8)

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



    def open_backup_restore(self) -> None:
        backups = core.list_switch_backups()
        if not backups:
            messagebox.showinfo("恢复备份", "目前没有可恢复的备份。")
            return
        win = tk.Toplevel(self)
        win.title("恢复配置备份")
        win.geometry("660x400")
        win.transient(self)

        ttk.Label(
            win,
            text="选择一个修改前快照。恢复前会再次备份当前配置。",
            padding=(10, 10, 10, 6),
        ).pack(anchor="w")
        area = ttk.Frame(win, padding=(10, 0, 10, 8))
        area.pack(fill="both", expand=True)
        tree = ttk.Treeview(area, columns=("time", "files"), show="headings", selectmode="browse")
        tree.heading("time", text="备份时间")
        tree.heading("files", text="包含文件")
        tree.column("time", width=230, anchor="w")
        tree.column("files", width=360, anchor="w")
        scroll = ttk.Scrollbar(area, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)
        tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        for index, backup in enumerate(backups):
            names = ", ".join(sorted(path.name for path in backup.glob("*.json")))
            tree.insert("", "end", iid=str(index), values=(backup.name.removeprefix("switch-"), names))
        tree.selection_set("0")

        def restore_selected() -> None:
            selection = tree.selection()
            if not selection:
                return
            backup = backups[int(selection[0])]
            if not messagebox.askyesno("确认恢复", f"恢复备份 {backup.name}？", parent=win):
                return
            try:
                restored = core.restore_switch_backup(backup, ts=mutation_timestamp())
            except (OSError, ValueError) as exc:
                messagebox.showerror("恢复失败", str(exc), parent=win)
                return
            win.destroy()
            self.current_provider = None
            self.refresh_providers()
            self.status_var.set(f"已恢复 {len(restored)} 个配置文件")
            messagebox.showinfo("恢复完成", "配置已恢复，恢复前状态也已自动备份。")

        buttons = ttk.Frame(win, padding=(10, 0, 10, 10))
        buttons.pack(fill="x")
        ttk.Button(buttons, text="取消", command=win.destroy).pack(side="right")
        ttk.Button(buttons, text="恢复所选", command=restore_selected).pack(side="right", padx=8)


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
