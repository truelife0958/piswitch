#!/usr/bin/env python3
"""Small GUI for managing custom pi model providers."""
from __future__ import annotations

import os
import queue
import sys
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

import core
import layout
from ui.form_guard import FormGuardMixin
from ui.model_ops import ModelOpsMixin
from ui.network import NetworkMixin
from ui.provider_crud import ProviderCrudMixin
from ui.provider_list import ProviderListMixin
from ui import theme


ICON_PATH = Path(__file__).resolve().parent / "assets" / "piswitch.png"


class App(
    FormGuardMixin, ProviderListMixin, ModelOpsMixin,
    NetworkMixin, ProviderCrudMixin, tk.Tk,
):
    def __init__(self) -> None:
        super().__init__()
        self.title(theme.WINDOW_TITLE)
        self.geometry("920x600")
        self.minsize(760, 500)
        self._window_icon = None
        if ICON_PATH.exists():
            try:
                self._window_icon = tk.PhotoImage(file=ICON_PATH)
                self.iconphoto(True, self._window_icon)
            except tk.TclError:
                pass

        theme.apply(self)

        self._declare_vars()
        self._build_ui()
        self._bind_events()
        self.after(100, self._poll_network_results)
        self.refresh_providers()

    def _declare_vars(self) -> None:
        """所有 Tk 变量与内部状态字段。只声明，不绑定、不读盘。"""
        self.current_provider: str | None = None
        self._current_is_builtin = False
        self._current_has_oauth = False
        self._current_is_hidden = False
        self.provider_var = tk.StringVar()
        self.name_var = tk.StringVar()
        self.base_url_var = tk.StringVar(value="https://")
        self.api_var = tk.StringVar(value=core.API_TYPES[0])
        self.api_key_var = tk.StringVar()
        self.key_status_var = tk.StringVar()
        self.show_key_var = tk.BooleanVar(value=False)
        self.status_var = tk.StringVar(value="就绪")
        self.form_status_var = tk.StringVar()
        self.show_hidden = tk.BooleanVar(value=False)  # show builtin providers the user hid
        self.provider_filter_var = tk.StringVar()
        self.provider_count_var = tk.StringVar()
        self.model_filter_var = tk.StringVar()
        self.model_count_var = tk.StringVar()
        self._network_results: queue.Queue = queue.Queue()
        self._network_busy = False
        # provider id -> last health-check cell text; survives refresh_providers redraws.
        self._health: dict[str, str] = {}
        self._provider_records: list[dict] = []
        self._current_config: dict = {}
        self._tracking_form = False
        self._form_snapshot: tuple[str, ...] = ()
        self._form_dirty = False

    def _bind_events(self) -> None:
        """快捷键、trace 回调、关窗协议。必须在 _build_ui 之后调用。"""
        self.bind("<Control-n>", lambda _event: self.new_provider())
        self.bind("<Control-s>", lambda _event: self.save_provider())
        self.bind("<Control-f>", lambda _event: self.provider_filter_entry.focus_set())
        for variable in (
            self.provider_var, self.name_var, self.base_url_var,
            self.api_var, self.api_key_var,
        ):
            variable.trace_add("write", self._on_form_changed)
        # Re-evaluate the $ENV_VAR indicator and the two list filters while typing.
        self.api_key_var.trace_add("write", lambda *_a: self._refresh_key_status())
        self.provider_filter_var.trace_add("write", self._on_provider_filter_changed)
        self.model_filter_var.trace_add("write", self._on_model_filter_changed)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._tracking_form = True

    def _build_ui(self) -> None:
        layout.build(self)


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
            messagebox.showerror(theme.WINDOW_TITLE, message)
        except tk.TclError:
            pass
        raise SystemExit(1) from exc
    app.mainloop()


if __name__ == "__main__":
    main()
