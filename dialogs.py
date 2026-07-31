"""模型导入、备份恢复与模型编辑对话框。

对话框只通过 App 的公开操作接口触发刷新，不依赖主窗口的具体布局。
"""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

import core


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

    def update_count(self) -> None:
        self.selection_text.set(f"发现 {self.total} 个模型，已选择 {len(self.selected)} 个")

    def set_checked(self, item: str, checked: bool) -> None:
        values = list(self.tree.item(item, "values"))
        values[0] = "☑" if checked else "☐"
        self.tree.item(item, values=values)
        if checked:
            self.selected.add(item)
        else:
            self.selected.discard(item)

    def toggle(self, item: str) -> None:
        self.set_checked(item, item not in self.selected)
        self.tree.focus_set()
        self.tree.focus(item)
        self.tree.selection_set(item)
        self.update_count()

    def on_click(self, event) -> str | None:
        item = self.tree.identify_row(event.y)
        if not item or self.tree.identify_region(event.x, event.y) not in {"cell", "tree"}:
            return None
        # Shift+click = marquee toggle over the range from the anchor to this row,
        # unifying the whole span to whatever state this click produces.
        if event.state & 0x0001 and self.anchor is not None:
            iids = self.tree.get_children()
            for row_iid, target in core.range_toggle_targets(
                iids, self.anchor, item, lambda i: i in self.selected
            ):
                self.set_checked(row_iid, target)
            self.anchor = item
            self.tree.focus_set()
            self.tree.focus(item)
            self.tree.selection_set(item)
            self.update_count()
            return "break"
        self.toggle(item)
        self.anchor = item
        return "break"

    def on_space(self, _event) -> str:
        item = self.tree.focus()
        if item:
            self.toggle(item)
        return "break"

    def select_all(self) -> None:
        for item in self.tree.get_children():
            self.set_checked(item, True)
        self.update_count()

    def clear(self) -> None:
        for item in self.tree.get_children():
            self.set_checked(item, False)
        self.tree.selection_remove(*self.tree.selection())
        self.update_count()


def _build_remote_tree(parent, models: list[dict]) -> ttk.Treeview:
    """构建远程模型树。"""
    tree = ttk.Treeview(
        parent,
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
    for index, model in enumerate(models):
        tree.insert("", "end", iid=str(index), values=("☐", model["id"], model["name"]))
    return tree


def _build_remote_buttons(
    parent, sel: _RemoteSelection, win, app, models, provider: str
) -> None:
    """构建远程模型对话框的按钮。"""
    def import_selected() -> None:
        selected_ids = sel.checked_ids()
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
                ts=core.mutation_timestamp(), metadata=metadata,
            )
        except (OSError, ValueError) as exc:
            messagebox.showerror("导入失败", str(exc), parent=win)
            return
        win.destroy()
        app.refresh_provider_models(provider)
        app.status_var.set(f"已导入 {len(selected_ids)} 个模型")

    buttons = ttk.Frame(parent, padding=(10, 0, 10, 10))
    buttons.pack(fill="x")
    ttk.Button(buttons, text="全选", command=sel.select_all).pack(side="left")
    ttk.Button(buttons, text="清空", command=sel.clear).pack(side="left", padx=6)
    ttk.Button(buttons, text="取消", command=win.destroy).pack(side="right")
    ttk.Button(buttons, text="导入所选", command=import_selected).pack(side="right", padx=8)


def _build_backup_tree(area, backups: list) -> ttk.Treeview:
    """构建备份恢复树。"""
    tree = ttk.Treeview(
        area, columns=("time", "files"), show="headings", selectmode="browse"
    )
    tree.heading("time", text="备份时间")
    tree.heading("files", text="包含文件")
    tree.column("time", width=230, anchor="w")
    tree.column("files", width=360, anchor="w")
    for index, backup in enumerate(backups):
        names = ", ".join(sorted(path.name for path in backup.glob("*.json")))
        tree.insert(
            "",
            "end",
            iid=str(index),
            values=(backup.name.removeprefix("switch-"), names),
        )
    tree.selection_set("0")
    return tree


def _build_backup_buttons(parent, tree, backups, app, win) -> None:
    """构建备份恢复按钮。"""
    def restore_selected() -> None:
        selection = tree.selection()
        if not selection:
            return
        if not app.confirm_form_transition():
            return
        backup = backups[int(selection[0])]
        if not messagebox.askyesno("确认恢复", f"恢复备份 {backup.name}？", parent=win):
            return
        try:
            restored = core.restore_switch_backup(backup, ts=core.mutation_timestamp())
        except (OSError, ValueError) as exc:
            messagebox.showerror("恢复失败", str(exc), parent=win)
            return
        win.destroy()
        app.current_provider = None
        app.refresh_providers()
        app.status_var.set(f"已恢复 {len(restored)} 个配置文件")
        messagebox.showinfo("恢复完成", "配置已恢复，恢复前状态也已自动备份。")

    buttons = ttk.Frame(parent, padding=(10, 0, 10, 10))
    buttons.pack(fill="x")
    ttk.Button(buttons, text="取消", command=win.destroy).pack(side="right")
    ttk.Button(buttons, text="恢复所选", command=restore_selected).pack(side="right", padx=8)


def _build_model_fields(body, model: dict) -> tuple:
    """构建模型编辑表单字段。"""
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
    return fields, reasoning_var


def _build_model_buttons(
    parent, fields, reasoning_var, model: dict, provider: str, app, win
) -> None:
    """构建模型编辑按钮。"""
    def save() -> None:
        raw = {key: variable.get() for _label, key, variable in fields}
        raw["reasoning"] = reasoning_var.get()
        try:
            changes = core.parse_model_edits(raw, existing=model)
            core.update_provider_model(
                provider, model["id"], changes, ts=core.mutation_timestamp()
            )
        except (OSError, ValueError) as exc:
            messagebox.showerror("保存失败", str(exc), parent=win)
            return
        win.destroy()
        app.refresh_provider_models(provider)
        app.status_var.set(f"已更新模型 {model['id']}")

    buttons = ttk.Frame(parent, padding=(12, 0, 12, 12))
    buttons.pack(fill="x")
    ttk.Button(buttons, text="取消", command=win.destroy).pack(side="right")
    ttk.Button(buttons, text="保存", command=save).pack(side="right", padx=8)


def show_remote_models(app, models: list[dict], provider: str) -> None:
    if not models:
        app.status_var.set("连接成功，但接口没有返回模型")
        messagebox.showinfo("拉取模型", "接口返回了空模型列表。")
        return
    app.status_var.set(f"已拉取 {len(models)} 个模型")
    win = tk.Toplevel(app)
    win.title("选择要导入的模型")
    win.geometry("620x440")
    win.transient(app)

    selection_text = tk.StringVar(value=f"发现 {len(models)} 个模型，已选择 0 个")
    ttk.Label(win, textvariable=selection_text, padding=(10, 10, 10, 6)).pack(
        anchor="w"
    )
    ttk.Label(
        win,
        text="提示：单击或空格切换单行勾选；Shift+单击框选一片。",
        padding=(10, 0, 10, 4),
    ).pack(anchor="w")
    area = ttk.Frame(win, padding=(10, 0, 10, 8))
    area.pack(fill="both", expand=True)
    tree = _build_remote_tree(area, models)
    scroll = ttk.Scrollbar(area, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=scroll.set)
    tree.pack(side="left", fill="both", expand=True)
    scroll.pack(side="right", fill="y")

    sel = _RemoteSelection(tree, selection_text, len(models))
    tree.bind("<Button-1>", sel.on_click)
    tree.bind("<space>", sel.on_space)
    _build_remote_buttons(win, sel, win, app, models, provider)


def open_backup_restore(app) -> None:
    backups = core.list_switch_backups()
    if not backups:
        messagebox.showinfo("恢复备份", "目前没有可恢复的备份。")
        return
    win = tk.Toplevel(app)
    win.title("恢复配置备份")
    win.geometry("660x400")
    win.transient(app)

    ttk.Label(
        win,
        text="选择一个修改前快照。恢复前会再次备份当前配置。",
        padding=(10, 10, 10, 6),
    ).pack(anchor="w")
    area = ttk.Frame(win, padding=(10, 0, 10, 8))
    area.pack(fill="both", expand=True)
    tree = _build_backup_tree(area, backups)
    scroll = ttk.Scrollbar(area, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=scroll.set)
    tree.pack(side="left", fill="both", expand=True)
    scroll.pack(side="right", fill="y")
    _build_backup_buttons(win, tree, backups, app, win)


def open_model_editor(app, provider: str, model: dict) -> tk.Toplevel:
    win = tk.Toplevel(app)
    win.title(f"编辑模型 {model['id']}")
    win.transient(app)
    body = ttk.Frame(win, padding=(12, 12, 12, 6))
    body.pack(fill="both", expand=True)
    body.columnconfigure(1, weight=1)

    fields, reasoning_var = _build_model_fields(body, model)
    _build_model_buttons(win, fields, reasoning_var, model, provider, app, win)
    return win
