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
        self.provider_var = tk.StringVar()
        self.name_var = tk.StringVar()
        self.base_url_var = tk.StringVar(value="https://")
        self.api_var = tk.StringVar(value=API_TYPES[0])
        self.api_key_var = tk.StringVar()
        self.show_key_var = tk.BooleanVar(value=False)
        self.status_var = tk.StringVar(value="就绪")
        self.show_hidden = tk.BooleanVar(value=False)  # show builtin providers the user hid
        self._network_results: queue.Queue = queue.Queue()
        self._network_busy = False

        self._build_ui()
        self.bind("<Control-n>", lambda _event: self.new_provider())
        self.bind("<Control-s>", lambda _event: self.save_provider())
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
            ("provider", "Provider ID", 145),
            ("name", "名称", 145),
            ("models", "模型", 55),
            ("auth", "验证", 80),
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

        model_header = ttk.Frame(right)
        model_header.pack(fill="x", pady=(2, 6))
        ttk.Label(model_header, text="模型", font=("TkDefaultFont", 11, "bold")).pack(side="left")
        self.clear_models_button = ttk.Button(model_header, text="清空", command=self.clear_models)
        self.clear_models_button.pack(side="right")
        self.delete_model_button = ttk.Button(model_header, text="删除模型", command=self.delete_model)
        self.delete_model_button.pack(side="right", padx=6)
        self.add_model_button = ttk.Button(model_header, text="增加模型", command=self.add_models)
        self.add_model_button.pack(side="right", padx=6)
        self.fetch_model_button = ttk.Button(model_header, text="拉取模型", command=self.fetch_models)
        self.fetch_model_button.pack(side="right")

        model_area = ttk.Frame(right)
        model_area.pack(fill="both", expand=True)
        self.model_tree = ttk.Treeview(
            model_area,
            columns=("id", "name", "reasoning"),
            show="headings",
            selectmode="extended",
        )
        for column, title, width in (
            ("id", "Model ID", 230),
            ("name", "名称", 160),
            ("reasoning", "推理", 55),
        ):
            self.model_tree.heading(column, text=title)
            self.model_tree.column(column, width=width, minwidth=45, anchor="w")
        model_scroll = ttk.Scrollbar(model_area, orient="vertical", command=self.model_tree.yview)
        self.model_tree.configure(yscrollcommand=model_scroll.set)
        self.model_tree.pack(side="left", fill="both", expand=True)
        model_scroll.pack(side="right", fill="y")

        ttk.Label(self, textvariable=self.status_var, anchor="w", relief="sunken", padding=(8, 4)).pack(fill="x")

    def _toggle_key_visibility(self) -> None:
        self.api_key_entry.configure(show="" if self.show_key_var.get() else "*")

    def _set_editing_state(self, editing: bool) -> None:
        self.provider_entry.configure(state="normal")
        state = "normal" if editing else "disabled"
        self.save_provider_button.configure(state=state)
        self.test_connection_button.configure(state=state)
        self.delete_provider_button.configure(state=state)
        self.add_model_button.configure(state=state)
        self.delete_model_button.configure(state=state)
        self.clear_models_button.configure(state=state)
        self.fetch_model_button.configure(state=state)
        # hide-from-list only applies to builtin; _load_provider re-enables it when a builtin is selected
        self.hide_builtin_button.configure(state="disabled")
    def refresh_providers(self, select: str | None = None) -> None:
        custom = core.load_custom()
        auth = core.load_auth()
        store = core.load_models_store()
        custom_providers = custom["providers"]
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
            self.provider_tree.insert(
                "",
                "end",
                iid=provider,
                values=(provider, config.get("name") or provider, model_count, auth_label),
            )

        for provider, config in sorted(custom_providers.items()):
            if not isinstance(config, dict):
                continue
            models = config.get("models", [])
            model_count = len(models) if isinstance(models, list) else 0
            _insert(provider, config, model_count)

        # Then builtin providers not overridden by a custom entry of the same id.
        hidden = core.load_hidden_builtins() if not getattr(self, "show_hidden", None) or not self.show_hidden.get() else set()
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
        self.status_var.set(f"已加载 {len(custom_providers)} 个自定义供应商")

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
        auth_entry = auth.get(provider) if isinstance(auth, dict) else None
        kind = core.auth_kind(provider, auth, custom)
        if kind == "api_key":
            auth_key = auth_entry.get("key") if isinstance(auth_entry, dict) else ""
            self.api_key_var.set(auth_key or config.get("apiKey", ""))
            self.api_key_entry.configure(state="normal")
        elif kind == "oauth":
            state = core.auth_login_state(provider, auth)
            # OAuth access tokens are extension-managed; show read-only status.
            label = "(OAuth，已登录)" if state == "logged_in" else ("(OAuth，已过期)" if state == "expired" else "(OAuth)")
            self.api_key_var.set(label)
            self.api_key_entry.configure(state="disabled")
        else:
            self.api_key_var.set(config.get("apiKey", ""))
            self.api_key_entry.configure(state="normal")


        # Logout / delete-credentials only makes sense for OAuth/session-login providers;
        # for api_key providers the user just edits the API-key field directly (no session to end).
        is_oauth = kind == "oauth"
        has_oauth_entry = is_oauth and isinstance(auth_entry, dict) and bool(auth_entry)
        self.logout_provider_button.configure(state="normal" if has_oauth_entry else "disabled")
        hidden = core.load_hidden_builtins()
        if builtin:
            # toggle button text reflects current hide state
            if provider in hidden:
                self.hide_builtin_button.configure(text="恢复显示", state="normal")
            else:
                self.hide_builtin_button.configure(text="从列表移除", state="normal")
        else:
            self.hide_builtin_button.configure(text="从列表移除", state="disabled")
        self.current_provider = provider
        self.provider_entry.configure(state="normal")
        self.provider_var.set(provider)
        self.name_var.set(config.get("name") or provider)
        self.base_url_var.set(config.get("baseUrl", ""))
        self.api_var.set(config.get("api", API_TYPES[0]))
        # Builtin providers are read-only: lock form fields, show store models, disable CRUD.
        if builtin:
            # editing-state first disables all action buttons; then we also lock form entry fields
            self._set_editing_state(False)
            self.provider_entry.configure(state="disabled")
            self.name_var.set(config.get("name") or provider + " (内置)")
            self.base_url_var.set(config.get("baseUrl") or "(内置)")
            self.api_key_entry.configure(state="disabled")
            # logout must remain enabled if this is an OAuth provider with an entry;
            if has_oauth_entry:
                self.logout_provider_button.configure(state="normal")
            # hide-from-list toggle is enabled for builtins; text/state reflects current hide status
            if provider in core.load_hidden_builtins():
                self.hide_builtin_button.configure(text="恢复显示", state="normal")
            else:
                self.hide_builtin_button.configure(text="从列表移除", state="normal")
        else:
            self._set_editing_state(True)
        self._refresh_models(config)

    def _refresh_models(self, config: dict) -> None:
        self.model_tree.delete(*self.model_tree.get_children())
        models = config.get("models", [])
        if not isinstance(models, list):
            return
        for index, model in enumerate(models):
            if not isinstance(model, dict) or not model.get("id"):
                continue
            self.model_tree.insert(
                "",
                "end",
                iid=str(index),
                values=(model["id"], model.get("name", model["id"]), "是" if model.get("reasoning") else "否"),
            )

    def new_provider(self) -> None:
        self.current_provider = None
        selection = self.provider_tree.selection()
        if selection:
            self.provider_tree.selection_remove(*selection)
        self.provider_entry.configure(state="normal")
        self.provider_var.set("")
        self.name_var.set("")
        self.base_url_var.set("https://")
        self.api_var.set(API_TYPES[0])
        self.api_key_var.set("")
        self.model_tree.delete(*self.model_tree.get_children())
        self._set_editing_state(True)  # new-provider mode: enable save/test so user can create
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
        self.test_connection_button.configure(state="disabled" if busy else "normal")
        self.save_provider_button.configure(state="disabled" if busy else "normal")
        edit_state = "disabled" if busy or not self.current_provider else "normal"
        self.delete_provider_button.configure(state=edit_state)
        self.add_model_button.configure(state=edit_state)
        self.delete_model_button.configure(state=edit_state)
        self.clear_models_button.configure(state=edit_state)
        self.fetch_model_button.configure(
            state="disabled" if busy or not self.current_provider else "normal"
        )

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

    def test_connection(self) -> None:
        def success(models: list[dict]) -> None:
            self.status_var.set(f"连接成功，发现 {len(models)} 个模型")
            messagebox.showinfo("连接成功", f"模型接口可用，共发现 {len(models)} 个模型。")

        self._run_network("正在测试模型接口…", self._fetch_action_from_form(), success)

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
                core.add_provider_models(provider, ",".join(selected_ids), ts=mutation_timestamp())
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
            core.add_provider_models(provider, model_ids, ts=mutation_timestamp())
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
        model_ids = [self.model_tree.item(iid, "values")[0] for iid in selection]
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


def main() -> None:
    result = core.dispatch(sys.argv[1:])
    if result is not None:
        raise SystemExit(result)
    try:
        App().mainloop()
    except tk.TclError as exc:
        if os.environ.get("PISWITCH_DEBUG"):
            raise
        print(f"[piswitch] 无法启动 GUI: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
