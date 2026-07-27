#!/usr/bin/env python3
"""
piswitch - 本地 GUI 工具,用于切换 pi (earendil-works/pi-coding-agent) 的默认模型,
并管理自定义 provider / API key。类似 ccswitch。

操作目标:
  ~/.pi/agent/settings.json        -> defaultProvider / defaultModel / defaultThinkingLevel / theme
  ~/.pi/agent/models-store.json   -> 内置 + 缓存的可用模型清单(只读,用于枚举模型)
  ~/.pi/agent/models.json         -> 自定义 provider(如 NewAPI)及其模型(可增删改)
  ~/.pi/agent/auth.json           -> 各 provider 的 API key(可查看/编辑/新增)

安全: 写入时先写临时文件再原子替换,避免把 pi 配置写坏。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk
from pathlib import Path
from typing import Any

import core

THINKING_LEVELS = ["off", "minimal", "low", "medium", "high", "xhigh", "max"]
API_TYPES = [
    "openai-completions",
    "openai-responses",
    "anthropic-messages",
    "google-generative-ai",
    "mistral-conversations",
    "google-vertex",
    "azure-openai-responses",
    "openai-codex-responses",
    "bedrock-converse-stream",
]
INPUT_TYPES = ["text", "image"]
TAG_SUGGESTIONS = ["常用", "便宜", "快", "强推理", "视觉", "测试用", "备用"]
# 结构: notes.json = { "provider/model": {"note":"...", "tags":["..."]} }
def load_notes() -> dict:
    return core.read_json(core.data_dir() / "notes.json", {}) or {}


def save_notes(data: dict) -> None:
    core.write_json_atomic(core.data_dir() / "notes.json", data)


def note_key(prov: str, model_id: str) -> str:
    return f"{prov}/{model_id}"


# ---------- pystray 加载(尽力而为) ----------
# pystray 在 import 时会强制执行 backend() 探测后端,遇到无 Gtk 的环境
# (Ubuntu minimal 之类没装 gir1.2-gtk-3.0)会直接抛 ValueError 导致整个
# `import pystray` 崩。规避:导入前先设 PYSTRAY_BACKEND=xorg,让它只走 Xorg 后端
# (Linux/X11 环境里这条最稳)。
def _ensure_pystray_backend_env() -> None:
    if "PYSTRAY_BACKEND" not in os.environ:
        os.environ["PYSTRAY_BACKEND"] = "xorg"


def _import_pystray():
    """返回 (Icon类, Menu类, MenuItem类) 或 None。失败不抛错。"""
    try:
        _ensure_pystray_backend_env()
        import pystray
        return pystray.Icon, pystray.Menu, pystray.MenuItem
    except Exception as e:  # noqa: BLE001
        print(f"[piswitch] pystray 不可用: {e}", file=sys.stderr)
        return None


def _has_x_systray() -> bool:
    """检测 X server 是否有系统托盘管理器(_NET_SYSTEM_TRAY_S<n> 有 owner)。"""
    try:
        import Xlib.display as _xd
        import Xlib.X
        disp = _xd.Display()
        atom = disp.intern_atom(f"_NET_SYSTEM_TRAY_S{disp.get_default_screen()}")
        owner = disp.get_selection_owner(atom)
        disp.close()
        return owner != Xlib.X.NONE  # type: ignore[attr-defined]
    except Exception:
        return False


def _make_tray_image():
    try:
        from PIL import Image, ImageDraw
        img = Image.new("RGBA", (64, 64), (30, 30, 46, 0))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle([6, 6, 58, 58], radius=14, fill=(137, 180, 250, 255))
        d.text((20, 16), "π", fill=(30, 30, 46, 255))
        # 缩小到合适尺寸
        return img
    except Exception:
        return None


# ---------- 迷你悬浮托盘(Tk 兜底) ----------
# 当系统托盘不可用时,用一个小窗口常驻屏幕一角作为"托盘"。


# ---------- UI ----------
class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("piswitch - pi 模型切换器")
        self.geometry("980x680")
        self.minsize(880, 600)
        self._apply_theme()

        self.settings = core.load_settings()
        self.models_store = core.load_models_store()
        self.custom = core.load_custom()
        self.auth = core.load_auth()
        self.notes = load_notes()
        self.presets = []  # 初始化预设列表
        self._tray_icon = None
        self._mini = None
        self._tag_filter = tk.StringVar(value="")

        # 左右分栏
        pane = tk.PanedWindow(self, orient=tk.HORIZONTAL, sashwidth=6)
        pane.pack(fill="both", expand=True, padx=8, pady=8)

        pane.add(self._build_left(pane), minsize=420)
        pane.add(self._build_right(pane), minsize=440)

        # 顶部菜单
        self._build_menu()

        self._status = tk.Label(self, text="就绪", anchor="w", relief="sunken", padx=8)
        self._status.pack(fill="x", side="bottom")

        # 快捷键(窗口内): Esc 最小化到托盘, Ctrl+H 显隐, Ctrl+R 刷新, Ctrl+S 应用默认
        self.bind("<Control-h>", lambda _e: self.toggle_visible())
        self.bind("<Control-r>", lambda _e: self.refresh_all())
        self.bind("<Control-s>", lambda _e: self.apply_default())
        self.bind("<Escape>", lambda _e: self.minimize_to_tray())

        # 关闭窗口 = 最小化到托盘(而非退出)
        self.protocol("WM_DELETE_WINDOW", self.minimize_to_tray)

        self.refresh_all()
        self.refresh_presets()  # 刷新预设列表
        self._refresh_providers_cb = None  # 切换 provider 时刷新

        # 启动系统托盘(后台线程)
        self._start_tray()

    # ---------- 主题 ----------
    def _apply_theme(self) -> None:
        theme = (load_settings() or {}).get("theme", "dark")
        bg = "#1e1e2e" if theme == "dark" else "#f5f5f5"
        fg = "#cdd6f4" if theme == "dark" else "#1e1e2e"
        accent = "#89b4fa" if theme == "dark" else "#1976d2"
        self.configure(bg=bg)
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TFrame", background=bg)
        style.configure("TLabel", background=bg, foreground=fg)
        style.configure("TLabelframe", background=bg, foreground=fg)
        style.configure("TLabelframe.Label", background=bg, foreground=accent)
        style.configure("TButton", background=accent, foreground=bg if theme == "dark" else "#fff")
        style.configure("TEntry", fieldbackground=bg, foreground=fg)
        style.configure("TCombobox", fieldbackground=bg, foreground=fg, background=bg)
        style.configure("Treeview", background=bg, fieldbackground=bg, foreground=fg)
        style.configure("Treeview.Heading", background=bg, foreground=accent)
        style.configure("TNotebook", background=bg)
        style.configure("TNotebook.Tab", background=bg, foreground=fg)
        self._colors = {"bg": bg, "fg": fg, "accent": accent}

    # ---------- 顶部菜单 ----------
    def _build_menu(self) -> None:
        menubar = tk.Menu(self)
        m_file = tk.Menu(menubar, tearoff=False)
        m_file.add_command(label="刷新 (Ctrl+R)", command=self.refresh_all)
        m_file.add_command(label="最小化到托盘 (Esc)", command=self.minimize_to_tray)
        m_file.add_command(label="备份整个 ~/.pi/agent", command=self.backup_agent)
        m_file.add_command(label="从备份恢复", command=self.restore_agent)
        m_file.add_separator()
        m_file.add_command(label="退出", command=self.quit_app)
        menubar.add_cascade(label="文件", menu=m_file)

        m_edit = tk.Menu(menubar, tearoff=False)
        m_edit.add_command(label="应用为默认 (Ctrl+S)", command=self.apply_default)
        m_edit.add_command(label="复制 model id", command=self.copy_model_id)
        m_edit.add_command(label="拉起 pi 测试", command=self.launch_pi)
        menubar.add_cascade(label="操作", menu=m_edit)

        m_help = tk.Menu(menubar, tearoff=False)
        m_help.add_command(label="关于 piswitch", command=self.about)
        m_help.add_command(label="安装桌面图标(.desktop)", command=self.install_desktop_entry)
        menubar.add_cascade(label="帮助", menu=m_help)
        self.configure(menu=menubar)

    # ---------- 备份/恢复 ----------
    def backup_agent(self) -> None:
        from datetime import datetime
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = core.switch_backups_dir() / f"agent-{stamp}"
        try:
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(core.agent_dir(), target, dirs_exist_ok=False)
            # 清理多余备份,仅保留最近 10 个
            backups = sorted(core.switch_backups_dir().glob("agent-*"))
            for old in backups[:-10]:
                shutil.rmtree(old, ignore_errors=True)
            self._set_status(f"已备份到 {target}")
            messagebox.showinfo("备份完成", f"已保存到:\n{target}\n(自动保留最近 10 份)")
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("备份失败", str(e))

    def restore_agent(self) -> None:
        backups = sorted(BACKUPS_DIR.glob("agent-*"), reverse=True)
        if not backups:
            messagebox.showinfo("恢复", "暂无备份")
            return
        win = tk.Toplevel(self)
        win.title("从备份恢复 ~/.pi/agent")
        win.geometry("640x380")
        tk.Label(win, text="选择一个备份(会先自动备份当前配置再覆盖):").pack(anchor="w", padx=8, pady=(8, 0))
        lb = tk.Listbox(win, height=12)
        lb.pack(fill="both", expand=True, padx=8, pady=8)
        for b in backups:
            total = 0
            for root, _, files in os.walk(b):
                for f in files:
                    total += os.path.getsize(os.path.join(root, f))
            lb.insert("end", f"{b.name}    {total/1024:.1f} KB")

        def do_restore():
            sel = lb.curselection()
            if not sel:
                messagebox.showerror("错误", "请选择一个备份", parent=win)
                return
            src = backups[sel[0]]
            if not messagebox.askyesno("确认", f"将覆盖 ~/.pi/agent 为\n{src.name}?\n(会先把当前配置备份)"):
                return
            # 先备份当前
            from datetime import datetime
            pre = core.switch_backups_dir() / f"agent-pre-restore-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
            try:
                shutil.copytree(core.agent_dir(), pre, dirs_exist_ok=True)
            except Exception:
                pass
            # 清空并恢复
            for p in (core.settings_path(), core.models_store_path(), core.models_path(), core.auth_path()):
                try:
                    if p.exists():
                        p.unlink()
                except Exception:
                    pass
            for item in core.agent_dir().iterdir():
                if item.name == "sessions":
                    continue  # 保留会话
                try:
                    if item.is_dir():
                        shutil.rmtree(item)
                    else:
                        item.unlink()
                except Exception:
                    pass
            for item in src.iterdir():
                dst = core.agent_dir() / item.name
                if item.is_dir():
                    shutil.copytree(item, dst, dirs_exist_ok=True)
                else:
                    shutil.copy2(item, dst)
            win.destroy()
            self.refresh_all(preserve_ui=False)
            self._apply_theme()
            messagebox.showinfo("恢复完成", f"已从 {src.name} 恢复")

        ttk.Button(win, text="恢复", command=do_restore).pack(pady=8)

    # ---------- 托盘 ----------
    def _start_tray(self) -> None:
        # 先检测当前 X server 是否有系统托盘管理器(_NET_SYSTEM_TRAY_S<n> 有 owner)
        # 没有就直接走迷你悬浮窗,根本不调 pystray,免得它在 stderr 上反复打栈。
        if not _has_x_systray():
            self._set_status("桌面无托盘管理器,使用悬浮迷你托盘")
            self._spawn_mini()
            return
        xmm = _import_pystray()
        if xmm is None:
            self._set_status("无 pystray 后端,使用悬浮迷你托盘")
            self._spawn_mini()
            return
        XIcon, XMenu, XMenuItem = xmm
        img = _make_tray_image()
        if img is None:
            self._set_status("托盘图标生成失败,使用悬浮迷你托盘")
            self._spawn_mini()
            return

        def on_show(icon, item=None):
            self.after(0, self.show_window)

        def on_quit(icon, item=None):
            self.after(0, self.quit_app)

        try:
            menu = XMenu(
                XMenuItem("显示 piswitch", on_show, default=True),
                XMenuItem("退出", on_quit),
            )
            icon = XIcon("piswitch", img, "piswitch", menu)
            self._tray_icon = icon
            t = threading.Thread(target=icon.run, daemon=True)
            t.start()
            self._set_status("已挂载系统托盘")
        except Exception as e:  # noqa: BLE001
            self._set_status(f"系统托盘启动失败: {e}; 使用悬浮迷你托盘")
            self._spawn_mini()

    def _spawn_mini(self) -> None:
        """创建一个常驻屏幕右上角的小悬浮窗作为兜底托盘。"""
        if self._mini is not None:
            return
        mini = tk.Toplevel(self)
        mini.overrideredirect(True)  # 无边框
        mini.attributes("-topmost", True)
        try:
            mini.attributes("-type", "utility")  # 部分环境下更不打扰
        except tk.TclError:
            pass
        sw = mini.winfo_screenwidth()
        mini.geometry(f"96x32+{sw-112}+12")
        b = tk.Button(
            mini, text="π piswitch", command=self.show_window,
            bg="#89b4fa", fg="#1e1e2e", relief="flat", bd=0, font=("Sans", 9, "bold")
        )
        b.pack(fill="both", expand=True)
        mini.bind("<Button-3>", lambda _e: self._mini_menu(mini))
        self._mini = mini

    def _mini_menu(self, mini) -> None:
        m = tk.Menu(mini, tearoff=False)
        m.add_command(label="显示/隐藏", command=self.toggle_visible)
        m.add_command(label="退出", command=self.quit_app)
        try:
            m.tk_popup(mini.winfo_rootx() + 20, mini.winfo_rooty() + 20)
        finally:
            m.grab_release()

    # ---------- 窗口显隐 ----------
    def show_window(self) -> None:
        self.after(0, self._do_show)

    def _do_show(self) -> None:
        self.deiconify()
        self.lift()
        self.focus_force()
        try:
            self.attributes("-topmost", True)
            self.after(200, lambda: self.attributes("-topmost", False))
        except tk.TclError:
            pass

    def hide_window(self) -> None:
        self.withdraw()

    def toggle_visible(self) -> None:
        if self.state() == "withdrawn" or not self.winfo_viewable():
            self._do_show()
        else:
            self.hide_window()

    def minimize_to_tray(self) -> None:
        self.hide_window()
        self._set_status("已最小化到托盘(点悬浮按钮 或 右键菜单唤回)")

    def quit_app(self) -> None:
        try:
            if self._tray_icon is not None:
                self._tray_icon.stop()
        except Exception:
            pass
        self.destroy()

    def about(self) -> None:
        messagebox.showinfo(
            "关于 piswitch",
            "piswitch - pi 模型切换 GUI\n\n"
            "本地管理 ~/.pi/agent 配置:\n"
            "  • 切换默认 provider/model/thinking\n"
            "  • 管理 NewAPI 等自定义 provider\n"
            "  • API key 编辑\n"
            "  • 备份/恢复 整个 agent 目录\n"
            "  • 模型备注与标签分组\n"
            "  • 系统托盘/悬浮迷你托盘\n\n"
            "快捷键: Esc 最小化 · Ctrl+H 显隐 · Ctrl+R 刷新 · Ctrl+S 应用默认",
        )

    def install_desktop_entry(self) -> None:
        apps = Path.home() / ".local/share/applications"
        icons = Path.home() / ".local/share/icons"
        apps.mkdir(parents=True, exist_ok=True)
        icons.mkdir(parents=True, exist_ok=True)
        launcher = Path.home() / ".local/bin/piswitch"
        icon_path = icons / "piswitch.svg"
        icon_path.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="128" height="128">'
            '<rect x="8" y="8" width="112" height="112" rx="24" fill="#89b4fa"/>'
            '<text x="64" y="86" font-size="72" text-anchor="middle" '
            'fill="#1e1e2e" font-family="sans-serif" font-weight="bold">π</text></svg>',
            encoding="utf-8",
        )
        desktop = apps / "piswitch.desktop"
        desktop.write_text(
            "[Desktop Entry]\n"
            "Type=Application\n"
            "Name=piswitch\n"
            "Comment=pi 模型切换器\n"
            "Exec=" + str(launcher) + "\n"
            "Icon=" + str(icon_path) + "\n"
            "Terminal=false\n"
            "Categories=Utility;Development;\n"
            "Keywords=pi;model;switch;\n",
            encoding="utf-8",
        )
        desktop.chmod(0o755)
        try:
            subprocess.run(["update-desktop-database", str(apps)], check=False)
        except FileNotFoundError:
            pass
        messagebox.showinfo("桌面图标", f"已安装:\n{desktop}\n图标:\n{icon_path}")

    # ---------- 左栏:预设卡片 ----------
    def _build_left(self, parent) -> tk.Frame:
        frame = ttk.Frame(parent)
        bar = ttk.Frame(frame)
        bar.pack(fill="x", padx=6, pady=6)
        for text, cmd in (("新增预设", lambda: self.open_preset_editor()),
                          ("编辑", self.edit_selected_preset),
                          ("删除", self.delete_selected_preset),
                          ("从当前配置导入", self.import_current_as_preset),
                          ("导入JSON", self.import_presets_json),
                          ("导出JSON", self.export_presets_json)):
            ttk.Button(bar, text=text, command=cmd).pack(side="left", padx=2)
        self.preset_list = ttk.Treeview(frame, columns=("name", "target", "kind", "key"),
                                        show="headings", selectmode="browse")
        for c, t, w in (("name", "预设", 220), ("target", "provider/model", 240),
                        ("kind", "类型", 70), ("key", "Key", 50)):
            self.preset_list.heading(c, text=t)
            self.preset_list.column(c, width=w, anchor="w")
        self.preset_list.pack(fill="both", expand=True, padx=6, pady=6)
        self.preset_list.bind("<Double-1>", lambda _e: self.switch_selected())
        ttk.Button(frame, text="切为当前生效", command=self.switch_selected).pack(fill="x", padx=6, pady=6)
        return frame

    # ---------- 右栏:管理 provider/模型/key ----------
    def refresh_presets(self) -> None:
        """刷新预设列表。"""
        self.presets = core.load_presets()
        settings = core.load_settings()
        active = core.active_preset_id(self.presets, settings)
        auth, custom = core.load_auth(), core.load_custom()
        self.preset_list.delete(*self.preset_list.get_children())
        for p in self.presets:
            mark = "✓ " if p.get("id") == active else ""
            haskey = "✓" if core.resolve_has_key(p.get("provider", ""), auth, custom) else "—"
            self.preset_list.insert("", "end", iid=p["id"],
                values=(mark + p.get("name", "?"), f"{p.get('provider')}/{p.get('model')}",
                        p.get("kind", ""), haskey))

    def _selected_preset(self) -> dict | None:
        """返回当前选中的预设,或 None。"""
        sel = self.preset_list.selection()
        if not sel:
            messagebox.showinfo("提示", "先选中一个预设")
            return None
        return next((p for p in self.presets if p["id"] == sel[0]), None)

    def switch_selected(self) -> None:
        """切换到选中的预设。"""
        p = self._selected_preset()
        if not p:
            return
        from datetime import datetime
        try:
            s = core.switch_to(p, datetime.now().strftime("%Y%m%d-%H%M%S"))
        except Exception as e:
            messagebox.showerror("切换失败", str(e))
            return
        self._set_status(f"已切换: {s.get('defaultProvider')}/{s.get('defaultModel')}")
        self.refresh_presets()

    def open_preset_editor(self, preset: dict | None = None) -> None:
        """打开预设编辑器弹窗。"""
        win = tk.Toplevel(self)
        win.title("编辑预设" if preset else "新增预设")
        win.geometry("560x460")
        v = {k: tk.StringVar(value=(preset or {}).get(k, d)) for k, d in
             (("name", ""), ("provider", ""), ("kind", "builtin"), ("model", ""),
              ("baseUrl", "https://"), ("api", "openai-completions"),
              ("apiKey", ""), ("thinking", ""))}
        rows = [("名称", "name"), ("provider", "provider"), ("kind(builtin/custom)", "kind"),
                ("model(逗号分隔可多)", "model"), ("baseUrl(custom)", "baseUrl"),
                ("api类型(custom)", "api"), ("apiKey(custom,可$ENV)", "apiKey"),
                ("thinking(可空)", "thinking")]
        for i, (label, key) in enumerate(rows):
            ttk.Label(win, text=label).grid(row=i, column=0, sticky="w", padx=8, pady=4)
            ttk.Entry(win, textvariable=v[key], width=52).grid(row=i, column=1, padx=8, pady=4)

        def save() -> None:
            data = {k: var.get().strip() for k, var in v.items()}
            if not data["name"] or not data["provider"] or not data["model"]:
                messagebox.showerror("必填", "name / provider / model 必填", parent=win)
                return
            if preset:
                core.update_preset(preset["id"], data)
            else:
                core.add_preset(data)
            win.destroy()
            self.refresh_presets()

        ttk.Button(win, text="保存", command=save).grid(row=len(rows), column=0, columnspan=2, pady=10)

    def edit_selected_preset(self) -> None:
        """编辑选中的预设。"""
        p = self._selected_preset()
        if p:
            self.open_preset_editor(p)

    def delete_selected_preset(self) -> None:
        """删除选中的预设。"""
        p = self._selected_preset()
        if p and messagebox.askyesno("确认", f"删除预设 {p.get('name')}?"):
            core.delete_preset(p["id"])
            self.refresh_presets()

    def import_current_as_preset(self) -> None:
        """从当前配置导入为预设。"""
        p = core.preset_from_current(core.load_settings(), core.load_custom())
        core.add_preset(p)
        self.refresh_presets()
        self._set_status(f"已从当前配置导入预设: {p['name']}")

    def export_presets_json(self) -> None:
        """导出预设为 JSON 文件。"""
        from tkinter import filedialog
        path = filedialog.asksaveasfilename(defaultextension=".json", initialfile="piswitch-presets.json")
        if path:
            core.write_json_atomic(__import__("pathlib").Path(path), {"presets": core.load_presets()})
            self._set_status(f"已导出到 {path}")

    def import_presets_json(self) -> None:
        """导入预设 JSON 文件。"""
        from tkinter import filedialog
        path = filedialog.askopenfilename(filetypes=[("JSON", "*.json")])
        if not path:
            return
        data = core.read_json(__import__("pathlib").Path(path), {})
        for p in data.get("presets", []):
            p.pop("id", None)
            core.add_preset(p)
        self.refresh_presets()
        self._set_status("导入完成")

    # ---------- 右栏:管理 provider/模型/key ----------
    def _build_right(self, parent) -> tk.Frame:
        frame = ttk.Frame(parent)
        nb = ttk.Notebook(frame)
        nb.pack(fill="both", expand=True)
        self._build_providers_tab(nb)
        self._build_auth_tab(nb)
        self._build_models_tab(nb)
        self._build_backup_tab(nb)
        return frame

    def _build_providers_tab(self, nb) -> None:
        tab = ttk.Frame(nb)
        nb.add(tab, text="Provider & 模型清单")
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(1, weight=1)

        top = ttk.Frame(tab)
        top.grid(row=0, column=0, columnspan=2, sticky="ew", padx=4, pady=4)
        ttk.Button(top, text="刷新", command=self.refresh_all).pack(side="left")
        ttk.Button(top, text="删除自定义 provider", command=self.delete_custom_provider).pack(side="left", padx=8)
        ttk.Button(top, text="编辑内置 provider 转发(baseUrl)", command=self.edit_builtin_override).pack(side="left")
        ttk.Button(top, text="编辑备注/标签", command=self.edit_note_for_selected).pack(side="left", padx=8)

        # 标签筛选栏
        filt = ttk.Frame(tab)
        filt.grid(row=1, column=0, columnspan=2, sticky="ew", padx=4)
        ttk.Label(filt, text="过滤标签(逗号分隔,空=全部):").pack(side="left")
        ttk.Entry(filt, textvariable=self._tag_filter, width=40).pack(side="left", padx=4)
        ttk.Button(filt, text="应用过滤", command=self.refresh_all).pack(side="left")

        cols = ("prov", "model", "name", "source", "haskey", "tags", "note")
        self.tree = ttk.Treeview(tab, columns=cols, show="headings")
        for c, w in zip(cols, (120, 240, 180, 60, 50, 120, 220)):
            self.tree.column(c, width=w, anchor="w")
            self.tree.heading(c, text={"prov": "Provider", "model": "Model ID", "name": "Name",
                                       "source": "来源", "haskey": "有Key",
                                       "tags": "标签", "note": "备注"}[c])
        self.tree.grid(row=2, column=0, sticky="nsew", padx=4, pady=4)
        sb = ttk.Scrollbar(tab, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        sb.grid(row=2, column=1, sticky="ns")
        tab.rowconfigure(2, weight=1)
        self.tree.bind("<Double-1>", lambda _e: self.edit_note_for_selected())

    def _build_auth_tab(self, nb) -> None:
        tab = ttk.Frame(nb)
        nb.add(tab, text="API Key 管理")
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(1, weight=1)

        top = ttk.Frame(tab)
        top.grid(row=0, column=0, sticky="ew", padx=4, pady=4)
        ttk.Button(top, text="新增 provider key", command=self.add_auth_row).pack(side="left")
        ttk.Button(top, text="保存", command=self.save_auth).pack(side="left", padx=8)

        self.auth_tree = ttk.Treeview(
            tab, columns=("prov", "type", "key"), show="tree headings", displaycolumns=(0, 1, 2)
        )
        self.auth_tree.column("#0", width=0, stretch=False)
        self.auth_tree.column("prov", width=160, anchor="w")
        self.auth_tree.column("type", width=100, anchor="w")
        self.auth_tree.column("key", width=480, anchor="w")
        self.auth_tree.heading("prov", text="Provider")
        self.auth_tree.heading("type", text="Type")
        self.auth_tree.heading("key", text="Key (明文, 仅本地)")
        self.auth_tree.grid(row=1, column=0, sticky="nsew", padx=4, pady=4)
        self.auth_tree.bind("<Double-1>", self.edit_auth_row)

    def _build_models_tab(self, nb) -> None:
        tab = ttk.Frame(nb)
        nb.add(tab, text="settings.json 原始")
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(0, weight=1)
        self.raw_settings = tk.Text(tab, undo=True)
        self.raw_settings.grid(row=0, column=0, sticky="nsew", padx=4, pady=4)
        ttk.Button(tab, text="保存原始 settings.json", command=self.save_raw_settings).grid(
            row=1, column=0, sticky="ew", padx=4, pady=4
        )

    def _build_backup_tab(self, nb) -> None:
        tab = ttk.Frame(nb)
        nb.add(tab, text="备份 & 恢复")
        tab.columnconfigure(0, weight=1)
        text = (
            "备份范围: 整个 ~/.pi/agent 目录(settings / models-store / models / auth / bin 等)。\n"
            "会话目录(sessions)在恢复时不予覆盖。\n"
            "自动保留最近 10 份备份。"
        )
        ttk.Label(tab, text=text, justify="left").pack(anchor="w", padx=10, pady=10)
        bf = ttk.Frame(tab)
        bf.pack(fill="x", padx=10)
        bf.columnconfigure(0, weight=1)
        bf.columnconfigure(1, weight=1)
        ttk.Button(bf, text="备份当前配置", command=self.backup_agent).grid(
            row=0, column=0, sticky="ew", padx=4, pady=4
        )
        ttk.Button(bf, text="从备份恢复…", command=self.restore_agent).grid(
            row=0, column=1, sticky="ew", padx=4, pady=4
        )
        # 备份列表
        self.backup_list = tk.Listbox(tab, height=10)
        self.backup_list.pack(fill="both", expand=True, padx=10, pady=8)
        ttk.Button(tab, text="删除选中备份", command=self.delete_selected_backup).pack(padx=10, pady=(0, 10))

    def delete_selected_backup(self) -> None:
        sel = self.backup_list.curselection()
        if not sel:
            return
        name = self.backup_list.get(sel[0])
        path = core.switch_backups_dir() / name.split("   ")[0].strip()
        if messagebox.askyesno("确认", f"删除 {path.name}?"):
            shutil.rmtree(path, ignore_errors=True)
            self.refresh_all()

    # ---------- 刷新 ----------
    def refresh_all(self, *, preserve_ui: bool = True) -> None:
        """重新从磁盘读取并刷新 UI。"""
        self.settings = core.load_settings()
        self.models_store = core.load_models_store()
        self.custom = core.load_custom()
        self.auth = core.load_auth()
        self.notes = load_notes()

        # tree
        self.tree.delete(*self.tree.get_children())
        shown = 0
        prov_map = core.provider_model_map(self.models_store, self.custom)

        # 解析 tag 过滤
        ftxt = self._tag_filter.get().strip()
        want = {s.strip() for s in ftxt.split(",") if s.strip()} if ftxt else set()

        for prov in sorted(prov_map):
            has = core.resolve_has_key(prov, self.auth, self.custom)
            for m in prov_map[prov]:
                key = note_key(prov, m["id"])
                n = self.notes.get(key, {})
                tags = ", ".join(n.get("tags", []))
                note = n.get("note", "")
                row_tags = n.get("tags", [])
                if want and not (set(row_tags) & want):
                    continue
                self.tree.insert(
                    "", "end",
                    values=(prov, m["id"], m["name"], m["source"],
                            "✓" if has else "—", tags, note),
                )
                shown += 1

        # auth tree
        self.auth_tree.delete(*self.auth_tree.get_children())
        for prov, info in sorted(self.auth.items()):
            self.auth_tree.insert("", "end", iid=prov,
                                  values=(prov, info.get("type", "apikey"), info.get("key", "")))

        # 原始
        self.raw_settings.delete("1.0", "end")
        self.raw_settings.insert("1.0", json.dumps(self.settings, indent=2, ensure_ascii=False))

        # 备份列表
        if hasattr(self, "backup_list"):
            self.backup_list.delete(0, "end")
            for b in sorted(core.switch_backups_dir().glob("agent-*"), reverse=True):
                total = 0
                for root, _, files in os.walk(b):
                    for f in files:
                        total += os.path.getsize(os.path.join(root, f))
                self.backup_list.insert("end", f"{b.name}   {total/1024:.1f} KB")

        self._set_status(f"已读取 {len(prov_map)} 个 provider, {shown} 个模型"
                         + (f"(过滤自 {sum(len(v) for v in prov_map.values())})" if want else ""))

        # 刷新预设列表
        self.refresh_presets()

    # ---------- 备注/标签 ----------
    def edit_note_for_selected(self) -> None:
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("提示", "先在表格里选中一个模型")
            return
        vals = self.tree.item(sel[0], "values")
        prov, model = vals[0], vals[1]
        key = note_key(prov, model)
        cur = self.notes.get(key, {})
        win = tk.Toplevel(self)
        win.title(f"备注/标签: {key}")
        win.geometry("520x260")
        tk.Label(win, text="备注:").pack(anchor="w", padx=10, pady=(10, 0))
        note_v = tk.StringVar(value=cur.get("note", ""))
        tk.Entry(win, textvariable=note_v, width=64).pack(padx=10, fill="x")
        tk.Label(win, text="标签(逗号分隔):").pack(anchor="w", padx=10, pady=(10, 0))
        tags_v = tk.StringVar(value=", ".join(cur.get("tags", [])))
        tk.Entry(win, textvariable=tags_v, width=64).pack(padx=10, fill="x")
        tk.Label(win, text="建议标签: " + ", ".join(TAG_SUGGESTIONS)).pack(anchor="w", padx=10, pady=(4, 0))

        def ok():
            tags = [s.strip() for s in tags_v.get().split(",") if s.strip()]
            self.notes[key] = {"note": note_v.get().strip(), "tags": tags}
            save_notes(self.notes)
            win.destroy()
            self.refresh_all()

        ttk.Button(win, text="保存", command=ok).pack(pady=10)

    def _populate_models(self) -> None:
        prov = self.provider_var.get()
        prov_map = core.provider_model_map(self.models_store, self.custom)
        models = prov_map.get(prov, [])
        ids = [m["id"] for m in models]
        self.model_box["values"] = ids
        # 优先沿用 UI 当前的 model;再尝试磁盘 settings 的默认;最后为第一个
        cur = self.model_var.get()
        if not cur or cur not in ids:
            cur = self.settings.get("defaultModel")
        if not cur or cur not in ids:
            cur = ids[0] if ids else ""
        self.model_var.set(cur)

    def _on_provider_changed(self) -> None:
        self._populate_models()
        tid = self.model_var.get()
        tlv = "high" if core.model_supports_reasoning(self.models_store, self.custom, self.provider_var.get(), tid) else "off"
        self.thinking_var.set(tlv)

    # ---------- 动作 ----------
    def _set_status(self, msg: str) -> None:
        self._status.config(text=msg)

    def apply_default(self) -> None:
        prov = self.provider_var.get()
        model = self.model_var.get()
        thinking = self.thinking_var.get()
        theme = self.theme_var.get()
        if not prov:
            messagebox.showerror("错误", "请选择 provider")
            return
        self.settings["defaultProvider"] = prov
        if model:
            self.settings["defaultModel"] = model
        self.settings["defaultThinkingLevel"] = thinking
        self.settings["theme"] = theme
        core.write_json_atomic(core.settings_path(), self.settings)
        self._set_status(f"已设置默认: {prov}/{model} thinking={thinking} theme={theme}")

    def copy_model_id(self) -> None:
        m = self.model_var.get()
        if not m:
            return
        self.clipboard_clear()
        self.clipboard_append(m)
        self._set_status(f"已复制: {m}")

    def launch_pi(self) -> None:
        m = self.model_var.get()
        prov = self.provider_var.get()
        if not m:
            return
        if not prov:
            return
        # 优先使用 PATH 里的 pi(用户从 nvm shell 启动本程序时可用),否则回退到
        # 已知的 nvm bin 路径(避免从 GUI/desktop entry 启动时 PATH 中没有 node)。
        pi_bin = shutil.which("pi")
        if pi_bin is None:
            nvm_pi = Path.home() / ".nvm/versions/node"
            if nvm_pi.exists():
                for node_dir in sorted(nvm_pi.iterdir()):
                    cand = node_dir / "bin" / "pi"
                    if cand.exists():
                        pi_bin = str(cand)
                        break
        if pi_bin is None:
            messagebox.showerror("未找到 pi", "PATH 中没有 pi,且未找到 ~/.nvm 下的 pi。")
            return
        cmd = [pi_bin, "--model", f"{prov}/{m}"]
        self._set_status(" ".join(cmd))
        try:
            # detach: 后台运行,stdout/stderr 落地日志,避免 GUI 卡住
            core.data_dir().mkdir(parents=True, exist_ok=True)
            logf = (core.data_dir() / "pi-launch.log").open("a", encoding="utf-8")
            subprocess.Popen(
                cmd, stdout=logf, stderr=subprocess.STDOUT,
                cwd=str(Path.home()), start_new_session=True,
            )
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("启动 pi 失败", str(e))

    def save_newapi(self) -> None:
        prov = self.na_prov_var.get().strip()
        if not prov:
            messagebox.showerror("错误", "Provider 名必填")
            return
        base = self.na_base_var.get().strip()
        if not base:
            messagebox.showerror("错误", "BaseURL 必填")
            return
        ids = [s.strip() for s in self.na_models_var.get().split(",") if s.strip()]
        models = []
        for i in ids:
            models.append({
                "id": i,
                "name": i,
                "reasoning": False,
                "input": INPUT_TYPES,
                "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
                "contextWindow": 128000,
                "maxTokens": 16384,
            })
        cfg = {
            "name": self.na_name_var.get().strip() or prov,
            "baseUrl": base,
            "api": self.na_api_var.get().strip(),
            "apiKey": self.na_key_var.get().strip(),
            "models": models,
        }
        self.custom.setdefault("providers", {})[prov] = cfg
        core.write_json_atomic(core.models_path(), self.custom)
        # 若 provider 删了 auth 同步保留(不动 auth)
        self._set_status(f"已保存自定义 provider: {prov} ({len(models)} 模型)")
        self.refresh_all()

    def fetch_models(self) -> None:
        """从 NewAPI /v1/models 拉模型清单。"""
        base = self.na_base_var.get().strip()
        key = self.na_key_var.get().strip()
        if not base:
            messagebox.showerror("错误", "请先填 BaseURL")
            return
        # 标准化:期望最终 GET 的是 https://xxx/v1/models
        b = base.rstrip("/")
        if b.endswith("/models"):
            url = b
        elif b.endswith("/v1"):
            url = b + "/models"
        else:
            url = b + "/v1/models"
        try:
            import urllib.request
            req = urllib.request.Request(url)
            token = key
            if token.startswith("$"):
                env = token[1:].strip("{}")
                token = os.environ.get(env, "")
            if token:
                req.add_header("Authorization", f"Bearer {token}")
            with urllib.request.urlopen(req, timeout=15) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            ids = [d.get("id") for d in payload.get("data", []) if d.get("id")]
            if not ids:
                messagebox.showinfo("结果", "服务返回空模型列表")
                return
            self.na_models_var.set(", ".join(ids))
            self._set_status(f"从 {url} 拉取到 {len(ids)} 个模型")
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("拉取失败", f"{url}\n{e}")

    def delete_custom_provider(self) -> None:
        sel = self.tree.selection()
        if not sel:
            return
        prov = self.tree.item(sel[0], "values")[0]
        if prov not in self.custom.get("providers", {}):
            messagebox.showinfo("提示", f"{prov} 不是自定义 provider,无法删除")
            return
        if not messagebox.askyesno("确认", f"删除自定义 provider '{prov}'?\n(不会删 auth.json 中对应 key)"):
            return
        del self.custom["providers"][prov]
        core.write_json_atomic(core.models_path(), self.custom)
        self._set_status(f"已删除 {prov}")
        self.refresh_all()

    def edit_builtin_override(self) -> None:
        sel = self.tree.selection()
        if not sel:
            return
        prov = self.tree.item(sel[0], "values")[0]
        win = tk.Toplevel(self)
        win.title(f"转发内置 provider: {prov}")
        win.geometry("560x300")
        cur = self.custom.get("providers", {}).get(prov, {})
        tk.Label(win, text="baseUrl(留空则不覆盖):").pack(anchor="w", padx=8, pady=(8, 0))
        bv = tk.StringVar(value=cur.get("baseUrl", ""))
        tk.Entry(win, textvariable=bv, width=70).pack(padx=8)
        tk.Label(win, text="自定义 headers(JSON, 可选):").pack(anchor="w", padx=8, pady=(8, 0))
        hv = tk.StringVar(value=json.dumps(cur.get("headers", {}), ensure_ascii=False))
        tk.Entry(win, textvariable=hv, width=70).pack(padx=8)

        def save():
            cfg = dict(self.custom.get("providers", {}).get(prov, {}))
            if bv.get().strip():
                cfg["baseUrl"] = bv.get().strip()
            elif "baseUrl" in cfg:
                del cfg["baseUrl"]
            try:
                hs = json.loads(hv.get() or "{}")
            except Exception as e:  # noqa: BLE001
                messagebox.showerror("headers JSON", str(e), parent=win)
                return
            if hs:
                cfg["headers"] = hs
            elif "headers" in cfg:
                del cfg["headers"]
            self.custom.setdefault("providers", {})[prov] = cfg
            core.write_json_atomic(core.models_path(), self.custom)
            win.destroy()
            self.refresh_all()

        tk.Button(win, text="保存", command=save).pack(pady=8)

    def add_auth_row(self) -> None:
        win = tk.Toplevel(self)
        win.title("新增 provider API key")
        win.geometry("480x240")
        tk.Label(win, text="Provider 名:").pack(anchor="w", padx=8, pady=(8, 0))
        pv = tk.StringVar()
        tk.Entry(win, textvariable=pv).pack(padx=8, fill="x")
        tk.Label(win, text="API Key(支持 $ENV 引用 / 明文):").pack(anchor="w", padx=8, pady=(8, 0))
        kv = tk.StringVar()
        tk.Entry(win, textvariable=kv, width=60).pack(padx=8, fill="x")
        # 推荐填入 auth.json 的应是明文(运行时被 pi 加密保存?)。备注
        tk.Label(win, text="注:auth.json 中 key 通常为明文,存于本地。").pack(anchor="w", padx=8, pady=(6, 0))

        def ok():
            prov = pv.get().strip()
            if not prov:
                messagebox.showerror("错误", "provider 名必填", parent=win)
                return
            self.auth[prov] = {"type": "apikey", "key": kv.get().strip()}
            core.write_json_atomic(core.auth_path(), self.auth)
            win.destroy()
            self.refresh_all()

        tk.Button(win, text="保存", command=ok).pack(pady=8)

    def edit_auth_row(self, _event) -> None:
        sel = self.auth_tree.selection()
        if not sel:
            return
        prov = sel[0]
        info = self.auth.get(prov, {})
        win = tk.Toplevel(self)
        win.title(f"编辑 {prov} 的 API key")
        win.geometry("560x200")
        tk.Label(win, text="Key:").pack(anchor="w", padx=8, pady=(8, 0))
        kv = tk.StringVar(value=info.get("key", ""))
        tk.Entry(win, textvariable=kv, width=70).pack(padx=8)
        tk.Label(win, text="(支持 $ENV_VAR 引用环境变量。)").pack(anchor="w", padx=8)

        def ok():
            self.auth.setdefault(prov, {})["key"] = kv.get().strip()
            self.auth[prov]["type"] = "apikey"
            core.write_json_atomic(core.auth_path(), self.auth)
            win.destroy()
            self.refresh_all()

        tk.Button(win, text="保存", command=ok).pack(pady=8)

    def save_auth(self) -> None:
        core.write_json_atomic(core.auth_path(), self.auth)
        self._set_status("auth.json 已保存")

    def save_raw_settings(self) -> None:
        try:
            data = json.loads(self.raw_settings.get("1.0", "end"))
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("JSON 错误", str(e))
            return
        core.write_json_atomic(core.settings_path(), data)
        self.settings = data
        self._apply_theme()
        self._set_status("settings.json 已保存并刷新")


def main() -> None:
    rc = core.dispatch(sys.argv[1:])
    if rc is not None:
        sys.exit(rc)
    # 无参数 → GUI（保留原有致命错误兜底）
    debug = bool(os.environ.get("PISWITCH_DEBUG"))
    try:
        App().mainloop()
    except Exception as e:  # noqa: BLE001
        if debug:
            raise
        try:
            messagebox.showerror("piswitch 致命错误", str(e))
        except Exception:
            print(f"[piswitch] 致命错误: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
