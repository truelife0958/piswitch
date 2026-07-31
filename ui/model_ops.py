"""模型列表的展示与增删改。"""
from __future__ import annotations

from tkinter import messagebox, simpledialog

import core
import dialogs
from core import mutation_timestamp


class ModelOpsMixin:
    """依赖 App 提供的：model_tree、model_filter_var、model_count_var、status_var、
    current_provider、_current_config、refresh_providers。"""

    def _refresh_models(self, config: dict, *, settings: dict | None = None) -> None:
        self.model_tree.delete(*self.model_tree.get_children())
        models = config.get("models", [])
        if not isinstance(models, list):
            self.model_count_var.set("0 个")
            return
        query = self.model_filter_var.get()
        settings = settings or core.load_settings()
        default_provider = settings.get("defaultProvider")
        default_model = settings.get("defaultModel")
        visible = 0
        for index, model in enumerate(models):
            if not isinstance(model, dict) or not model.get("id"):
                continue
            if not core.text_matches_query(query, model.get("id"), model.get("name")):
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
            visible += 1
        total = sum(
            1 for model in models
            if isinstance(model, dict) and model.get("id")
        )
        self.model_count_var.set(
            f"{visible}/{total}" if query.strip() else f"{total} 个"
        )

    def _on_model_filter_changed(self, *_args) -> None:
        self._refresh_models(self._current_config)

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
        self._model_editor = dialogs.open_model_editor(self, provider, model)

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
        self.refresh_provider_models(provider)
        self.status_var.set(f"pi 默认模型 → {provider}/{model_id}")

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
        self.refresh_provider_models(provider)
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
        self.refresh_provider_models(provider)
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
        self.refresh_provider_models(provider)
        self.status_var.set(f"已清空 {removed} 个模型")

    def refresh_provider_models(self, provider: str) -> None:
        """Reload model rows and provider summaries without replacing form edits."""
        if provider != self.current_provider:
            # A fetch/editor started on A may finish after the user switched to B.
            # Update provider summaries, but never put A's model rows under B's form.
            self.refresh_providers(load_selection=False)
            return
        custom = core.load_custom()
        store = core.load_models_store()
        config = custom["providers"].get(provider)
        if not isinstance(config, dict):
            config = store.get(provider, {})
        self._current_config = config if isinstance(config, dict) else {}
        self.refresh_providers(select=provider, load_selection=False)
        self._refresh_models(self._current_config)

    def _selected_model_id(self) -> str:
        selection = self.model_tree.selection() or (
            (self.model_tree.focus(),) if self.model_tree.focus() else ()
        )
        if selection:
            return self.model_tree.set(selection[0], "id")
        rows = self.model_tree.get_children()
        return self.model_tree.set(rows[0], "id") if rows else ""
