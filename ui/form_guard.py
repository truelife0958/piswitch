"""表单脏状态跟踪与转场确认。"""
from __future__ import annotations

from tkinter import messagebox

from ui import theme


class FormGuardMixin:
    """依赖 App 提供的：表单五个 StringVar、provider_tree、current_provider、
    _current_is_builtin、_tracking_form、save_provider、refresh_providers。"""

    def _toggle_key_visibility(self) -> None:
        self.api_key_entry.configure(show="" if self.show_key_var.get() else "*")

    def _capture_form_state(self) -> tuple[str, ...]:
        return tuple(variable.get() for variable in (
            self.provider_var,
            self.name_var,
            self.base_url_var,
            self.api_var,
            self.api_key_var,
        ))

    def _on_form_changed(self, *_args) -> None:
        if not self._tracking_form:
            return
        dirty = not self._current_is_builtin and self._capture_form_state() != self._form_snapshot
        if dirty == self._form_dirty:
            return
        self._form_dirty = dirty
        self.form_status_var.set("未保存" if dirty else "")
        self.title("piswitch *" if dirty else "piswitch")

    def _mark_form_clean(self) -> None:
        self._form_snapshot = self._capture_form_state()
        self._form_dirty = False
        self.form_status_var.set("")
        self.title("piswitch")

    def confirm_form_transition(self) -> bool:
        """Offer save/discard/cancel before an action would replace the form."""
        if not self._form_dirty:
            return True
        answer = messagebox.askyesnocancel(
            theme.WINDOW_TITLE,
            "供应商信息尚未保存。\n\n"
            "选择“是”保存后继续，“否”放弃修改，“取消”留在当前页面。",
            parent=self,
        )
        if answer is None:
            return False
        if answer:
            return self.save_provider()
        return True

    def _restore_provider_selection(self) -> None:
        selection = self.provider_tree.selection()
        if selection:
            self.provider_tree.selection_remove(*selection)
        if self.current_provider and self.provider_tree.exists(self.current_provider):
            self.provider_tree.selection_set(self.current_provider)
            self.provider_tree.focus(self.current_provider)

    def _on_close(self) -> None:
        if self.confirm_form_transition():
            self.destroy()

    def request_refresh(self) -> None:
        if self.confirm_form_transition():
            self.refresh_providers()
