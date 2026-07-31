"""The three Toplevel dialogs: remote-model picker, backup restore, model editor.

Each takes the App as `app` and drives it through its own surface (refresh_providers,
status_var, current_provider) rather than holding state of its own, so they stay
independent of how the main window is laid out.
"""
from __future__ import annotations

import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import core


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
                ts=core.mutation_timestamp(), metadata=metadata,
            )
        except (OSError, ValueError) as exc:
            messagebox.showerror("导入失败", str(exc), parent=win)
            return
        win.destroy()
        app._refresh_provider_models(provider)
        app.status_var.set(f"已导入 {len(selected_ids)} 个模型")

    buttons = ttk.Frame(win, padding=(10, 0, 10, 10))
    buttons.pack(fill="x")
    ttk.Button(buttons, text="全选", command=select_all).pack(side="left")
    ttk.Button(buttons, text="清空", command=clear_selection).pack(side="left", padx=6)
    ttk.Button(buttons, text="取消", command=win.destroy).pack(side="right")
    ttk.Button(buttons, text="导入所选", command=import_selected).pack(side="right", padx=8)


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
        if not app._confirm_form_transition():
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

    buttons = ttk.Frame(win, padding=(10, 0, 10, 10))
    buttons.pack(fill="x")
    ttk.Button(buttons, text="取消", command=win.destroy).pack(side="right")
    ttk.Button(buttons, text="恢复所选", command=restore_selected).pack(side="right", padx=8)


def open_model_editor(app, provider: str, model: dict) -> None:
    win = tk.Toplevel(app)
    win.title(f"编辑模型 {model['id']}")
    win.transient(app)
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
    app._model_editor = win  # let tests reach the open dialog

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
        app._refresh_provider_models(provider)
        app.status_var.set(f"已更新模型 {model['id']}")

    buttons = ttk.Frame(win, padding=(12, 0, 12, 12))
    buttons.pack(fill="x")
    ttk.Button(buttons, text="取消", command=win.destroy).pack(side="right")
    ttk.Button(buttons, text="保存", command=save).pack(side="right", padx=8)


def export_config(app) -> None:
    """Write the provider bundle to a file. core.export_providers removes secrets."""
    payload = core.export_providers()
    if not payload["providers"]:
        messagebox.showinfo("导出配置", "没有可导出的自定义供应商。")
        return
    path = filedialog.asksaveasfilename(
        parent=app,
        title="导出供应商配置",
        defaultextension=".json",
        initialfile=f"piswitch-providers-{datetime.now().strftime('%Y%m%d')}.json",
        filetypes=[("JSON", "*.json"), ("所有文件", "*.*")],
    )
    if not path:
        return
    try:
        core.write_json_atomic(Path(path), payload)
    except OSError as exc:
        messagebox.showerror("导出失败", str(exc))
        return
    count = len(payload["providers"])
    app.status_var.set(f"已导出 {count} 个供应商 → {Path(path).name}")
    messagebox.showinfo(
        "导出完成",
        f"已导出 {count} 个供应商。\n\n"
        "文件不含 API Key。$ENV_VAR 形式的引用会保留，\n"
        "导入方需自行设置对应的环境变量。",
    )


def import_config(app) -> None:
    path = filedialog.askopenfilename(
        parent=app,
        title="导入供应商配置",
        filetypes=[("JSON", "*.json"), ("所有文件", "*.*")],
    )
    if not path:
        return
    try:
        payload = core.read_json(Path(path), None)
    except (OSError, ValueError) as exc:
        messagebox.showerror("导入失败", str(exc))
        return
    incoming = payload.get("providers") if isinstance(payload, dict) else None
    if not isinstance(incoming, dict) or not incoming:
        messagebox.showerror("导入失败", "导入文件不包含任何供应商")
        return

    existing = set(core.load_custom()["providers"])
    clashes = sorted(name for name in incoming if name in existing)
    prompt = f"将导入 {len(incoming)} 个供应商。\n\n"
    overwrite = False
    if clashes:
        prompt += (
            f"其中 {len(clashes)} 个已存在：\n"
            + "\n".join(clashes[:8])
            + (f"\n… 共 {len(clashes)} 个\n\n" if len(clashes) > 8 else "\n\n")
            + "点“是”覆盖它们，点“否”只导入新的供应商。"
        )
        answer = messagebox.askyesnocancel("导入配置", prompt)
        if answer is None:
            return
        overwrite = bool(answer)
    else:
        prompt += "继续？"
        if not messagebox.askyesno("导入配置", prompt):
            return

    try:
        result = core.import_providers(
            payload, ts=core.mutation_timestamp(), overwrite=overwrite
        )
    except (OSError, ValueError) as exc:
        messagebox.showerror("导入失败", str(exc))
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
        detail += f"\n\n以下条目格式无效，已忽略：\n" + "\n".join(result["invalid"][:8])
    messagebox.showinfo("导入完成", detail)


def choose_template(app) -> None:
    """Pick a provider template to seed the form.

    The template only fills the form — nothing is written until the user saves, which is
    deliberate: these endpoints are recorded from documentation and do change, so the user
    gets a chance to check them (and 测试连接) first.
    """
    taken = set(core.load_custom()["providers"]) | set(core.load_models_store())
    templates = core.PROVIDER_TEMPLATES

    win = tk.Toplevel(app)
    win.title("从模板新建供应商")
    win.geometry("640x420")
    win.transient(app)

    ttk.Label(
        win,
        text="模板只填表单，不会立即保存。端点可能变化，保存前请用“测试连接”确认。",
        padding=(10, 10, 10, 6),
    ).pack(anchor="w")
    area = ttk.Frame(win, padding=(10, 0, 10, 8))
    area.pack(fill="both", expand=True)
    tree = ttk.Treeview(area, columns=("label", "baseUrl", "api"), show="headings",
                        selectmode="browse")
    for column, title, width in (("label", "供应商", 150),
                                 ("baseUrl", "Base URL", 300),
                                 ("api", "API 类型", 140)):
        tree.heading(column, text=title)
        tree.column(column, width=width, minwidth=60, anchor="w")
    scroll = ttk.Scrollbar(area, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=scroll.set)
    scroll.pack(side="right", fill="y")
    tree.pack(side="left", fill="both", expand=True)
    for index, tpl in enumerate(templates):
        tree.insert("", "end", iid=str(index),
                    values=(tpl["label"], tpl["baseUrl"], tpl["api"]))
    if templates:
        tree.selection_set("0")
        tree.focus("0")

    def use_selected(_event=None) -> None:
        selection = tree.selection()
        if not selection:
            return
        template = templates[int(selection[0])]
        values = core.template_form_values(template, taken=taken)
        win.destroy()
        app.apply_template_values(values)

    tree.bind("<Double-Button-1>", use_selected)

    buttons = ttk.Frame(win, padding=(10, 0, 10, 10))
    buttons.pack(fill="x")
    ttk.Button(buttons, text="取消", command=win.destroy).pack(side="right")
    ttk.Button(buttons, text="使用此模板", command=use_selected).pack(side="right", padx=8)
