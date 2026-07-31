"""远程模型选择、导入状态与未返回模型清理。"""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

import core
from ui import theme


class _RemoteSelection:
    """维护可导入行的勾选状态，锁定已导入和远端未返回行。"""

    def __init__(
        self,
        tree,
        selection_text,
        remote_total: int,
        imported_items: set[str] | None = None,
        missing_items: set[str] | None = None,
    ):
        self.tree = tree
        self.selection_text = selection_text
        self.remote_total = remote_total
        self.imported_items = imported_items or set()
        self.missing_items = missing_items or set()
        self.locked_items = self.imported_items | self.missing_items
        self.selected: set[str] = set()
        self.anchor: str | None = None
        self._on_change = None
        self.update_count()

    def checked_ids(self) -> list[str]:
        return [
            self.tree.set(item, "id")
            for item in self.tree.get_children()
            if item in self.selected
        ]

    def update_count(self) -> None:
        parts = [
            f"远端 {self.remote_total} 个",
            f"已导入 {len(self.imported_items)} 个",
        ]
        if self.missing_items:
            parts.append(f"未返回 {len(self.missing_items)} 个")
        parts.append(f"已选择 {len(self.selected)} 个")
        self.selection_text.set("，".join(parts))
        if self._on_change is not None:
            self._on_change(bool(self.selected))

    def set_change_callback(self, callback) -> None:
        self._on_change = callback
        callback(bool(self.selected))

    def set_checked(self, item: str, checked: bool) -> None:
        if item in self.locked_items:
            return
        values = list(self.tree.item(item, "values"))
        values[0] = "[x]" if checked else "[ ]"
        self.tree.item(item, values=values)
        if checked:
            self.selected.add(item)
        else:
            self.selected.discard(item)

    def _focus(self, item: str) -> None:
        self.tree.focus_set()
        self.tree.focus(item)
        self.tree.selection_set(item)

    def toggle(self, item: str) -> None:
        if item in self.locked_items:
            return
        self.set_checked(item, item not in self.selected)
        self._focus(item)
        self.update_count()

    def on_click(self, event) -> str | None:
        item = self.tree.identify_row(event.y)
        if not item or self.tree.identify_region(event.x, event.y) not in {"cell", "tree"}:
            return None
        if item in self.locked_items:
            self._focus(item)
            return "break"
        if event.state & 0x0001 and self.anchor is not None:
            iids = self.tree.get_children()
            for row_iid, target in core.range_toggle_targets(
                iids, self.anchor, item, lambda i: i in self.selected
            ):
                self.set_checked(row_iid, target)
            self.anchor = item
            self._focus(item)
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


def _build_remote_tree(
    parent,
    models: list[dict],
    imported_ids: set[str],
    missing_ids: set[str],
) -> tuple[ttk.Treeview, set[str], set[str]]:
    tree = ttk.Treeview(
        parent,
        columns=("selected", "status", "id", "name"),
        show="headings",
        selectmode="browse",
    )
    for column, title, width, anchor in (
        ("selected", "选择", 48, "center"),
        ("status", "状态", 96, "center"),
        ("id", "Model ID", 285, "w"),
        ("name", "名称", 200, "w"),
    ):
        tree.heading(column, text=title)
        tree.column(
            column,
            width=width,
            minwidth=width if column in {"selected", "status"} else 80,
            stretch=column not in {"selected", "status"},
            anchor=anchor,
        )
    theme.configure_tree_tags(tree)

    imported_items: set[str] = set()
    missing_items: set[str] = set()
    for index, model in enumerate(models):
        iid = str(index)
        model_id = model["id"]
        missing = model_id in missing_ids
        imported = model_id in imported_ids and not missing
        if missing:
            missing_items.add(iid)
        elif imported:
            imported_items.add(iid)
        status = "远端未返回" if missing else ("已导入" if imported else "")
        tags = ["stripe"] if index % 2 else []
        if missing:
            tags.append("missing")
        elif imported:
            tags.append("imported")
        tree.insert(
            "",
            "end",
            iid=iid,
            values=("" if imported or missing else "[ ]", status, model_id, model["name"]),
            tags=tuple(tags),
        )
    return tree, imported_items, missing_items


def _current_model_ids(provider: str) -> set[str] | None:
    config = core.load_custom()["providers"].get(provider)
    if not isinstance(config, dict):
        return None
    models = config.get("models", [])
    return {
        model.get("id")
        for model in models
        if isinstance(model, dict) and isinstance(model.get("id"), str)
    }


def _build_remote_buttons(
    parent,
    selection: _RemoteSelection,
    win,
    app,
    remote_models: list[dict],
    provider: str,
    missing_ids: list[str],
) -> None:
    def import_selected() -> None:
        selected_ids = selection.checked_ids()
        if not selected_ids:
            messagebox.showinfo("导入模型", "请至少选择一个尚未导入的模型。", parent=win)
            return
        current_ids = _current_model_ids(provider)
        if current_ids is None:
            messagebox.showerror("导入失败", f"供应商 {provider} 已不存在", parent=win)
            win.destroy()
            return
        selected_ids = [model_id for model_id in selected_ids if model_id not in current_ids]
        if not selected_ids:
            messagebox.showinfo("导入模型", "所选模型均已导入，无需重复添加。", parent=win)
            return
        try:
            store = core.load_models_store()
            wanted = set(selected_ids)
            metadata = {}
            for model in remote_models:
                model_id = model.get("id")
                if model_id not in wanted:
                    continue
                merged = dict(model.get("meta") or {})
                merged.update(core.builtin_model_metadata(model_id, store))
                if merged:
                    metadata[model_id] = merged
            core.add_provider_models(
                provider,
                ",".join(selected_ids),
                ts=core.mutation_timestamp(),
                metadata=metadata,
            )
        except (OSError, ValueError) as exc:
            messagebox.showerror("导入失败", str(exc), parent=win)
            return
        win.destroy()
        app.refresh_provider_models(provider)
        app.status_var.set(f"已导入 {len(selected_ids)} 个模型")

    def delete_missing() -> None:
        current_ids = _current_model_ids(provider)
        if current_ids is None:
            messagebox.showerror("删除失败", f"供应商 {provider} 已不存在", parent=win)
            win.destroy()
            return
        candidates = [model_id for model_id in missing_ids if model_id in current_ids]
        if not candidates:
            messagebox.showinfo("删除模型", "这些模型已不在本地配置中。", parent=win)
            win.destroy()
            app.refresh_provider_models(provider)
            return

        preview = "\n".join(candidates[:10])
        if len(candidates) > 10:
            preview += f"\n... 共 {len(candidates)} 个"
        prompt = (
            f"本次远端接口未返回以下 {len(candidates)} 个已导入模型：\n\n"
            f"{preview}\n\n"
            "未返回不一定表示模型已下线，也可能由权限或接口暂时变化导致。"
        )
        settings = core.load_settings()
        default_model = settings.get("defaultModel")
        if settings.get("defaultProvider") == provider and default_model in candidates:
            prompt += f"\n\n{default_model} 是 pi 当前默认模型，删除后将不可用。"
        prompt += "\n\n确认从本地配置删除？"
        if not messagebox.askyesno("删除远端未返回模型", prompt, parent=win):
            return
        try:
            removed = core.delete_provider_models(
                provider, candidates, ts=core.mutation_timestamp()
            )
        except OSError as exc:
            messagebox.showerror("删除失败", str(exc), parent=win)
            return
        win.destroy()
        app.refresh_provider_models(provider)
        app.status_var.set(f"已删除 {removed} 个远端未返回模型")

    has_importable = selection.remote_total > len(selection.imported_items)
    buttons = ttk.Frame(parent, padding=(10, 0, 10, 10))
    buttons.pack(fill="x")
    ttk.Button(
        buttons,
        text="全选",
        command=selection.select_all,
        state="normal" if has_importable else "disabled",
    ).pack(side="left")
    clear_button = ttk.Button(
        buttons, text="清空", command=selection.clear, state="disabled"
    )
    clear_button.pack(side="left", padx=6)
    ttk.Button(
        buttons,
        text="删除全部未返回项",
        command=delete_missing,
        state="normal" if missing_ids else "disabled",
        style="Danger.TButton",
    ).pack(side="left", padx=(8, 0))
    ttk.Button(buttons, text="取消", command=win.destroy).pack(side="right")
    import_button = ttk.Button(
        buttons,
        text="导入所选",
        command=import_selected,
        state="disabled",
        style="Primary.TButton",
    )
    import_button.pack(side="right", padx=8)

    def update_actions(has_selection: bool) -> None:
        state = "normal" if has_selection else "disabled"
        clear_button.configure(state=state)
        import_button.configure(state=state)

    selection.set_change_callback(update_actions)


def show_remote_models(app, models: list[dict], provider: str) -> None:
    config = core.load_custom()["providers"].get(provider, {})
    local_models = config.get("models", []) if isinstance(config, dict) else []
    existing_by_id = {}
    for model in local_models:
        if isinstance(model, dict) and isinstance(model.get("id"), str):
            existing_by_id.setdefault(model["id"], model)

    remote_ids = {model["id"] for model in models}
    missing_ids = [model_id for model_id in existing_by_id if model_id not in remote_ids]
    missing_rows = [
        {
            "id": model_id,
            "name": existing_by_id[model_id].get("name") or model_id,
        }
        for model_id in missing_ids
    ]
    display_models = [*models, *missing_rows]
    if not display_models:
        app.status_var.set("连接成功，但接口没有返回模型")
        messagebox.showinfo("拉取模型", "接口返回了空模型列表。")
        return

    if missing_ids:
        app.status_var.set(
            f"已拉取 {len(models)} 个模型，{len(missing_ids)} 个已导入模型未返回"
        )
    else:
        app.status_var.set(f"已拉取 {len(models)} 个模型")
    win = tk.Toplevel(app)
    win.title("同步远端模型")
    win.geometry("700x470")
    win.transient(app)

    selection_text = tk.StringVar()
    ttk.Label(
        win,
        textvariable=selection_text,
        padding=(10, 10, 10, 6),
        style="Muted.TLabel",
    ).pack(anchor="w")
    if missing_ids:
        ttk.Label(
            win,
            text=(
                f"{len(missing_ids)} 个已导入模型本次未由远端返回，"
                "请确认服务权限和模型状态后再清理。"
            ),
            style="Dirty.TLabel",
            padding=(10, 0, 10, 4),
        ).pack(anchor="w")
    ttk.Label(
        win,
        text="提示：单击或空格切换单行勾选；Shift+单击框选一片。",
        padding=(10, 0, 10, 4),
        style="Muted.TLabel",
    ).pack(anchor="w")
    area = ttk.Frame(win, padding=(10, 0, 10, 8))
    area.pack(fill="both", expand=True)
    tree, imported_items, missing_items = _build_remote_tree(
        area,
        display_models,
        set(existing_by_id),
        set(missing_ids),
    )
    scroll = ttk.Scrollbar(area, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=scroll.set)
    tree.pack(side="left", fill="both", expand=True)
    scroll.pack(side="right", fill="y")

    selection = _RemoteSelection(
        tree,
        selection_text,
        len(models),
        imported_items,
        missing_items,
    )
    tree.bind("<Button-1>", selection.on_click)
    tree.bind("<space>", selection.on_space)
    _build_remote_buttons(
        win,
        selection,
        win,
        app,
        models,
        provider,
        missing_ids,
    )
