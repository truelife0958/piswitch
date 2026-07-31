"""备份恢复与模型元数据编辑对话框。"""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

import core


def _build_backup_tree(parent, backups: list) -> ttk.Treeview:
    tree = ttk.Treeview(
        parent, columns=("time", "files"), show="headings", selectmode="browse"
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
    def restore_selected() -> None:
        selection = tree.selection()
        if not selection or not app.confirm_form_transition():
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
    ttk.Button(
        buttons,
        text="恢复所选",
        command=restore_selected,
        style="Primary.TButton",
    ).pack(side="right", padx=8)


def _build_model_fields(body, model: dict) -> tuple:
    cost = model.get("cost") if isinstance(model.get("cost"), dict) else {}

    def text_of(value) -> str:
        return "" if value in (None, "") else str(value)

    fields = (
        ("名称", "name", tk.StringVar(value=text_of(model.get("name") or model["id"]))),
        (
            "上下文窗口",
            "contextWindow",
            tk.StringVar(value=text_of(model.get("contextWindow"))),
        ),
        (
            "最大输出 tokens",
            "maxTokens",
            tk.StringVar(value=text_of(model.get("maxTokens"))),
        ),
        (
            "输入价格 /百万",
            "costInput",
            tk.StringVar(value=text_of(cost.get("input", 0))),
        ),
        (
            "输出价格 /百万",
            "costOutput",
            tk.StringVar(value=text_of(cost.get("output", 0))),
        ),
    )
    for index, (label, _key, variable) in enumerate(fields):
        ttk.Label(body, text=label).grid(
            row=index, column=0, sticky="w", padx=(0, 10), pady=4
        )
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
    ttk.Button(
        buttons, text="保存", command=save, style="Primary.TButton"
    ).pack(side="right", padx=8)


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
