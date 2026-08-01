"""供应商配置导入、导出与模板选择对话框。"""
from __future__ import annotations

import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import core
from ui import theme


def _resolve_import_conflicts(incoming: dict, clashes: list[str]) -> bool | None:
    """询问冲突处理方式；取消时返回 None。"""
    prompt = f"将导入 {len(incoming)} 个供应商。\n\n"
    if clashes:
        prompt += (
            f"其中 {len(clashes)} 个已存在：\n"
            + "\n".join(clashes[:8])
            + (f"\n... 共 {len(clashes)} 个\n\n" if len(clashes) > 8 else "\n\n")
            + "点“是”覆盖它们，点“否”只导入新的供应商。"
        )
        answer = messagebox.askyesnocancel(theme.WINDOW_TITLE, prompt)
        return None if answer is None else bool(answer)

    if not messagebox.askyesno(theme.WINDOW_TITLE, prompt + "继续？"):
        return None
    return False


def _build_template_tree(parent, templates: list[dict]) -> ttk.Treeview:
    tree = ttk.Treeview(
        parent,
        columns=("label", "baseUrl", "api"),
        show="headings",
        selectmode="browse",
    )
    for column, title, width in (
        ("label", "供应商", 150),
        ("baseUrl", "Base URL", 300),
        ("api", "API 类型", 140),
    ):
        tree.heading(column, text=title)
        tree.column(column, width=width, minwidth=60, anchor="w")
    for index, template in enumerate(templates):
        tree.insert(
            "",
            "end",
            iid=str(index),
            values=(template["label"], template["baseUrl"], template["api"]),
        )
    if templates:
        tree.selection_set("0")
        tree.focus("0")
    return tree


def _build_template_buttons(parent, tree, templates, app, win, taken: set[str]) -> None:
    def use_selected(_event=None) -> None:
        selection = tree.selection()
        if not selection:
            return
        template = templates[int(selection[0])]
        values = core.template_form_values(template, taken=taken)
        win.destroy()
        app.apply_template_values(values)

    tree.bind("<Double-Button-1>", use_selected)
    buttons = ttk.Frame(parent, padding=(10, 0, 10, 10))
    buttons.pack(fill="x")
    ttk.Button(buttons, text="取消", command=win.destroy).pack(side="right")
    ttk.Button(
        buttons,
        text="使用此模板",
        command=use_selected,
        style="Primary.TButton",
    ).pack(side="right", padx=8)


def export_config(app) -> None:
    """导出不含明文密钥的供应商配置。"""
    payload = core.export_providers()
    if not payload["providers"]:
        messagebox.showinfo(theme.WINDOW_TITLE, "没有可导出的自定义供应商。")
        return
    path = filedialog.asksaveasfilename(
        parent=app,
        title=theme.WINDOW_TITLE,
        defaultextension=".json",
        initialfile=f"piswitch-providers-{datetime.now().strftime('%Y%m%d')}.json",
        filetypes=[("JSON", "*.json"), ("所有文件", "*.*")],
    )
    if not path:
        return
    try:
        core.write_json_atomic(Path(path), payload)
    except OSError as exc:
        messagebox.showerror(theme.WINDOW_TITLE, str(exc))
        return
    count = len(payload["providers"])
    app.status_var.set(f"已导出 {count} 个供应商到 {Path(path).name}")
    messagebox.showinfo(
        theme.WINDOW_TITLE,
        f"已导出 {count} 个供应商。\n\n"
        "文件不含 API Key。$ENV_VAR 形式的引用会保留，\n"
        "导入方需自行设置对应的环境变量。",
    )


def import_config(app) -> None:
    path = filedialog.askopenfilename(
        parent=app,
        title=theme.WINDOW_TITLE,
        filetypes=[("JSON", "*.json"), ("所有文件", "*.*")],
    )
    if not path:
        return
    try:
        payload = core.read_json(Path(path), None)
    except (OSError, ValueError) as exc:
        messagebox.showerror(theme.WINDOW_TITLE, str(exc))
        return
    incoming = payload.get("providers") if isinstance(payload, dict) else None
    if not isinstance(incoming, dict) or not incoming:
        messagebox.showerror(theme.WINDOW_TITLE, "导入文件不包含任何供应商")
        return

    existing = set(core.load_custom()["providers"])
    overwrite = _resolve_import_conflicts(
        incoming,
        sorted(name for name in incoming if name in existing),
    )
    if overwrite is None:
        return
    try:
        result = core.import_providers(
            payload, ts=core.mutation_timestamp(), overwrite=overwrite
        )
    except (OSError, ValueError) as exc:
        messagebox.showerror(theme.WINDOW_TITLE, str(exc))
        return

    app.current_provider = None
    app.refresh_providers()
    summary = (
        f"新增 {len(result['added'])} 个，"
        f"覆盖 {len(result['overwritten'])} 个，"
        f"跳过 {len(result['skipped'])} 个"
    )
    app.status_var.set(f"导入完成：{summary}")
    detail = summary
    if result["invalid"]:
        detail += "\n\n以下条目格式无效，已忽略：\n" + "\n".join(result["invalid"][:8])
    messagebox.showinfo(theme.WINDOW_TITLE, detail)


def choose_template(app) -> None:
    """选择模板填充新供应商表单，不立即写入配置。"""
    taken = set(core.load_custom()["providers"]) | set(core.load_models_store())
    templates = core.PROVIDER_TEMPLATES

    win = tk.Toplevel(app)
    win.title(theme.WINDOW_TITLE)
    win.geometry("640x420")
    win.transient(app)
    ttk.Label(
        win,
        text="模板只填表单，不会立即保存。端点可能变化，保存前请用“测试连接”确认。",
        padding=(10, 10, 10, 6),
    ).pack(anchor="w")
    area = ttk.Frame(win, padding=(10, 0, 10, 8))
    area.pack(fill="both", expand=True)
    tree = _build_template_tree(area, templates)
    scroll = ttk.Scrollbar(area, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=scroll.set)
    scroll.pack(side="right", fill="y")
    tree.pack(side="left", fill="both", expand=True)
    _build_template_buttons(win, tree, templates, app, win, taken)
