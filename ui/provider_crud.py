"""供应商的新建、保存、删除与配置导入导出。"""
from __future__ import annotations

from tkinter import messagebox

import core
import config_dialogs
import dialogs
from core import mutation_timestamp
from ui import theme


class ProviderCrudMixin:
    """依赖 App 提供的：表单五个 StringVar 与 show_key_var、provider_tree、model_tree、
    provider_entry/name_entry/base_url_entry/api_combo/api_key_entry/key_visibility_check、
    model_count_var、status_var、show_hidden、current_provider、_current_is_builtin、
    _current_has_oauth、_current_is_hidden、_current_config、_tracking_form、
    _toggle_key_visibility、_apply_action_states、_mark_form_clean、
    confirm_form_transition、refresh_providers。"""

    def _reset_new_provider_form(self) -> None:
        self.current_provider = None
        self._current_is_builtin = False
        self._current_has_oauth = False
        self._current_is_hidden = False
        self._current_config = {}
        selection = self.provider_tree.selection()
        if selection:
            self.provider_tree.selection_remove(*selection)
        self.provider_entry.configure(state="normal")
        self.name_entry.configure(state="normal")
        self.base_url_entry.configure(state="normal")
        self.api_combo.configure(state="readonly")
        self.api_key_entry.configure(state="normal")
        self.key_visibility_check.configure(state="normal")
        self._tracking_form = False
        try:
            self.provider_var.set("")
            self.name_var.set("")
            self.base_url_var.set("https://")
            self.api_var.set(core.API_TYPES[0])
            self.api_key_var.set("")
            self.show_key_var.set(False)
            self._toggle_key_visibility()
        finally:
            self._tracking_form = True
        self.model_tree.delete(*self.model_tree.get_children())
        self.model_count_var.set("0 个")
        self._apply_action_states()  # new-provider mode: save/test on, per-provider actions off
        self._mark_form_clean()
        self.provider_entry.focus_set()
        self.status_var.set("填写供应商信息后保存")

    def new_provider(self) -> bool:
        if not self.confirm_form_transition():
            return False
        self._reset_new_provider_form()
        return True

    def new_from_template(self) -> None:
        if self.confirm_form_transition():
            config_dialogs.choose_template(self)

    def apply_template_values(self, values: dict) -> None:
        """Seed the form from a template, as a brand-new unsaved provider."""
        self._reset_new_provider_form()
        self.provider_var.set(values["provider"])
        self.name_var.set(values["name"])
        self.base_url_var.set(values["baseUrl"])
        self.api_var.set(values["api"])
        self.api_key_var.set(values["apiKey"])
        self._apply_action_states()
        self.status_var.set(f"已套用模板 {values['name']}: 确认 Base URL 与 Key 后保存")

    def save_provider(self) -> bool:
        provider = self.provider_var.get().strip()
        if core.is_builtin_provider(provider, core.load_models_store()):
            messagebox.showerror(
                theme.WINDOW_TITLE, f"{provider} 是内置供应商，不能覆盖或保存。"
            )
            return False
        if not self.current_provider and provider in core.load_custom()["providers"]:
            messagebox.showerror(
                theme.WINDOW_TITLE,
                f"Provider ID {provider} 已存在，请从左侧选择后编辑",
            )
            return False
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
                preserve_auth=self._current_has_oauth,
            )
        except (OSError, ValueError) as exc:
            messagebox.showerror(theme.WINDOW_TITLE, str(exc))
            return False
        self.current_provider = provider
        self.refresh_providers(select=provider)
        self.status_var.set(f"已保存供应商 {provider}")
        return True

    def delete_provider(self) -> None:
        provider = self.current_provider
        if not provider:
            return
        if core.is_builtin_provider(provider, core.load_models_store()):
            messagebox.showinfo(
                theme.WINDOW_TITLE,
                f"{provider} 是内置供应商，不能删除。\n"
                "可用“更多操作”菜单中的“从列表移除”把它隐藏，"
                "或用“退出登录”移除其凭据。",
            )
            return
        prompt = f"删除 {provider} 及其模型和 API key？"
        if core.is_default_provider(provider):
            prompt = (
                f"{provider} 是 pi 当前默认供应商。\n\n"
                "删除后默认模型将不可用，建议先在 pi 中切换默认模型。\n\n"
                "仍然删除？"
            )
        if not messagebox.askyesno(theme.WINDOW_TITLE, prompt):
            return
        try:
            core.delete_custom_provider(provider, ts=mutation_timestamp())
        except OSError as exc:
            messagebox.showerror(theme.WINDOW_TITLE, str(exc))
            return
        self.current_provider = None
        self.refresh_providers()
        self.status_var.set(f"已删除供应商 {provider}")

    def logout_provider(self) -> None:
        if not self.confirm_form_transition():
            return
        provider = self.current_provider
        if not provider:
            return
        auth = core.load_auth()
        entry = auth.get(provider)
        if not isinstance(entry, dict) or not entry:
            messagebox.showinfo(
                theme.WINDOW_TITLE, f"{provider} 当前没有存储的凭据"
            )
            return
        kind = core.auth_kind(provider, auth, core.load_custom())
        noun = "OAuth 凭据" if kind == "oauth" else "API Key"
        prompt = f"删除 {provider} 的{noun}?\n\n这将仅清除凭据,保留该供应商的模型配置。"
        if kind == "oauth":
            prompt += (
                "\n之后需重新走 pi /login 流程来重新登录(由该供应商的扩展负责)。"
            )
        if not messagebox.askyesno(theme.WINDOW_TITLE, prompt):
            return
        try:
            removed = core.delete_provider_credentials(provider, ts=mutation_timestamp())
        except OSError as exc:
            messagebox.showerror(theme.WINDOW_TITLE, str(exc))
            return
        if not removed:
            messagebox.showinfo(theme.WINDOW_TITLE, "未发生变化")
            return
        self.refresh_providers(select=provider)
        self.status_var.set(f"已退出登录 {provider}")

    def toggle_hide_builtin(self) -> None:
        """隐藏或恢复内置供应商，不修改 models-store.json。"""
        provider = self.current_provider
        if not provider:
            return
        store = core.load_models_store()
        if not core.is_builtin_provider(provider, store):
            messagebox.showinfo(theme.WINDOW_TITLE, f"{provider} 不是内置供应商。")
            return
        hidden = core.load_hidden_builtins()
        if provider in hidden:
            core.unhide_builtin(provider)
            self.refresh_providers(select=provider)
            self.status_var.set(f"已恢复显示 {provider}")
        else:
            core.hide_builtin(provider)
            self.refresh_providers()
            self.status_var.set(
                f"已从列表移除 {provider}（顶部“更多”中可重新显示）"
            )

    def export_config(self) -> None:
        config_dialogs.export_config(self)

    def import_config(self) -> None:
        if self.confirm_form_transition():
            config_dialogs.import_config(self)

    def open_backup_restore(self) -> None:
        dialogs.open_backup_restore(self)
